"""extract_hud_anchors.py — dump HUD crops for anchor reading from a taisei
gdigrab capture.

Two modes:
  --idx  I [I ...]   extract by distinct-frame index (slow: full decode)
  --time T [T ...]   extract by PTS time via -ss seek (fast)

Writes simdata/cache/hud-<tag>-<key>.png (right column, 2x scale) and prints
"key  t_s  filename" so the HUD score can be read and paired with the
sim-score table (simdata/cache/simscore-<tag>.txt).

Usage:
  python tools\\extract_hud_anchors.py <capture.mp4> --tag mica --time 20 50 80 110 140 170 195 210 220 228
"""
import argparse
import subprocess
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "simdata", "cache")

# HUD crop for a 960x540 window (right column: score/lives/power/value/graze)
CROP_960 = "crop=430:370:530:0,scale=860:740:flags=neighbor"
# HUD crop for a 1280x720 window
CROP_1280 = "crop=470:370:810:0,scale=940:740:flags=neighbor"


def get_pts(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return [float(x) for x in out.replace(",", " ").split() if x.strip()]


def probe_width(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    return int(out) if out else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--idx", type=int, nargs="*", default=[])
    ap.add_argument("--time", type=float, nargs="*", default=[])
    a = ap.parse_args()

    crop = CROP_1280 if probe_width(a.capture) == 1280 else CROP_960

    pts = get_pts(a.capture)
    D = len(pts)
    print("distinct_frames =", D, " span =", round(pts[-1], 3), "s")

    if a.idx:
        for i in [i for i in a.idx if 0 <= i < D]:
            out = os.path.join(CACHE, "hud-%s-%d.png" % (a.tag, i))
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", a.capture,
                 "-vf", "select=eq(n\\,%d),%s" % (i, crop),
                 "-frames:v", "1", out],
                check=False)
            print("idx=%6d  t=%8.3f  %s" % (i, pts[i], os.path.basename(out)))
    elif a.time:
        import bisect
        for t in a.time:
            i = min(max(bisect.bisect_left(pts, t), 0), D - 1)
            # snap to the neighbour PTS closest to t
            if i + 1 < D and abs(pts[i + 1] - t) < abs(pts[i] - t):
                i += 1
            ta = pts[i]
            out = os.path.join(CACHE, "hud-%s-%d.png" % (a.tag, i))
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.4f" % ta,
                 "-i", a.capture, "-vf", crop, "-frames:v", "1", out],
                check=False)
            print("idx=%6d  t=%8.3f  %s" % (i, ta, os.path.basename(out)))
    else:
        print("pass --idx or --time")


if __name__ == "__main__":
    main()
