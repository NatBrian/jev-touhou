#!/usr/bin/env python3
"""detect_gameplay_start.py — find the first replay (gameplay) frame in a
taisei gdigrab capture, using frame-to-frame motion.

The capture is: [loading/title (static)] -> [stage gameplay (high motion)]
-> [clear screen (static)].  Replay frame 0 == stage frame 0 == the first
sustained high-motion frame.

Usage:
  python tools\\detect_gameplay_start.py <capture.mp4> [--secs 60] [--out-dir simdata/cache]

Prints the detected start frame (in capture frame numbers) and saves preview
PNGs around it for visual confirmation.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image

CAP_W, CAP_H = 1280, 720
# analyze at 1/4 res for speed
SM_W, SM_H = 320, 180


def stream_frames(path, max_frames):
    """Yield (frame_index, small_uint8_array) by piping raw rgb24 from ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", path,
        "-vf", f"scale={SM_W}:{SM_H}",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_size = SM_W * SM_H * 3
    idx = 0
    try:
        while idx < max_frames:
            buf = proc.stdout.read(frame_size)
            if len(buf) < frame_size:
                break
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(SM_H, SM_W, 3)
            yield idx, arr
            idx += 1
    finally:
        proc.stdout.close()
        proc.terminate()


def detect_start(path, max_frames, out_dir):
    diffs = []
    prev = None
    frames_cache = {}
    for i, arr in stream_frames(path, max_frames):
        g = arr.mean(axis=2)  # grayscale
        if prev is not None:
            diffs.append(float(np.abs(g - prev).mean()))
        else:
            diffs.append(0.0)
        prev = g
        frames_cache[i] = arr

    n = len(diffs)
    if n < 120:
        print("ERROR: not enough frames", n)
        sys.exit(1)

    # baseline = median of the first 30 diffs (loading screen, mostly static)
    base = float(np.median(diffs[:30]))
    # threshold: a frame is "motion" if its diff is well above baseline
    thr = max(base * 4.0, base + 6.0)

    # find first index where diff > thr AND the following 30-frame window is
    # also high (sustained motion => gameplay, not a one-frame flash)
    start = None
    for i in range(30, n - 40):
        if diffs[i] > thr:
            win = diffs[i:i + 30]
            if float(np.mean(win)) > thr * 0.8:
                start = i
                break

    print(f"frames_analyzed = {n}")
    print(f"baseline_diff   = {base:.2f}")
    print(f"threshold       = {thr:.2f}")
    print(f"DETECTED_START  = {start}")

    # save a motion profile + previews for confirmation
    prof = np.array(diffs)
    Image.fromarray((np.clip(prof / max(prof.max(), 1e-6) * 255, 0, 255)).astype(np.uint8)
                    .repeat(SM_H, axis=0)).save(os.path.join(out_dir, "motion_profile.png"))

    if start is not None:
        for off in (-30, -15, -8, -4, -2, 0, 2, 4, 8, 15, 30):
            j = start + off
            if 0 <= j in frames_cache:
                big = Image.fromarray(frames_cache[j]).resize(CAP_W, CAP_H, Image.BILINEAR)
                big.save(os.path.join(out_dir, f"start_preview_{j:+06d}.png"))
        # report the diffs around the start
        lo, hi = max(0, start - 20), min(n, start + 20)
        print("diffs around start:")
        for j in range(lo, hi):
            mark = " <-- G0" if j == start else ""
            print(f"  f{j:6d}  {diffs[j]:8.2f}{mark}")

    # also save a late frame (should be clear screen) for sanity
    last = n - 1
    if last in frames_cache:
        Image.fromarray(frames_cache[last]).resize(CAP_W, CAP_H, Image.BILINEAR).save(
            os.path.join(out_dir, "start_preview_LAST.png"))
    return start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--secs", type=int, default=60)
    ap.add_argument("--out-dir", default="simdata/cache")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    max_frames = a.secs * 60
    detect_start(a.capture, max_frames, a.out_dir)


if __name__ == "__main__":
    main()
