# video-agent-skills

This project is an open-source video analysis tool. It contains only original source code and standard open-source dependencies. Users are responsible for third-party licenses and Terms of Service.

## Included skills

- `tiktok-see` creates a contact sheet and scene-cut summary from a local video file or a public
  video URL.
- `video-audit` performs pre-render duplicate checks and post-render media checks, then creates a
  contact sheet for visual review.

## Requirements

- Bash
- FFmpeg, including `ffmpeg` and `ffprobe`
- `yt-dlp` only when using a public URL

## Quick start

```sh
bash tiktok-see/tiktok_see.sh ./example.mp4 ./video-see-output
bash video-audit/video_audit.sh pre ./clips.txt
bash video-audit/video_audit.sh post ./example.mp4 ./video-audit-output
```

Run `bash <script> --help` for command usage. Local-file operation does not require network access.

## Testing

The tests create a temporary FFmpeg color-bars fixture locally and run both skills against it.

```sh
python3 -m pytest -q
```
