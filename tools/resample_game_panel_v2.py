#!/usr/bin/env python3
"""resample_game_panel_v2.py — anchor-based 60 fps game panel from a taisei
gdigrab capture with VARIABLE real-time pace (e.g. 58 fps early, 45 fps late).

Instead of assuming a constant sim fps, piecewise-linear anchors
  (capture_time_s, sim_frame)
define the time -> sim-frame map; each output frame j picks the distinct
capture frame whose PTS is nearest the time of sim frame j.

Anchors file: one "<time_s> <sim_frame>" per line, ascending in both.
The last anchor should be the stage-clear moment (sim_frame = stage_len-1).
Output frames [stage_len, N) hold the distinct frame nearest the clear time.

Usage:
  python tools\\resample_game_panel_v2.py <capture.mp4> --anchors <a.txt> \
      --out <panel.mp4> --frames N [--stage-len 13653]
"""
import argparse
import subprocess
import sys

import numpy as np

W, H = 1280, 720


def get_pts(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return np.array([float(x) for x in out.replace(",", " ").split() if x.strip()])


def decode_raw(path, w, h):
    """Yield (idx, uint8 HxWx3) distinct frames via an ffmpeg raw pipe."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", path,
           "-fps_mode", "passthrough",
           "-vf", "scale=%d:%d" % (w, h),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fs = w * h * 3
    idx = 0
    try:
        while True:
            buf = p.stdout.read(fs)
            if len(buf) < fs:
                break
            yield idx, np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
            idx += 1
    finally:
        p.stdout.close()
        p.terminate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--anchors", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, required=True, help="output frame count N")
    ap.add_argument("--stage-len", type=int, required=True,
                    help="sim frames in the episode (clear frame = stage_len-1)")
    a = ap.parse_args()
    N, stage_len = a.frames, a.stage_len

    at = []
    af = []
    for line in open(a.anchors, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        t, f = line.split()
        at.append(float(t))
        af.append(int(f))
    at = np.array(at)
    af = np.array(af)
    if len(at) < 2:
        sys.exit("need >= 2 anchors")
    if np.any(np.diff(at) <= 0) or np.any(np.diff(af) <= 0):
        sys.exit("anchors must be strictly ascending in time and frame")
    print("anchors: " + "  ".join("%.3fs=f%d" % (t, f) for t, f in zip(at, af)))

    t = get_pts(a.capture)
    D = len(t)
    print("distinct_frames = %d, span = %.3fs" % (D, t[-1]))

    # inverse map: sim frame j -> capture time (piecewise linear)
    def time_of_frame(j):
        if j <= af[0]:
            return at[0]
        if j >= af[-1]:
            return at[-1]
        k = int(np.searchsorted(af, j, side="right")) - 1
        f0, f1 = af[k], af[k + 1]
        t0, t1 = at[k], at[k + 1]
        return t0 + (j - f0) * (t1 - t0) / (f1 - f0)

    # clear frame (panel frame stage_len-1) hold target
    t_clear = time_of_frame(stage_len - 1)
    i_clear = int(np.argmin(np.abs(t - t_clear)))
    print("clear time = %.3fs -> distinct %d (t=%.3fs)" % (t_clear, i_clear, t[i_clear]))

    # per distinct frame, how many output frames map to it
    counts = np.zeros(D, dtype=np.int64)
    tgt = np.array([time_of_frame(j) if j < stage_len else t_clear for j in range(N)])
    i = 0
    for j in range(N):
        tj = tgt[j]
        while i < D - 1 and t[i + 1] < tj:
            i += 1
        best = i
        if i > 0 and abs(t[i - 1] - tj) < abs(t[i] - tj):
            best = i - 1
        counts[best] += 1
    assert counts.sum() == N
    first = int(np.argmax(counts > 0))
    last = D - 1 - int(np.argmax(counts[::-1] > 0))
    print("distinct frames used: %d..%d (t=%.3f..%.3f s)" % (first, last, t[first], t[last]))

    err_path = a.out + ".enc.log"
    out_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", "60", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "%dx%d" % (W, H), "-i", "pipe:0",
        "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        a.out,
    ]
    with open(err_path, "wb") as errf:
        p_out = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stderr=errf)
    fs = W * H * 3
    written = 0
    try:
        for i, frame in decode_raw(a.capture, W, H):
            c = int(counts[i])
            if c:
                data = frame.tobytes()
                for _ in range(c):
                    p_out.stdin.write(data)
                    written += 1
            if i == D - 1:
                break
        p_out.stdin.close()
    except (BrokenPipeError, OSError) as e:
        print("pipe error:", e)
    p_out.wait()
    if p_out.returncode != 0:
        tail = open(err_path, "rb").read()[-600:].decode(errors="replace")
        print("encoder stderr tail:\n", tail)
    print("output_frames = %d -> %s (rc=%d)" % (written, a.out, p_out.returncode))


if __name__ == "__main__":
    main()
