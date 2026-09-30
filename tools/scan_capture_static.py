"""scan_capture_static.py — find the 'Replay Paused' transition in a raw
gdigrab capture: scan frame-to-frame diffs at low res, report big jumps and
the start of a long static run (the pause menu).

    venv\\Scripts\\python.exe tools\\scan_capture_static.py <capture.mp4>
"""
import subprocess
import sys

import numpy as np
from PIL import Image

SW, SH = 320, 180


def main():
    path = sys.argv[1]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", path,
           "-vf", "scale=%d:%d" % (SW, SH), "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    fs = SW * SH * 3
    prev = None
    idx = 0
    prev_g = None
    quiet = 0
    static_start = None
    jumps = []
    try:
        while True:
            buf = p.stdout.read(fs)
            if len(buf) < fs:
                break
            a = np.frombuffer(buf, dtype=np.uint8).reshape(SH, SW, 3)
            g = a.mean(axis=2)
            if prev_g is not None:
                d = float(np.abs(g - prev_g).mean())
                if d > 12.0:
                    jumps.append((idx, d))
                if d < 0.05:
                    quiet += 1
                    if quiet == 90 and static_start is None:
                        static_start = idx - 90
                else:
                    quiet = 0
            prev_g = g
            idx += 1
    finally:
        p.stdout.close()
        p.terminate()
    print("total_frames = %d" % idx)
    print("big jumps (idx, diff):")
    for i, d in jumps:
        print("  f%6d  %.1f" % (i, d))
    print("static_run_start (>=90 quiet frames) = %s" % static_start)


if __name__ == "__main__":
    main()
