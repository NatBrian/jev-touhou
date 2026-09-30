"""Diag: per-frame beam approach around the stage-3 death (pure guard run).

Dumps player pos + nearest-beam distance for frames 7150-7215 to show the
sweeping-laser approach speed.

    venv\Scripts\python.exe tools\diag_beam_sweep.py
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
    for f in range(7400):
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        b = v.raw.boss
        x = max(X_MIN, min(X_MAX, float(b.position.x))) if b.active else 240.0
        t = MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)
        m = Macro(macro_id="guard", target=t, issued_frame=f, source="fallback")
        sim.step(buttons=ex.execute(m, v))
        if 7150 <= f <= 7215:
            pl = v.raw.player
            px, py = float(pl.position.x), float(pl.position.y)
            lps = v.laser_points
            best = None
            for L in v.lasers:
                if not L.collision_active:
                    continue
                end = min(int(L.first_point) + int(L.point_count), len(lps))
                for i in range(int(L.first_point), end):
                    pt = lps[i]
                    d = ((float(pt.position.x) - px) ** 2 +
                         (float(pt.position.y) - py) ** 2) ** 0.5 \
                        - (float(pt.half_width) if pt.half_width > 0 else 0.0)
                    if best is None or d < best[0]:
                        best = (d, L.age_frames, float(L.width), float(L.speed),
                                int(L.point_count), int(L.first_point))
            dt = int(v.raw.player.death_timer)
            print("f%d player=(%.1f,%.1f) lasers_active=%d death_timer=%d nearest: %s"
                  % (f, px, py,
                     sum(1 for L in v.lasers if L.collision_active), dt,
                     ("d=%.1f age=%d w=%.1f speed=%.2f pts=%d/%d" % best)
                     if best else "-"))
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
