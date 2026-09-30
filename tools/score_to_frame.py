"""score_to_frame.py — map HUD score readings to sim frames using the
simscore dump (tools/dump_replay_scores.py output: frame score power piv
graze ... rows every 250 frames, score monotonic non-decreasing).

Usage: python tools\\score_to_frame.py simdata\\cache\\simscore-mica.txt 537865 694880
Prints: score -> frame (linear interp; note rows are 250-frame spaced).
"""
import sys
import numpy as np


def main():
    path = sys.argv[1]
    frames, scores = [], []
    # detect encoding (simscore dumps may be utf-16 or utf-8)
    enc = "utf-16" if open(path, "rb").read(2) in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    for line in open(path, encoding=enc):
        p = line.split()
        if len(p) >= 2 and p[0].isdigit():
            frames.append(int(p[0]))
            scores.append(int(p[1]))
    frames = np.array(frames)
    scores = np.array(scores)
    if not np.all(np.diff(scores) >= 0):
        print("WARNING: score table not monotonic")
    out = []
    for s in sys.argv[2:]:
        s = int(s)
        f = float(np.interp(s, scores, frames))
        out.append("%d -> f%.0f" % (s, f))
    print("  ".join(out))
    print("table: %d rows, f%d..f%d, score %d..%d" %
          (len(frames), frames[0], frames[-1], scores[0], scores[-1]))


if __name__ == "__main__":
    main()
