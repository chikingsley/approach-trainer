"""Cut-aware segmentation (call 2): split a transcribed source/clip into discrete
segments using diarized turns + stored scene cuts, and write child rows with
start/end offsets into the `segments` table (virtual slicing — no files cut).

Continuous monologue/lecture rows get a single full-span segment with no LLM call.
Dialogue-rich / multi-cut rows are sent to Sonnet for interaction boundaries.

Run in the approach-trainer uv env:
  uv run --project ~/github/approach-trainer approach-trainer segment <db> [--table sources|clips]
    [--ids a,b,c] [--limit N] [--dry-run]
"""

import argparse
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from superwhisper_api.text.client import SuperwhisperClient

MODEL = "claude-sonnet-4-6"
WORKERS = 16
_local = threading.local()


def client() -> SuperwhisperClient:
    c = getattr(_local, "c", None)
    if c is None:
        c = _local.c = SuperwhisperClient()
    return c


def ensure_outcome_columns(db: sqlite3.Connection) -> None:
    """Add the meta/sub/detail outcome columns to a pre-existing segments table."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(segments)")}
    for col in ("outcome_meta", "outcome_sub", "outcome_detail"):
        if col not in cols:
            db.execute(f"ALTER TABLE segments ADD COLUMN {col} TEXT")
    db.commit()
KINDS = ["interaction", "lecture", "intro", "outro", "breakdown", "transition"]
# Two-level outcome taxonomy (interactions only; everything else is meta="na").
# meta -> allowed subcategories:
OUTCOME_SUBS = {
    "commitment": ["contact", "date", "physical", "pull"],
    "engagement": ["rapport", "unresolved"],
    "rejection": ["soft", "hard", "non_responsive"],
    "na": ["na"],
}
META = list(OUTCOME_SUBS)
SUBS = sorted({s for subs in OUTCOME_SUBS.values() for s in subs})
SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "start time in seconds"},
                    "end": {"type": "number", "description": "end time in seconds"},
                    "kind": {"type": "string", "enum": KINDS},
                    "outcome_meta": {"type": "string", "enum": META},
                    "outcome_sub": {"type": "string", "enum": SUBS},
                    "outcome_detail": {"type": "string",
                                       "description": "short reason/specifics, e.g. 'boyfriend', "
                                                      "'in a rush', 'number+IG', '' if n/a"},
                    "summary": {"type": "string", "description": "one concise line"},
                },
                "required": ["start", "end", "kind", "outcome_meta", "outcome_sub", "summary"],
            },
        }
    },
    "required": ["segments"],
}

PROMPT = (
    "You are segmenting ONE pickup/dating coaching video into discrete segments. It may be "
    "infield footage (a man approaching multiple different people, one after another), a "
    "lecture/monologue, a hot-seat breakdown (coach + student dialogue), or a mix.\n\n"
    "You are given the diarized transcript turns (each with [start-end] seconds) and the hard "
    "scene-cut timestamps from video scene detection.\n\n"
    "TASK: return a list of NON-OVERLAPPING segments covering the timeline in order. For each:\n"
    "- start/end in seconds (use turn timestamps; a real infield boundary usually sits at or "
    "near a scene cut, so use cuts as corroboration).\n"
    "- kind: 'interaction' = one approach to one person; 'lecture'/'breakdown' = teaching/talk; "
    "'intro'/'outro'/'transition' = framing.\n"
    "- outcome_meta + outcome_sub (interactions ONLY; everything else meta='na', sub='na'):\n"
    "    commitment → contact (number/IG/handle) | date (meet now/soon) | physical (kiss/makeout) "
    "| pull (leaves venue → private)\n"
    "    engagement → rapport (good convo, no ask made) | "
    "unresolved (cut away mid-flow, no result)\n"
    "    rejection  → soft (polite no/excuse) | hard (hostile/told to leave/group blocks) | "
    "non_responsive (ignored, no engagement)\n"
    "- outcome_detail: a few words on the specifics/reason — e.g. 'boyfriend', 'in a rush', "
    "'language barrier', 'number + Instagram', 'makeout' — or '' if not applicable.\n"
    "- summary: one concise line.\n\n"
    "SPLIT FINELY for infield: every distinct approach to a NEW person is its own segment, no "
    "matter how short (even a 3-second brush-off). When in doubt, SPLIT. Do NOT split a single "
    "continuous lecture/monologue — that is ONE segment spanning the whole thing.\n\n"
    "OUTPUT: return ONLY a JSON object (no prose, no markdown fences) of the form\n"
    '{{"segments":[{{"start":<seconds>,"end":<seconds>,"kind":"<kind>",'
    '"outcome_meta":"<commitment|engagement|rejection|na>","outcome_sub":"<sub>",'
    '"outcome_detail":"<short reason or empty>","summary":"<one line>"}}]}}\n\n'
    "SCENE CUTS (seconds): {cuts}\n\nTRANSCRIPT TURNS:\n{turns}"
)


def turns_block(turns: list[dict]) -> str:
    out = []
    for t in turns:
        who = t.get("name") or t.get("speaker") or "?"
        out.append(f"[{t.get('start', 0):.1f}-{t.get('end', 0):.1f}] {who}: {t.get('text', '')}")
    return "\n".join(out)


def is_worthy(turns: list[dict], cuts: list, duration: float) -> bool:
    """Dialogue-rich (>=4 turns/min) or visually busy (>=5 cuts) => LLM-segment."""
    if duration <= 0:
        return len(turns) > 8
    return (len(turns) * 60.0 / duration >= 4) or (len(cuts) >= 5)


def segment_one(turns: list[dict], cuts: list, duration: float) -> list[dict]:
    if not turns or not is_worthy(turns, cuts, duration):
        end = duration or (turns[-1].get("end", 0) if turns else 0)
        kind = "interaction" if turns and len(turns) > 4 else "lecture"
        return [{"start": 0.0, "end": float(end), "kind": kind, "outcome_meta": "na",
                 "outcome_sub": "na", "outcome_detail": "",
                 "summary": "(single full-span segment)"}]
    msg = PROMPT.format(cuts=cuts, turns=turns_block(turns))
    res = client().generate_json(MODEL, [{"role": "user", "content": msg}],
                                 schema=SCHEMA, max_tokens=8000)
    return res.get("segments", []) if isinstance(res, dict) else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--table", default="sources", choices=["sources", "clips"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db, timeout=60)
    db.execute(
        "CREATE TABLE IF NOT EXISTS segments ("
        "id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_table TEXT, idx INTEGER, "
        "start_ms INTEGER, end_ms INTEGER, kind TEXT, outcome_meta TEXT, outcome_sub TEXT, "
        "outcome_detail TEXT, summary TEXT, transcript TEXT, created_at TEXT)"
    )
    ensure_outcome_columns(db)
    db.execute("CREATE INDEX IF NOT EXISTS idx_seg_source ON segments(source_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_seg_meta ON segments(outcome_meta)")
    db.commit()

    titlecol = "title" if args.table == "sources" else "creator"
    q = f"SELECT id, {titlecol}, duration, turns, cuts FROM {args.table}"
    if args.ids:
        ids = args.ids.split(",")
        q += f" WHERE id IN ({','.join('?' * len(ids))})"
        rows = db.execute(q, ids).fetchall()
    else:
        q += " WHERE id NOT IN (SELECT DISTINCT source_id FROM segments)"
        if args.limit:
            q += f" LIMIT {args.limit}"
        rows = db.execute(q).fetchall()

    print(f"{len(rows)} {args.table} rows to segment "
          f"(workers={args.workers}, dry_run={args.dry_run})", flush=True)
    lock = threading.Lock()
    done = 0

    def work(row: tuple) -> tuple:
        cid, title, duration, turns_json, cuts_json = row
        turns = json.loads(turns_json) if turns_json else []
        cuts = json.loads(cuts_json) if cuts_json else []
        return cid, title, duration or 0, segment_one(turns, cuts, duration or 0)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(work, r): r for r in rows}
        for fut in as_completed(futs):
            try:
                cid, title, duration, segs = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  [skip {futs[fut][0][:12]}: {e}]", flush=True)
                continue
            kinds = ",".join(sorted({s["kind"] for s in segs}))
            done += 1
            print(f"[{done}/{len(rows)}] {title[:55]} ({duration / 60:.1f}m) "
                  f"-> {len(segs)} segs [{kinds}]", flush=True)
            if args.dry_run:
                for s in segs:
                    print(f"    [{s['start']:.0f}-{s['end']:.0f}s] {s['kind']}/"
                          f"{s.get('outcome_meta')}.{s.get('outcome_sub')}"
                          f"({s.get('outcome_detail', '')}): {s['summary']}")
                continue
            with lock:
                db.execute("DELETE FROM segments WHERE source_id=?", (cid,))
                db.executemany(
                    "INSERT INTO segments (id, source_id, source_table, idx, start_ms, end_ms, "
                    "kind, outcome_meta, outcome_sub, outcome_detail, summary, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                    [(f"{cid}:{i}", cid, args.table, i, int(s["start"] * 1000),
                      int(s["end"] * 1000), s["kind"], s.get("outcome_meta", "na"),
                      s.get("outcome_sub", "na"), s.get("outcome_detail", ""), s["summary"])
                     for i, s in enumerate(segs)],
                )
                db.commit()
    db.close()


if __name__ == "__main__":
    main()
