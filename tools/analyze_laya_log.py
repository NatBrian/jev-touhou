"""Summarize a Laya call jsonl (harness/agent.py _log_call records).

    venv\Scripts\python.exe tools\analyze_laya_log.py simdata\laya-<tag>.jsonl
"""
import json
import statistics
import sys
from collections import Counter

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: analyze_laya_log.py <laya-*.jsonl>")
        return
    recs = [json.loads(l) for l in open(path, encoding="utf-8")]
    ok = [r for r in recs if r["status"] == "ok"]
    bad = [r for r in recs if r["status"] != "ok"]
    print("file: %s" % path)
    print("total calls=%d  ok=%d  bad=%d (%s)"
          % (len(recs), len(ok), len(bad),
             dict(Counter(r["status"] for r in bad)) or "-"))
    if not ok:
        return
    frames = [r["frame"] for r in ok]
    walls = [r["wall_ms"] for r in ok if r["wall_ms"]]
    print("frame range: %d .. %d   (span %.1f s game)"
          % (min(frames), max(frames), (max(frames) - min(frames)) / 60.0))
    if walls:
        print("wall_ms: med=%.0f min=%.0f max=%.0f"
              % (statistics.median(walls), min(walls), max(walls)))

    print("\nmacro distribution:")
    for k, v in Counter(r["macro"] for r in ok).most_common():
        print("  %-14s %3d  (%.1f%%)" % (k, v, 100.0 * v / len(ok)))

    def dist(key, lo, hi, label):
        vals = [r[key] for r in ok if r.get(key) is not None]
        if not vals:
            print("\n%s: (no data)" % label)
            return
        sv = sorted(vals)
        q = lambda p: sv[min(len(sv) - 1, int(p * len(sv)))]
        print("\n%s: n=%d med=%.3f p25=%.3f p75=%.3f min=%.3f max=%.3f"
              % (label, len(vals), statistics.median(vals), q(0.25), q(0.75),
                 sv[0], sv[-1]))
        for t in (0.5, 0.7, 0.8, 0.9):
            if lo <= t <= hi:
                print("  >=%.1f: %d  (%.1f%%)" % (t, sum(1 for x in vals if x >= t),
                                                  100.0 * sum(1 for x in vals if x >= t) / len(vals)))

    dist("bomb_now", 0, 1, "bomb_now noul")
    dist("focus", 0, 1, "focus noul")
    dist("danger", 0, 2, "danger score (0-2)")

    # boss DPS / death timeline (only present in enriched logs)
    boss = [r for r in ok if r.get("boss_active")]
    if boss and boss[0].get("boss_hp_frac") is not None:
        print("\nboss fight timeline (first/last active call):")
        first = min(boss, key=lambda r: r["frame"])
        last = max(boss, key=lambda r: r["frame"])
        print("  active f%d (hp %.2f) .. f%d (hp %.2f)   power first/last: %s / %s"
              % (first["frame"], first["boss_hp_frac"], last["frame"],
                 last["boss_hp_frac"], first.get("power"), last.get("power")))
        # per-call HP drop => rough DPS rate
        drops = []
        for a, b in zip(sorted(boss, key=lambda r: r["frame"]),
                        sorted(boss, key=lambda r: r["frame"])[1:]):
            if b["frame"] > a["frame"] and a["boss_hp_frac"] is not None \
                    and b["boss_hp_frac"] is not None:
                df = b["frame"] - a["frame"]
                drop = (a["boss_hp_frac"] - b["boss_hp_frac"]) / df  # hp-frac per frame
                drops.append(drop)
        if drops:
            print("  boss hp-frac drop per frame: med=%.2e (neg=boss not dying)"
                  % statistics.median(drops))

    # death timeline: calls where the deaths counter jumped
    withd = [r for r in ok if r.get("deaths") is not None]
    if withd:
        print("\ndeath / bomb timeline (per call):")
        prev_d, prev_b = None, None
        for r in sorted(withd, key=lambda r: r["frame"]):
            d, b_left = r["deaths"], r.get("bombs_left")
            if prev_d is None or d != prev_d or b_left != prev_b:
                pos = r.get("player")
                ev = []
                if prev_d is not None:
                    if d > prev_d:
                        ev.append("DEATH %d" % d)
                    if b_left is not None and prev_b is not None and b_left < prev_b:
                        ev.append("bomb->%d" % b_left)
                print("  f%-5d deaths=%d bombs_left=%s power=%s pos=%s boss_hp=%s %s"
                      % (r["frame"], d, b_left, r.get("power"),
                         pos,
                         ("%.2f" % r["boss_hp_frac"]) if r.get("boss_hp_frac") is not None else "-",
                         " ".join(ev)))
                prev_d, prev_b = d, b_left

    # time evolution (quartiles of the frame span)
    if ok:
        f0, f1 = min(frames), max(frames)
        w = max(1, (f1 - f0) // 4)
        print("\nbomb_now noul by time quartile (frame range):")
        for i in range(4):
            seg = [r["bomb_now"] for r in ok
                   if f0 + i * w <= r["frame"] < f0 + (i + 1) * w
                   and r["bomb_now"] is not None]
            if seg:
                print("  f%-5d..%-5d  med=%.3f  >=0.7: %d/%d"
                      % (f0 + i * w, f0 + (i + 1) * w, statistics.median(seg),
                         sum(1 for x in seg if x >= 0.7), len(seg)))


if __name__ == "__main__":
    main()
