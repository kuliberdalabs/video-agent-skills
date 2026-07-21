#!/usr/bin/env bash
# Run generic pre-render and post-render video checks.
set -euo pipefail
export LC_ALL=C

usage() {
  printf '%s\n' 'usage: video_audit.sh pre <clip-list.txt> | post <video-file> [output-directory]'
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi
if [ "$#" -lt 1 ]; then
  usage >&2
  exit 2
fi

mode="$1"
shift

if [ "$mode" = "pre" ]; then
  if [ "$#" -ne 1 ]; then
    usage >&2
    exit 2
  fi
  clip_list="$1"
  [ -f "$clip_list" ] || { printf 'no such list: %s\n' "$clip_list" >&2; exit 1; }
  total=$(awk 'NF { count += 1 } END { print count + 0 }' "$clip_list")
  distinct=$(awk 'NF && !seen[$0]++ { count += 1 } END { print count + 0 }' "$clip_list")
  printf '%s\n' '== PRE-RENDER REVIEW =='
  printf 'clips: %s total / %s distinct\n' "$total" "$distinct"
  if [ "$distinct" -lt "$total" ]; then
    printf 'review: %s repeated reference(s)\n' "$((total - distinct))"
  else
    printf '%s\n' 'review: all references are distinct'
  fi
  printf '%s\n' 'visual review: confirm relevance, variety, and a clear opening and ending.'
  exit 0
fi

if [ "$mode" = "post" ]; then
  if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage >&2
    exit 2
  fi
  video="$1"
  out="${2:-./video-audit-output}"
  [ -f "$video" ] || { printf 'no such video: %s\n' "$video" >&2; exit 1; }
  mkdir -p "$out"
  duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$video")
  dimensions=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$video")
  [ -n "$duration" ] || { printf '%s\n' 'unreadable video input' >&2; exit 1; }
  printf '== POST-RENDER REVIEW: %s ==\n' "$(basename "$video")"
  printf 'duration: %ss; dimensions: %s\n' "$duration" "$dimensions"
  audio=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$video" || true)
  if [ -n "$audio" ]; then
    loudness=$(ffmpeg -nostats -i "$video" -af ebur128 -f null - 2>&1 | grep -E '^\s*I:' | tail -1 | tr -s ' ' || true)
    printf 'loudness: %s\n' "${loudness:-unavailable}"
  else
    printf '%s\n' 'loudness: no audio stream'
  fi
  frozen=$(ffmpeg -i "$video" -vf 'freezedetect=n=-50dB:d=0.5' -map 0:v -f null - 2>&1 | grep -c 'freeze_start' || true)
  printf 'frozen segments: %s\n' "${frozen:-0}"
  ffmpeg -y -sseof -0.15 -i "$video" -frames:v 1 -update 1 "$out/end-frame.png"
  brightness=$(ffmpeg -v error -i "$out/end-frame.png" -vf 'scale=2:2,format=gray' -f rawvideo - 2>/dev/null | od -An -tu1 | awk '{ for (field = 1; field <= NF; field++) { sum += $field; count += 1 } } END { if (count) print int(sum / count); else print -1 }')
  printf 'final-frame brightness: %s/255\n' "$brightness"
  sample_count=20
  sample_rate=$(awk -v count="$sample_count" -v duration="$duration" 'BEGIN { printf "%.3f", (duration > 0) ? count / duration : 1 }')
  ffmpeg -y -i "$video" -vf "fps=${sample_rate},scale=200:356,tile=5x4:padding=3:color=0x333333" -frames:v 1 "$out/contact.png"
  [ -s "$out/contact.png" ] || { printf '%s\n' 'contact sheet was not created' >&2; exit 1; }
  printf 'contact sheet: %s\n' "$out/contact.png"
  printf '%s\n' 'visual review: inspect continuity, repeated material, color consistency, and the ending.'
  exit 0
fi

usage >&2
exit 2
