"""Profile a campaign decision trace (simdata/laya-<tag>.jsonl).

Usage: python tools/profile_decision_trace.py <jsonl> [<jsonl2> ...]
Prints per-trace: decisions, failures, macro distribution, evade/exile
rates + raw-noul stats, danger-score distribution, death frames, server
latency, input tokens, coverage.
"""
import json
import sys
from collections import Counter


def profile(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    n = len(rows)
    ok = [r for r in rows if r.get("status") == "ok"]
    macro = Counter(r.get("macro") for r in ok)
    raw = [r["bomb_now"] for r in ok if isinstance(r.get("bomb_now"), (int, float))]
    evade_eff = sum(1 for r in ok if r.get("evade_eff"))
    exile_eff = sum(1 for r in ok if r.get("exile_eff"))
    raw_when_eff = [r["bomb_now"] for r in ok
                    if r.get("evade_eff") and isinstance(r.get("bomb_now"), (int, float))]
    raw_when_safe = [r["bomb_now"] for r in ok
                     if not r.get("evade_eff") and not r.get("exile_eff")
                     and isinstance(r.get("bomb_now"), (int, float))]
    danger = Counter(r.get("danger") for r in ok)
    wall = [r["wall_ms"] for r in ok if isinstance(r.get("wall_ms"), (int, float))]
    server = [r["server_ms"] for r in ok if isinstance(r.get("server_ms"), (int, float))]
    tok = [r["input_tokens"] for r in ok if isinstance(r.get("input_tokens"), (int, float))]
    deaths = [(r["frame"], r.get("deaths")) for r in rows
              if isinstance(r.get("deaths"), int) and r.get("deaths", 0) > 0]
    focus = sum(1 for r in ok if r.get("focus_eff"))
    focus_raw_hi = sum(1 for r in ok if isinstance(r.get("focus"), (int, float)) and r["focus"] >= 0.5)

    def pct(x, y):
        return 100.0 * x / y if y else 0.0

    def quant(vals):
        if not vals:
            return "n/a"
        v = sorted(vals)
        q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
        return "p50=%.0f p90=%.0f max=%.0f" % (q(0.5), q(0.9), v[-1])

    print("== %s" % path)
    print("  decisions=%d ok=%d failures=%d" % (n, len(ok), n - len(ok)))
    print("  macro dist:", dict(macro))
    print("  raw_move dist:", dict(Counter(r.get("raw_move") for r in ok)))
    print("  evade_eff=%d (%.1f%%) exile_eff=%d (%.1f%%) focus_eff=%d focus_raw>=0.5=%d"
          % (evade_eff, pct(evade_eff, len(ok)),
             exile_eff, pct(exile_eff, len(ok)), focus, focus_raw_hi))
    def p50_p90(v):
        if not v:
            return "n/a"
        v = sorted(v)
        return "p50=%.2f p90=%.2f n=%d" % (v[len(v) // 2], v[int(0.9 * len(v))], len(v))

    print("  bomb_now(evade) raw: all %s | when evade_eff %s | when quiet %s"
          % (p50_p90(raw), p50_p90(raw_when_eff), p50_p90(raw_when_safe)))
    print("  danger dist:", dict(danger))
    print("  wall_ms:", quant(wall), " server_ms:", quant(server))
    print("  input_tokens:", quant(tok))
    print("  death rows:", deaths[:12])
    print()


for p in sys.argv[1:]:
    profile(p)
