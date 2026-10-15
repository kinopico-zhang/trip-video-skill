#!/usr/bin/env python3
"""Adjacent-frame MAD flicker check -- PIL only (no numpy on this box).

Downsamples every frame to 192x108 grayscale, diffs each frame against the
previous, and reports the mean-absolute-difference statistics.  This is the
flicker gate used across the trip-video pipeline (v7-v17).

Calibration (measured on real ES cloud renders, 1080p30):
  median ~ 7    static scene / healthy motion
  20 - 27       inherent staircase of 0.43-per-frame log-zoom steps (OK)
  > 40          flicker -- investigate before encoding

usage: python3 mad_check.py <frames_dir> [--win 30] [--top 5]
  <frames_dir>  directory of f%05d.jpg (0- or 1-indexed, auto-detected)
  --win N       per-window size in frames (default 30 = 1 second @30fps)
  --top N       how many worst windows to list (default 5)
Env: PYTHONPATH must reach PIL (e.g. PYTHONPATH=~/workspace/google-earth/pylibs).
"""
import os
import sys

from PIL import Image, ImageChops

W, H = 192, 108


def mad(a, b):
    """Mean absolute difference of two same-size L images (0-255 scale)."""
    h = ImageChops.difference(a, b).histogram()   # 256 bins
    total = sum(h)
    return sum(i * n for i, n in enumerate(h)) / total


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    d = sys.argv[1]
    win = 30
    top = 5
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--win" and i + 1 < len(args):
            win = int(args[i + 1])
        if a == "--top" and i + 1 < len(args):
            top = int(args[i + 1])

    # 0-indexed dirs contain f00001 as well, so f00000 is the discriminator
    zero = os.path.exists(os.path.join(d, "f00000.jpg"))
    if not zero and not os.path.exists(os.path.join(d, "f00001.jpg")):
        sys.exit("no f%05d.jpg found in " + d)

    files = []
    i = 0 if zero else 1
    while True:
        p = os.path.join(d, "f%05d.jpg" % i)
        if not os.path.exists(p):
            break
        files.append(p)
        i += 1
    if len(files) < 2:
        sys.exit("need >= 2 frames")

    diffs = []
    prev = None
    for p in files:
        im = Image.open(p).convert("L").resize((W, H))
        if prev is not None:
            diffs.append(mad(prev, im))
        prev = im

    diffs_sorted = sorted(diffs)
    n = len(diffs)

    def pct(q):
        return diffs_sorted[min(n - 1, int(q * n))]

    print("frames %d  diffs %d  (%s)" % (len(files), n, d))
    print("median %.1f  mean %.1f  p90 %.1f  p99 %.1f  max %.1f"
          % (pct(0.5), sum(diffs) / n, pct(0.9), pct(0.99), diffs_sorted[-1]))
    print("gate: median<=14 pass / 20-27 log-zoom staircase / >40 flicker")

    # per-window medians, worst first
    wins = []
    for s in range(0, n, win):
        chunk = diffs[s:s + win]
        if chunk:
            chunk_s = sorted(chunk)
            wins.append((chunk_s[len(chunk_s) // 2], s, s + len(chunk),
                         chunk_s[-1]))
    wins.sort(reverse=True)
    print("worst %d windows (frame ranges are diff indices):" % min(top, len(wins)))
    for med, s, e, mx in wins[:top]:
        flag = "  <-- CHECK" if med > 27 else ""
        print("  [%5d,%5d) median %5.1f max %5.1f%s" % (s, e, med, mx, flag))


if __name__ == "__main__":
    main()
