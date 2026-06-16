"""One-time backfill: map the legacy flat `outcome` column on existing segments
to the new meta/sub taxonomy (commitment/engagement/rejection + subcategory).

Deterministic — no LLM. `outcome_detail` is left blank here; it gets populated
going forward by the segmenter, or by a later LLM enrichment pass. The ambiguous
legacy `close` rows are mapped to commitment/contact provisionally and flagged
(detail='review') for manual re-tag.

Run AFTER the factory backlog finishes writing (so all rows are covered):
  uv run --project ~/github/approach-trainer scripts/retag_outcomes.py <db>
"""

import sqlite3
import sys

from segment import ensure_outcome_columns

# legacy outcome -> (meta, sub, detail)
MAP = {
    "number": ("commitment", "contact", ""),
    "instant_date": ("commitment", "date", ""),
    "kiss": ("commitment", "physical", "kiss"),
    "makeout": ("commitment", "physical", "makeout"),
    "pull": ("commitment", "pull", ""),
    "rejection": ("rejection", "soft", ""),
    "blowout": ("rejection", "hard", ""),
    "ongoing": ("engagement", "rapport", ""),
    "na": ("engagement", "unresolved", ""),
    "close": ("commitment", "contact", "review"),  # ambiguous legacy bucket
}


def main() -> None:
    db = sqlite3.connect(sys.argv[1], timeout=60)
    ensure_outcome_columns(db)
    # only touch rows not already on the new scheme
    rows = db.execute(
        "SELECT id, outcome FROM segments WHERE outcome_meta IS NULL AND outcome IS NOT NULL"
    ).fetchall()
    print(f"{len(rows)} legacy segments to remap", flush=True)
    n = 0
    for n, (sid, outcome) in enumerate(rows, start=1):
        meta, sub, detail = MAP.get(outcome, ("na", "na", ""))
        db.execute(
            "UPDATE segments SET outcome_meta=?, outcome_sub=?, outcome_detail=? WHERE id=?",
            (meta, sub, detail, sid),
        )
        if n % 2000 == 0:
            db.commit()
            print(f"  {n}/{len(rows)}", flush=True)
    db.commit()
    print("=== new distribution ===", flush=True)
    for meta, sub, c in db.execute(
        "SELECT outcome_meta, outcome_sub, count(*) FROM segments "
        "GROUP BY outcome_meta, outcome_sub ORDER BY count(*) DESC"
    ):
        print(f"  {meta}/{sub}: {c}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
