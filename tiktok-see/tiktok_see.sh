#!/usr/bin/env bash
# Create a contact sheet and scene-cut summary for one video.
set -euo pipefail
export LC_ALL=C

usage() {
  printf '%s\n' 'usage: tiktok_see.sh <url-or-local-file> [output-directory]'
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage >&2
  exit 2
fi

src="$1"
out="${2:-./video-see-output}"
mkdir -p "$out"

if [[ "$src" =~ ^https?:// ]]; then
  if ! command -v yt-dlp >/dev/null 2>&1; then
    printf '%s\n' 'yt-dlp is required for URL input; save the video locally and use its path instead.' >&2
    exit 1
  fi
  rm -f "$out"/video.*
  printf '%s\n' 'fetching URL with yt-dlp...'
  yt-dlp -o "$out/video.%(ext)s" "$src"
  video=$(find "$out" -maxdepth 1 -type f -name 'video.*' ! -name '*.part' ! -name '*.ytdl' -print -quit)
else
  video="$src"
fi

[ -f "${video:-}" ] || { printf '%s\n' 'no video file found' >&2; exit 1; }

duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$video")
dimensions=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$video")
audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$video" || true)
printf '== %s  %ss  %s  audio:%s ==\n' "$(basename "$video")" "$duration" "$dimensions" "${audio:-none}"

ffmpeg -i "$video" -vf "select='gt(scene,0.3)',showinfo" -an -f null - 2>&1 \
  | grep -oE 'pts_time:[0-9]+\.[0-9]+' | sed 's/pts_time://' | sort -n > "$out/cuts.txt" || true
cut_count=$(wc -l < "$out/cuts.txt" | tr -d ' ')
average=$(awk -v duration="$duration" -v count="$cut_count" 'BEGIN { if (count > 0) printf "%.2f", duration / (count + 1); else print "n/a" }')
printf 'cut cadence: %s cuts; average shot length: %ss\n' "$cut_count" "$average"
printf 'intervals: '
awk 'NR == 1 { previous = 0 } { printf "%.2f ", $1 - previous; previous = $1 } END { print "" }' "$out/cuts.txt"

sample_count=20
sample_rate=$(awk -v count="$sample_count" -v duration="$duration" 'BEGIN { printf "%.3f", (duration > 0) ? count / duration : 1 }')
ffmpeg -y -i "$video" -vf "fps=${sample_rate},scale=200:356,tile=5x4:padding=3:color=0x222222" -frames:v 1 "$out/contact.png"
[ -s "$out/contact.png" ] || { printf '%s\n' 'contact sheet was not created' >&2; exit 1; }
printf 'contact sheet: %s\n' "$out/contact.png"
printf 'cut times: %s\n' "$out/cuts.txt"
