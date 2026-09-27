#!/usr/bin/env python3
"""tiktok-see helper: low-contrast cuts and gradual transitions, labelled sheets, exact frames.

Called by tiktok_see.sh; each subcommand also works on its own.

  soft     VIDEO OUTDIR                      -> soft_cuts.txt (reads OUTDIR/cuts.txt)
  contact  VIDEO OUTDIR                      -> contact.png (about 20 frames, aspect kept, timecoded)
  evidence VIDEO OUTDIR --depth standard|deep [--window S-E]
           standard -> exact/*.png (full resolution) + exact-NN.png sheets
           deep     -> also frames at every shot start, filmstrip-NN.png (2 fps),
                       waveform.png, shots.tsv (verified-insert worksheet)

Needs ffmpeg/ffprobe on PATH, numpy and Pillow.
"""
import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 30.0            # analysis rate for the frame-difference pass
SIDE = 64             # analysis frames are SIDE x SIDE grey
CUT_ABS = 8.0         # single-sample jump (mean abs diff, 0-255) to count as a cut
CUT_REL = 4.0         # ... and this many times the local median change
GRAD_ABS = 10.0       # change across GRAD_SPAN seconds to count as gradual
GRAD_REL = 3.0        # ... and this many times the local median of that change
GRAD_SPAN = 0.4       # seconds
GRAD_MAX = 3.0        # longer windows are sustained motion, not transitions
BLACK_LUMA = 14.0     # mean grey level under which a frame counts as black
NEAR_HARD = 0.1       # a soft candidate this close to a cuts.txt entry is the same cut
CLUSTER_GAP = 0.3     # hard cuts closer than this form a micro-cut cluster
LONG_GAP = 4.0        # a stretch longer than this without any boundary gets sampled
GAP_STEP = 1.5
CAPS = {"standard": 48, "deep": 150}
SHEET_LONG = 1560     # long side budget of a labelled sheet, px


# ---------- small utilities ----------

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,start_time",
         "-of", "json", video], capture_output=True, text=True, check=True).stdout
    fmt = json.loads(out).get("format", {})
    dur = float(fmt.get("duration") or 0.0)
    start = float(fmt.get("start_time") or 0.0)
    if start < 0:
        start = 0.0
    return dur, start


def display_size(video):
    """Width and height as displayed: rotation and non-square pixels applied."""
    png = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video, "-frames:v", "1",
         "-vf", "scale=trunc(iw*sar/2)*2:ih,setsar=1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(png)).size


