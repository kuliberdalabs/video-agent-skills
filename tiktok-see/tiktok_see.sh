#!/usr/bin/env bash
# tiktok-see: inspect a local video or a public reference.
# Usage: tiktok_see.sh <url-or-localfile> [outdir] [--depth quick|standard|deep] [--window START-END]
#
# Env:
#   TIKTOK_SEE_DEPTH                 quick | standard (default) | deep
#   TIKTOK_SEE_WINDOW                START-END seconds; limits exact frames, filmstrip and shots.tsv
#   TIKTOK_SEE_TRANSCRIBE=0          skip transcription (visual-only on request)
#   TIKTOK_SEE_MODEL                 mlx_whisper model (default mlx-community/whisper-large-v3-turbo)
#   TIKTOK_SEE_PYTHON                python3 with numpy + Pillow (default: python3 on PATH)
set -uo pipefail
export LC_ALL=C
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SRC=""; OUT=""
DEPTH="${TIKTOK_SEE_DEPTH:-standard}"
WINDOW="${TIKTOK_SEE_WINDOW:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --depth) DEPTH="${2:-}"; shift 2 ;;
    --depth=*) DEPTH="${1#--depth=}"; shift ;;
    --window) WINDOW="${2:-}"; shift 2 ;;
    --window=*) WINDOW="${1#--window=}"; shift ;;
    -h|--help) echo 'usage: tiktok_see.sh <public-url-or-local-file> [output-directory] [--depth quick|standard|deep] [--window START-END]'; exit 0 ;;
    *) if [[ -z "$SRC" ]]; then SRC="$1"; elif [[ -z "$OUT" ]]; then OUT="$1"; else echo "ERROR: unexpected argument: $1" >&2; exit 2; fi; shift ;;
  esac
done
[[ -n "$SRC" ]] || { echo "usage: tiktok_see.sh <url|localfile> [outdir] [--depth quick|standard|deep] [--window S-E]"; exit 1; }
case "$DEPTH" in quick|standard|deep) ;; *) echo "ERROR: --depth must be quick, standard or deep"; exit 1 ;; esac
OUT="${OUT:-./video-see-output}"; mkdir -p "$OUT"
TRANSCRIBE="${TIKTOK_SEE_TRANSCRIBE:-1}"
WHISPER_MODEL="${TIKTOK_SEE_MODEL:-mlx-community/whisper-large-v3-turbo}"
PY="${TIKTOK_SEE_PYTHON:-$(command -v python3 || true)}"
HAVE_PY=0
if [[ -n "$PY" ]] && "$PY" -c 'import numpy, PIL' >/dev/null 2>&1; then HAVE_PY=1; fi

