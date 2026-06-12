#!/bin/bash
# Download shorts/videos from new YouTube channels into the corpus.
# Sequential (never parallel YouTube), flock-guarded, 480p cap, resumable archive.
set -u
exec 9>/tmp/yt_channels.lock; flock -n 9 || { echo "already running"; exit 0; }
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/kasm/chrome-home/.config/google-chrome/Profile 1"
BASE=/mnt/media/gmk-server-share/approach-clips/yt
LOG=/tmp/yt_channels.log
: > "$LOG"; rm -f /tmp/yt_channels.done
log(){ echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

pull() {
  local slug="$1" url="$2"
  mkdir -p "$BASE/$slug"
  log "START $slug <- $url"
  yt-dlp --cookies-from-browser "chrome:$PROFILE" \
    --extractor-args "youtube:player_client=web_safari" \
    -f "bv*[height<=1920]+ba/b[height<=1920]/b" --fragment-retries 5 \
    --download-archive "$BASE/$slug/.archive.txt" \
    --sleep-requests 2 --sleep-interval 3 --ignore-errors \
    -o "$BASE/$slug/%(id)s.%(ext)s" "$url" >> "$LOG" 2>&1
  log "DONE $slug = $(ls $BASE/$slug/*.mp4 2>/dev/null | wc -l) mp4"
}

pull stanis   "https://www.youtube.com/@stanis_1204/shorts"
pull vladradu "https://www.youtube.com/@vladradu1/shorts"
pull vladradu "https://www.youtube.com/@vladradu1/videos"
pull tlizamm  "https://www.youtube.com/@tlizamm/shorts"

echo "DONE stanis=$(ls $BASE/stanis/*.mp4 2>/dev/null|wc -l) vladradu=$(ls $BASE/vladradu/*.mp4 2>/dev/null|wc -l) tlizamm=$(ls $BASE/tlizamm/*.mp4 2>/dev/null|wc -l)" > /tmp/yt_channels.done
