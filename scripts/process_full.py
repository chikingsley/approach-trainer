"""Full-run post-processor: 5-run compile-down + diarized turns + names -> SQLite.

Run inside the tajik-asr uv env:
  cd ~/github/peacock-asr/projects/tajik-asr && uv run python <this> <runs_dir> <db>

<runs_dir> holds run0.jsonl..run4.jsonl from superwhisper-audio --diarize.
Creator/lang are derived per clip from where the mp4 lives (no language arg needed).
"""

import json
import re
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from omni_curator.create.fuse import compile_down
from superwhisper_api.audio.formats import to_markdown, words_to_turns
from superwhisper_api.text.client import SuperwhisperClient

WORKERS = 64
_local = threading.local()


def client_for_thread() -> SuperwhisperClient:
    c = getattr(_local, "client", None)
    if c is None:
        c = _local.client = SuperwhisperClient()
    return c

IG = Path("/mnt/media/gmk-server-share/approach-clips/ig")
RU = Path.home() / "ru-pickup"

# slug -> (approacher display name, handle/channel, source, lang, mp4_dir)
CREATORS = {
    "itspolokidd":     ("Polo", "@itspolokidd", "instagram", "en", IG / "itspolokidd"),
    "tristansocial":   ("Tristan", "@tristansocial", "instagram", "en", IG / "tristansocial"),
    "rizzzcam":        ("Cameron", "@rizzzcam", "instagram", "en", IG / "rizzzcam"),
    "tristan-youtube": ("Tristan", "@tristansocial", "youtube", "en", IG / "tristan-youtube"),
    "boryamba":        ("Борямба", "Борямба", "youtube", "ru", RU / "boryamba"),
    "pikap-prank-show":("Пикап Пранк Шоу", "Пикап Пранк Шоу", "youtube", "ru", RU / "pikap-prank-show"),
    "my-s-toboy":      ("Мы с тобой", "Мы с тобой на ютубе", "youtube", "ru", RU / "my-s-toboy"),
    "podoydi-k-ney":   ("Да подойди", "Да подойди уже к ней!", "youtube", "ru", RU / "podoydi-k-ney"),
}

EN_INSTRUCTION = (
    "Below are several independent ASR hypotheses of the SAME short English audio clip "
    "(a man cold-approaching a woman in public). Produce the single most accurate, verbatim "
    "transcript using agreement across hypotheses and linguistic sense to fix mishearings, "
    "dropped words, and hallucinations. Keep slang and filler as spoken. No speaker labels or "
    "commentary. Output ONLY the transcript inside <transcript></transcript> tags."
)
# Russian: use the package default compile instruction (transliterates to Cyrillic) -> instruction=None

APPROACHER = "speaker_0"
PRE_ROLL = 0.4

# build id -> slug once
def build_index() -> dict[str, str]:
    idx = {}
    for slug, (_, _, _, _, d) in CREATORS.items():
        if d.exists():
            for f in d.glob("*.mp4"):
                idx[f.stem] = slug
    return idx


def turns_from(words, names):
    out = []
    for t in words_to_turns(words):
        out.append({"speaker": t.speaker, "name": names.get(t.speaker),
                    "text": t.text.strip(), "start": round(t.start, 2),
                    "end": round(t.end, 2), "duration": round(t.end - t.start, 2)})
    return out


def pause_and_opener(words):
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
    text = re.sub(r"\s+([.,!?;:])", r"\1", " ".join(opener)).strip()
    return round(pause, 2), text


def extract_names(client, transcript, approacher_name, speakers, lang):
    others = [s for s in speakers if s != APPROACHER]
    if not others or not transcript.strip():
        return {}
    note = "The conversation may be in Russian." if lang == "ru" else ""
    prompt = (
        f"Diarized transcript of {approacher_name} (speaker_0) approaching one or more women. "
        f"{note} Speakers: {speakers}. For each NON-approacher speaker ({others}), give their "
        f"first name ONLY if clearly stated (e.g. 'I'm Lexi' / 'меня зовут...'). Else null. "
        f'Return JSON {{"speaker_1":"Name or null",...}}.\n\n{transcript}'
    )
    try:
        data = client.generate_json("claude-sonnet-4-6", [{"role": "user", "content": prompt}],
                                    max_tokens=300)
        return {k: v for k, v in (data or {}).items() if v and str(v).lower() != "null"}
    except Exception as e:  # noqa: BLE001
        print(f"  [name extract failed: {e}]")
        return {}


