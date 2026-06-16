#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Build the drill manifest from diarized transcripts.

For each clip: find the approacher (speaker_0, who opens), compute the
pause-point (just before his first word), and collect his opener line.
"""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "clips" / "raw"
TRANSCRIPTS = ROOT / "clips" / "transcripts"
OUT = ROOT / "clips" / "manifest.json"

# The approacher always speaks first in these infield clips.
APPROACHER = "speaker_0"
PRE_ROLL = 0.4  # seconds of lead-in to keep before his first word


def duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return float(out) if out else 0.0


def build_entry(rec: dict) -> dict | None:
    audio_path = Path(rec["audio_path"])
    clip_id = audio_path.stem
    mp4 = RAW / f"{clip_id}.mp4"
    if not mp4.exists():
        return None

    words = [
        w
        for w in rec.get("raw_response", {}).get("words", [])
        if w.get("type") == "word"
    ]
    if not words:
        return None

    his = [w for w in words if w.get("speaker_id") == APPROACHER]
    first = his[0] if his else words[0]
    pause_at = max(0.0, first["start"] - PRE_ROLL)

    # His opener: words until the first reply from anyone else.
    opener = []
    for w in words:
        if w.get("speaker_id") == APPROACHER:
            opener.append(w["text"])
        elif opener:
            break
    opener_text = re.sub(r"\s+([.,!?;:])", r"\1", " ".join(opener)).strip()

    speakers = sorted({w.get("speaker_id") for w in words})
    return {
        "id": clip_id,
        "creator": "itspolokidd",
        "creator_handle": "@itspolokidd",
        "approacher": "Polo (@itspolokidd)",
        "file": f"clips/raw/{clip_id}.mp4",
        "duration": round(duration(mp4), 2),
        "pause_at": round(pause_at, 2),
        "opener": opener_text,
        "full_transcript": rec.get("transcript", "").strip(),
        "num_speakers": len(speakers),
    }


def main() -> None:
    entries = []
    for tfile in TRANSCRIPTS.glob("*.jsonl"):
        for raw in tfile.read_text().splitlines():
            line = raw.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "error" in rec:
                continue
            entry = build_entry(rec)
            if entry:
                entries.append(entry)

    entries.sort(key=lambda e: e["id"])
    OUT.write_text(json.dumps(entries, indent=2))
    print(f"wrote {len(entries)} entries -> {OUT.relative_to(ROOT)}")
    for e in entries:
        print(
            f"  {e['id']}  pause@{e['pause_at']:>5.1f}s  "
            f"{e['num_speakers']}spk  opener: {e['opener'][:60]!r}"
        )


if __name__ == "__main__":
    main()