def layout(size, per_sheet):
    """Columns, rows and tile size so a sheet of per_sheet tiles keeps the source aspect."""
    w, h = size
    ar = w / float(h)
    best = None
    for cols in range(1, per_sheet + 1):
        rows = -(-per_sheet // cols)
        tw = SHEET_LONG / cols
        th = tw / ar
        if th * rows > SHEET_LONG:
            th = SHEET_LONG / rows
            tw = th * ar
        area = tw * th * per_sheet / float(cols * rows)  # empty cells count against a layout
        if best is None or area > best[0] + 1e-6:
            best = (area, cols, rows, int(tw) // 2 * 2, int(th) // 2 * 2)
    _, cols, rows, tw, th = best
    return cols, rows, max(tw, 2), max(th, 2)


def font(px):
    path = os.environ.get("TIKTOK_SEE_FONT")
    if path:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def sheets(frames, size, per_sheet, out_prefix, outdir, numbered=True):
    """frames: list of (label, path). Writes <out_prefix>-NN.png, or <out_prefix>.png when not numbered."""
    if not frames:
        return []
    cols, rows, tw, th = layout(size, per_sheet)
    fnt = font(max(11, min(th, tw) // 11))
    pad = 3
    chunks = [frames[i:i + per_sheet] for i in range(0, len(frames), per_sheet)]
    written = []
    for ci, chunk in enumerate(chunks):
        r = -(-len(chunk) // cols) if len(chunks) == 1 else rows
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * pad, r * th + (r + 1) * pad), (34, 34, 34))
        draw = ImageDraw.Draw(sheet)
        for i, (label, path) in enumerate(chunk):
            im = Image.open(path).convert("RGB")
            im.thumbnail((tw, th), Image.LANCZOS)
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + pad)
            sheet.paste(im, (x + (tw - im.width) // 2, y + (th - im.height) // 2))
            lines = [label]
            if draw.textlength(label, font=fnt) > tw - 8 and " " in label:
                lines = label.split(" ", 1)  # time on top, tags below
            ty = y
            for line in lines:
                while len(line) > 1 and draw.textlength(line, font=fnt) > tw - 8:
                    line = line[:-1]
                bbox = draw.textbbox((0, 0), line, font=fnt)
                draw.rectangle([x, ty, x + bbox[2] - bbox[0] + 8, ty + bbox[3] - bbox[1] + 8], fill=(0, 0, 0))
                draw.text((x + 4 - bbox[0], ty + 4 - bbox[1]), line, font=fnt, fill=(255, 220, 0))
                ty += bbox[3] - bbox[1] + 8
        name = f"{out_prefix}-{ci + 1:02d}.png" if numbered else f"{out_prefix}.png"
        path = os.path.join(outdir, name)
        sheet.save(path)
        written.append(path)
    return written


SHOWINFO = re.compile(r"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:(-?[0-9.]+)")


def grab(video, select_expr, outdir, stem, scale=None):
    """Decode once, keep frames matching select_expr, return [(pts_time, path)] in order."""
    os.makedirs(outdir, exist_ok=True)
    tmp = os.path.join(outdir, f".{stem}_%05d.png")
    vf = f"select='{select_expr}',showinfo"
    if scale:
        vf += f",scale={scale[0]}:{scale[1]}:flags=area"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "info", "-y", "-i", video, "-an", "-vf", vf,
         "-fps_mode", "passthrough", "-compression_level", "1", tmp], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-2000:])
        raise SystemExit(f"ffmpeg frame grab failed ({stem})")
    times = [float(m.group(1)) for m in SHOWINFO.finditer(proc.stderr)]
    out = []
    for i, t in enumerate(times, start=1):
        src = tmp % i
        if not os.path.exists(src):
            continue
        dst = os.path.join(outdir, f"{stem}{t:09.3f}.png")
        os.replace(src, dst)
        out.append((t, dst))
    return out


def fmt_t(t, nd=2):
    return f"{t:.{nd}f}s"


def read_cuts(outdir):
    path = os.path.join(outdir, "cuts.txt")
    if not os.path.exists(path):
        return []
    vals = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    vals.append(float(line))
                except ValueError:
                    pass
    return sorted(vals)


def read_soft(outdir):
    path = os.path.join(outdir, "soft_cuts.txt")
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            try:
                rows.append((float(parts[0]), float(parts[1]), parts[2].strip()))
            except (IndexError, ValueError):
                pass
    return rows


# ---------- soft: low-contrast cuts + gradual transitions ----------

def cmd_soft(a):
    dur, start = probe(a.video)
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", a.video, "-an",
         "-vf", f"fps={FPS:g},scale={SIDE}:{SIDE}:flags=area,format=gray",
         "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    raw = proc.stdout.read()
    proc.wait()
    f = np.frombuffer(raw, dtype=np.uint8)
    n = len(f) // (SIDE * SIDE)
    f = f[: n * SIDE * SIDE].reshape(n, SIDE * SIDE)
    hard = read_cuts(a.outdir)
    rows = []
    if n >= 3:
        luma = f.mean(axis=1)
        d1 = np.zeros(n)
        L = max(2, int(round(GRAD_SPAN * FPS)))
        dL = np.zeros(n)
        step = 2000
        for s in range(1, n, step):
            e = min(n, s + step)
            d1[s:e] = np.abs(f[s:e].astype(np.int16) - f[s - 1:e - 1]).mean(axis=1)
        for s in range(L, n, step):
            e = min(n, s + step)
            dL[s:e] = np.abs(f[s:e].astype(np.int16) - f[s - L:e - L]).mean(axis=1)

        def rolling_median(x, half):
            padded = np.pad(x, half, mode="edge")
            win = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
            return np.median(win, axis=1)

        base1 = rolling_median(d1, int(0.5 * FPS))
        baseL = rolling_median(dL, int(2.0 * FPS))
        black = luma < BLACK_LUMA

        def t_of(i):
            return start + i / FPS

        def near_hard(t):
            return any(abs(t - h) <= NEAR_HARD for h in hard)

        # single-sample jumps the 0.3 scene threshold missed
        cut_idx = set()
        for i in range(1, n):
            nb = max(d1[i - 1], d1[i + 1] if i + 1 < n else 0.0)
            if d1[i] >= CUT_ABS and d1[i] >= CUT_REL * max(base1[i], 1.0) and d1[i] >= 2.0 * nb:
                cut_idx.add(i)
                t = t_of(i)
                if near_hard(t):
                    continue
                kind = "cut"
                if black[i] and not black[i - 1]:
                    kind = "cut-to-black"
                elif black[i - 1] and not black[i]:
                    kind = "cut-from-black"
                rows.append((t, t, kind, d1[i]))

        # change spread over several samples (dissolve, fade, whip)
        flag = np.zeros(n, dtype=bool)
        for i in range(L, n):
            if dL[i] < GRAD_ABS or dL[i] < GRAD_REL * max(baseL[i], 1.5):
                continue
            if d1[i - L + 1:i + 1].max() > 0.5 * dL[i]:
                continue
            flag[i] = True
        i = L
        while i < n:
            if not flag[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and (flag[j + 1] or (j + 2 < n and flag[j + 2]) or (j + 3 < n and flag[j + 3])):
                j += 1
            # the flagged run compares each sample with the one L before it, so the
            # transition sits inside [i - L, j]: start shows the old state, end the new one
            s_i, e_i = max(0, i - L), j
            ts, te = t_of(s_i), t_of(e_i)
            if te - ts <= GRAD_MAX and not any(s_i <= c <= e_i for c in cut_idx) \
                    and not any(ts - NEAR_HARD <= h <= te + NEAR_HARD for h in hard):
                l_start = luma[max(0, s_i - L // 2)]
                l_end = luma[min(n - 1, e_i + L // 2)]
                l_min = luma[s_i:e_i + 1].min()
                kind = "gradual"
                if l_min < BLACK_LUMA <= min(l_start, l_end):
                    kind = "fade-through-black"
                elif l_end < BLACK_LUMA <= l_start:
                    kind = "fade-out"
                elif l_start < BLACK_LUMA <= l_end:
                    kind = "fade-in"
                rows.append((ts, te, kind, float(dL[i:j + 1].max())))
            i = j + 1
    rows.sort()
    with open(os.path.join(a.outdir, "soft_cuts.txt"), "w") as fh:
        fh.write("# start\tend\tkind\tscore   (candidates the 0.3 scene pass missed; verify on exact frames)\n")
        for ts, te, kind, sc in rows:
            fh.write(f"{ts:.3f}\t{te:.3f}\t{kind}\t{sc:.1f}\n")
    kinds = {}
    for r in rows:
        kinds[r[2]] = kinds.get(r[2], 0) + 1
    detail = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "none"
    print(f"soft transitions: {len(rows)} ({detail})")


# ---------- contact sheet ----------

def cmd_contact(a):
    dur, start = probe(a.video)
    size = display_size(a.video)
    n = 20
    spacing = max(dur / n, 0.04)
    cols, rows, tw, th = layout(size, n)
    frames = grab(a.video, f"isnan(prev_selected_t)+gte(t-prev_selected_t\\,{spacing:.4f})",
                  os.path.join(a.outdir, ".contact"), "c", scale=(tw, th))[:n]
    written = sheets([(fmt_t(t, 1), p) for t, p in frames], size, n, "contact", a.outdir, numbered=False)
    for _, p in frames:
        os.remove(p)
    try:
        os.rmdir(os.path.join(a.outdir, ".contact"))
    except OSError:
        pass
    orient = "landscape" if size[0] > size[1] else ("portrait" if size[1] > size[0] else "square")
    print(f"contact sheet: {len(frames)} frames, {size[0]}x{size[1]} {orient}, aspect kept")
    return written


# ---------- evidence frames, filmstrip, shots ----------

def parse_window(w, dur):
    if not w:
        return None
    m = re.match(r"^\s*([0-9.]+)\s*-\s*([0-9.]+)\s*$", w)
    if not m:
        raise SystemExit(f"bad --window '{w}', expected START-END in seconds")
    s, e = float(m.group(1)), min(float(m.group(2)), dur)
    if e <= s:
        raise SystemExit(f"bad --window '{w}': end must be after start")
    return s, e


def evidence_times(dur, start, hard, soft, depth, window):
    """Return [(time, tag, priority)] of frames worth pulling at full resolution."""
    want = []
    first = start
    last = max(start, start + dur - 0.05)
    want.append((first, "first", 0))
    want.append((last, "last", 0))
    for ts, te, kind in soft:
        if ts == te:
            if depth == "deep":
                want.append((ts - 0.06, f"before {kind}", 2))
            want.append((ts + 0.03, kind, 2))
        else:
            want.append((ts - 0.05, f"{kind} start", 2))
            want.append(((ts + te) / 2, f"{kind} mid", 2))
            want.append((te + 0.05, f"{kind} end", 2))
    # micro-cut clusters
    for i, c in enumerate(hard):
        prev_gap = c - hard[i - 1] if i > 0 else 99
        next_gap = hard[i + 1] - c if i + 1 < len(hard) else 99
        if min(prev_gap, next_gap) < CLUSTER_GAP:
            eps = min(0.03, next_gap / 2)
            want.append((c + eps, "micro-cut", 3))
            if prev_gap >= CLUSTER_GAP:
                want.append((c - 0.08, "before cluster", 3))
    # long stretches without any detected boundary
    bounds = sorted(set([start] + hard + [ts for ts, te, k in soft] + [start + dur]))
    for a_, b_ in zip(bounds, bounds[1:]):
        if b_ - a_ > LONG_GAP:
            t = a_ + GAP_STEP
            k = 0
            while t < b_ - 0.3 and k < 8:
                want.append((t, f"gap {a_:.1f}-{b_:.1f}", 1))
                t += GAP_STEP
                k += 1
    if depth == "deep":
        edges = sorted(set(hard + [ts for ts, te, k in soft if ts == te] +
                           [te for ts, te, k in soft if ts != te]))
        for i, b_ in enumerate(edges):
            nxt = edges[i + 1] if i + 1 < len(edges) else start + dur
            want.append((b_ + min(0.03, (nxt - b_) / 2), "shot start", 4))
    out = []
    for t, tag, pr in want:
        t = min(max(t, start), last)
        if window and not (window[0] <= t <= window[1]):
            continue
        out.append((t, tag, pr))
    return out


def cmd_evidence(a):
    dur, start = probe(a.video)
    size = display_size(a.video)
    window = parse_window(a.window, start + dur)
    hard = read_cuts(a.outdir)
    soft = read_soft(a.outdir)
    want = evidence_times(dur, start, hard, soft, a.depth, window)
    cap = CAPS[a.depth]
    capped = len(want) > cap
    kept = []
    for pr in sorted(set(x[2] for x in want)):
        group = sorted(x for x in want if x[2] == pr)
        room = cap - len(kept)
        if room <= 0:
            break
        if len(group) > room:  # spread the budget across the timeline, not the first N
            idx = np.unique(np.linspace(0, len(group) - 1, room).round().astype(int))
            group = [group[k] for k in idx]
        kept.extend(group)
    want = kept
    # one frame per distinct request; requests collapse onto the first frame at or after them
    req = sorted(set(round(t, 3) for t, _, _ in want))
    exact_dir = os.path.join(a.outdir, "exact")
    if os.path.isdir(exact_dir):
        for name in os.listdir(exact_dir):
            if name.endswith(".png"):
                os.remove(os.path.join(exact_dir, name))
    terms = []
    for t in req:
        if t <= start + 1e-3:
            terms.append("eq(n\\,0)")
        else:
            terms.append(f"gte(t\\,{t:.3f})*lt(prev_pts*TB\\,{t:.3f})")
    frames = grab(a.video, "+".join(terms), exact_dir, "t") if terms else []
    got = [t for t, _ in frames]
    path_of = {t: p for t, p in frames}
    tags = {}
    for t, tag, _ in want:
        match = next((g for g in got if g >= round(t, 3) - 1e-3), got[-1] if got else None)
        if match is None:
            continue
        tags.setdefault(match, [])
        if tag not in tags[match]:
            tags[match].append(tag)
    for old in os.listdir(a.outdir):
        if re.match(r"^exact(-\d+)?\.png$", old):
            os.remove(os.path.join(a.outdir, old))
    labelled = [(f"{fmt_t(t, 3)} {'/'.join(tags.get(t, []))}", path_of[t]) for t in got]
    written = sheets(labelled, size, 12, "exact", a.outdir)
    with open(os.path.join(a.outdir, "exact.tsv"), "w") as fh:
        fh.write("time\ttags\tframe\n")
        for t in got:
            fh.write(f"{t:.3f}\t{'/'.join(tags.get(t, []))}\t{path_of[t]}\n")
    note = f" (capped at {cap}; narrow with --window)" if capped else ""
    print(f"exact frames: {len(got)} full-res in {exact_dir}{note}; sheets: {len(written)}")

    if a.depth != "deep":
        return
    # filmstrip: 2 fps, timecoded, aspect kept
    fs_win = window or (start, start + dur)
    if not window and dur > 180:
        print("filmstrip: skipped for a video over 180 s; rerun deep with --window START-END")
    else:
        per = 20
        cols, rows, tw, th = layout(size, per)
        expr = (f"between(t\\,{fs_win[0]:.3f}\\,{fs_win[1]:.3f})*"
                f"(isnan(prev_selected_t)+gte(t-prev_selected_t\\,0.5))")
        fdir = os.path.join(a.outdir, ".filmstrip")
        fr = grab(a.video, expr, fdir, "f", scale=(tw, th))
        for old in os.listdir(a.outdir):
            if re.match(r"^filmstrip(-\d+)?\.png$", old):
                os.remove(os.path.join(a.outdir, old))
        fs = sheets([(fmt_t(t, 1), p) for t, p in fr], size, per, "filmstrip", a.outdir)
        for _, p in fr:
            os.remove(p)
        try:
            os.rmdir(fdir)
        except OSError:
            pass
        print(f"filmstrip: {len(fr)} frames at 2 fps over {fs_win[0]:.1f}-{fs_win[1]:.1f}s -> {len(fs)} sheets")
    # waveform
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout.strip()
    if has_audio:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-filter_complex",
                        "aformat=channel_layouts=mono,showwavespic=s=1600x200:colors=white",
                        "-frames:v", "1", os.path.join(a.outdir, "waveform.png")])
    # shots.tsv: one row per detected shot, speech aligned from transcript.json
    words = []
    tj = os.path.join(a.outdir, "transcript.json")
    if os.path.exists(tj):
        try:
            data = json.load(open(tj))
            for seg in data.get("segments", []):
                for w in seg.get("words", []) or []:
                    words.append((float(w.get("start", 0)), str(w.get("word", "")).strip()))
        except (ValueError, OSError):
            words = []
    edges = [(start, "start")]
    for c in hard:
        edges.append((c, "hard-cut"))
    for ts, te, kind in soft:
        edges.append((te, f"soft {kind}"))  # a gradual shot starts once the transition has settled
    edges.sort()
    merged = []
    for t, k in edges:
        if merged and t - merged[-1][0] < 0.02:
            continue
        merged.append((t, k))
    with open(os.path.join(a.outdir, "shots.tsv"), "w") as fh:
        fh.write("n\tstart\tend\tdur\tenters_by\tinsert_candidate\tframe\tspeech\tverified\tnote\n")
        rows_out = 0
        for i, (t, k) in enumerate(merged):
            end = merged[i + 1][0] if i + 1 < len(merged) else start + dur
            if window and (end < window[0] or t > window[1]):
                continue
            d = end - t
            frame = next((p for g, p in frames if t - 1e-3 <= g <= t + max(0.3, d / 2)), "")
            said = " ".join(w for ws, w in words if t <= ws < end)
            cand = "yes" if (d < 1.0 and i > 0) else ""
            fh.write(f"{i + 1}\t{t:.3f}\t{end:.3f}\t{d:.3f}\t{k}\t{cand}\t{frame}\t{said}\t\t\n")
            rows_out += 1
    print(f"shots.tsv: {rows_out} shots (fill 'verified' only after reading the frame)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("soft", "contact", "evidence"):
        p = sub.add_parser(name)
        p.add_argument("video")
        p.add_argument("outdir")
        if name == "evidence":
            p.add_argument("--depth", choices=("standard", "deep"), default="standard")
            p.add_argument("--window", default="")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    {"soft": cmd_soft, "contact": cmd_contact, "evidence": cmd_evidence}[a.cmd](a)


if __name__ == "__main__":
    main()
