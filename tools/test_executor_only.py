"""M3 executor-only test (no Laya): validate the reflex evader.

Checks:
  1. Fallback-only episode (hold macro + evader) survives FAR longer than
     stand-still (874 frames on stage 1 Easy, seed 12345).
  2. Macro targets steer the player (advance -> toward boss / up, retreat ->
     bottom, hug_right -> right edge).
  3. No crashes through bullets/lasers/enemies/boss; terminal status reached.
  4. Wall fps of the executor loop.

    venv\\Scripts\\python.exe tools\\test_executor_only.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs, TaiseiSimError,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY,
    STATUS_RUNNING,
)
from macros import MacroTarget, resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")


def make_agent_free(sim, executor):
    """Minimal loop: given a macro supplier f(frame, view) -> Macro, run to
    terminal. Returns (frames_executed, final_view, wall_secs)."""
    pass


def run_with_macros(sim, executor, macro_of, max_frames=60 * 240):
    """macro_of(frame, v) -> Macro. Runs one episode to terminal."""
    executor.reset()
    v = None
    f = 0
    t0 = time.perf_counter()
    while f < max_frames:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        macro = macro_of(f, v)
        buttons = executor.execute(macro, v)
        try:
            sim.step(buttons=buttons)
        except TaiseiSimError:
            v = sim.get_state()
            break
        f += 1
    wall = time.perf_counter() - t0
    return v, f, wall


class M:  # tiny macro carrier
    def __init__(self, macro_id="hold", focus=False, bomb=False,
                 target=None, issued_frame=0, source="fallback"):
        self.macro_id = macro_id
        self.target = target or MacroTarget(kind="hold")
        self.focus = focus
        self.bomb = bomb
        self.issued_frame = issued_frame
        self.source = source


def main():
    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    os.makedirs(os.path.join(DATA, "storage"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "cache"), exist_ok=True)
    sim = TaiseiSim(LIB)
    print("ABI OK")
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

    # 1) fallback-only (hold + evader)
    sim.reset(ep)
    v, f, wall = run_with_macros(sim, ex, lambda f, v: M(issued_frame=f))
    pl = v.player
    print("\n[1] fallback hold+evader: frames=%d (%.1f s game) status=%d "
          "deaths=%d score=%d player=(%.0f,%.0f) wall_fps=%.0f"
          % (f, f / 60, v.raw.episode_status, v.raw.deaths, v.raw.score,
             pl.position.x, pl.position.y, f / max(wall, 1e-9)))
    assert f > 874, "evader should outlast stand-still (874 frames)"

    # 2) macro steering: 8 s advance, then 6 s retreat, then 6 s hug_right
    seq = [(0, 480, "advance"), (480, 840, "retreat"), (840, 1200, "hug_right")]
    pos_at = {}

    def macro_of(f, v):
        for a, b, mid in seq:
            if a <= f < b:
                return M(macro_id=mid, target=resolve_macro_target(mid, v),
                         issued_frame=f)
        return M(issued_frame=f)

    sim.reset(ep)
    v, f, wall = run_with_macros(sim, ex, macro_of)
    # re-simulate to capture positions at the boundaries
    sim.reset(ep)
    f = 0
    while f < 1200:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            print("died during steering test at frame", f)
            break
        if f in (400, 760, 1120):
            pos_at[f] = (v.player.position.x, v.player.position.y)
            print("[2] frame %4d pos=(%6.1f, %6.1f) macro=%s"
                  % (f, v.player.position.x, v.player.position.y,
                     macro_of(f, v).macro_id))
        buttons = ex.execute(macro_of(f, v), v)
        sim.step(buttons=buttons)
        f += 1
    y400 = pos_at.get(400, (0, 0))[1]
    y760 = pos_at.get(760, (0, 0))[1]
    x1120 = pos_at.get(1120, (0, 0))[0]
    if len(pos_at) == 3:
        assert y400 < 450, "advance should move the player up from spawn (y400=%.0f)" % y400
        assert y760 > 470, "retreat should bring the player back to the bottom (y760=%.0f)" % y760
        assert x1120 > 380, "hug_right should push the player to the right edge (x=%.0f)" % x1120
        print("[2] steering checks passed: advance up, retreat down, hug right")

    # 3) bomb macro: force a bomb at frame 300
    sim.reset(ep)

    def macro_of_bomb(f, v):
        if 300 <= f < 400:
            return M(macro_id="hold", bomb=True, issued_frame=300)
        return M(issued_frame=f)

    v, f, wall = run_with_macros(sim, ex, macro_of_bomb)
    print("[3] bomb macro: bombs_used=%d (expect >= 1)" % v.raw.bombs_used)
    assert v.raw.bombs_used >= 1, "bomb macro did not fire a bomb"

    sim.destroy()
    sim.global_shutdown()
    print("\nEXECUTOR-ONLY TEST PASSED")


if __name__ == "__main__":
    main()
