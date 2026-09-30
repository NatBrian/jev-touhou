"""Log all item spawns during a passive stage-3 run (no input).

    venv\Scripts\python.exe tools\diag_item_spawns.py [stage] [seed] [max_frames]

Prints each newly-appeared item with frame, type, position, velocity.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, STATUS_RUNNING, STATUS_WON,
    STATUS_LOST, STATUS_ABORTED,
)
from macros import MacroTarget  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
ITEM_NAMES = {
    1: "PIV", 2: "points", 3: "mini power", 4: "power",
    5: "surge", 6: "voltage", 7: "bomb frag", 8: "life frag",
    9: "BOMB", 10: "LIFE",
}


def main():
    stage = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 12348
    max_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 6000

    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    os.makedirs(os.path.join(DATA, "storage"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "cache"), exist_ok=True)
    sim = TaiseiSim(os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll"))
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    sim.reset(EpisodeConfig(
        stage_id=stage, difficulty=DIFFICULTY_EASY,
        player_character=CHAR_MARISA, shot_mode=SHOT_A, rng_seed=seed,
    ))

    ex = ReflexExecutor()
    ex.reset()

    def guard_target(v):
        b = v.raw.boss
        x = max(60.0, min(420.0, float(b.position.x))) if b.active else 240.0
        return MacroTarget(kind="point", point=(x, 470.0), boss_anchored=False)

    class M:
        macro_id = "guard"
        source = "fallback"
        focus = False
        bomb = False
        issued_frame = 0
        def __init__(self, target):
            self.target = target

    from collections import deque
    seen = set()
    lives = None
    tail = deque(maxlen=40)
    f = 0
    while f < max_frames:
        v = sim.get_state()
        pl = v.raw.player
        st = v.raw
        if v.raw.episode_status != STATUS_RUNNING:
            print("=== last %d states before end ===" % len(tail))
            for t in tail:
                print("  " + t)
            print("episode ended at f%d status=%d" % (f + 1, v.raw.episode_status))
            print("FINAL STATE: f=%d stage_id=%s lives=%s frags=%s bombs=%s cont_used=%s deaths=%s pos=(%.1f,%.1f) score=%s" % (
                st.logical_frame, st.stage_id, pl.lives, pl.life_fragments,
                pl.bombs, st.continues_used, st.deaths,
                pl.position.x, pl.position.y, st.score))
            break
        tail.append("f%d stage_id=%s lives=%s frags=%s bombs=%s cont=%s deaths=%s pos=(%.1f,%.1f)" % (
            f + 1, st.stage_id, pl.lives, pl.life_fragments, pl.bombs,
            st.continues_used, st.deaths, pl.position.x, pl.position.y))
        for it in v.items:
            if it.spawn_id not in seen:
                seen.add(it.spawn_id)
                print("f%-6d item type=%d (%s) pos=(%.0f,%.0f) v=(%.1f,%.1f) lives=%s" % (
                    f + 1, it.item_type, ITEM_NAMES.get(it.item_type, "?"),
                    it.position.x, it.position.y, it.velocity.x, it.velocity.y,
                    v.raw.player.lives))
        if v.raw.player.lives != lives:
            print("f%-6d LIVES = %s (frags=%s)" % (f + 1, v.raw.player.lives,
                                                   v.raw.player.life_fragments))
            lives = v.raw.player.lives
        sim.step(buttons=ex.execute(M(guard_target(v)), v))
        f += 1
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