# ---------- fetch ----------
if [[ "$SRC" =~ ^https?:// ]]; then
  if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "ERROR: yt-dlp not installed. Install it, or pass a local video file you are allowed to use."; exit 1
  fi
  rm -f "$OUT"/video.* 2>/dev/null
  LOG="$OUT/download.log"; : > "$LOG"
  echo "fetching a working copy for local analysis via yt-dlp (log: $LOG); do not redistribute it"
  if yt-dlp --ignore-config --no-playlist --no-progress -S "res:1080,ext:mp4:m4a" --merge-output-format mp4 \
       -o "$OUT/video.%(ext)s" "$SRC" >>"$LOG" 2>&1; then
    echo "fetch: ok"
  else
    echo "ERROR: public URL fetch failed; see $LOG" >&2
    exit 1
  fi
  V=$(ls -t "$OUT"/video.* 2>/dev/null | grep -viE '\.(part|ytdl|log)$' | head -1)
else
  V="$SRC"
fi
[ -f "$V" ] || { echo "ERROR: no video file found"; exit 1; }

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$V" 2>/dev/null)
DIMS=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$V" 2>/dev/null)
HASA=$(ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$V" 2>/dev/null | head -1)
echo "== $(basename "$V")   ${DUR}s   ${DIMS}   audio:${HASA:-none}   depth:${DEPTH} =="

# ---------- hard cuts (scene > 0.3) ----------
ffmpeg -i "$V" -vf "select='gt(scene,0.3)',showinfo" -an -f null - 2>&1 \
  | grep -oE "pts_time:[0-9]+\.[0-9]+" | sed 's/pts_time://' | sort -n > "$OUT/cuts.txt"
NC=$(wc -l < "$OUT/cuts.txt" | tr -d ' ')
AVG=$(awk -v d="${DUR:-0}" -v n="$NC" 'BEGIN{if(n>0)printf "%.2fs", d/(n+1); else print "n/a"}')
echo "hard cuts (scene>0.3): ${NC}   avg shot ~ ${AVG}"
printf "intervals: "; awk 'NR==1{p=0} {printf "%.2f ",$1-p; p=$1} END{print ""}' "$OUT/cuts.txt"

# ---------- soft transitions: low-contrast cuts, dissolves, fades ----------
rm -f "$OUT/soft_cuts.txt"
if [[ "$HAVE_PY" == 1 ]]; then
  "$PY" "$HERE/see.py" soft "$V" "$OUT" || echo "WARN: soft-transition pass failed"
else
  echo "WARN: ${PY:-python3} lacks numpy/Pillow; falling back to a lower-threshold scene pass (dissolves may still hide)"
  ffmpeg -i "$V" -vf "select='gt(scene,0.12)',showinfo" -an -f null - 2>&1 \
    | grep -oE "pts_time:[0-9]+\.[0-9]+" | sed 's/pts_time://' | sort -n \
    | awk -v cf="$OUT/cuts.txt" 'BEGIN{while((getline c < cf)>0) h[++n]=c; print "# start\tend\tkind\tscore   (lower-threshold fallback; verify on exact frames)"}
        {near=0; for(i=1;i<=n;i++) if($1-h[i]<=0.1 && h[i]-$1<=0.1) near=1; if(!near) printf "%s\t%s\tcut?\t\n",$1,$1}' \
    > "$OUT/soft_cuts.txt"
  echo "soft transitions: $(grep -vc '^#' "$OUT/soft_cuts.txt") (fallback)"
fi
NS=$(grep -vc '^#' "$OUT/soft_cuts.txt" 2>/dev/null)
TOT=$((NC + ${NS:-0}))
AVG2=$(awk -v d="${DUR:-0}" -v n="$TOT" 'BEGIN{if(n>0)printf "%.2fs", d/(n+1); else print "n/a"}')
echo "visual boundaries (hard + soft candidates): ${TOT}   avg state ~ ${AVG2}"

# ---------- contact sheet (aspect kept, timecoded) ----------
rm -f "$OUT/contact.png"
if [[ "$HAVE_PY" == 1 ]]; then
  "$PY" "$HERE/see.py" contact "$V" "$OUT" || echo "WARN: contact sheet failed"
else
  N=20; FPSV=$(awk -v n=$N -v d="${DUR:-20}" 'BEGIN{printf "%.3f",(d>0)?n/d:1}')
  ffmpeg -y -i "$V" -vf "fps=${FPSV},scale=356:356:force_original_aspect_ratio=decrease,pad=356:356:(ow-iw)/2:(oh-ih)/2:color=0x222222,tile=5x4:padding=3:color=0x222222" \
    -frames:v 1 "$OUT/contact.png" 2>/dev/null
  echo "contact sheet: fallback, letterboxed cells, no timecodes"
fi

# ---------- transcript ----------
rm -f "$OUT/transcript.txt" "$OUT/transcript.srt" "$OUT/transcript.vtt" \
  "$OUT/transcript.tsv" "$OUT/transcript.json"
if [[ -n "${HASA:-}" && "$TRANSCRIBE" != "0" ]]; then
  if command -v mlx_whisper >/dev/null 2>&1; then
    echo "transcribing speech locally (auto-language, word timestamps)..."
    if mlx_whisper "$V" \
      --model "$WHISPER_MODEL" \
      --output-name transcript \
      --output-dir "$OUT" \
      --output-format all \
      --word-timestamps True \
      --verbose False >"$OUT/transcribe.log" 2>&1; then
      if [[ -s "$OUT/transcript.txt" ]]; then
        WORDS=$(wc -w < "$OUT/transcript.txt" | tr -d ' ')
        echo "transcript: ${WORDS} words (timings in transcript.srt / transcript.json)"
      else
        echo "WARN: audio exists, but no speech was detected; inspect $OUT/transcribe.log"
      fi
    else
      echo "WARN: transcription failed; visual analysis is still available. See $OUT/transcribe.log"
    fi
  else
    echo "WARN: audio exists, but mlx_whisper is unavailable; no transcript was created"
  fi
elif [[ "$TRANSCRIBE" == "0" ]]; then
  echo "transcription skipped (TIKTOK_SEE_TRANSCRIBE=0)"
fi

# ---------- exact frames, filmstrip, shots (standard / deep) ----------
rm -f "$OUT"/exact.png "$OUT"/exact-*.png "$OUT/exact.tsv" "$OUT/shots.tsv" "$OUT/waveform.png" \
  "$OUT"/filmstrip.png "$OUT"/filmstrip-*.png "$OUT"/exact/t*.png 2>/dev/null
if [[ "$DEPTH" != "quick" ]]; then
  if [[ "$HAVE_PY" == 1 ]]; then
    if [[ -n "$WINDOW" ]]; then
      "$PY" "$HERE/see.py" evidence "$V" "$OUT" --depth "$DEPTH" --window "$WINDOW" || echo "WARN: evidence pass failed"
    else
      "$PY" "$HERE/see.py" evidence "$V" "$OUT" --depth "$DEPTH" || echo "WARN: evidence pass failed"
    fi
  else
    echo "WARN: exact frames need python3 with numpy + Pillow (set TIKTOK_SEE_PYTHON)."
    echo "      Pull them manually: ffmpeg -ss <t> -i '$V' -frames:v 1 <out>.png."
  fi
fi

[[ -s "$OUT/contact.png" && -f "$OUT/cuts.txt" && -f "$OUT/soft_cuts.txt" ]] || {
  echo "ERROR: core analysis output is incomplete" >&2
  exit 1
}
if [[ "$HAVE_PY" == 1 && "$DEPTH" != "quick" && ! -f "$OUT/exact.tsv" ]]; then
  echo "ERROR: exact frame output is incomplete" >&2
  exit 1
fi

# ---------- what to read ----------
any_exists() { local f; for f in "$@"; do [[ -e "$f" ]] && return 0; done; return 1; }
echo
echo "READ, in this order ($OUT):"
if [[ -s "$OUT/transcript.txt" ]]; then
  echo "  transcript.txt            what is said (timings: transcript.srt, transcript.json)"
fi
echo "  contact.png               ~20 evenly spaced frames; navigation only"
if any_exists "$OUT"/exact.png "$OUT"/exact-*.png; then
  echo "  exact*.png                full-res frames at soft transitions, long gaps, micro-cut clusters (index exact.tsv, files exact/)"
fi
if any_exists "$OUT"/filmstrip.png "$OUT"/filmstrip-*.png; then
  echo "  filmstrip*.png            2 fps timecoded strip (deep)"
fi
if [[ -s "$OUT/shots.tsv" ]]; then
  echo "  shots.tsv                 one row per shot with frame + speech; fill 'verified' for the insert list"
fi
echo "  cuts.txt / soft_cuts.txt  hard cuts / candidates the 0.3 pass misses"
