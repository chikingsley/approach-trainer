"""Backfill real clip durations via ffprobe (DB duration field is mostly 0 from Scribe).
Run:  uv run --project ~/github/approach-trainer approach-trainer durations <db>
"""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def probe(path: str) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        return round(float(out), 2) if out else 0.0
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def backfill(db: sqlite3.Connection, table: str, pathcol: str) -> None:
    rows = db.execute(
        f"SELECT id, {pathcol} FROM {table} "
        f"WHERE (duration IS NULL OR duration<=0) AND {pathcol} IS NOT NULL"
    ).fetchall()
    print(f"{table}: probing {len(rows)} rows missing duration...")
    if not rows:
        return
    results = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        futs = {pool.submit(probe, fp): cid for cid, fp in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            results[futs[fut]] = fut.result()
            if i % 1000 == 0:
                print(f"  {table}: {i}/{len(rows)}", flush=True)
    db.executemany(
        f"UPDATE {table} SET duration=? WHERE id=?",
        [(d, cid) for cid, d in results.items()],
    )
    db.commit()
    got = sum(1 for d in results.values() if d > 0)
    print(f"DONE {table}: {got}/{len(rows)} got a real duration")


def main() -> None:
    db_path = sys.argv[1]
    db = sqlite3.connect(db_path, timeout=60)
    backfill(db, "clips", "file_path")
    backfill(db, "sources", "path")
    db.close()


if __name__ == "__main__":
    main()
