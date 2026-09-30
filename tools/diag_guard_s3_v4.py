"""Diag: pure-guard stage 3 (seed 12348) with executor v4, no frame cap.

Prints a milestone every 500 frames (deaths, lives, boss state, player pos)
to see why the stage drags past 18000 frames.

    venv\Scripts\python.exe tools\diag_guard_s3_v4.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, STATUS_RUNNING,
)
from macros import MacroTarget  # noqa: E402
from agent import Macro  # noqa: E402
from executor import ReflexExecutor  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")
GUARD_Y = 470.0
X_MIN, X_MAX = 60.0, 420.0


def main():
    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    os.makedirs(os.path.join(DATA, "storage"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "cache"), exist_ok=True)
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    ep = EpisodeConfig(stage_id=3, difficulty=DIFFICULTY_EASY,
                       player_character=CHAR_MARISA, shot_mode=SHOT_A,
                       rng_seed=12348)
    ex = ReflexExecutor()
    ex.reset()
    sim.reset(ep)
    last_report = 0
    f = 0
    while f < 40000:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            print("f%d status=%d deaths=%d score=%d"
                  % (int(v.raw.logical_frame), v.raw.episode_status,
                     int(v.raw.deaths), int(v.raw.score)))
            break
        b = v.raw.boss
        x = max(X_MIN, min(X_MAX, float(b.position.x))) if b.active else 240.0
        m = Macro(macro_id="guard",
                  target=MacroTarget(kind="point", point=(x, GUARD_Y),
                                     boss_anchored=False),
                  issued_frame=f, source="fallback")
        sim.step(buttons=ex.execute(m, v))
        f += 1
        if f - last_report >= 500:
            pl = v.raw.player
            hp = (float(b.hp) / float(b.max_hp)) if b.active else None
            print("f%6d deaths=%d lives=%d boss=%s hp=%s player=(%.0f,%.0f) "
                  "laser_pts=%d"
                  % (f, int(v.raw.deaths), int(pl.lives) + 1,
                     "A" if b.active else "-",
                     ("%.3f" % hp) if hp is not None else "-",
                     float(pl.position.x), float(pl.position.y),
                     len(v.laser_points)))
            last_report = f
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
