"""Trial: feed diarized turns + ffmpeg scene-cut timestamps to Sonnet, have it
mark boundaries between fully-separate interactions with a '\\n\\n---\\n\\n' line.
Run:  uv run --project ~/github/approach-trainer scripts/segment_trial.py <clip_id>
"""

import json
import re
import sqlite3
import subprocess
import sys

from superwhisper_api.text.client import SuperwhisperClient

DB = "/home/simon/github/approach-trainer/data/clips.db"


def scene_cuts(path: str, thresh: float = 0.3) -> list[float]:
    out = subprocess.run(
        [
            "ffmpeg",
            "-i",
            path,
            "-vf",
            f"select='gt(scene,{thresh})',metadata=print",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stderr
    return [round(float(m), 1) for m in re.findall(r"pts_time:([0-9.]+)", out)]


def main():
    cid = sys.argv[1]
    db = sqlite3.connect(DB)
    path, turns_json = db.execute(
        "SELECT file_path, turns FROM clips WHERE id=?", (cid,)
    ).fetchone()
    turns = json.loads(turns_json)
    cuts = scene_cuts(path)

    # format turns for the prompt
    lines = []
    for t in turns:
        who = t.get("name") or t["speaker"]
        lines.append(f"[{t['start']:.1f}-{t['end']:.1f}] {who}: {t['text']}")
    turns_block = "\n".join(lines)

    prompt = (
        "Below is a diarized transcript of ONE long street-pickup/prank video that contains "
        "MULTIPLE fully-separate interactions (the creator walks up to different people, one "
        "after another). You also get the hard video-cut timestamps from scene detection.\n\n"
        "TASK: reproduce the turns EXACTLY as given (same order, same text — do not rewrite, "
        "merge, or summarize), but insert a separator line of exactly\n\n---\n\n between turns "
        "that belong to DIFFERENT interactions.\n"
        "SPLIT FINELY: every distinct interaction is its own segment, NO MATTER HOW SHORT. "
        "Each time the creator turns to a NEW person, that is a new segment — even a 2-line "
        "failed approach, even a 3-second brush-off, gets its own block. When in doubt, SPLIT. "
        "Do NOT lump rapid-fire approaches to different people into one block.\n"
        "A new interaction = a fresh approach to a new person (a close/goodbye/rejection, then a "
        "new opener like 'привет/простите/девушка' aimed at someone else). Use the DIALOGUE as "
        "the primary signal; the scene cuts are corroboration — a real boundary usually sits at "
        "or near a cut. Intros/outros/transitions are their own blocks.\n\n"
        f"SCENE CUT TIMESTAMPS (seconds): {cuts}\n\n"
        f"TRANSCRIPT TURNS:\n{turns_block}"
    )
    print(
        f"clip={cid}  turns={len(turns)}  cuts={len(cuts)}  "
        f"prompt_chars={len(prompt)} (~{len(prompt) // 4} tok)\n"
    )
    print(f"CUTS: {cuts}\n{'=' * 70}")
    client = SuperwhisperClient()
    r = client.generate(
        "claude-sonnet-4-6", [{"role": "user", "content": prompt}], max_tokens=6000
    )
    print(r.text)


if __name__ == "__main__":
    main()
