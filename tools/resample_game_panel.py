#!/usr/bin/env python3
"""resample_game_panel.py — build a clean 60 fps game panel from a taisei
gdigrab capture that was recorded at an irregular (~43 fps) rate on a virtual
display.

The capture has D distinct frames with (irregular) PTS t[0..D-1].  The game's
*simulation* advances at a fixed rate (default 60 fps, but a taisei replay on a
GPU-limited virtual display can run faster, e.g. ~91 fps -- pass --sim-fps), so
distinct frame i (at time t[i]) shows stage frame (t[i] - t[G0]) * sim_fps,
where G0 is the first distinct frame that is *not* the static loading screen
(i.e. stage frame 0).

For each 60 fps output frame j (time t[G0] + j/sim_fps from stage start), pick
the distinct frame whose t[i] is nearest that time (clamped to [G0, G_end]).
G_end is the last non-black distinct frame (the end card holds it).  If the
game jumps straight to a menu after the stage (no clear screen), pass
--end-offset (seconds) to hold the last *gameplay* frame instead.

Two streaming passes (no full-frame RAM):
  pass 1 (low res): brightness + diff-from-frame-0  ->  G0, G_end
  pass 2 (full res): forward each distinct frame counts[i] times -> 60 fps mp4

Usage:
  python tools\\resample_game_panel.py <capture.mp4> --out <panel.mp4> \
      --frames 12787 [--g0 auto] [--g-end auto] [--br-thr 3]
"""
import argparse
import subprocess
import sys

import numpy as np

W, H = 1280, 720
SW, SH = 160, 90  # low-res for metadata pass


def get_pts(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout
    return np.array([float(x) for x in out.replace(",", " ").split() if x.strip()])


def decode_raw(path, w, h, fps_mode):
    """Yield (idx, uint8 HxWx3) distinct frames via an ffmpeg raw pipe."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", path]
    if fps_mode == "passthrough":
        cmd += ["-fps_mode", "passthrough"]
    cmd += ["-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
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


def metadata_pass(path):
    """Return (brightness[], diff_from_0[]) at low res."""
    br, df = [], []
    ref = None
    for i, a in decode_raw(path, SW, SH, "passthrough"):
        g = a.mean(axis=2)
        br.append(float(g.mean()))
        if ref is None:
            ref = g
            df.append(0.0)
        else:
            df.append(float(np.abs(g - ref).mean()))
    return np.array(br), np.array(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, required=True, help="output frame count N")
    ap.add_argument("--g0", default="auto")
    ap.add_argument("--bright-thr", type=float, default=15.0,
                    help="brightness threshold for the end-card hold frame")
    ap.add_argument("--diff-thr", type=float, default=2.5)
    ap.add_argument("--sim-fps", type=float, default=60.0,
                    help="game simulation fps (distinct frame i shows stage "
                         "frame (t[i]-t[G0])*sim_fps; default 60)")
    ap.add_argument("--end-offset", type=float, default=0.0,
                    help="seconds before the stage-clear time to hold for the "
                         "end card (use >0 when the game shows a menu, not a "
                         "clear screen, right after the stage)")
    a = ap.parse_args()
    N = a.frames

    t = get_pts(a.capture)
    D = len(t)
    print(f"distinct_frames = {D}, span = {t[-1]:.3f}s")

    br, df = metadata_pass(a.capture)

    if a.g0 == "auto":
        # first frame that differs from the loading screen (frame 0)
        g0 = int(np.argmax(df > a.diff_thr)) if (df > a.diff_thr).any() else 0
    else:
        g0 = int(a.g0)
    # stage end (panel frame stage_len-1) is at t[g0] + (stage_len-1)/sim_fps
    stage_len = N - 135  # end card = 135 frames (2.25 s)
    T_start = t[g0]
    # the stage-clear moment = distinct frame for panel frame (stage_len - 1)
    stage_clear_time = T_start + (stage_len - 1) / a.sim_fps - a.end_offset
    i_clear = g0
    while i_clear < D - 1 and t[i_clear + 1] < stage_clear_time:
        i_clear += 1
    if i_clear > g0 and abs(t[i_clear - 1] - stage_clear_time) < abs(t[i_clear] - stage_clear_time):
        i_clear -= 1
    print(f"G0 = {g0}  (t={t[g0]:.3f}s, br={br[g0]:.1f})")
    print(f"stage {stage_len} frames; stage-clear at t={stage_clear_time:.3f}s "
          f"-> distinct {i_clear} (br={br[i_clear]:.1f}); capture ends {t[-1]:.3f}s")

    # build the resampling counts via a two-pointer over sorted t.
    # stage (panel 0..stage_len-1): nearest distinct frame, clamped [g0, D-1].
    # end card (panel stage_len..N-1): hold the stage-clear frame (i_clear).
    counts = np.zeros(D, dtype=np.int64)
    tgt = T_start + np.arange(N) / a.sim_fps
    i = g0
    for j in range(N):
        if j >= stage_len:
            counts[i_clear] += 1
            continue
        tj = tgt[j]
        while i < D - 1 and t[i + 1] < tj:
            i += 1
        best = i
        if i > g0 and abs(t[i - 1] - tj) < abs(t[i] - tj):
            best = i - 1
        counts[best] += 1
    assert counts.sum() == N, (counts.sum(), N)

    # pass 2: stream full-res distinct frames, write each counts[i] times
    out_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", "60", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-i", "pipe:0",
        "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        a.out,
    ]
    err_path = a.out + ".enc.log"
    with open(err_path, "wb") as errf:
        p_out = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stderr=errf)
    fs = W * H * 3
    written = 0
    try:
        for i, frame in decode_raw(a.capture, W, H, "passthrough"):
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
    print(f"output_frames = {written} -> {a.out} (rc={p_out.returncode})")


if __name__ == "__main__":
    main()
