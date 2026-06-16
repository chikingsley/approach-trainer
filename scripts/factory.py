"""Factory: turn a raw video into fully-processed DB rows in one chain.

For each NEW video (not yet in the DB) it runs:
  detect cuts -> extract audio -> 5x diarized Scribe -> compile-down consensus
  -> write parent row (sources|clips) -> cut-aware segmentation -> write child segments.

Root decides the target table:
  /mnt/media/pickup-courses/...            -> sources  (long-form; id = md5(path))
  /mnt/media/.../approach-clips/{ig,ru,yt,douyin}/<creator>/<id>.mp4 -> clips (id = stem)

Usage:
  uv run --project ~/github/approach-trainer scripts/factory.py <db>
  uv run --project ~/github/approach-trainer scripts/factory.py <db> --path FILE ...
  uv run --project ~/github/approach-trainer scripts/factory.py <db> --root DIR
Resumable + idempotent: rows already present are skipped; safe to re-run anytime.
"""

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from omni_curator.create.fuse import compile_down
from superwhisper_api.audio.formats import words_to_turns
from superwhisper_api.languages import language_name, scribe_code, script_of
from superwhisper_api.text.client import SuperwhisperClient

from segment import ensure_outcome_columns, segment_one

COURSES = Path("/mnt/media/pickup-courses")
CLIPS_ROOT = Path("/mnt/media/gmk-server-share/approach-clips")
CLIP_DIRS = ["ig", "ru", "yt", "douyin", "yt-intl"]
AUD = CLIPS_ROOT / "factory-audio"
APPROACH = Path(__file__).resolve().parents[1]
THRESH = 0.3
RUNS = 5
def instruction_for(lang_name: str) -> str:
    return (
        f"Below are several independent ASR hypotheses of the SAME {lang_name} audio (a pickup/"
        "dating coaching video — lecture and/or infield footage). Produce the single most "
        "accurate, verbatim transcript using agreement across hypotheses to fix mishearings and "
        "dropped words. Keep slang and filler. No speaker labels or commentary. Output ONLY the "
        "transcript in <transcript></transcript>."
    )


def fid_of(p: Path) -> str:
    return hashlib.md5(str(p).encode()).hexdigest()


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


def detect_cuts(path: str) -> list[float]:
    try:
        err = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-an",
             "-vf", f"scale=320:-2,select='gt(scene,{THRESH})',showinfo", "-f", "null", "-"],
            capture_output=True, text=True, timeout=900,
        ).stderr
        return [round(float(m), 2) for m in re.findall(r"pts_time:([0-9.]+)", err)]
    except (subprocess.SubprocessError, ValueError):
        return []


def extract_audio(v: Path) -> Path | None:
    AUD.mkdir(parents=True, exist_ok=True)
    flac = AUD / f"{fid_of(v)}.flac"
    if not flac.exists():
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(v), "-vn", "-ac", "1",
                 "-ar", "16000", "-c:a", "flac", str(flac)], check=False, timeout=600,
            )
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0:
            return None
    return flac


def batch_scribe(flacs: list[Path], scribe_code: str, tag: str,
                 max_workers: int = 200) -> dict[str, list[dict]]:
    """Run RUNS diarized Scribe passes over ALL flacs at once (one process per pass,
    high internal concurrency). Returns {flac_stem (= fid): [records across runs]}."""
    paths_file = AUD / f"backlog_{tag}.paths.txt"
    paths_file.write_text("\n".join(str(f) for f in flacs))
    by_fid: dict[str, list[dict]] = {}
    for r in range(RUNS):
        out = AUD / f"backlog_{tag}.run{r}.jsonl"
        subprocess.run(
            ["uv", "run", "--project", str(APPROACH), "superwhisper-audio",
             "--paths-file", str(paths_file),
             "--jsonl", str(out), "--diarize", "--language", scribe_code,
             "--max-workers", str(max_workers)],
            check=False,
        )
        if out.exists():
            for line in out.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("transcript") or not rec.get("error"):
                    by_fid.setdefault(Path(rec["audio_path"]).stem, []).append(rec)
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
            creator = v.relative_to(base).parts[0]
            if d == "yt-intl":
                # folders are slugged "<lang>-<creator>-<videos|shorts>", e.g. es-alvaroreyes-videos
                lang = creator.split("-", 1)[0]  # es/fr/zh/de -> resolve() maps to spa/fra/zho/deu
                return "clips", {"creator": creator, "source": "youtube", "lang": lang}
            source = {"ig": "instagram", "yt": "youtube", "douyin": "douyin"}.get(d, d)
            lang = {"ru": "ru", "douyin": "zh"}.get(d, "en")
            return "clips", {"creator": creator, "source": source, "lang": lang}
    return None


def already_done(db: sqlite3.Connection, table: str, v: Path) -> bool:
    cid = fid_of(v) if table == "sources" else v.stem
    return db.execute(f"SELECT 1 FROM {table} WHERE id=?", (cid,)).fetchone() is not None


def finalize_one(db: sqlite3.Connection, client: SuperwhisperClient, v: Path,
                 table: str, extra: dict, recs: list[dict]) -> str:
    """Given the Scribe records for one video, compile consensus, write the parent
    row, segment, and write child rows. (Scribe already done in batch.)"""
    cid = fid_of(v) if table == "sources" else v.stem
    lang = extra.get("lang", "en")
    lang_name, script = language_name(lang), script_of(lang)

    cuts = detect_cuts(str(v))
    duration = probe_duration(str(v))
    variants = [r.get("transcript", "").strip() for r in recs if r.get("transcript")]
    best = max(recs, key=lambda r: len(r.get("raw_response", {}).get("words", [])), default={})
    words = best.get("raw_response", {}).get("words", [])
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
    turns = [{"speaker": t.speaker, "text": t.text.strip(),
              "start": round(t.start, 2), "end": round(t.end, 2)} for t in words_to_turns(words)]
    speakers = sorted({w.get("speaker_id") for w in words if w.get("type") == "word"})

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
