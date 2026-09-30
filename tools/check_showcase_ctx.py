"""Quick state_sha1 context check for the showcase renderer (2026-09-29).

Replays the first N frames of a recorded campaign stage with the exact
showcase replay path and verifies the reconstructed state texts against
the trace's state_sha1 — cheap pre-flight before a full 5+ minute render.

    venv\Scripts\python.exe tools\check_showcase_ctx.py <tag> <stage> [maxf] [diff]
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING,
)
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from state_compiler import compile_state  # noqa: E402
from agent import Agent  # noqa: E402
from dump_probe_states import TraceMacro  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")


def main():
    tag, stage = sys.argv[1], int(sys.argv[2])
    maxf = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    diff = DIFFS.get(sys.argv[4] if len(sys.argv) > 4 else "normal",
                     DIFFICULTY_NORMAL)

    rows = [json.loads(x) for x in
            open(os.path.join(DATA, "laya-%s.jsonl" % tag), encoding="utf-8")
            if x.strip()]
    seg, prev = [], None
    for r in rows:
        f_ = r.get("frame")
        if prev is not None and isinstance(f_, int) and f_ < prev:
            break
        seg.append(r)
        prev = f_
    decisions = sorted((r for r in seg
                        if r.get("status") == "ok" and r.get("state_sha1")),
                       key=lambda r: r["frame"])
    decisions = [d for d in decisions if d["frame"] <= maxf]
    cp = json.load(open(os.path.join(DATA, "checkpoints",
                                     "%s-stage%d.json" % (tag, stage)),
                        encoding="utf-8"))
    carry = {} if stage == 1 else dict(cp.get("carry") or {})
    if cp.get("no_bomb"):
        carry.update(initial_bombs=0, initial_bomb_fragments=0)

    register_runtime_dirs(
        os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"))
    sim.create()
    sim.reset(EpisodeConfig(stage_id=stage, difficulty=diff,
                            player_character=CHAR_MARISA, shot_mode=SHOT_A,
                            rng_seed=12345 + stage, **carry))
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=False,
                        gap_horizon=True, laser_blind_fix=True,
                        laser_ring=True)
    ex.reset()

    di, rendered = 0, 0
    prev_macro_id, prev_focus = None, False
    cur_macro = None
    results = []
    while rendered < maxf + 5:
        v = sim.get_state()
        st = int(v.raw.episode_status)
        lf = int(v.raw.logical_frame)
        if st != STATUS_RUNNING:
            break
        while di < len(decisions) and lf >= decisions[di]["frame"]:
            row = decisions[di]
            ctx = "none (degraded mode, no Laya macro)"
            if prev_macro_id is not None:
                ctx = prev_macro_id + (", focus on" if prev_focus else "")
            text = compile_state(v, macro_context=ctx)
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            results.append((row["frame"], h == row["state_sha1"],
                            h[:8], (row.get("state_sha1") or "")[:8]))
            prev_macro_id = row.get("macro")
            prev_focus = bool(row.get("focus_eff"))
            mid, foc = row.get("macro", "guard"), bool(row.get("focus_eff"))
            if row.get("exile_eff") or row.get("evade_eff"):
                tgt = Agent._evade_target(None, v)[0]
            else:
                tgt = resolve_macro_target(mid, v)
            cur_macro = TraceMacro(mid, foc, row["frame"], tgt)
            di += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))
        rendered += 1

    ok = sum(1 for r in results if r[1])
    print("tag=%s stage=%d: checked %d decisions (<=f%d): %d OK"
          % (tag, stage, len(results), maxf, ok))
    for r in results[:8]:
        print("  f%-7d %s  mine=%s trace=%s"
              % (r[0], "OK " if r[1] else "BAD", r[2], r[3]))
    sim.destroy()
    sim.global_shutdown()
    sys.exit(0 if ok == len(results) and results else 1)


if __name__ == "__main__":
    main()
