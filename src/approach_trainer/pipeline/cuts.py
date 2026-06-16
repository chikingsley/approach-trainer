"""Run ffmpeg scene-cut detection on EVERY video (clips + long-form sources) and store
the cut timestamps (JSON array of seconds) in the DB. Downscales to 320w for speed
(cuts are global frame changes — detected fine at low res). Resumable: skips rows that
already have cuts. Re-run anytime as new videos land.
  uv run --project ~/github/approach-trainer approach-trainer cuts
"""

import json
import re
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from approach_trainer.paths import DEFAULT_DB

DB = str(DEFAULT_DB)
THRESH = 0.3
WORKERS = 6


def detect_cuts(path: str) -> list[float] | None:
    if not Path(path).exists():
        return None
    try:
        err = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                path,
                "-an",
                "-vf",
                f"scale=320:-2,select='gt(scene,{THRESH})',showinfo",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=900,
        ).stderr
        return [round(float(m), 2) for m in re.findall(r"pts_time:([0-9.]+)", err)]
    except (subprocess.SubprocessError, ValueError):
        return None


def run(table: str, pathcol: str) -> None:
    db = sqlite3.connect(DB, timeout=60)
    rows = db.execute(
        f"SELECT id, {pathcol} FROM {table} WHERE cuts IS NULL AND {pathcol} IS NOT NULL"
    ).fetchall()
    print(f"{table}: {len(rows)} videos need cut detection", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(detect_cuts, p): cid for cid, p in rows}
        for fut in as_completed(futs):
            cuts = fut.result()
            if cuts is not None:
                db.execute(
                    f"UPDATE {table} SET cuts=? WHERE id=?",
                    (json.dumps(cuts), futs[fut]),
                )
                done += 1
                if done % 200 == 0:
                    db.commit()
                    print(f"  {table}: {done}/{len(rows)}", flush=True)
    db.commit()
    db.close()
    print(f"DONE {table}: {done} videos got cuts", flush=True)


def main() -> None:
    run("clips", "file_path")
    run("sources", "path")
    print("ALL CUTS DONE", flush=True)


if __name__ == "__main__":
    main()
