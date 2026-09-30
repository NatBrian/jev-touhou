"""M3 strategy validation (executor-only, no Laya): 'guard' play.

Hypothesis: the winning Marisa A strategy is to stay in the LOWER CENTER,
roughly below the boss (so the fixed-upward shot keeps hitting the boss) while
the reflex evader dodges. This test runs that strategy executor-only on stage 1
Easy and measures survival + boss-kill time + deaths.

    venv\Scripts\python.exe tools\test_guard_strategy.py
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
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, DIFFICULTY_NORMAL,
    DIFFICULTY_HARD, DIFFICULTY_LUNATIC, STATUS_RUNNING,
)
DIFFS = {"easy": DIFFICULTY_EASY, "normal": DIFFICULTY_NORMAL,
         "hard": DIFFICULTY_HARD, "lunatic": DIFFICULTY_LUNATIC}
from macros import MacroTarget  # noqa: E402
from executor import ReflexExecutor  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")
GUARD_Y = 470.0          # lower center, safe from most patterns
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
    stage = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    diff = DIFFS.get(sys.argv[2] if len(sys.argv) > 2 else "easy", DIFFICULTY_EASY)
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 12345
    forced_focus = (len(sys.argv) > 4 and sys.argv[4].lower() in ("focus", "1", "true"))
    no_assist = (len(sys.argv) > 5 and sys.argv[5].lower() in ("noassist", "0", "false"))
    if no_assist:
        import executor as _ex
        _ex.ITEM_ASSIST_BETA = 0.0
    ep = EpisodeConfig(stage_id=stage, difficulty=diff,
                       player_character=CHAR_MARISA, shot_mode=SHOT_A,
                       rng_seed=seed)
    ex = ReflexExecutor()
    ex.reset()

    def guard_target(v):
        b = v.raw.boss
        if b.active:
            x = max(X_MIN, min(X_MAX, float(b.position.x)))
        else:
            x = 240.0
        return MacroTarget(kind="point", point=(x, GUARD_Y), boss_anchored=False)

    sim.reset(ep)
    f = 0
    t0 = time.perf_counter()
    boss_first_active = None
    boss_hp_series = []
    death_frames = []
    bullet_peak = 0
    final = None
    prev_deaths = 0
    while f < 60 * 600:  # 10 min game-time cap (stage 3 Easy v4 ~19.6k frames)
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            final = v
            break
        if v.raw.deaths > prev_deaths:
            death_frames.append((f, round(v.raw.player.position.x, 1),
                                 round(v.raw.player.position.y, 1),
                                 len(v.projectiles)))
            prev_deaths = v.raw.deaths
        bullet_peak = max(bullet_peak, len(v.projectiles))
        b = v.raw.boss
        if b.active and boss_first_active is None:
            boss_first_active = f
        if b.active and b.max_hp > 0 and f % 30 == 0:
            boss_hp_series.append((f, b.hp / b.max_hp))
        t = guard_target(v)
        buttons = ex.execute(M(target=t, issued_frame=f, focus=forced_focus), v)
        sim.step(buttons=buttons)
        f += 1
    wall = time.perf_counter() - t0

    if final is None:
        print("UNFINISHED: stage still running at the frame cap")
        sim.destroy()
        sim.global_shutdown()
        return
    pl = final.player
    st = final.raw
    print("\n== guard strategy (stage %d %s, seed %d, %s%s) ==" % (stage,
          {v: k for k, v in DIFFS.items()}.get(diff, diff), seed,
          "forced-focus" if forced_focus else "no-focus",
          ", no-assist" if no_assist else ""))
    print("status=%s frames=%d deaths=%d bombs=%d score=%d"
          % ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(st.episode_status,
             st.episode_status), st.logical_frame, st.deaths,
             st.bombs_used, st.score))
    print("boss first active at frame %s" % boss_first_active)
    if boss_first_active is not None:
        active = [(ff, hp) for (ff, hp) in boss_hp_series if ff >= boss_first_active]
        if active:
            print("boss hp at first active: %.2f (f%d)" % (active[0][1], active[0][0]))
            print("boss hp at last sample:  %.2f (f%d)" % (active[-1][1], active[-1][0]))
            # find first frame hp <= 0 (kill)
            kill = None
            for (ff, hp) in active:
                if hp <= 0.0:
                    kill = ff
                    break
            print("boss killed at frame %s (%.1f s after boss appeared)"
                  % (kill, (kill - boss_first_active) / 60.0) if kill
                  else "boss NOT killed before episode end")
    print("player end pos=(%s,%s)" % (pl.position.x, pl.position.y) if pl else "")
    print("deaths: %s (boss from f%s, max live bullets %d)"
          % (death_frames or "-", boss_first_active, bullet_peak))
    print("wall fps=%.0f" % (f / max(wall, 1e-9)))
    replay_dir = os.path.join(DATA, "replays")
    os.makedirs(replay_dir, exist_ok=True)
    replay_path = os.path.join(
        replay_dir,
        "guard-stage%d-%s-%d.trsr" % (stage,
                                      {v: k for k, v in DIFFS.items()}.get(diff, diff),
                                      seed))
    try:
        sim.save_replay(replay_path)
        print("replay:", replay_path)
    except Exception as e:
        print("replay save failed (non-fatal):", e)
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
