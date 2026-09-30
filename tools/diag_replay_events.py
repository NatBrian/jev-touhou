"""One-shot: dump replay events around a frame range (divergence forensics)."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from merge_replays import parse  # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, "simdata", "replays", "guard-stage1-easy-12346.trsr")
lo = int(sys.argv[2]) if len(sys.argv) > 2 else 7440
hi = int(sys.argv[3]) if len(sys.argv) > 3 else 7470

TYPES = {0: "PRESS", 1: "RELEASE", 2: "OVER", 3: "AXIS_LR", 4: "AXIS_UD",
         5: "CHECK_DESYNC", 6: "FPS", 7: "INFLAGS", 8: "CONTINUE",
         9: "RESUME"}

import struct  # noqa: E402

data = parse(path)
raw = data["events"]
n = len(raw) // 7
evs = [struct.unpack_from("<IBH", raw, i * 7) for i in range(n)]
print("total events:", len(evs))
for f, t, v in evs:
    if lo <= f <= hi:
        if t == 5:
            note = "digest=0x%04x" % v
        elif t in (0, 1):
            note = "key=%d" % v
        elif t == 7:
            note = "flags=0x%02x%s" % (v,
                                       " [has SKIP]" if v & 0x40 else "")
        else:
            note = "value=%d" % v
        print("f%-5d %-12s %s" % (f, TYPES.get(t, "?"), note))
