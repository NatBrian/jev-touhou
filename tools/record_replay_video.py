"""M4 video: play a (merged) replay in the fork's gl33 renderer + screen-record it.

    venv\\Scripts\\python.exe tools\\record_replay_video.py <replay.trsr> <output.mp4>
        [--title T] [--width 1280] [--height 720] [--fps 60] [--dur 2400]

Launches the gl33 build's taisei.exe with `--replay <replay>`, waits for the game
window, detects its exact title (window title = "Taisei Project v<version>",
src/video.c:503), then captures it with `ffmpeg -f gdigrab` at the given fps until
the replay ends (or --dur seconds). The Taisei window must be VISIBLE on an active
display (lid open / monitor on) for the capture to be non-black (PLAN.md M4 display
constraint). Press Ctrl+C to stop early.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAISEI_EXE = os.path.join(HERE, "third_party", "taisei-sim", "build-gl33", "src", "taisei.exe")
MINGW_BIN = os.path.join(HERE, "third_party", "mingw", "mingw64", "bin")

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.EnumWindows.restype = ctypes.c_bool
WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))


def find_taisei_title(prefix="Taisei Project", timeout=20.0):
    """Return the window title of the first window whose title starts with prefix."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n > 0:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if buf.value.startswith(prefix):
                        found.append(buf.value)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), None)
        if found:
            return found[0]
        time.sleep(0.5)
    return None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("usage: record_replay_video.py <replay.trsr> <output.mp4> "
              "[--title T] [--width 1280] [--height 720] [--fps 60] [--dur 2400]")
        sys.exit(1)
    replay, out = args[0], args[1]
    opts = {"title": None, "width": 1280, "height": 720, "fps": 60, "dur": 2400}
    i = 2
    while i < len(args):
        key = args[i]
        if key in opts:
            opts[key] = int(args[i + 1]) if key != "title" else args[i + 1]
            i += 2
        else:
            i += 1

    if not os.path.exists(TAISEI_EXE):
        print("gl33 taisei.exe not found at:", TAISEI_EXE,
              "(run tools/build_taisei_gl33.bat first)")
        sys.exit(1)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found on PATH (WinGet install ffmpeg)")
        sys.exit(1)

    env = os.environ.copy()
    # The final video host must launch reproducibly from this project without
    # relying on a caller-specific PATH. Keep any MinGW runtime dependencies
    # project-local (the exe is statically linked where supported).
    env["PATH"] = MINGW_BIN + os.pathsep + env.get("PATH", "")
    # Keep the recording subject to the same per-frame replay checks as the
    # preceding verification run. A desync therefore cannot be hidden by the
    # renderer/video path.
    env["TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY"] = "1"
    taisei = subprocess.Popen(
        [TAISEI_EXE, "--replay", replay, "--renderer", "gl33",
         "--width", str(opts["width"]), "--height", str(opts["height"])],
        env=env,
        cwd=os.path.dirname(TAISEI_EXE))
    try:
        title = opts["title"] or find_taisei_title(timeout=25.0)
        if not title:
            print("could not detect the Taisei window title; pass --title explicitly")
            sys.exit(1)
        print("Taisei window title:", title, flush=True)
        time.sleep(1.0)  # let the first frame render

        cmd = [ffmpeg, "-y", "-f", "gdigrab", "-framerate", str(opts["fps"]),
               "-i", 'title="%s"' % title,
               "-t", str(opts["dur"]), "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-crf", "18", out]
        print("recording:", " ".join(cmd), flush=True)
        ffmpeg_proc = subprocess.Popen(cmd)
        ffmpeg_proc.wait()
    except KeyboardInterrupt:
        print("\nstopping (Ctrl+C)")
    finally:
        taisei.terminate()
    print("video saved to:", out)


if __name__ == "__main__":
    main()
