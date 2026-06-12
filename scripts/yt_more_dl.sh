#!/bin/bash
set -u
exec 9>/tmp/yt_channels.lock; flock 9   # serialize behind running YouTube jobs
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/kasm/chrome-home/.config/google-chrome/Profile 1"
BASE=/mnt/media/gmk-server-share/approach-clips/yt
LOG=/tmp/yt_more.log; : > "$LOG"; rm -f /tmp/yt_more.done
log(){ echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }
pull(){ local slug="$1" url="$2"; mkdir -p "$BASE/$slug"; log "START $slug"
  yt-dlp --cookies-from-browser "chrome:$PROFILE" --extractor-args "youtube:player_client=web_safari" \
    -f "bv*[height<=1920]+ba/b[height<=1920]/b" --fragment-retries 5 --download-archive "$BASE/$slug/.archive.txt" \
    --sleep-requests 2 --sleep-interval 3 --ignore-errors -o "$BASE/$slug/%(id)s.%(ext)s" "$url" >> "$LOG" 2>&1
  log "DONE $slug = $(ls $BASE/$slug/*.mp4 2>/dev/null|wc -l)"; }
pull benseda-shorts "https://www.youtube.com/@realbenjaminseda/shorts"
pull benseda-videos "https://www.youtube.com/@realbenjaminseda/videos"
pull socialanimal   "https://www.youtube.com/@socialanimal/videos"
pull sergio-sorokin "https://youtu.be/b6aOuT3EWk0"
echo "DONE" > /tmp/yt_more.done
