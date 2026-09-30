#!/usr/bin/env python3
"""v5 death-bomb instrumentation: pure-guard stage 3 (seed 12348), print
death-window frames: death_timer, bombs, bomb_active, executor BOMB bit.
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
    ACTION_BOMB,
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

    def guard_target(v):
        b = v.raw.boss
        x = max(X_MIN, min(X_MAX, float(b.position.x))) if b.active else 240.0
        return MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)

    sim.reset(ep)
    f = 0
    prev_dt = None
    deaths = 0
    while f < 60 * 600:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            print("\nENDED status=%s frame=%d deaths=%d score=%d bombs_used=%d"
                  % ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(
                        v.raw.episode_status, v.raw.episode_status),
                      v.raw.logical_frame, v.raw.deaths, v.raw.score,
                      v.raw.bombs_used))
            break
        pl = v.raw.player
        dt = pl.death_timer
        if prev_dt is not None and prev_dt < 0 and dt >= 0:
            deaths += 1
            print("HIT visible at frame f=%d" % v.raw.logical_frame)
        if dt >= 0:
            print("  WIN f=%-6d death_timer=%-3d bombs=%d bomb_active=%d "
                  "alive=%d invuln=%d pos=(%.1f,%.1f)"
                  % (v.raw.logical_frame, dt, pl.bombs, pl.bomb_active,
                     pl.alive, pl.invulnerable,
                     float(pl.position.x), float(pl.position.y)))
        prev_dt = dt
        buttons = ex.execute(M(target=guard_target(v), issued_frame=f), v)
        if dt >= 0:
            print("  ^^^ buttons=0x%02x BOMB=%s"
                  % (buttons, bool(buttons & ACTION_BOMB)))
        sim.step(buttons=buttons)
        f += 1
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
