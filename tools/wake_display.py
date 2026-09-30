"""wake_display.py — send a synthetic mouse move (SendInput) to WAKE a
display that is already off. Needed before gdigrab captures of GL windows:
ES_DISPLAY_REQUIRED (keep_awake.ps1) only PREVENTS future display-off; it
does not turn an off display back on. Run it right before/after launching
the taisei capture so the window is composited while the display is on.

    venv\\Scripts\\python.exe tools\\wake_display.py [dx dy]
"""
import ctypes
import sys
import time
from ctypes import wintypes

MOUSE_MOVE = 0x0002  # MOUSEEVENTF_MOVE


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_long))]


class _I(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("i", _I)]


def move(dx=3, dy=3, n=3):
    extra = ctypes.pointer(ctypes.c_long(0))
    for _ in range(n):
        inp = INPUT(type=0, i=_I(mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=0,
                                              dwFlags=MOUSE_MOVE, time=0,
                                              dwExtraInfo=extra)))
        r = ctypes.windll.user32.SendInput(1, ctypes.byref(inp),
                                           ctypes.sizeof(inp))
        if r != 1:
            raise RuntimeError("SendInput failed: %d"
                               % ctypes.GetLastError())
        time.sleep(0.05)
    print("mouse move sent (dx=%d dy=%d x%d)" % (dx, dy, n))


if __name__ == "__main__":
    dx = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    dy = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    move(dx, dy)
