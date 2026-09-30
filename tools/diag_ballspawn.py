"""R5.2 ball spawn-time measurement (2026-09-26).

Replays the stage with the trace macros (base evader + gap horizon) and
counts, per frame in a window, enemy projectiles by collision radius
bucket.  Pins down WHEN the lasertrap balls (r ~ 12.6) appear.

    venv\\Scripts\\python.exe tools\\diag_ballspawn.py <tag> <stage> <lo> <hi> [diff] [carry.json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING, PROJ_ENEMY,
)
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from probe_evader import TraceMacro, load_trace_seq, DIFFS, LIB  # noqa: E402


def main():
    args = sys.argv[1:]
    tag, stage = args[0], int(args[1])
    lo, hi = int(args[2]), int(args[3])
    diff = DIFFS.get(args[4] if len(args) > 4 else "normal", DIFFICULTY_NORMAL)
    carry_file = args[5] if len(args) > 5 else None

    carry = {}
    if carry_file:
        cp_in = json.load(open(carry_file, encoding="utf-8"))
        carry = dict(cp_in.get("carry") or
                     (cp_in if "initial_score" in cp_in else {}))

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

    seq = load_trace_seq(tag, stage)
    seq_idx = 0
    cur_macro = None
    frames = 0
    while frames < 30000:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, mid, foc = seq[seq_idx]
            cur_macro = TraceMacro(mid, foc, _f, resolve_macro_target(mid, v))
            seq_idx += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))

        if lo <= lf <= hi:
            buckets = {}
            for p in v.projectiles:
                if p.category != PROJ_ENEMY:
                    continue
                r = round(max(p.collision_size.x, p.collision_size.y))
                buckets[r] = buckets.get(r, 0) + 1
            print("f=%-5d %s" % (lf,
                  {int(k): n for k, n in sorted(buckets.items())}))
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))
        frames += 1
        if lf > hi + 50:
            break
    sim.destroy()
    sim.global_shutdown()
    print("== done: frames=%d ==" % frames)


if __name__ == "__main__":
    main()
