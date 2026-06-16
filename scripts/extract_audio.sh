#!/bin/bash
# Extract 16kHz mono FLAC for every clip, organized per creator.
# Builds paths_en.txt and paths_ru.txt for the Scribe runner.
set -u
BASE=/mnt/media/gmk-server-share/approach-clips
AUDIO=$BASE/audio
mkdir -p "$AUDIO"
: > "$AUDIO/paths_en.txt"
: > "$AUDIO/paths_ru.txt"

# source dir | creator-slug | lang
SOURCES="
$BASE/ig/itspolokidd|itspolokidd|en
$BASE/ig/tristansocial|tristansocial|en
$BASE/ig/rizzzcam|rizzzcam|en
$BASE/ig/tristan-youtube|tristan-youtube|en
$HOME/ru-pickup/boryamba|boryamba|ru
$HOME/ru-pickup/pikap-prank-show|pikap-prank-show|ru
$HOME/ru-pickup/my-s-toboy|my-s-toboy|ru
$HOME/ru-pickup/podoydi-k-ney|podoydi-k-ney|ru
"

extract_one() {
  src="$1"; out="$2"
  [ -f "$out" ] && return 0   # resumable: skip done
  ffmpeg -nostdin -y -v error -i "$src" -vn -ac 1 -ar 16000 -c:a flac "$out" 2>/dev/null
}
export -f extract_one

count_flac() {
  find "$1" -maxdepth 1 -type f -name '*.flac' | wc -l | tr -d ' '
}

echo "$SOURCES" | while IFS='|' read -r dir slug lang; do
  [ -z "$dir" ] && continue
  [ -d "$dir" ] || { echo "MISSING dir: $dir"; continue; }
    mkdir -p "$AUDIO/$slug"
    # extract in parallel (8 at a time)
    jobs=0
    while IFS= read -r -d '' f; do
      id=$(basename "$f" .mp4)
      extract_one "$f" "$AUDIO/$slug/$id.flac" &
      jobs=$((jobs + 1))
      if [ "$jobs" -ge 8 ]; then
        wait -n
        jobs=$((jobs - 1))
      fi
    done < <(find "$dir" -name '*.mp4' -print0)
    wait
    # append to language paths file
    find "$AUDIO/$slug" -maxdepth 1 -type f -name '*.flac' | sort >> "$AUDIO/paths_$lang.txt"
    echo "$slug: $(count_flac "$AUDIO/$slug") flac"
done

echo "EN clips: $(wc -l < "$AUDIO/paths_en.txt" | tr -d ' ')  RU clips: $(wc -l < "$AUDIO/paths_ru.txt" | tr -d ' ')"
echo "EXTRACT_DONE" > "$AUDIO/extract.done"
