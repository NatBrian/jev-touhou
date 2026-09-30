"""Analyze a campaign jsonl (multiple stages in one file, chronological order).

    venv\Scripts\python.exe tools\analyze_campaign_log.py simdata\laya-m3cam-<tag>.jsonl
"""
import json
import sys
from collections import Counter


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: analyze_campaign_log.py <laya-m3cam-*.jsonl>")
        return
    recs = [json.loads(l) for l in open(path, encoding="utf-8")]
    ok = [r for r in recs if r["status"] == "ok"]
    # split into stages by frame reset (file order is chronological)
    stages = []
    cur = []
    for r in ok:
        if cur and r["frame"] < cur[-1]["frame"] - 500:
            stages.append(cur)
            cur = []
        cur.append(r)
    if cur:
        stages.append(cur)
    print("file: %s  stages detected: %d" % (path, len(stages)))
    for i, st in enumerate(stages):
        fmax = max(r["frame"] for r in st)
        print("\n=== stage block %d: n=%d fmax=%d ===" % (i, len(st), fmax))
        print("  macros:", dict(Counter(r["macro"] for r in st).most_common(10)))
        print("  death/bomb timeline:")
        pd = pbl = None
        for r in st:
            d = r.get("deaths")
            bl = r.get("bombs_left")
            ev = []
            if pd is not None:
                if d > pd:
                    ev.append("DEATH%d" % d)
                if bl is not None and pbl is not None and bl < pbl:
                    ev.append("bomb->%d" % bl)
            if pd is None or d != pd or bl != pbl:
                bh = r.get("boss_hp_frac")
                print("   f%-5d d=%d bl=%s power=%s pos=%s bhp=%s macro=%s %s"
                      % (r["frame"], d, bl, r.get("power"), r.get("player"),
                         ("%.2f" % bh) if bh is not None else "-",
                         r.get("macro"), " ".join(ev)))
            pd, pbl = d, bl


if __name__ == "__main__":
    main()
