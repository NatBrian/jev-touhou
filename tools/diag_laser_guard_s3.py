"""M3 laser re-validation (v1.4.6 content).

Runs the stage-3 guard (executor-only, -O0 build) and, at each death, logs the
PRE-HIT state's laser points near the player. Purpose: confirm the executor
actually SEES the v1.4.6 laser beam bodies in the snapshot (the rebase changed
laser.c +420 lines + added lasers/rules.c), so Laya + the reflex executor can
dodge them. If a death has laser points within a few px of the player, the beam
was visible (strategy problem, not a blindness problem).

    venv\\Scripts\\python.exe tools\\diag_laser_guard_s3.py [seed]
"""
import os, sys, math

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, STATUS_RUNNING,
)
from macros import MacroTarget  # noqa: E402
from executor import ReflexExecutor  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")
GUARD_Y = 470.0
X_MIN, X_MAX = 60.0, 420.0


class M:
    def __init__(self, target, issued_frame=0):
        self.macro_id = "guard"
        self.target = target
        self.focus = False
        self.bomb = False
        self.issued_frame = issued_frame
        self.source = "fallback"


def log_prehit(v, frame):
    p = v.raw.player.position
    px, py = float(p.x), float(p.y)
    near = []
    for lp in v.laser_points:
        lx, ly = float(lp.position.x), float(lp.position.y)
        hw = float(lp.half_width)
        d = math.hypot(lx - px, ly - py) - hw
        near.append((d, lx, ly, hw, float(lp.time)))
    near.sort()
    print("=== DEATH PRE-HIT (state frame ~%d) ===" % frame)
    print("  player=(%.1f,%.1f)  bullets=%d  laser_points=%d"
          % (px, py, len(v.projectiles), len(v.laser_points)))
    if near:
        print("  NEAREST beam body: %.1f px  (point (%.1f,%.1f) hw=%.1f time=%.1f)"
              % (near[0][0], near[0][1], near[0][2], near[0][3], near[0][4]))
        within = sum(1 for n in near if n[0] < 30.0)
        print("  beam-body points within 30 px of player: %d" % within)
        for n in near[:3]:
            print("    %5.1f px  (%5.1f,%5.1f) hw=%4.1f t=%6.1f" % n)
    else:
        print("  NO laser points on screen (pure-bullet death)")


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
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 12348
    ep = EpisodeConfig(stage_id=3, difficulty=DIFFICULTY_EASY,
                       player_character=CHAR_MARISA, shot_mode=SHOT_A, rng_seed=seed)
    ex = ReflexExecutor()
    ex.reset()

    def guard_target(v):
        b = v.raw.boss
        x = max(X_MIN, min(X_MAX, float(b.position.x))) if b.active else 240.0
        return MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)

    sim.reset(ep)
    f = 0
    prev_v = None
    prev_dt = None
    while f < 60 * 600:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            print("\nENDED status=%s frame=%d deaths=%d score=%d"
                  % ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(
                        v.raw.episode_status, v.raw.episode_status),
                      v.raw.logical_frame, v.raw.deaths, v.raw.score))
            break
        dt = v.raw.player.death_timer
        if prev_dt is not None and prev_dt < 0 and dt >= 0:
            log_prehit(prev_v, f - 1)
        prev_dt = dt
        prev_v = v
        buttons = ex.execute(M(target=guard_target(v), issued_frame=f), v)
        sim.step(buttons=buttons)
        f += 1
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
