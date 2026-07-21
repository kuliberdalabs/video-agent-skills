---
name: video-audit
description: Run repeatable pre-render and post-render video quality checks, including a contact sheet for visual review.
---

# video-audit

Use this skill to make video review repeatable before and after a render.

## Pre-render

Create a text file with one clip path per line, then run:

```sh
bash video-audit/video_audit.sh pre <clip-list.txt>
```

It reports the total and distinct clip counts. Review the planned clips for relevance, variety,
and a clear opening and ending.

## Post-render

```sh
bash video-audit/video_audit.sh post <video-file> [output-directory]
```

It reports duration, dimensions, audio availability, integrated loudness when available, frozen
segments, final-frame brightness, and a contact sheet. Read the contact sheet before deciding that
a render is ready: mechanical checks cannot judge visual continuity, repeated material, color
consistency, or an intentional ending.
