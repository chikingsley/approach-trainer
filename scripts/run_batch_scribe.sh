#!/bin/bash
# Extract audio for a small batch and run 5 diarized Scribe passes.
set -u
IG=/mnt/media/gmk-server-share/approach-clips/ig
OUT=/tmp/batch1
mkdir -p "$OUT/audio"
: > "$OUT/paths.txt"

# 5 English clips: 2 polo, 2 tristan, 1 rizzzcam
{
  ls "$IG"/itspolokidd/*.mp4 | head -2
  ls "$IG"/tristansocial/*.mp4 | head -2
  ls "$IG"/rizzzcam/*.mp4 | head -1
} > "$OUT/clips.txt"

while read -r c; do
  id=$(basename "$c" .mp4)
  ffmpeg -y -v error -i "$c" -vn -ac 1 -ar 16000 -c:a flac "$OUT/audio/$id.flac" 2>/dev/null
  echo "$OUT/audio/$id.flac" >> "$OUT/paths.txt"
done < "$OUT/clips.txt"
echo "audio extracted: $(wc -l < "$OUT/paths.txt" | tr -d ' ') clips"

cd ~/github/peacock-asr/projects/tajik-asr || exit 1
for r in 0 1 2 3 4; do
  timeout 400 uv run superwhisper-audio --paths-file "$OUT/paths.txt" \
    --jsonl "$OUT/run$r.jsonl" --diarize --language eng --max-workers 5 >/dev/null 2>&1
  echo "run $r: $(wc -l < "$OUT/run$r.jsonl" 2>/dev/null | tr -d ' ') results"
done
echo "SCRIBE_DONE" > "$OUT/scribe.done"
