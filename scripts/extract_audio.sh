#!/bin/bash
# Extract 16kHz mono FLAC for every clip, organized per creator.
# Builds paths_en.txt and paths_ru.txt for the Scribe runner.
set -u
BASE=/mnt/media/gmk-server-share/approach-clips
AUDIO=$BASE/audio
mkdir -p "$AUDIO"
rm -f "$AUDIO/paths_en.txt" "$AUDIO/paths_ru.txt"

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
  ffmpeg -y -v error -i "$src" -vn -ac 1 -ar 16000 -c:a flac "$out" 2>/dev/null
}
export -f extract_one

echo "$SOURCES" | while IFS='|' read -r dir slug lang; do
  [ -z "$dir" ] && continue
  [ -d "$dir" ] || { echo "MISSING dir: $dir"; continue; }
  mkdir -p "$AUDIO/$slug"
  # extract in parallel (8 at a time)
  find "$dir" -name '*.mp4' -print0 | while IFS= read -r -d '' f; do
    id=$(basename "$f" .mp4)
    echo "$f|$AUDIO/$slug/$id.flac"
  done | xargs -P 8 -d '\n' -I {} bash -c 'p="{}"; extract_one "${p%%|*}" "${p##*|}"'
  # append to language paths file
  ls "$AUDIO/$slug"/*.flac 2>/dev/null >> "$AUDIO/paths_$lang.txt"
  echo "$slug: $(ls $AUDIO/$slug/*.flac 2>/dev/null | wc -l | tr -d ' ') flac"
done

echo "EN clips: $(wc -l < $AUDIO/paths_en.txt | tr -d ' ')  RU clips: $(wc -l < $AUDIO/paths_ru.txt | tr -d ' ')"
echo "EXTRACT_DONE" > "$AUDIO/extract.done"
