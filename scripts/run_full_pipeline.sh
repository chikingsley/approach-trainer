#!/bin/bash
# Full run: wait for audio -> 5 diarized Scribe passes (en + ru, 200 workers)
# -> parallel compile-down/turns/names post-process -> SQLite.
set -u
AUDIO=/mnt/media/gmk-server-share/approach-clips/audio
APPROACH="$HOME/github/approach-trainer"
DB="$HOME/github/approach-trainer/data/clips.db"
mkdir -p /tmp/full/en /tmp/full/ru
: > /tmp/full/pipeline.log
log() { echo "[$(date +%H:%M:%S)] $*" >> /tmp/full/pipeline.log; }

# wait for audio extraction
while [ ! -f "$AUDIO/extract.done" ]; do sleep 20; done
log "audio ready: en=$(wc -l < "$AUDIO/paths_en.txt") ru=$(wc -l < "$AUDIO/paths_ru.txt")"

scribe_lang() {
  local lang="$1" code="$2" paths="$3" outdir="$4"
  [ -s "$paths" ] || { log "$lang: no paths, skip"; return; }
  for r in 0 1 2 3 4; do
    log "$lang scribe run $r start"
      uv run --project "$APPROACH" superwhisper-audio --paths-file "$paths" --jsonl "$outdir/run$r.jsonl" \
        --diarize --language "$code" --max-workers 200 >> /tmp/full/pipeline.log 2>&1
      log "$lang scribe run $r done: $(wc -l < "$outdir/run$r.jsonl" 2>/dev/null) results"
    done
}

scribe_lang en eng "$AUDIO/paths_en.txt" /tmp/full/en
scribe_lang ru rus "$AUDIO/paths_ru.txt" /tmp/full/ru
log "all scribe done; post-processing"

uv run --project "$APPROACH" "$APPROACH/scripts/process_full.py" /tmp/full/en "$DB" >> /tmp/full/pipeline.log 2>&1
uv run --project "$APPROACH" "$APPROACH/scripts/process_full.py" /tmp/full/ru "$DB" >> /tmp/full/pipeline.log 2>&1

TOTAL=$(sqlite3 "$DB" "SELECT count(*) FROM clips;")
DRILLS=$(sqlite3 "$DB" "SELECT count(*) FROM clips WHERE is_drill=1;")
log "PIPELINE COMPLETE: $TOTAL clips, $DRILLS drills"
echo "DONE total=$TOTAL drills=$DRILLS" > /tmp/full/pipeline.done
