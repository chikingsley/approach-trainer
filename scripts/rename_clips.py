"""Re-run target-name extraction for drill clips missing a name, with LENIENT JSON
parsing (the model wraps JSON in ```json fences, which broke generate_json).

Reuses stored transcripts/turns — no re-transcribing. Updates speakers + turns name fields.
Run:  uv run --project ~/github/approach-trainer scripts/rename_clips.py <db>
"""

import json
import re
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from superwhisper_api.text.client import SuperwhisperClient

WORKERS = 64
APPROACHER = "speaker_0"
_local = threading.local()


def client():
    c = getattr(_local, "c", None)
    if c is None:
        c = _local.c = SuperwhisperClient()
    return c


def parse_lenient(text: str) -> dict[str, Any]:
    """Handle bare JSON, ```json fences, or prose with an embedded object."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        t = m.group(0)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, TypeError):
        return {}


def get_names(
    transcript: str, approacher: str, speakers: list[str], lang: str
) -> dict[str, str]:
    others = [s for s in speakers if s != APPROACHER]
    if not others or not transcript.strip():
        return {}
    note = "The conversation may be in Russian (Cyrillic)." if lang == "ru" else ""
    prompt = (
        f"Diarized transcript of {approacher} (speaker_0) approaching one or more women. {note} "
        f"Speakers: {speakers}. For each NON-approacher speaker ({others}), give their first "
        f"name ONLY if clearly stated in the dialogue (e.g. 'I'm Lexi' / 'меня зовут Аня'). "
        f'Otherwise null. Reply with ONLY a JSON object like {{"speaker_1":"Name or null"}}.'
        f"\n\nTranscript:\n{transcript}"
    )
    for _ in range(2):
        try:
            r = client().generate(
                "claude-sonnet-4-6",
                [{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            data = parse_lenient(r.text)
            if data:
                return {
                    str(k): str(v)
                    for k, v in data.items()
                    if v and str(v).strip().lower() not in ("null", "none", "")
                }
        # Resilience: retry a transient LLM/network failure once, then return {}.
        except Exception:  # noqa: BLE001, S112
            continue
    return {}


def work(row):
    cid, lang, approacher, transcript, turns_json, speakers_json = row
    speakers = json.loads(speakers_json) if speakers_json else {}
    spk_ids = list(speakers.keys())
    found = get_names(transcript or "", approacher, spk_ids, lang)
    if not found:
        return cid, None, None  # nothing to update
    # update speakers map
    for sid, nm in found.items():
        if sid in speakers and sid != APPROACHER:
            speakers[sid]["name"] = nm
    # update turns name fields
    turns = json.loads(turns_json) if turns_json else []
    for t in turns:
        if t.get("speaker") in found and t.get("speaker") != APPROACHER:
            t["name"] = found[t["speaker"]]
    return (
        cid,
        json.dumps(speakers, ensure_ascii=False),
        json.dumps(turns, ensure_ascii=False),
    )


def main() -> None:
    db_path = sys.argv[1]
    db = sqlite3.connect(db_path, timeout=60)
    db.execute("PRAGMA busy_timeout=60000")
    rows = db.execute(
        "SELECT id,lang,approacher_name,full_transcript,turns,speakers FROM clips "
        "WHERE is_drill=1 AND json_extract(speakers,'$.speaker_1.name') IS NULL"
    ).fetchall()
    print(f"re-naming {len(rows)} clips...")
    updated = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(work, r) for r in rows]
        for i, fut in enumerate(as_completed(futs), 1):
            cid, smap, turns = fut.result()
            if smap:
                db.execute(
                    "UPDATE clips SET speakers=?, turns=? WHERE id=?",
                    (smap, turns, cid),
                )
                updated += 1
                if updated % 50 == 0:
                    db.commit()
            if i % 200 == 0:
                print(f"  {i}/{len(rows)} checked, {updated} named", flush=True)
    db.commit()
    db.close()
    print(f"DONE: {updated}/{len(rows)} clips got a target name")


if __name__ == "__main__":
    main()
