"""Long-form diarized transcription (pickup courses + Julien YT) — SAME method as the
short clips: 5x diarized Scribe -> compile-down consensus -> SQLite. No drill fields
(no opener/pause_at/approacher — those don't apply to lectures). Writes to `sources`.
Resumable via the DB:
  uv run --project ~/github/approach-trainer scripts/transcribe_longform.py
"""

import hashlib
import json
import sqlite3
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from omni_curator.create.fuse import compile_down
from superwhisper_api.audio.formats import words_to_turns
from superwhisper_api.text.client import SuperwhisperClient

ROOT = Path("/mnt/media/pickup-courses")
AUD = Path("/mnt/media/gmk-server-share/approach-clips/course-audio")
DB = str(Path.home() / "github/approach-trainer/data/clips.db")
APPROACH = Path(__file__).resolve().parents[1]
RUNS = 5
WORKERS = 48

EN_INSTRUCTION = (
    "Below are several independent ASR hypotheses of the SAME English audio (a pickup/dating "
    "coaching video — lecture and/or infield footage). Produce the single most accurate, verbatim "
    "transcript using agreement across hypotheses to fix mishearings and dropped words. Keep slang "
    "and filler. No speaker labels or commentary. Output ONLY the transcript in "
    "<transcript></transcript>."
)
_local = threading.local()


def client():
    c = getattr(_local, "c", None)
    if c is None:
        c = _local.c = SuperwhisperClient()
    return c


def fid_of(p: Path) -> str:
    return hashlib.md5(str(p).encode()).hexdigest()


def extract(v: Path):
    flac = AUD / f"{fid_of(v)}.flac"
    if not flac.exists():
        r = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(v),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "flac",
                str(flac),
            ],
            check=False,
        )
        if r.returncode != 0:
            return None
    return str(flac)


def main():
    AUD.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=60)
    done = {r[0] for r in db.execute("SELECT id FROM sources WHERE status='resolved'")}
    vids = [v for v in ROOT.rglob("*.mp4") if fid_of(v) not in done]
    print(f"{len(vids)} videos to transcribe (5x compile-down)", flush=True)
    if not vids:
        return

    # extract audio (parallel) + map
    fid2v = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for v, flac in zip(vids, pool.map(extract, vids), strict=False):
            if flac:
                fid2v[fid_of(v)] = v
    (AUD / "paths.txt").write_text("\n".join(str(AUD / f"{f}.flac") for f in fid2v))
    print(
        f"extracted {len(fid2v)} audio files; running {RUNS}x diarized Scribe...",
        flush=True,
    )

    # 5 diarized Scribe passes (proven batched entry, 200 workers each)
    for r in range(RUNS):
        subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(APPROACH),
                "superwhisper-audio",
                "--paths-file",
                str(AUD / "paths.txt"),
                "--jsonl",
                str(AUD / f"run{r}.jsonl"),
                "--diarize",
                "--language",
                "eng",
                "--max-workers",
                "200",
            ],
            check=False,
        )
        print(f"  scribe run {r} done", flush=True)

    # gather runs per fid
    by_fid = {}
    for r in range(RUNS):
        f = AUD / f"run{r}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("error") and not rec.get("transcript"):
                continue
            by_fid.setdefault(Path(rec["audio_path"]).stem, []).append(rec)

    def process(fid):
        recs = by_fid.get(fid, [])
        v = fid2v[fid]
        variants = [
            r.get("transcript", "").strip() for r in recs if r.get("transcript")
        ]
        best = (
            max(recs, key=lambda r: len(r.get("raw_response", {}).get("words", [])))
            if recs
            else {}
        )
        words = best.get("raw_response", {}).get("words", [])
        resolved = ""
        if variants:
            for _ in range(3):  # retry: a single ReadTimeout must not kill the batch
                try:
                    resolved = compile_down(
                        variants,
                        language="English",
                        script="Latin",
                        client=client(),
                        instruction=EN_INSTRUCTION,
                    )
                    break
                # Resilience: a single ReadTimeout / transient API error must not
                # kill the batch — retry up to 3x, then give up on this clip.
                except Exception:  # noqa: BLE001, S112
                    continue
        turns = [
            {
                "speaker": t.speaker,
                "text": t.text.strip(),
                "start": round(t.start, 2),
                "end": round(t.end, 2),
            }
            for t in words_to_turns(words)
        ]
        speakers = sorted(
            {w.get("speaker_id") for w in words if w.get("type") == "word"}
        )
        rel = v.relative_to(ROOT)
        collection = rel.parts[0] if len(rel.parts) > 1 else "misc"
        kind = "youtube-archive" if "YouTube" in collection else "course"
        return (
            fid,
            (
                fid,
                str(v),
                collection,
                v.stem,
                kind,
                "en",
                round(float(best.get("duration") or 0), 2),
                len(speakers),
                resolved,
                json.dumps(turns, ensure_ascii=False),
                json.dumps(speakers),
                "resolved",
            ),
            [(fid, i, r.get("transcript", "")) for i, r in enumerate(recs)],
        )

    n = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(process, fid): fid for fid in fid2v}
        for fut in as_completed(futs):
            try:
                _fid, row, runs = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  [skip {futs[fut]}: {e}]", flush=True)
                continue
            db.execute(
                """INSERT OR REPLACE INTO sources
                (id,path,collection,title,kind,lang,duration,num_speakers,transcript,turns,speakers,status,processed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                row,
            )
            db.executemany(
                "INSERT OR REPLACE INTO runs (clip_id,run_idx,text,created_at) "
                "VALUES (?,?,?,datetime('now'))",
                runs,
            )
            db.commit()
            n += 1
            if n % 50 == 0:
                print(f"  processed {n}/{len(fid2v)}", flush=True)
    db.close()
    print(f"DONE: {n} long-form sources transcribed -> sources table", flush=True)


if __name__ == "__main__":
    main()
