#!/usr/bin/env python3
"""composite_real_showcase.py — build the real-art showcase video.

LEFT  (1280x720) = real taisei.exe gl33 gameplay, trimmed from the gdigrab
                  capture starting at the detected replay-start frame G0.
RIGHT (1280x720) = the existing dashboard video's right panel (x>=640).

Output: 2560x720 @ 60 fps, N frames (same length as the dashboard).

Usage:
  python tools\\composite_real_showcase.py <game_capture.mp4> <dashboard.mp4> \
      --start <G0> --frames <N> --out <out.mp4> [--crf 19]
"""
import argparse
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game_capture")
    ap.add_argument("dashboard")
    ap.add_argument("--start", type=int, required=True, help="gameplay start frame G0 in the capture")
    ap.add_argument("--frames", type=int, required=True, help="output frame count N (dashboard length)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--crf", type=int, default=19)
    a = ap.parse_args()

    G0, N = a.start, a.frames
    # game: frames [G0, G0+N) -> 1280x720 ; dashboard: right 1280px panel, N frames
    fc = (
        f"[0:v]trim=start_frame={G0}:end_frame={G0 + N},setpts=PTS-STARTPTS,"
        f"scale=1280:720[vgame];"
        f"[1:v]crop=1280:720:640:0,setpts=PTS-STARTPTS[vdash];"
        f"[vgame][vdash]hstack=inputs=2[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", a.game_capture,
        "-i", a.dashboard,
        "-filter_complex", fc,
        "-map", "[v]",
        "-r", "60",
        "-c:v", "libx264", "-crf", str(a.crf), "-pix_fmt", "yuv420p", "-preset", "veryfast",
        a.out,
    ]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc != 0:
        print("ffmpeg failed rc=", rc)
        sys.exit(rc)
    # report output frame count
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames", "-of", "csv", a.out],
        capture_output=True, text=True)
    print("output:", probe.stdout.strip())


if __name__ == "__main__":
    main()
