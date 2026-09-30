"""Quick life/death trajectory analysis for a campaign jsonl (M3 tuning).

    venv\Scripts\python.exe tools\analyze_lives.py simdata\laya-m3cam-XXXX.jsonl
"""
import json
import sys

path = sys.argv[1]
recs = [json.loads(l) for l in open(path, encoding="utf-8")]
ok = [r for r in recs if r.get("status") == "ok" and r.get("ctx")]

# split into stages on frame resets
blocks = []
cur = []
for r in ok:
    if cur and r["frame"] < cur[-1]["frame"] - 500:
        blocks.append(cur)
        cur = []
    cur.append(r)
if cur:
    blocks.append(cur)

for i, b in enumerate(blocks):
    print("=== stage block %d: n=%d fmax=%d ===" % (i, len(b), b[-1]["frame"]))
    print("  macros:", end=" ")
    mix = {}
    for r in b:
        mix[r["macro"]] = mix.get(r["macro"], 0) + 1
    print(mix)
    print("  focus frac>=0.8: %.2f  bomb frac>=0.8: %.2f" % (
        sum(1 for r in b if (r.get("focus") or 0) >= 0.8) / len(b),
        sum(1 for r in b if (r.get("bomb") or 0) >= 0.8) / len(b)))
    prev_d = -1
    print("  frame   lives frags bombs power pos              macro      boss_hp")
    last = None
    for r in b:
        c = r["ctx"]
        d = c.get("deaths", 0)
        if d != prev_d or r["frame"] in (1,) or (last and r["frame"] - last["frame"] > 1500):
            last = r
            mark = "  <== DEATH%d" % d if d > prev_d and prev_d >= 0 else ""
            print("  f%-6d %s     %s   %s   %s   (%.0f,%.0f)  %-11s %s%s" % (
                r["frame"],
                c.get("lives", "?"), c.get("life_frags", "?"), c.get("bombs_left", "?"),
                c.get("power", "?"),
                c.get("player", [0, 0])[0], c.get("player", [0, 0])[1],
                r["macro"],
                round(c["boss_hp_frac"], 2) if c.get("boss_hp_frac") is not None else "-",
                mark))
            prev_d = d
    # life items collected: max lives reached
    lives_series = [r["ctx"].get("lives", 0) for r in b]
    print("  lives min=%s max=%s end=%s" % (min(lives_series), max(lives_series), lives_series[-1]))
