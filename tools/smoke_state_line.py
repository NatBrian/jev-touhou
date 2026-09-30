"""Smoke test: new state-compiler line + agent imports, no Laya needed.

    venv\Scripts\python.exe tools\smoke_state_line.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
import agent  # noqa: E402,F401  (imports state_compiler, executor, macros)
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, STATUS_RUNNING,
)
from executor import ReflexExecutor  # noqa: E402
from state_compiler import compile_state, _extra_life_hint  # noqa: E402
from macros import MacroTarget  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")
GUARD_Y = 470.0
X_MIN, X_MAX = 60.0, 420.0


class M:
    macro_id = "guard"
    source = "fallback"
    focus = False
    bomb = False

    def __init__(self, target, issued_frame=0):
        self.target = target
        self.issued_frame = issued_frame


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
    ep = EpisodeConfig(stage_id=1, difficulty=DIFFICULTY_EASY,
                       player_character=CHAR_MARISA, shot_mode=SHOT_A,
                       rng_seed=12345)
    ex = ReflexExecutor()
    ex.reset()
    sim.reset(ep)
    for f in range(900):
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        b = v.raw.boss
        x = max(X_MIN, min(X_MAX, float(b.position.x))) if b.active else 240.0
        t = MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)
        buttons = ex.execute(M(target=t, issued_frame=f), v)
        sim.step(buttons=buttons)
        if f in (120, 480, 880):
            text = compile_state(v)
            scene = text.split(". ")[0] + "."
            print("--- f%d state head: %s" % (f, scene))
    print("--- hint unit checks:")
    for s in (0, 4_950_000, 5_050_000, 19_950_000):
        print("   %9d ->%s" % (s, _extra_life_hint(s)))
    sim.destroy()
    sim.global_shutdown()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
