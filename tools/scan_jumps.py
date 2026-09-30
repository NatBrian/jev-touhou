"""scan_jumps.py — frame-to-frame diff scan with PTS times.

    venv\\Scripts\\python.exe tools\\scan_jumps.py <capture.mp4> [--thr 4.0]

Reports every frame whose low-res mean abs diff from the previous frame
exceeds --thr, as (distinct-idx, pts_s, diff). Use to locate: stage-start
transition, spell-card starts, the death explosion, the clear/end-screen
transition.
"""
import argparse
import subprocess
import sys

import numpy as np

SW, SH = 320, 180


def get_pts(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return [float(x) for x in out.replace(",", " ").split() if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--thr", type=float, default=4.0)
    args = ap.parse_args()
    thr = args.thr

    pts = get_pts(args.capture)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", args.capture,
           "-fps_mode", "passthrough",
           "-vf", "scale=%d:%d" % (SW, SH), "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    fs = SW * SH * 3
    prev_g = None
    idx = 0
    n = 0
    try:
        while True:
            buf = p.stdout.read(fs)
            if len(buf) < fs:
                break
            a = np.frombuffer(buf, dtype=np.uint8).reshape(SH, SW, 3)
            g = a.mean(axis=2)
            if prev_g is not None:
                d = float(np.abs(g - prev_g).mean())
                if d > thr:
                    t = pts[idx] if idx < len(pts) else float("nan")
                    print("f%6d  t=%8.3f  diff=%6.1f" % (idx, t, d))
                    n += 1
            prev_g = g
            idx += 1
    finally:
        p.stdout.close()
        p.terminate()
    print("total_frames = %d, jumps(>%s) = %d" % (idx, thr, n))


if __name__ == "__main__":
    main()
