"""Diagnostic: field-wide cost landscape at selected frames of a recorded
campaign stage (2026-09-26). For each grid position, computes the best-of-9
heading cost with the real executor cost function (VA4 via probe patch when
--gap-horizon), to locate safe regions during dense walls.

    venv\Scripts\python.exe tools\diag_cost_field.py <tag> <stage> [f1,f2,...] [normal]

Prints an ASCII heat map (best-of-9 cost per grid cell, log-scaled) plus the
cheapest cells. A cell marked '#' is a full wall (>= 150); 'o' is safe (< 8).
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))
sys.path.insert(0, os.path.join(HERE, "tools"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING)
from executor import ReflexExecutor, MOVES, PX_MIN, PX_MAX, PY_MIN, PY_MAX
from probe_evader import make_candidate_cost, VARIANTS, GAP_WINDOW
from dump_probe_states import DIFFS, LIB, load_trace_seq  # noqa: E402
from macros import resolve_macro_target  # noqa: E402
from dump_probe_states import TraceMacro  # noqa: E402

SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")


def heat(c):
    if c >= 150.0:
        return "#"
    if c >= 60.0:
        return "%"
    if c >= 25.0:
        return "*"
    if c >= 8.0:
        return "."
    return "o"


def main():
    tag, stage = sys.argv[1], int(sys.argv[2])
    frames = sorted(int(x) for x in sys.argv[3].split(",")) if len(sys.argv) > 3 \
        else [5320]
    diff = DIFFS.get(sys.argv[4] if len(sys.argv) > 4 else "normal",
                     DIFFICULTY_NORMAL)

    carry = {}
    cp_path = os.path.join(DATA, "checkpoints",
                           "%s-stage%d.json" % (tag, stage - 1))
    if stage > 1 and os.path.exists(cp_path):
        cp = json.load(open(cp_path, encoding="utf-8"))
        if cp.get("carry"):
            carry = cp["carry"]
    seq = load_trace_seq(tag, stage)

    register_runtime_dirs(
        os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    for d in ("storage", "cache"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    sim.reset(EpisodeConfig(
        stage_id=stage, difficulty=diff, player_character=CHAR_MARISA,
        shot_mode=SHOT_A, rng_seed=12345 + stage, **carry,
    ))
    ex = ReflexExecutor(allow_bombs=False, gap_horizon=True)
    ex.reset()
    ex._candidate_cost = types.MethodType(
        make_candidate_cost(ex, VARIANTS["VA4"], GAP_WINDOW), ex)

    xs = list(range(int(PX_MIN), int(PX_MAX) + 1, 28))
    ys = list(range(int(PY_MAX), int(PY_MIN) - 1, -32))  # top -> bottom

    todo = set(frames)
    seq_idx = 0
    cur_macro = None
    speed = ex.speed_full
    while True:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, _mid, foc = seq[seq_idx]
            cur_macro = TraceMacro(_mid, foc, _f,
                                   resolve_macro_target(_mid, v))
            seq_idx += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))
        if lf in todo:
            px, py = (float(v.raw.player.position.x),
                      float(v.raw.player.position.y))
            grid = []
            cells = []
            for gy in ys:
                row = []
                for gx in xs:
                    hz, sn, sf = ex._collect_hazards(v, gx, gy, False)
                    best = min(ex._candidate_cost(gx, gy, dx, dy, speed,
                                                  hz, sn, sf)
                               for dx, dy in (m[0] for m in MOVES))
                    row.append(heat(best))
                    cells.append((best, gx, gy))
                grid.append("".join(row))
            cells.sort()
            print("f%d player=(%.0f,%.0f)  (rows: top y=%d -> bottom y=%d)"
                  % (lf, px, py, ys[0], ys[-1]))
            for row in grid:
                print("   " + row)
            print("   legend: o<8 . <25 * <60 % <150 # >=150 "
                  "(cost = best of 9 headings)")
            print("   cheapest cells: " +
                  ", ".join("(%d, %d)=%.1f" % (x, y, c)
                            for c, x, y in cells[:6]))
            todo.discard(lf)
        sim.step(buttons=ex.execute(cur_macro, v))
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
