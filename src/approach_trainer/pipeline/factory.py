"""Factory: turn a raw video into fully-processed DB rows in one chain.

For each NEW video (not yet in the DB) it runs:
  detect cuts -> extract audio -> 5x diarized Scribe -> compile-down consensus
  -> write parent row (sources|clips) -> cut-aware segmentation -> write child segments.

Root decides the target table:
  /mnt/media/pickup-courses/...            -> sources  (long-form; id = md5(path))
  /mnt/media/.../approach-clips/{ig,yt/<lang>,douyin}/<creator>/<id>.mp4 -> clips (id = stem)

Usage:
  uv run --project ~/github/approach-trainer approach-trainer factory <db>
  uv run --project ~/github/approach-trainer approach-trainer factory <db> --path FILE ...
  uv run --project ~/github/approach-trainer approach-trainer factory <db> --root DIR
Resumable + idempotent: rows already present are skipped; safe to re-run anytime.
"""

import argparse
import fcntl
import json
import sqlite3
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from omni_curator.create.fuse import compile_down
from omni_curator.swservice import SuperwhisperClient

from approach_trainer.languages import language_name, scribe_code, script_of
from approach_trainer.paths import AUDIO_CACHE, CLIPS_ROOT, COURSES_ROOT
from approach_trainer.pipeline.audio import drop_cache, extract_audio, fid_of
from approach_trainer.pipeline.cuts import detect_cuts
from approach_trainer.pipeline.segment import ensure_outcome_columns, segment_one
from approach_trainer.swservice import transcribe_file

COURSES = COURSES_ROOT
CLIP_DIRS = ["ig", "yt", "douyin"]
AUD = AUDIO_CACHE
RUNS = 5


def instruction_for(lang_name: str) -> str:
    return (
        f"Below are several independent ASR hypotheses of the SAME {lang_name} audio (a pickup/"
        "dating coaching video — lecture and/or infield footage). Produce the single most "
        "accurate, verbatim transcript using agreement across hypotheses to fix mishearings and "
        "dropped words. Keep slang and filler. No speaker labels or commentary. Output ONLY the "
        "transcript in <transcript></transcript>."
    )


def probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return round(float(out), 2) if out else 0.0
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def batch_scribe(flacs: list[Path], scribe_code: str, tag: str,
                 max_workers: int = 200) -> dict[str, list[dict]]:
    """Run RUNS diarized Scribe passes over ALL flacs via the deployed ASR service.

    Each pass submits every flac to ``transcribe_file`` (diarized, ``detail=["turns"]``)
    concurrently; ``RUNS`` passes give the ensemble its repeated hypotheses. Returns
    {flac_stem (= fid): [result dicts across runs]}, each result carrying ``transcript``
    and diarized ``turns``. The service owns ASR key rotation, so no keys are handled here.
    """
    by_fid: dict[str, list[dict]] = {}
    pool_size = min(max_workers, max(1, len(flacs)))

    def one(flac: Path) -> tuple[str, dict | None]:
        try:
            result = transcribe_file(
                flac, asr_model="scribe-v2", mode="single",
                language=scribe_code, diarize=True, detail=["turns"],
            )
        # Resilience: a failed clip must not abort the whole backlog pass.
        except Exception as e:  # noqa: BLE001
            print(f"  scribe FAIL {flac.stem} ({tag}): {e}", flush=True)
            return flac.stem, None
        return flac.stem, result

    for r in range(RUNS):
        print(f"  pass {r + 1}/{RUNS} ({tag}): {len(flacs)} files...", flush=True)
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            for fid, result in pool.map(one, flacs):
                if result is not None and (result.get("transcript") or result.get("turns")):
                    by_fid.setdefault(fid, []).append(result)
    return by_fid


def target_for(v: Path) -> tuple[str, dict] | None:
    """Return (table, extra-columns) for a video path, or None if outside known roots."""
    if COURSES in v.parents:
        rel = v.relative_to(COURSES)
        collection = rel.parts[0] if len(rel.parts) > 1 else "misc"
        kind = "youtube-archive" if "YouTube" in collection else "course"
        return "sources", {"collection": collection, "kind": kind}
    for d in CLIP_DIRS:
        base = CLIPS_ROOT / d
        if base in v.parents:
            rel = v.relative_to(base)
            if d == "yt":
                # yt/<lang>/<creator>/<id>.mp4 — lang resolves via approach_trainer.languages
                lang = rel.parts[0]
                creator = rel.parts[1] if len(rel.parts) > 1 else rel.parts[0]
                return "clips", {"creator": creator, "source": "youtube", "lang": lang}
            creator = rel.parts[0]
            source = {"ig": "instagram", "douyin": "douyin"}[d]
            lang = "zh" if d == "douyin" else "en"
            return "clips", {"creator": creator, "source": source, "lang": lang}
    return None


