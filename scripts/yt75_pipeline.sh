#!/bin/bash
# Wait for Tristan-YT re-download, then extract -> 5x diarized Scribe -> process into DB.
set -u
SRC=/mnt/media/gmk-server-share/approach-clips/ig/tristan-youtube
AUD=/tmp/yt75/audio
DB="$HOME/github/approach-trainer/data/clips.db"
TAJIK="$HOME/github/peacock-asr/projects/tajik-asr"
mkdir -p "$AUD" /tmp/yt75/runs
: > /tmp/yt75/pipe.log
log() { echo "[$(date +%H:%M:%S)] $*" >> /tmp/yt75/pipe.log; }

while [ ! -f /tmp/ytredl.done ]; do sleep 30; done
log "download done: $(ls $SRC/*.mp4 2>/dev/null | wc -l) mp4"

: > "$AUD/paths.txt"
for f in "$SRC"/*.mp4; do
  [ -e "$f" ] || continue
  id=$(basename "$f" .mp4)
  [ -f "$AUD/$id.flac" ] || ffmpeg -y -v error -i "$f" -vn -ac 1 -ar 16000 -c:a flac "$AUD/$id.flac" 2>/dev/null
  echo "$AUD/$id.flac" >> "$AUD/paths.txt"
done
log "audio: $(wc -l < $AUD/paths.txt) clips"

cd "$TAJIK" || exit 1
for r in 0 1 2 3 4; do
  uv run superwhisper-audio --paths-file "$AUD/paths.txt" --jsonl "/tmp/yt75/runs/run$r.jsonl" \
    --diarize --language eng --max-workers 64 >> /tmp/yt75/pipe.log 2>&1
  log "scribe run $r: $(wc -l < /tmp/yt75/runs/run$r.jsonl 2>/dev/null)"
done
uv run python "$HOME/github/approach-trainer/scripts/process_full.py" /tmp/yt75/runs "$DB" >> /tmp/yt75/pipe.log 2>&1

N=$(sqlite3 "$DB" "SELECT count(*) FROM clips WHERE creator='tristan-youtube';")
log "DONE: tristan-youtube in DB = $N"
echo "DONE tristan_youtube=$N" > /tmp/yt75/pipe.done
