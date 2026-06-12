#!/bin/bash
# Re-process specific clip IDs that were missed (have audio but no DB row).
# Usage: reprocess_ids.sh <creator-dir-name> <id> [<id> ...]
set -u
exec 9>/tmp/reprocess.lock; flock -n 9 || { echo "already running"; exit 0; }
CREATOR="$1"; shift
IG=/mnt/media/gmk-server-share/approach-clips/ig
WORK=/tmp/reprocess
DB="$HOME/github/approach-trainer/data/clips.db"
TAJIK="$HOME/github/peacock-asr/projects/tajik-asr"
mkdir -p "$WORK/runs"; : > "$WORK/paths.txt"; rm -f "$WORK/done"

for id in "$@"; do
  src="$IG/$CREATOR/$id.mp4"
  [ -f "$src" ] || { echo "MISSING $src"; continue; }
  ffmpeg -y -v error -i "$src" -vn -ac 1 -ar 16000 -c:a flac "$WORK/$id.flac" 2>/dev/null
  echo "$WORK/$id.flac" >> "$WORK/paths.txt"
done
echo "audio: $(wc -l < $WORK/paths.txt) clips"

cd "$TAJIK" || exit 1
for r in 0 1 2 3 4; do
  uv run superwhisper-audio --paths-file "$WORK/paths.txt" --jsonl "$WORK/runs/run$r.jsonl" \
    --diarize --language eng --max-workers 4 >/dev/null 2>&1
  echo "run $r: $(wc -l < $WORK/runs/run$r.jsonl 2>/dev/null) results"
done
uv run python "$HOME/github/approach-trainer/scripts/process_full.py" "$WORK/runs" "$DB"
echo "DONE" > "$WORK/done"
