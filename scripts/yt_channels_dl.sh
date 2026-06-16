#!/bin/bash
# Download shorts/videos from new YouTube channels into the corpus.
# Sequential (never parallel YouTube), flock-guarded, 480p cap, resumable archive.
set -u
exec 9>/tmp/yt_channels.lock; flock -n 9 || { echo "already running"; exit 0; }
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/docker/kasm/chrome-home/.config/google-chrome/Profile 1"
BASE=/mnt/media/gmk-server-share/approach-clips/yt
LOG=/tmp/yt_channels.log
: > "$LOG"
rm -f /tmp/yt_channels.done
log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

count_mp4() {
  find "$1" -maxdepth 1 -type f -name '*.mp4' | wc -l | tr -d ' '
}

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
    log "DONE $slug = $(count_mp4 "$BASE/$slug") mp4"
}

pull stanis   "https://www.youtube.com/@stanis_1204/shorts"
pull vladradu "https://www.youtube.com/@vladradu1/shorts"
pull vladradu "https://www.youtube.com/@vladradu1/videos"
pull tlizamm  "https://www.youtube.com/@tlizamm/shorts"

echo "DONE stanis=$(count_mp4 "$BASE/stanis") vladradu=$(count_mp4 "$BASE/vladradu") tlizamm=$(count_mp4 "$BASE/tlizamm")" > /tmp/yt_channels.done
nohup bash "$HOME/github/approach-trainer/scripts/factory_trigger.sh" >/dev/null 2>&1 &
