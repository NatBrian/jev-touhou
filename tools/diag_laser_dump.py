"""Diag: full laser dump at the stage-3 hit frame (pure guard run, f~7195-7200).

    venv\Scripts\python.exe tools\diag_laser_dump.py
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
    for f in range(7210):
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        b = v.raw.boss
        x = max(X_MIN, min(X_MAX, float(b.position.x))) if b.active else 240.0
        t = MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)
        m = Macro(macro_id="guard", target=t, issued_frame=f, source="fallback")
        sim.step(buttons=ex.execute(m, v))
        if f not in (7197, 7198):
            continue
        pl = v.raw.player
        px, py = float(pl.position.x), float(pl.position.y)
        print("=== f%d player=(%.1f,%.1f) lasers=%d laser_points=%d ==="
              % (f, px, py, len(v.lasers), len(v.laser_points)))
        for li, L in enumerate(v.lasers):
            if not L.collision_active:
                continue
            end = min(int(L.first_point) + int(L.point_count), len(v.laser_points))
            pts = v.laser_points[int(L.first_point):end]
            # distance from player to each sampled point
            ds = []
            for pt in pts:
                d = ((float(pt.position.x) - px) ** 2 +
                     (float(pt.position.y) - py) ** 2) ** 0.5
                ds.append(d)
            near = (min(ds) if ds else None)
            if near is None or near < 120:
                o = L.origin
                tip = pts[-1].position if pts else None
                print("  laser[%d] origin=(%.1f,%.1f) age=%d w=%.1f speed=%.2f "
                      "timespan=%.1f tshift=%.1f death=%.1f pts=%d/%d "
                      "tip=(%s,%s) min_pt_d=%s half_w=%s"
                      % (li, float(o.x), float(o.y), int(L.age_frames), float(L.width),
                         float(L.speed), float(L.timespan), float(L.time_shift),
                         float(L.death_time), int(L.first_point), int(L.point_count),
                         ("%.1f" % float(tip.x)) if tip else "-",
                         ("%.1f" % float(tip.y)) if tip else "-",
                         ("%.1f" % near) if near is not None else "-",
                         ("%.1f" % float(pts[0].half_width)) if pts else "-"))
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
