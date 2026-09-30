"""One-shot: per-frame state dump around a frame range (divergence forensics).

Runs the guard strategy on a stage and prints per-frame: score, player pos,
boss pos+hp, bullet/enemy/item counts, inputflags.
"""
import os
import sys
import time

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
    def __init__(self, target, issued_frame=0, focus=False, bomb=False):
        self.macro_id = "guard"
        self.target = target
        self.focus = focus
        self.bomb = bomb
        self.issued_frame = issued_frame
        self.source = "fallback"


def main():
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 7440
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else 7470
    stage = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 12346

    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    ep = EpisodeConfig(stage_id=stage, difficulty=DIFFICULTY_EASY,
                       player_character=CHAR_MARISA, shot_mode=SHOT_A,
                       rng_seed=seed)
    ex = ReflexExecutor()
    ex.reset()
    sim.reset(ep)

    def guard_target(v):
        b = v.raw.boss
        if b.active:
            x = max(X_MIN, min(X_MAX, float(b.position.x)))
        else:
            x = 240.0
        return MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)

    f = 0
    prev = None
    while f <= hi and f < 60 * 600:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        if lo <= f <= hi:
            pl = v.player
            b = v.raw.boss
            items = len(v.items)
            enemies = len(v.enemies)
            line = ("f%-5d score=%-9d plr=(%6.1f,%6.1f) v=(%4.1f,%4.1f) in=0x%02x "
                    "boss=%s hp=%-6.3f bullets=%-4d enemies=%-3d items=%d"
                    % (f, v.raw.score, float(pl.position.x), float(pl.position.y),
                       float(pl.velocity.x), float(pl.velocity.y), pl.input_flags,
                       "on" if b.active else "off",
                       (b.hp / b.max_hp) if (b.active and b.max_hp > 0) else -1.0,
                       len(v.projectiles), enemies, items))
            if prev is not None:
                d = " d(score)=%+d" % (v.raw.score - prev)
            else:
                d = ""
            print(line + d, flush=True)
            prev = v.raw.score
        t = guard_target(v)
        buttons = ex.execute(M(target=t, issued_frame=f, focus=False), v)
        sim.step(buttons=buttons)
        f += 1
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