def already_done(db: sqlite3.Connection, table: str, v: Path) -> bool:
    cid = fid_of(v) if table == "sources" else v.stem
    return db.execute(f"SELECT 1 FROM {table} WHERE id=?", (cid,)).fetchone() is not None


def _speaker_id(label: object) -> str:
    """Map a service ``"Speaker N"`` turn label to the legacy 0-indexed ``speaker_{N-1}`` id.

    The deployed ASR service emits diarized turn speakers as ``"Speaker 1"``, ``"Speaker 2"``,
    … (1-indexed, sorted by raw provider id). The rest of this pipeline keys on the old
    ``speaker_0``/``speaker_1`` ids (``speaker_0`` = approacher), so re-base to 0-indexed.
    Anything unparseable falls back to ``speaker_0``.
    """
    text = str(label or "").strip()
    if text.lower().startswith("speaker"):
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            n = int(digits)
            return f"speaker_{n - 1}" if "speaker " in text.lower() else f"speaker_{n}"
    return "speaker_0"


def finalize_one(db: sqlite3.Connection, client: SuperwhisperClient, v: Path,
                 table: str, extra: dict, recs: list[dict]) -> str:
    """Given the Scribe records for one video, compile consensus, write the parent
    row, segment, and write child rows. (Scribe already done in batch.)"""
    cid = fid_of(v) if table == "sources" else v.stem
    lang = extra.get("lang", "en")
    lang_name, script = language_name(lang), script_of(lang)

    cuts = detect_cuts(str(v)) or []
    duration = probe_duration(str(v))
    variants = [r.get("transcript", "").strip() for r in recs if r.get("transcript")]
    transcript = ""
    if variants:
        for _ in range(3):
            try:
                transcript = compile_down(variants, language=lang_name, script=script,
                                          client=client, instruction=instruction_for(lang_name))
                break
            # Resilience: retry a transient LLM/network failure up to 3x, then give up
            # on this clip without aborting the whole batch.
            except Exception:  # noqa: BLE001, S112
                continue
    # Use the richest run's diarized turns from the service (it serializes "Speaker N"
    # labels). Normalize to the legacy 0-indexed `speaker_N` ids the rest of the pipeline
    # expects (speaker_0 = approacher; consumed by segment + speaker_identity).
    best = max(recs, key=lambda r: len(r.get("turns") or []), default={})
    turns = [
        {"speaker": _speaker_id(t.get("speaker")), "text": str(t.get("text", "")).strip(),
         "start": round(float(t.get("start", 0.0)), 2), "end": round(float(t.get("end", 0.0)), 2)}
        for t in (best.get("turns") or [])
    ]
    speakers = sorted({t["speaker"] for t in turns})

    if table == "sources":
        db.execute(
            "INSERT OR REPLACE INTO sources (id,path,collection,title,kind,lang,duration,"
            "num_speakers,transcript,turns,speakers,cuts,status,processed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'resolved',datetime('now'))",
            (cid, str(v), extra["collection"], v.stem, extra["kind"], lang, duration,
             len(speakers), transcript, json.dumps(turns, ensure_ascii=False),
             json.dumps(speakers), json.dumps(cuts)),
        )
    else:
        db.execute(
            "INSERT OR REPLACE INTO clips (id,creator,source,lang,file_path,duration,"
            "full_transcript,num_speakers,turns,speakers,cuts,status,processed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,'resolved',datetime('now'))",
            (cid, extra["creator"], extra["source"], extra["lang"], str(v), duration,
             transcript, len(speakers), json.dumps(turns, ensure_ascii=False),
             json.dumps(speakers), json.dumps(cuts)),
        )
    db.commit()

    segs = segment_one(turns, cuts, duration)
    db.execute("DELETE FROM segments WHERE source_id=?", (cid,))
    db.executemany(
        "INSERT INTO segments (id,source_id,source_table,idx,start_ms,end_ms,kind,outcome_meta,"
        "outcome_sub,outcome_detail,summary,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
        [(f"{cid}:{i}", cid, table, i, int(s["start"] * 1000), int(s["end"] * 1000),
          s["kind"], s.get("outcome_meta", "na"), s.get("outcome_sub", "na"),
          s.get("outcome_detail", ""), s["summary"]) for i, s in enumerate(segs)],
    )
    db.commit()
    drop_cache(v)  # transcript is persisted; the cached flac is no longer needed
    return f"OK {table} {v.name} -> {len(turns)} turns, {len(cuts)} cuts, {len(segs)} segs"


