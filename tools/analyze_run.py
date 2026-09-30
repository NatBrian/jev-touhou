"""Summarize a campaign trace + checkpoints (2026-09-26).

    venv\Scripts\python.exe tools\analyze_run.py <tag>

Prints per-stage status, decision stats (raw move distribution, focus,
evade triggers + bomb_now distribution, decision cadence) and, for every
death_hit record, the frame, position, active macro, evade state, executor
choice, and the dodge line from the (snapshot-corrected) hit state text.
"""
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "simdata")

STATUS = {1: "RUNNING", 2: "WON", 3: "LOST", 4: "ABORTED", 5: "ERROR"}


def load(tag):
    trace = os.path.join(DATA, "laya-%s.jsonl" % tag)
    rows = [json.loads(x) for x in open(trace, encoding="utf-8")
            if x.strip()]
    # split into stage segments at frame decreases
    segs, cur, prev = [], [], None
    for r in rows:
        f = r.get("frame")
        if prev is not None and isinstance(f, int) and f < prev:
            segs.append(cur)
            cur = []
        cur.append(r)
        prev = f
    if cur:
        segs.append(cur)
    cps = []
    for s in range(1, 7):
        p = os.path.join(DATA, "checkpoints", "%s-stage%d.json" % (tag, s))
        if os.path.exists(p):
            cps.append(json.load(open(p, encoding="utf-8")))
    return segs, cps


def dodge_line(text):
    if not text:
        return "(none)"
    i = text.find("You are at (")
    if i < 0:
        return text[:160]
    j = text.find("Items nearby", i)
    return text[i:j if j > 0 else i + 260][:260]


def main():
    tag = sys.argv[1]
    segs, cps = load(tag)
    cp_by_stage = {c["stage"]: c for c in cps}
    for idx, seg in enumerate(segs, 1):
        ok = [r for r in seg if r.get("status") == "ok"]
        # standalone stage trace (--start-stage N): one segment + one
        # checkpoint — label with the checkpoint's real stage number
        label = (cps[0]["stage"]
                 if len(segs) == 1 and len(cps) == 1 else idx)
        cp = cp_by_stage.get(label, {})
        flags = {k: cp.get(k) for k in
                 ("no_bomb", "no_focus", "edge_escape", "path_risk",
                  "danger_valve", "no_bomb_evade")}
        print("== STAGE %d %s frames=%s deaths=%s bombs=%s cov=%s taint=%s"
              % (label, STATUS.get(cp.get("status"), cp.get("status")),
                 cp.get("frames"), cp.get("deaths"), cp.get("bombs_used"),
                 cp.get("coverage"), cp.get("taint")))
        print("   flags:", flags)
        if not ok:
            continue
        print("   ok_calls=%d  raw_move=%s" % (
            len(ok), collections.Counter(r.get("raw_move") for r in ok)))
        print("   remapped=%d  focus_eff=%d  target_kinds=%s" % (
            sum(bool(r.get("move_remapped")) for r in ok),
            sum(bool(r.get("focus_eff")) for r in ok),
            collections.Counter(r.get("target_kind") for r in ok)))
        ev = [r for r in ok if r.get("evade_eff")]
        print("   evade_eff=%d/%d (%.1f%%)  dirs=%s" % (
            len(ev), len(ok), 100.0 * len(ev) / len(ok),
            collections.Counter(r.get("evade_dir") for r in ev)))
        ex = [r for r in ok if r.get("exile_eff")]
        print("   exile_eff=%d/%d (%.1f%%)  dirs=%s" % (
            len(ex), len(ok), 100.0 * len(ex) / len(ok),
            collections.Counter(r.get("evade_dir") for r in ex)))
        bn = [r.get("bomb_now") for r in ok
              if isinstance(r.get("bomb_now"), (int, float))]
        if bn:
            bn.sort()
            print("   bomb_now(noul): mean=%.3f min=%.3f p10=%.3f "
                  "p50=%.3f p90=%.3f max=%.3f  >=0.55: %d" % (
                      statistics.mean(bn), bn[0],
                      bn[len(bn) * 10 // 100], statistics.median(bn),
                      bn[len(bn) * 90 // 100], bn[-1],
                      sum(1 for x in bn if x >= 0.55)))
        dg = [r.get("danger") for r in ok
              if isinstance(r.get("danger"), (int, float))]
        if dg:
            print("   danger: mean=%.3f max=%.3f" %
                  (statistics.mean(dg), max(dg)))
        fps = [r.get("focus") for r in ok
               if isinstance(r.get("focus"), (int, float))]
        if fps:
            print("   focus_raw: mean=%.3f >=0.80: %d" % (
                statistics.mean(fps), sum(1 for x in fps if x >= 0.80)))
        frames = sorted(r["frame"] for r in ok)
        iv = [b - a for a, b in zip(frames, frames[1:])]
        if iv:
            print("   decision interval: median=%d max=%d" %
                  (statistics.median(iv), max(iv)))
        it = [r.get("input_tokens") for r in ok
              if isinstance(r.get("input_tokens"), int)]
        if it:
            print("   input_tokens: min=%d mean=%d max=%d" %
                  (min(it), int(statistics.mean(it)), max(it)))
        for r in seg:
            if r.get("status") == "death_hit":
                print("   DEATH f=%s pos=%s raw_move=%s evade_eff=%s "
                      "exile_eff=%s bomb_now=%s danger=%s kind=%s "
                      "move_idx=%s" % (
                          r.get("frame"), r.get("player"),
                          r.get("raw_move"), r.get("evade_eff"),
                          r.get("exile_eff"),
                          None if r.get("bomb_now") is None
                          else round(r.get("bomb_now"), 3),
                          None if r.get("danger") is None
                          else round(r.get("danger"), 2),
                          r.get("target_kind"),
                          r.get("executor_move_idx")))
                costs = r.get("executor_costs")
                if costs:
                    best = min(range(len(costs)), key=lambda i: costs[i])
                    print("      min-cost heading=%d costs=%s" % (
                        best, [round(c, 1) for c in costs]))
                print("      hit_state:", dodge_line(
                    r.get("hit_state_text", "")))
    # campaign totals if present in checkpoints
    if cps:
        print("== totals: stages=%d deaths=%d bombs=%d" % (
            len(cps), sum(c.get("deaths", 0) for c in cps),
            sum(c.get("bombs_used", 0) for c in cps)))


if __name__ == "__main__":
    main()
