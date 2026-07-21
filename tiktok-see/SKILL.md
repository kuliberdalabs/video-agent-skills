---
name: tiktok-see
description: Inspect a local video file or a public video URL by creating a contact sheet and cut-cadence summary.
---

# tiktok-see

Use this skill when you need evidence from a video rather than a title or description.

## Use

```sh
bash tiktok-see/tiktok_see.sh <url-or-local-file> [output-directory]
```

- A local file is inspected without network access.
- A public URL is fetched with `yt-dlp` without browser state.

The command prints duration, dimensions, audio availability, a scene-cut summary, and writes a
contact sheet plus `cuts.txt` to the output directory.

## Review

Open the contact sheet and base any visual assessment on the frames it contains. If a URL cannot
be fetched, save the video locally and run the command with that file instead.
