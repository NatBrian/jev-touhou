"""Executor-only guard diagnostic on a selected v1.4.6 stage.

Uses the same build-gl33 DLL as the campaign and logs every hit/death,
including the active laser count and the player's resources. This is a
diagnostic, not a final campaign: it may use explicit initial resources to
separate stage survivability from carry-over depletion.

    venv\\Scripts\\python.exe tools\\diag_guard_stage.py 6 12351 easy 3 3 [horizon]

For a campaign carry reproduction, optional arguments after horizon are
`point_item_value score bomb_fragments power graze wall_k scan_radius`.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, DIFFICULTY_NORMAL,
    DIFFICULTY_HARD, DIFFICULTY_LUNATIC, STATUS_RUNNING,
    ACTION_BOMB,
)
from macros import MacroTarget  # noqa: E402
from executor import ReflexExecutor  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")
DIFFS = {"easy": DIFFICULTY_EASY, "normal": DIFFICULTY_NORMAL,
         "hard": DIFFICULTY_HARD, "lunatic": DIFFICULTY_LUNATIC}
GUARD_Y = 470.0
X_MIN, X_MAX = 60.0, 420.0


class GuardMacro:
    macro_id = "guard"
    focus = False
    bomb = False
    source = "fallback"

    def __init__(self, target, issued_frame):
        self.target = target
        self.issued_frame = issued_frame


def main():
    args = []
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg == "--guard-y":
            skip_next = True
            continue
        if arg not in ("--no-bomb", "--rollout", "--raw-risk",
                       "--edge-escape", "--no-focus", "--wide-scan",
                       "--path-risk", "--danger-valve"):
            args.append(arg)
    stage = int(args[0]) if len(args) > 0 else 6
    seed = int(args[1]) if len(args) > 1 else 12351
    diff_name = args[2].lower() if len(args) > 2 else "easy"
    initial_lives = int(args[3]) if len(args) > 3 else 3
    initial_bombs = int(args[4]) if len(args) > 4 else 3
    no_bomb = "--no-bomb" in sys.argv
    rollout = "--rollout" in sys.argv
    raw_risk = "--raw-risk" in sys.argv
    edge_escape = "--edge-escape" in sys.argv
    no_focus = "--no-focus" in sys.argv
    wide_scan = "--wide-scan" in sys.argv
    path_risk = "--path-risk" in sys.argv
    danger_valve = "--danger-valve" in sys.argv
    guard_y = GUARD_Y
    if "--guard-y" in sys.argv:
        index = sys.argv.index("--guard-y")
        guard_y = float(sys.argv[index + 1])
        print("GUARD_Y=%.1f" % guard_y, flush=True)
    if no_bomb:
        initial_bombs = 0
    if rollout:
        import executor as executor_module
        executor_module.DODGE_ROLLOUT_WEIGHT = 0.35
        executor_module.DANGER_INTENT_FACTOR = 1.0
        print("DODGE_ROLLOUT_WEIGHT=0.35 DANGER_INTENT_FACTOR=1.0", flush=True)
    if raw_risk:
        import executor as executor_module
        executor_module.DANGER_INTENT_FACTOR = 0.0
        print("DANGER_INTENT_FACTOR=0.0", flush=True)
    if edge_escape:
        import executor as executor_module
        executor_module.EDGE_ESCAPE_PENALTY = 1000.0
        print("EDGE_ESCAPE_PENALTY=%.1f EDGE_GATE_TTH=%.1f (R4.5)" %
              (executor_module.EDGE_ESCAPE_PENALTY,
               executor_module.EDGE_GATE_TTH), flush=True)
    if wide_scan:
        import executor as executor_module
        executor_module.R_SCAN = 300.0
        executor_module.R_SCAN2 = executor_module.R_SCAN ** 2
        print("R_SCAN=300.0 R_SCAN2=90000.0", flush=True)
    if path_risk:
        import executor as executor_module
        executor_module.PATH_RISK_WEIGHT = 0.35
        print("PATH_RISK_FRAMES=%d PATH_RISK_WEIGHT=0.35" %
              executor_module.PATH_RISK_FRAMES, flush=True)
    if len(args) > 5:
        import executor as executor_module
        executor_module.THREAT_HORIZON = int(args[5])
        print("THREAT_HORIZON=%d" % executor_module.THREAT_HORIZON, flush=True)
    carry = {}
    carry_names = ("initial_point_item_value", "initial_score",
                   "initial_bomb_fragments", "initial_power", "initial_graze")
    for index, name in enumerate(carry_names, start=6):
        if len(args) > index:
            carry[name] = int(args[index])
    if no_bomb:
        carry["initial_bomb_fragments"] = 0
    if len(args) > 11:
        import executor as executor_module
        executor_module.WALL_K = float(args[11])
        print("WALL_K=%.3f" % executor_module.WALL_K, flush=True)
    if len(args) > 12:
        import executor as executor_module
        executor_module.R_SCAN = float(args[12])
        executor_module.R_SCAN2 = executor_module.R_SCAN ** 2
        print("R_SCAN=%.1f" % executor_module.R_SCAN, flush=True)
    if carry:
        print("CARRY=%s" % carry, flush=True)
    diff = DIFFS[diff_name]

    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    for d in ("storage", "cache"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    sim.reset(EpisodeConfig(
        stage_id=stage, difficulty=diff, player_character=CHAR_MARISA,
        shot_mode=SHOT_A, rng_seed=seed, initial_lives=initial_lives,
        initial_bombs=initial_bombs,
        **carry,
    ))
    ex = ReflexExecutor(allow_bombs=not no_bomb,
                        allow_edge_escape=edge_escape,
                        speed_focus=(6.25 if no_focus else 2.75),
                        danger_valve=danger_valve)
    ex.reset()
    prev_dt = -1
    f = 0
    hits = 0
    bomb_presses = 0
    print("START stage=%d seed=%d diff=%s initial_lives=%d initial_bombs=%d "
          "no_bomb=%s no_focus=%s rollout=%s raw_risk=%s edge_escape=%s "
          "wide_scan=%s path_risk=%s danger_valve=%s guard_y=%.1f" %
          (stage, seed, diff_name, initial_lives, initial_bombs, no_bomb,
           no_focus, rollout, raw_risk, edge_escape, wide_scan, path_risk,
           danger_valve, guard_y),
          flush=True)
    while f < 60 * 900:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            print("END status=%s frame=%d deaths=%d bombs_used=%d score=%d "
                  "lives=%d bombs=%d life_frags=%d bomb_frags=%d "
                  "power=%d piv=%d graze=%d" %
                  ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(
                      v.raw.episode_status, v.raw.episode_status),
                      v.raw.logical_frame, v.raw.deaths, v.raw.bombs_used,
                       v.raw.score, v.raw.player.lives, v.raw.player.bombs,
                      v.raw.player.life_fragments, v.raw.player.bomb_fragments,
                      v.raw.player.stored_power, v.raw.player.point_item_value,
                       v.raw.graze), flush=True)
            break
        pl = v.raw.player
        dt = int(pl.death_timer)
        if prev_dt < 0 and dt >= 0:
            hits += 1
            print("HIT f=%d pos=(%.1f,%.1f) dt=%d bombs=%d bullets=%d enemies=%d lasers=%d points=%d" %
                  (v.raw.logical_frame, float(pl.position.x), float(pl.position.y),
                   dt, pl.bombs,
                   len(v.projectiles), len([e for e in v.enemies if e.harmful]),
                   len([l for l in v.lasers if l.collision_active]),
                   len(v.laser_points)), flush=True)
        target_x = 240.0
        if v.raw.boss.active:
            target_x = max(X_MIN, min(X_MAX, float(v.raw.boss.position.x)))
        macro = GuardMacro(MacroTarget(kind="point", point=(target_x, guard_y),
                                       boss_anchored=False), f)
        buttons = ex.execute(macro, v)
        if buttons & ACTION_BOMB:
            bomb_presses += 1
        if dt >= 0 and (buttons & ACTION_BOMB):
            print("DEATH_BOMB_PRESS f=%d dt=%d bombs=%d" %
                  (v.raw.logical_frame, dt, pl.bombs), flush=True)
        sim.step(buttons=buttons)
        prev_dt = dt
        f += 1
    else:
        print("END max_frames hits=%d" % hits, flush=True)
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
