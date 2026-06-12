"""Backfill real clip durations via ffprobe (DB duration field is mostly 0 from Scribe).
Run:  python backfill_durations.py <db>
"""
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed


def probe(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return round(float(out), 2) if out else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def main():
    db_path = sys.argv[1]
    db = sqlite3.connect(db_path, timeout=60)
    rows = db.execute("SELECT id, file_path FROM clips").fetchall()
    print(f"probing {len(rows)} clips...")
    results = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        futs = {pool.submit(probe, fp): cid for cid, fp in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            results[futs[fut]] = fut.result()
            if i % 1000 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    db.executemany("UPDATE clips SET duration=? WHERE id=?",
                   [(d, cid) for cid, d in results.items()])
    db.commit()
    got = sum(1 for d in results.values() if d > 0)
    print(f"DONE: {got}/{len(rows)} clips got a real duration")
    db.close()


if __name__ == "__main__":
    main()
