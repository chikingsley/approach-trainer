#!/bin/bash
set -u
exec 9>/tmp/yt_channels.lock; flock 9   # serialize behind running YouTube jobs
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/docker/kasm/chrome-home/.config/google-chrome/Profile 1"
BASE=/mnt/media/gmk-server-share/approach-clips/yt
LOG=/tmp/yt_sergio.log
: > "$LOG"
rm -f /tmp/yt_sergio.done
count_mp4() {
  find "$1" -maxdepth 1 -type f -name '*.mp4' | wc -l | tr -d ' '
}
mkdir -p "$BASE/sergio-sorokin"
echo "[$(date +%H:%M:%S)] START sergio-sorokin (699 vids)" >> "$LOG"
yt-dlp --cookies-from-browser "chrome:$PROFILE" --extractor-args "youtube:player_client=web_safari" \
  -f "bv*[height<=1920]+ba/b[height<=1920]/b" --fragment-retries 5 --download-archive "$BASE/sergio-sorokin/.archive.txt" \
  --sleep-requests 2 --sleep-interval 3 --ignore-errors \
  -o "$BASE/sergio-sorokin/%(id)s.%(ext)s" "https://www.youtube.com/@sergiosorokin/videos" >> "$LOG" 2>&1
echo "DONE sergio-sorokin = $(count_mp4 "$BASE/sergio-sorokin")" > /tmp/yt_sergio.done
nohup bash "$HOME/github/approach-trainer/scripts/factory_trigger.sh" >/dev/null 2>&1 &
