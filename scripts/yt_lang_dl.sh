#!/bin/bash
set -u
exec 9>/tmp/yt_channels.lock; flock 9   # serialize behind running YouTube jobs
export PATH="$HOME/.deno/bin:$HOME/.local/bin:$PATH"
PROFILE="/home/simon/docker/kasm/chrome-home/.config/google-chrome/Profile 1"
BASE=/mnt/media/gmk-server-share/approach-clips/yt-intl
LOG=/tmp/yt_lang.log
: > "$LOG"
rm -f /tmp/yt_lang.done
log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

count_mp4() {
  find "$1" -maxdepth 1 -type f -name '*.mp4' | wc -l | tr -d ' '
}

pull() {
  local slug="$1" url="$2"
  mkdir -p "$BASE/$slug"
  log "START $slug"
  yt-dlp --cookies-from-browser "chrome:$PROFILE" --extractor-args "youtube:player_client=web_safari" \
    -f "bv*[height<=1920]+ba/b[height<=1920]/b" --fragment-retries 5 --download-archive "$BASE/$slug/.archive.txt" \
    --sleep-requests 2 --sleep-interval 3 --ignore-errors -o "$BASE/$slug/%(id)s.%(ext)s" "$url" >> "$LOG" 2>&1
  log "DONE $slug = $(count_mp4 "$BASE/$slug")"
}
# each channel: videos + shorts
for c in \
  "es-alvaroreyes|https://www.youtube.com/@alvarodaygame" \
  "es-adrianbravo|https://www.youtube.com/@AdrianBravo" \
  "es-seduccionperu|https://www.youtube.com/@SeduccionPeru" \
  "fr-fabricejulien|https://www.youtube.com/channel/UCP5yyxM2OM8b9f2KrOAbWnw" \
  "fr-clementrodriguez|https://www.youtube.com/channel/UC6O0lDfMTGGkap-AsSScj9w" \
  "fr-dragueurdeparis|https://www.youtube.com/channel/UCFoJeNmQDRRXWsR59AxJpsQ" \
  "zh-chris|https://www.youtube.com/channel/UCF9qiA5T-QH8kVA0t_Vhluw" \
  "zh-mikey|https://www.youtube.com/@pick-up_Mikey" \
  "zh-ryan|https://www.youtube.com/channel/UCpDr5JQrC7lX-VKq2AXm-5g" \
  "de-flirtprofis|https://www.youtube.com/channel/UCJL3zoFiQW0wOT4-e56R2VQ" \
  "de-abdel|https://www.youtube.com/channel/UCBkQzss2PPoiYVS8iuMCT_g" \
  "de-flirtempire|https://www.youtube.com/c/FlirtEmpire" ; do
    slug="${c%%|*}"; base="${c##*|}"
    pull "$slug-videos" "$base/videos"
    pull "$slug-shorts" "$base/shorts"
done
echo "DONE intl channels" > /tmp/yt_lang.done
nohup bash "$HOME/github/approach-trainer/scripts/factory_trigger.sh" >/dev/null 2>&1 &
