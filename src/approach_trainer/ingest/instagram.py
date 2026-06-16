"""Instagram ingest via gallery-dl (re-runnable, resumable).

Mirrors the youtube CLI: a small creator registry, a shared resume archive, and
the logged-in cookie jar. gallery-dl tracks already-downloaded posts in its own
SQLite archive (``ig/archive.sqlite``), so re-runs only fetch new posts.

NOTE: unverified end-to-end — IG auth/cookies are finicky. Confirm the cookie file
is fresh and do a ``--limit 1`` run before a full pull.

Usage:
  approach-trainer instagram list
  approach-trainer instagram download [--creator itspolokidd] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import shlex
import subprocess

from approach_trainer.paths import CLIPS_ROOT, PROJECT_ROOT

IG_ROOT = CLIPS_ROOT / "ig"
ARCHIVE = IG_ROOT / "archive.sqlite"
COOKIES = PROJECT_ROOT / ".instagram-cookies.txt"

# Known infield creators already in the library; add handles here to grow it.
CREATORS = ("itspolokidd", "rizzzcam", "tristansocial")


def download_creator(handle: str, *, limit: int | None = None, dry_run: bool = False) -> int:
    """Fetch a creator's IG posts into ig/<handle>/ via gallery-dl (resumable)."""
    dest = IG_ROOT / handle
    cmd = [
        "gallery-dl",
        "--cookies", str(COOKIES),
        "--download-archive", str(ARCHIVE),
        "-D", str(dest),
    ]
    if limit is not None:
        cmd += ["--range", f"1-{limit}"]
    cmd.append(f"https://www.instagram.com/{handle}/")
    if dry_run:
        print(shlex.join(cmd))
        return 0
    return subprocess.run(cmd, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    """CLI: list creators or download one/all via gallery-dl."""
    ap = argparse.ArgumentParser(prog="approach-trainer instagram")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list registered IG creators")
    dl = sub.add_parser("download", help="download IG creator(s)")
    dl.add_argument("--creator", help="one handle; default = all")
    dl.add_argument("--limit", type=int)
    dl.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.command == "list":
        for handle in CREATORS:
            print(handle)
        return 0
    handles = [args.creator] if args.creator else list(CREATORS)
    rc = 0
    for handle in handles:
        rc |= download_creator(handle, limit=args.limit, dry_run=args.dry_run)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
