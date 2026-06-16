#!/bin/bash
# Download @nstv69 shorts + videos. Uses BLOCKING flock on the shared YouTube lock,
# so it waits for any running YouTube job to finish (never parallel YouTube).
set -u
exec 9>/tmp/yt_channels.lock; flock 9   # blocking: queue behind current job
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/docker/kasm/chrome-home/.config/google-chrome/Profile 1"
BASE=/mnt/media/gmk-server-share/approach-clips/yt
LOG=/tmp/yt_nstv.log
: > "$LOG"
rm -f /tmp/yt_nstv.done
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
pull nstv-shorts "https://www.youtube.com/@nstv69/shorts"
pull nstv-videos "https://www.youtube.com/@nstv69/videos"
echo "DONE shorts=$(count_mp4 "$BASE/nstv-shorts") videos=$(count_mp4 "$BASE/nstv-videos")" > /tmp/yt_nstv.done
nohup bash "$HOME/github/approach-trainer/scripts/factory_trigger.sh" >/dev/null 2>&1 &
