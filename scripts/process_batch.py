"""Process a batch of clips: 5-run compile-down + diarized turns + names -> SQLite.

Run inside the tajik-asr uv env (has omni_curator + superwhisper_api):
  cd ~/github/peacock-asr/projects/tajik-asr && uv run python <this> <runs_dir> <db>

Expects <runs_dir>/run0.jsonl .. run4.jsonl produced by:
  superwhisper-audio --paths-file paths.txt --jsonl runN.jsonl --diarize --language eng
"""

import json
import sqlite3
import sys
from pathlib import Path

from omni_curator.create.fuse import compile_down
from superwhisper_api.audio.formats import words_to_turns
from superwhisper_api.text.client import SuperwhisperClient

IG = Path("/mnt/media/gmk-server-share/approach-clips/ig")

# creator -> (display name, handle, source, lang). approacher is always speaker_0.
CREATORS = {
    "itspolokidd": ("Polo", "@itspolokidd", "instagram", "en"),
    "tristansocial": ("Tristan", "@tristansocial", "instagram", "en"),
    "rizzzcam": ("Cameron", "@rizzzcam", "instagram", "en"),
}

# English consensus fusion (NOT transliteration — that default is for Cyrillic/Tajik).
EN_INSTRUCTION = (
    "Below are several independent ASR hypotheses of the SAME short English audio clip "
    "(a man cold-approaching a woman in public). Produce the single most accurate, verbatim "
    "transcript by using agreement across hypotheses and linguistic sense to fix mishearings, "
    "dropped words, and hallucinations. Keep slang and filler as spoken. Do not add speaker "
    "labels or commentary. Output ONLY the transcript inside <transcript></transcript> tags."
)

APPROACHER = "speaker_0"
PRE_ROLL = 0.4


def find_creator(clip_id: str) -> str | None:
    for c in CREATORS:
        if (IG / c / f"{clip_id}.mp4").exists():
            return c
    return None


def load_runs(runs_dir: Path) -> dict[str, list[dict]]:
    """clip_id -> list of run records (each: {transcript, raw_response})."""
    by_clip: dict[str, list[dict]] = {}
    for rf in sorted(runs_dir.glob("run*.jsonl")):
        for line in rf.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if "error" in rec and not rec.get("transcript"):
                continue
            cid = Path(rec["audio_path"]).stem
            by_clip.setdefault(cid, []).append(rec)
    return by_clip


def turns_from(words: list[dict], names: dict[str, str]) -> list[dict]:
    out = []
    for t in words_to_turns(words):
        out.append({
            "speaker": t.speaker,
            "name": names.get(t.speaker),
            "text": t.text.strip(),
            "start": round(t.start, 2),
            "end": round(t.end, 2),
            "duration": round(t.end - t.start, 2),
        })
    return out


def pause_and_opener(words: list[dict]) -> tuple[float, str]:
    w = [x for x in words if x.get("type") == "word"]
    his = [x for x in w if x.get("speaker_id") == APPROACHER]
    first = his[0] if his else (w[0] if w else None)
    pause = max(0.0, float(first["start"]) - PRE_ROLL) if first else 0.0
    opener = []
    for x in w:
        if x.get("speaker_id") == APPROACHER:
            opener.append(x["text"])
        elif opener:
            break
    import re
    text = re.sub(r"\s+([.,!?;:])", r"\1", " ".join(opener)).strip()
    return round(pause, 2), text


def extract_names(client: SuperwhisperClient, transcript: str, approacher_name: str,
                  speakers: list[str]) -> dict[str, str]:
    """Ask the LLM which non-approacher speakers reveal a name. speaker_0 = approacher."""
    others = [s for s in speakers if s != APPROACHER]
    if not others:
        return {}
    prompt = (
        f"This is a diarized transcript of a man ({approacher_name}, speaker_0) approaching "
        f"one or more women. Speakers present: {speakers}. For each NON-approacher speaker "
        f"({others}), give their first name ONLY if it is clearly stated in the conversation "
        f"(e.g. she says 'I'm Lexi'). If a name is not stated, use null. "
        f'Return JSON: {{"speaker_1": "Name or null", ...}}.\n\nTranscript:\n{transcript}'
    )
    try:
        data = client.generate_json("claude-sonnet-4-6", [{"role": "user", "content": prompt}],
                                    max_tokens=300)
        return {k: v for k, v in data.items() if v and str(v).lower() != "null"}
    except Exception as e:  # noqa: BLE001
        print(f"  [name extract failed: {e}]")
        return {}


def main() -> None:
    runs_dir = Path(sys.argv[1])
    db_path = sys.argv[2]
    by_clip = load_runs(runs_dir)
    client = SuperwhisperClient()
    db = sqlite3.connect(db_path)

    for cid, recs in by_clip.items():
        creator = find_creator(cid)
        if not creator:
            print(f"SKIP {cid}: creator not found")
            continue
        name, handle, source, lang = CREATORS[creator]
        variants = [r.get("transcript", "").strip() for r in recs if r.get("transcript")]
        # representative run = the one with the most words (richest diarization)
        best = max(recs, key=lambda r: len(r.get("raw_response", {}).get("words", [])))
        words = best.get("raw_response", {}).get("words", [])

        resolved = compile_down(variants, language="English", script="Latin",
                                client=client, instruction=EN_INSTRUCTION) if variants else ""
        speakers = sorted({w.get("speaker_id") for w in words if w.get("type") == "word"})
        names = {APPROACHER: name}
        names.update(extract_names(client, resolved or variants[0], name, speakers))
        turns = turns_from(words, names)
        pause_at, opener = pause_and_opener(words)
        speaker_map = {APPROACHER: {"name": name, "role": "approacher"}}
        for s in speakers:
            if s != APPROACHER:
                speaker_map[s] = {"name": names.get(s), "role": "target"}

        db.execute("""INSERT OR REPLACE INTO clips
          (id,creator,creator_handle,source,lang,file_path,duration,
           approacher_name,approacher_handle,approacher_speaker,
           pause_at,opener,full_transcript,num_speakers,turns,speakers,status,processed_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", (
            cid, creator, handle, source, lang,
            str(IG / creator / f"{cid}.mp4"),
            round(float(best.get("duration") or 0), 2),
            name, handle, APPROACHER,
            pause_at, opener, resolved, len(speakers),
            json.dumps(turns, ensure_ascii=False),
            json.dumps(speaker_map, ensure_ascii=False),
            "resolved",
        ))
        for i, r in enumerate(recs):
            db.execute("INSERT OR REPLACE INTO runs (clip_id,run_idx,text,created_at) "
                       "VALUES (?,?,?,datetime('now'))", (cid, i, r.get("transcript", "")))
        db.commit()

        # ---- inspection print ----
        print(f"\n{'='*70}\n{creator}/{cid}  ({len(variants)} runs, {len(speakers)} speakers)")
        print(f"  pause_at={pause_at}s  opener: {opener!r}")
        print(f"  names: {names}")
        print(f"  RESOLVED: {resolved[:220]}")
        print("  TURNS:")
        for t in turns[:8]:
            who = t["name"] or t["speaker"]
            print(f"    [{t['start']:>5.1f}-{t['end']:>5.1f}s {t['duration']:>4.1f}s] {who}: {t['text'][:80]}")

    db.close()
    print(f"\nDone: {len(by_clip)} clips -> {db_path}")


if __name__ == "__main__":
    main()
