#!/bin/bash
# Download the 75 Tristan-YouTube clips, then extract -> 5x diarized Scribe -> process into DB.
# Single self-contained run, guarded by flock so it can NEVER run twice.
set -u
# --- single-instance guard ---
exec 9>/tmp/yt75.lock
if ! flock -n 9; then echo "another yt_complete already running; exiting"; exit 0; fi
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/kasm/chrome-home/.config/google-chrome/Profile 1"
SRC=/mnt/media/gmk-server-share/approach-clips/ig/tristan-youtube
AUD=/tmp/yt75/audio
DB="$HOME/github/approach-trainer/data/clips.db"
TAJIK="$HOME/github/peacock-asr/projects/tajik-asr"
mkdir -p "$SRC" "$AUD" /tmp/yt75/runs
: > /tmp/yt75/complete.log
log() { echo "[$(date +%H:%M:%S)] $*" >> /tmp/yt75/complete.log; }
rm -f /tmp/yt75/complete.done

log "download start (single-format -f b to dodge fragment 403s)"
yt-dlp --cookies-from-browser "chrome:$PROFILE" \
  --extractor-args "youtube:player_client=web_safari" \
  -f "best[height<=480]/b[height<=480]/b" \
  --download-archive "$SRC/.archive.txt" \
  --sleep-requests 2 --sleep-interval 3 --ignore-errors \
  -o "$SRC/%(id)s.%(ext)s" \
  "https://www.youtube.com/channel/UCjmuJK0k3gjYeNR25ZzUMpQ/videos" >> /tmp/yt75/complete.log 2>&1
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
    --diarize --language eng --max-workers 64 >> /tmp/yt75/complete.log 2>&1
  log "scribe run $r: $(wc -l < /tmp/yt75/runs/run$r.jsonl 2>/dev/null)"
done
uv run python "$HOME/github/approach-trainer/scripts/process_full.py" /tmp/yt75/runs "$DB" >> /tmp/yt75/complete.log 2>&1

N=$(sqlite3 "$DB" "SELECT count(*) FROM clips WHERE creator='tristan-youtube';")
log "DONE tristan-youtube in DB = $N"
echo "DONE tristan_youtube=$N" > /tmp/yt75/complete.done
