"""measure_bullet_density.py — enemy-bullet density for a recorded campaign
stage, for the S6 "many bullets" claim. Replays the stage bit-exactly with
the SAME setup as dump_replay_scores.py (trace macro sequence + VA4/blind/
ring executor, build-gl33 DLL, seed 12345+stage, checkpoint carry) and
reports enemy-bullet counts (mean/p50/p95/max + 10-segment table).

    venv\\Scripts\\python.exe tools\\measure_bullet_density.py <tag> <stage>
"""
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
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING, PROJ_ENEMY,
)
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from agent import Agent  # noqa: E402
from dump_probe_states import TraceMacro  # noqa: E402
from dump_replay_scores import load_stage, start_carry  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    tag, stage = sys.argv[1], int(sys.argv[2])

    seg, decisions, death_hits, cp = load_stage(tag, stage)
    diff_name = cp.get("difficulty", "normal")
    diff = DIFFS.get(diff_name, DIFFICULTY_NORMAL)
    carry = start_carry(tag, cp)
    if cp.get("no_bomb"):
        carry.update(initial_bombs=0, initial_bomb_fragments=0)

    register_runtime_dirs(
        os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
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
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=False,
                        gap_horizon=True, laser_blind_fix=True,
                        laser_ring=True)
    ex.reset()

    counts = []
    di = 0
    cur_macro = None
    while True:
        v = sim.get_state()
        lf = int(v.raw.logical_frame)
        st = int(v.raw.episode_status)
        counts.append(sum(1 for p in v.projectiles if p.category == PROJ_ENEMY))
        terminal = st != STATUS_RUNNING
        if not terminal:
            while di < len(decisions) and lf >= decisions[di]["frame"]:
                row = decisions[di]
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
        if terminal:
            break
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))

    sim.destroy()
    sim.global_shutdown()

    n = len(counts)
    s = sorted(counts)
    mean = sum(counts) / max(n, 1)
    p50 = s[n // 2] if n else 0
    p95 = s[min(n - 1, int(n * 0.95))] if n else 0
    mx = max(counts) if n else 0
    peak_f = (counts.index(mx) + 1) if n else 0
    print("tag=%s stage=%d diff=%s frames=%d deaths=%s"
          % (tag, stage, diff_name, n, death_hits))
    print("enemy bullets: mean=%.1f p50=%d p95=%d max=%d (peak f%d)"
          % (mean, p50, p95, mx, peak_f))
    K = 10
    seg_len = max(1, n // K)
    print("%10s %10s %8s" % ("frames", "mean", "max"))
    for k in range(K):
        chunk = counts[k * seg_len:(k + 1) * seg_len]
        if not chunk:
            continue
        print("%10d %10.1f %8d" % (k * seg_len + 1,
                                   sum(chunk) / len(chunk), max(chunk)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
