"""Small, replay-linked human-likeness sanity report for a Laya run.

This is intentionally not a classifier. It records visible red flags from the
Laya trace: wall-skimming, repeated edge occupancy, direction oscillation,
and bomb/death usage. The accepted bar is only that the playback is not
obviously scripted; interpretation remains documented with the run.

    venv\\Scripts\\python.exe tools\\analyze_human_likeness.py trace.jsonl replay.trsr report.md
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from merge_replays import parse  # noqa: E402


def segments(rows):
    out, cur, prev = [], [], -1
    for row in rows:
        frame = int(row.get("frame", -1))
        if cur and frame < prev:
            out.append(cur)
            cur = []
        cur.append(row)
        prev = frame
    if cur:
        out.append(cur)
    return out


def main():
    if len(sys.argv) not in (2, 3, 4):
        print("usage: analyze_human_likeness.py trace.jsonl [replay.trsr] [report.md]")
        return 2
    trace = os.path.abspath(sys.argv[1])
    replay = os.path.abspath(sys.argv[2]) if len(sys.argv) >= 3 else None
    report_path = os.path.abspath(sys.argv[3]) if len(sys.argv) == 4 else None
    rows = [json.loads(line) for line in open(trace, encoding="utf-8") if line.strip()]
    segs = segments(rows)
    positions = [r["player"] for r in rows if r.get("player")]
    edge = [p for p in positions if p[0] <= 28 or p[0] >= 452 or p[1] <= 24 or p[1] >= 536]
    macros = {}
    for r in rows:
        macros[r.get("macro")] = macros.get(r.get("macro"), 0) + 1
    direction_changes = 0
    prev_sign = None
    for a, b in zip(positions, positions[1:]):
        dx = b[0] - a[0]
        sign = 1 if dx > 3 else -1 if dx < -3 else 0
        if sign and prev_sign and sign != prev_sign:
            direction_changes += 1
        if sign:
            prev_sign = sign
    death_hits = sum(r.get("status") == "death_hit" for r in rows)
    deaths = sum(r.get("status") == "death" for r in rows)
    bomb_now = [r for r in rows if r.get("macro") == "bomb_setup"]
    lines = [
        "# Human-likeness sanity report",
        "",
        "Trace: `%s`" % trace,
        "Segments/stages inferred from frame resets: %d" % len(segs),
        "Trace rows: %d; visible positions: %d" % (len(rows), len(positions)),
        "",
        "## Signals",
        "",
        "- Wall/edge samples: %d / %d (%.2f%%)" %
        (len(edge), len(positions), 100.0 * len(edge) / max(len(positions), 1)),
        "- Horizontal direction reversals: %d" % direction_changes,
        "- Death-hit records: %d; real death records: %d" % (death_hits, deaths),
        "- Laya `bomb_setup` decisions: %d" % len(bomb_now),
        "- Macro counts: `%s`" % json.dumps(macros, sort_keys=True),
        "",
        "## Interpretation",
        "",
        "The report is a sanity check, not a gameplay-quality score. A run is",
        "accepted only when replay inspection shows varied interior positioning,",
        "no sustained wall-skim pattern, and non-pathological bomb timing.",
    ]
    if replay:
        parsed = parse(replay)
        stages = []
        for stg in parsed["stages"]:
            stages.append({
                "id": struct.unpack_from("<H", stg, 4)[0],
                "flags": struct.unpack_from("<I", stg, 0)[0],
                "events": struct.unpack_from("<H", stg, 70)[0],
                "lives_used": stg[67], "bombs_used": stg[68],
            })
        lines.extend(["", "## Replay linkage", "", "- Replay: `%s`" % replay,
                      "- Replay stages/checksums: `%s`" % json.dumps(stages)])
    text = "\n".join(lines) + "\n"
    if report_path:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
