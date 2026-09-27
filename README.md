# video-agent-skills

This project is an open-source video analysis tool. It contains only original source code and standard open-source dependencies. Users are responsible for third-party licenses and Terms of Service.

## Included skills

- `tiktok-see` studies a local video or a public reference you are allowed to watch. It creates a
  transcript when local speech recognition is available, a timecoded contact sheet, hard-cut and
  gradual-transition candidates, and full-resolution evidence frames. Quick, standard, and deep
  modes let you choose the level of detail.
- `video-audit` performs pre-render duplicate checks and post-render media checks, then creates a
  contact sheet for visual review.

## Requirements

- Bash
- FFmpeg, including `ffmpeg` and `ffprobe`
- `yt-dlp` only when using a public URL
- Python 3 with NumPy and Pillow for transition analysis, timecoded sheets, and exact frames
- Optional: `mlx_whisper` for local speech transcription

## Quick start

```sh
bash tiktok-see/tiktok_see.sh ./example.mp4 ./video-see-output
bash tiktok-see/tiktok_see.sh ./example.mp4 ./video-see-output --depth deep --window 0-30
bash video-audit/video_audit.sh pre ./clips.txt
bash video-audit/video_audit.sh post ./example.mp4 ./video-audit-output
```

Run `bash <script> --help` for command usage. Local-file operation does not require network access.
The `tiktok-see` output directory contains `contact.png`, `cuts.txt`, and `soft_cuts.txt`. Standard
mode adds `exact/` frames and labelled sheets; deep mode adds a filmstrip, waveform, and `shots.tsv`.
Speech output is written to `transcript.txt`, `.srt`, and `.json` when recognition succeeds.
Transition lists are candidates to verify against frames before drawing editing conclusions.

## Testing

The tests create a temporary FFmpeg color-bars fixture locally and run both skills against it.

```sh
python3 -m pytest -q
```