def scan_roots(root: Path | None) -> list[Path]:
    roots = [root] if root else [COURSES, *[CLIPS_ROOT / d for d in CLIP_DIRS]]
    vids: list[Path] = []
    for r in roots:
        if r.exists():
            vids.extend(r.rglob("*.mp4"))
    return sorted(vids)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--path", nargs="*", default=[])
    ap.add_argument("--root", default="")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--scan-only", action="store_true", help="report new videos, do not process")
    args = ap.parse_args()

    if not args.scan_only:
        # Single-writer lock: a download trigger fires this, and runs must not overlap.
        lock = Path("/tmp/approach-factory.lock").open("w")  # noqa: S108, SIM115  # held for run
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another factory run is active; exiting", flush=True)
            return

    db = sqlite3.connect(args.db, timeout=60)
    db.execute(
        "CREATE TABLE IF NOT EXISTS segments ("
        "id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_table TEXT, idx INTEGER, "
        "start_ms INTEGER, end_ms INTEGER, kind TEXT, outcome_meta TEXT, outcome_sub TEXT, "
        "outcome_detail TEXT, summary TEXT, transcript TEXT, created_at TEXT)"
    )
    ensure_outcome_columns(db)
    db.commit()

    if args.path:
        vids = [Path(p) for p in args.path]
    else:
        vids = scan_roots(Path(args.root) if args.root else None)
    todo = []  # (video, table, extra)
    for v in vids:
        tgt = target_for(v)
        if tgt and not already_done(db, tgt[0], v):
            todo.append((v, tgt[0], tgt[1]))
    print(f"{len(vids)} videos scanned, {len(todo)} new to process", flush=True)
    if args.scan_only:
        for v, t, _ in todo[:50]:
            print(f"  NEW [{t}] {v}")
        if len(todo) > 50:
            print(f"  ... and {len(todo) - 50} more")
        db.close()
        return
    if not todo:
        db.close()
        return
    db.close()

    # 1) extract audio for everything in parallel (ffmpeg, cheap, IO-bound)
    AUD.mkdir(parents=True, exist_ok=True)
    fid2item = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for (v, table, extra), flac in zip(
            todo, pool.map(lambda it: extract_audio(it[0]), todo), strict=True
        ):
            if flac:
                fid2item[flac.stem] = (v, table, extra, flac)
    print(f"extracted {len(fid2item)} audio files", flush=True)

    # 2) batch Scribe per language (one process per pass, high internal concurrency)
    by_lang: dict[str, list[Path]] = {}
    for (_v, _t, extra, flac) in fid2item.values():
        by_lang.setdefault(extra.get("lang", "en"), []).append(flac)
    recs_by_fid: dict[str, list[dict]] = {}
    for lang, flacs in by_lang.items():
        code = scribe_code(lang)
        print(f"scribe: {len(flacs)} files, lang={lang} ({code}), {RUNS}x...", flush=True)
        recs_by_fid.update(batch_scribe(flacs, code, tag=lang))

    # 3) finalize (compile + segment + write) in a thread pool
    tl = threading.local()

    def work(item: tuple) -> str:
        fid, (v, table, extra, _flac) = item
        if not hasattr(tl, "db"):
            tl.db = sqlite3.connect(args.db, timeout=60)
            tl.client = SuperwhisperClient()
        try:
            return finalize_one(tl.db, tl.client, v, table, extra, recs_by_fid.get(fid, []))
        except Exception as e:  # noqa: BLE001
            return f"FAIL {v.name}: {e}"

    n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(work, it): it for it in fid2item.items()}
        for fut in as_completed(futs):
            n += 1
            print(f"[{n}/{len(fid2item)}] {fut.result()}", flush=True)
    print("FACTORY DONE", flush=True)


if __name__ == "__main__":
    main()