def real_word_count(text):
    # words that aren't bracketed sound events like [laughs]
    return len(re.findall(r"\b\w+\b", re.sub(r"\[[^\]]*\]", "", text or "")))


def load_runs(runs_dir):
    by_clip = {}
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


def process_clip(cid, recs, slug):
    """Pure compute (LLM calls) for one clip -> row tuples. Runs in a worker thread."""
    name, handle, source, lang, mdir = CREATORS[slug]
    variants = [r.get("transcript", "").strip() for r in recs if r.get("transcript")]
    best = max(recs, key=lambda r: len(r.get("raw_response", {}).get("words", [])))
    words = best.get("raw_response", {}).get("words", [])
    instr = EN_INSTRUCTION if lang == "en" else None
    script = "Latin" if lang == "en" else "Cyrillic"
    language = "English" if lang == "en" else "Russian"
    client = client_for_thread()
    resolved = compile_down(variants, language=language, script=script,
                            client=client, instruction=instr) if variants else ""
    speakers = sorted({w.get("speaker_id") for w in words if w.get("type") == "word"})
    names = {APPROACHER: name}
    names.update(extract_names(client, resolved or (variants[0] if variants else ""),
                               name, speakers, lang))
    turns = turns_from(words, names)
    pause_at, opener = pause_and_opener(words)
    smap = {APPROACHER: {"name": name, "role": "approacher"}}
    for s in speakers:
        if s != APPROACHER:
            smap[s] = {"name": names.get(s), "role": "target"}
    is_drill = 1 if (len(speakers) >= 2 and real_word_count(resolved) >= 5) else 0
    md = to_markdown(words_to_turns(words)) if words else ""
    clip_row = (cid, slug, handle, source, lang, str(mdir / f"{cid}.mp4"),
                round(float(best.get("duration") or 0), 2), name, handle, APPROACHER,
                pause_at, opener, resolved, len(speakers),
                json.dumps(turns, ensure_ascii=False), json.dumps(smap, ensure_ascii=False),
                md, is_drill, "resolved")
    run_rows = [(cid, i, r.get("transcript", "")) for i, r in enumerate(recs)]
    return clip_row, run_rows


def main():
    runs_dir = Path(sys.argv[1])
    db_path = sys.argv[2]
    by_clip = load_runs(runs_dir)
    index = build_index()
    tasks = [(cid, recs, index[cid]) for cid, recs in by_clip.items() if cid in index]

    db = sqlite3.connect(db_path, timeout=60)
    db.execute("PRAGMA busy_timeout=60000")
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(process_clip, *t): t[0] for t in tasks}
        for fut in as_completed(futs):
            try:
                clip_row, run_rows = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  [clip {futs[fut]} failed: {e}]")
                continue
            db.execute("""INSERT OR REPLACE INTO clips
              (id,creator,creator_handle,source,lang,file_path,duration,
               approacher_name,approacher_handle,approacher_speaker,pause_at,opener,
               full_transcript,num_speakers,turns,speakers,turns_md,is_drill,status,processed_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", clip_row)
            db.executemany("INSERT OR REPLACE INTO runs (clip_id,run_idx,text,created_at) "
                           "VALUES (?,?,?,datetime('now'))", run_rows)
            db.commit()
            done += 1
            if done % 100 == 0:
                print(f"  processed {done}/{len(tasks)} clips...", flush=True)

    db.close()
    print(f"DONE: {done} clips from {runs_dir.name} -> {db_path}")


if __name__ == "__main__":
    main()
