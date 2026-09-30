"""M3 G3: full campaign — 6 chained stages (default Easy; --diff for M4 ramp).

Gate (doc/design-m3-reflex-and-macros.md §7):
  * all 6 stages WON, Marisa A, fixed seed
  * per-stage Laya coverage >= 99% (untainted), no protocol errors
  * resource sanity: total deaths <= 9, total bombs <= 9 (M3 bar; the strict
    3-lives/3-bombs clean-run bar is the M4 Lunatic target)
  * per-episode checkpoints + replays written (crash-safe overnight runs, §12)

    venv\\Scripts\\python.exe tools\\test_m3_campaign.py [--seed N] [--diff easy|normal|hard|lunatic] [--engine laya|mica]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
REPO_PKGDIR = os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir")
DATA = os.path.join(HERE, "simdata")
# --build-dir selects which compiled sim DLL to drive (default: the -O0 headless
# 'build'; use 'build-gl33' for the M4 Lunatic clear that gets rendered by the
# gl33 taisei.exe, so the campaign + video use the same engine).
_build_dir = "build"
if "--build-dir" in sys.argv:
    _build_dir = sys.argv[sys.argv.index("--build-dir") + 1]
LIB = os.path.join(SIM_ROOT, _build_dir, "src", "sim", "libtaisei_sim.dll")

sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, DIFFICULTY_NORMAL,
    DIFFICULTY_HARD, DIFFICULTY_LUNATIC, STATUS_WON,
)
DIFFS = {"easy": DIFFICULTY_EASY, "normal": DIFFICULTY_NORMAL,
         "hard": DIFFICULTY_HARD, "lunatic": DIFFICULTY_LUNATIC}
from laya_client import LayaClient, MicaClient  # noqa: E402
from agent import Agent  # noqa: E402


def main():
    seed = 12345
    diff = DIFFICULTY_EASY
    diff_name = "easy"
    no_bomb = "--no-bomb" in sys.argv
    no_focus = "--no-focus" in sys.argv
    edge_escape = "--edge-escape" in sys.argv
    path_risk = "--path-risk" in sys.argv
    danger_valve = "--danger-valve" in sys.argv
    gap_horizon = "--gap-horizon" in sys.argv
    escape_commit = "--escape-commit" in sys.argv
    laser_blind_fix = "--laser-blind-fix" in sys.argv
    laser_ring = "--laser-ring" in sys.argv
    wall_commit = "--wall-commit" in sys.argv
    dense_wall = "--dense-wall" in sys.argv
    wall_danger = "--wall-danger" in sys.argv
    if danger_valve:
        print("DANGER_VALVE=1 (R3 opt-in; no-bomb only)", flush=True)
    if gap_horizon:
        import executor as executor_module
        print("GAP_HORIZON=1 (R4.7 adaptive gap horizon; tts=%s snap_at=%.1f)"
              % (executor_module.GAP_HORIZON_TTS,
                 executor_module.GAP_HORIZON_SNAP_AT), flush=True)
    if escape_commit:
        import executor as executor_module
        print("ESCAPE_COMMIT=1 (R4.8 escape commit; at=%.1f frames=%d)"
              % (executor_module.ESCAPE_COMMIT_AT,
                 executor_module.ESCAPE_COMMIT_FRAMES), flush=True)
    if laser_blind_fix:
        print("LASER_BLIND_FIX=1 (R5.1: keep retraction-phase beams; "
              "trace IS the drawn beam)", flush=True)
    if laser_ring:
        import executor as executor_module
        print("LASER_RING=1 (R5.2 converging-ring escape; shrink>=%.1f px/f)"
              % executor_module.RING_SHRINK_RATE, flush=True)
    if wall_commit:
        import executor as executor_module
        print("WALL_COMMIT=1 (R6.1 wall commit; at=%.0f persist=%d "
              "frames=%d path=%d)"
              % (executor_module.WALL_COMMIT_AT,
                 executor_module.WALL_COMMIT_PERSIST,
                 executor_module.WALL_COMMIT_FRAMES,
                 executor_module.WALL_COMMIT_PATH), flush=True)
    if dense_wall:
        import executor as executor_module
        print("DENSE_WALL=1 (R7 dense-wall stay-up bias; band=%.0f px "
              "threshold=%.0f persist=%d release=%.0f/%d penalty=%.0f)"
              % (executor_module.DENSE_BAND, executor_module.DENSE_THRESHOLD,
                 executor_module.DENSE_PERSIST, executor_module.DENSE_RELEASE,
                 executor_module.DENSE_RELEASE_PERSIST,
                 executor_module.DENSE_DOWN_PENALTY), flush=True)
    if wall_danger:
        import executor as executor_module
        print("WALL_DANGER=1 (R7b per-wall bullet danger; count=%.0f "
              "radius=%.0f k=%.0f)"
              % (executor_module.WALL_DANGER_COUNT,
                 executor_module.WALL_DANGER_R,
                 executor_module.WALL_DANGER_K), flush=True)
    # --start-stage / --end-stage / --carry (2026-09-26): standalone stage
    # measurement — run one stage (or a tail) with an explicit carry so
    # S4-S6 death distributions can be measured without S1-S3 (the stage
    # pattern is identical: rng_seed = seed + stage).
    start_stage, end_stage = 1, 6
    if "--start-stage" in sys.argv:
        start_stage = int(sys.argv[sys.argv.index("--start-stage") + 1])
    if "--end-stage" in sys.argv:
        end_stage = int(sys.argv[sys.argv.index("--end-stage") + 1])
    carry_file = None
    if "--carry" in sys.argv:
        carry_file = sys.argv[sys.argv.index("--carry") + 1]
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])
    if "--diff" in sys.argv:
        diff_name = sys.argv[sys.argv.index("--diff") + 1].lower()
        diff = DIFFS.get(diff_name, DIFFICULTY_EASY)
    # --engine {laya,mica} (2026-09-27): A/B the decision engine. Laya is the
    # default (project constraint); Mica (mica-v0.1-4b, :8010) is opt-in.
    # Same harness/executor either way — only the decision maker changes
    # (doc/research-mica.md).
    engine = "laya"
    if "--engine" in sys.argv:
        engine = sys.argv[sys.argv.index("--engine") + 1].lower()
        if engine not in ("laya", "mica"):
            sys.exit("--engine must be 'laya' or 'mica'")

    if path_risk:
        import executor as executor_module
        executor_module.PATH_RISK_WEIGHT = 0.35
        print("PATH_RISK_FRAMES=%d PATH_RISK_WEIGHT=0.35" %
              executor_module.PATH_RISK_FRAMES, flush=True)

    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    for d in ("storage", "cache", "replays", "checkpoints"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)

    sim = TaiseiSim(LIB)
    print("ABI OK", flush=True)
    sim.global_init(
        resource_path=REPO_PKGDIR,
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()

    if engine == "mica":
        laya = MicaClient()
        h = laya.health()
        print("mica health:", h.get("status"), h.get("model"), flush=True)
    else:
        laya = LayaClient(base_url="http://127.0.0.1:8002")
        h = laya.health()
        print("laya host health:", h.get("status"), h.get("gpu"), flush=True)

    tag = ("micacam-" if engine == "mica" else "m3cam-") + \
        "%02d%02d-%02d%02d%02d" % time.localtime()[1:6]
    agent = Agent(sim, laya, log_dir=DATA, episode_tag=tag,
                  allow_bombs=not no_bomb, allow_focus=not no_focus,
                  allow_edge_escape=edge_escape,
                  danger_valve=danger_valve, gap_horizon=gap_horizon,
                  escape_commit=escape_commit,
                  laser_blind_fix=laser_blind_fix, laser_ring=laser_ring,
                  wall_commit=wall_commit, dense_wall=dense_wall,
                  wall_danger=wall_danger)
    carry = {}
    if carry_file:
        cp_in = json.load(open(carry_file, encoding="utf-8"))
        # accept a raw carry dict or a checkpoint file with a "carry" key
        carry = dict(cp_in.get("carry") or (cp_in if "initial_score" in cp_in else {}))
        print("CARRY loaded from %s: %s" % (carry_file, carry), flush=True)
    if no_bomb:
        carry.update(initial_bombs=0, initial_bomb_fragments=0)
    totals = {"deaths": 0, "bombs": 0, "score": 0}
    all_ok = True
    t_game0 = time.perf_counter()

    # 'final' mode: the sim pauses (freezes) while Laya is unreachable, so a
    # transient Laya-host outage costs wall-clock time only -> 100% Laya coverage by
    # construction (untainted). 'explore' mode (fallback + taint) is for
    # overnight tuning runs, not for the clean campaign.
    for stage in range(start_stage, end_stage + 1):
        ep = EpisodeConfig(
            stage_id=stage, difficulty=diff,
            player_character=CHAR_MARISA, shot_mode=SHOT_A,
            rng_seed=seed + stage,
            **carry,
        )
        t0 = time.perf_counter()
        r = agent.run_episode(ep, mode="final")
        wall = time.perf_counter() - t0
        cov = 1.0 - (r.uncovered_frames / max(r.executed_frames, 1))

        replay_path = os.path.join(DATA, "replays", "%s-stage%d-%s.trsr" % (tag, stage, diff_name))
        try:
            sim.save_replay(replay_path)
        except Exception as e:
            print("replay save failed (non-fatal):", e)
            replay_path = None

        ok_stage = (r.status == STATUS_WON and cov >= 0.99
                    and not r.taint and r.protocol_errors == 0
                    and (not no_bomb or r.bombs_used == 0))
        all_ok = all_ok and ok_stage
        totals["deaths"] += r.deaths
        totals["bombs"] += r.bombs_used
        totals["score"] += r.score

        cp = {
            "tag": tag, "seed": seed, "stage": stage, "difficulty": diff_name,
            "engine": engine,  # 'laya' | 'mica' (A/B decision engine, 2026-09-27)
            "character": "marisa", "shot_mode": "A",
            "carried_from": (carry_file if stage == start_stage else stage - 1),
            "no_bomb": no_bomb, "allow_bombs": not no_bomb,
            "no_focus": no_focus, "allow_focus": not no_focus,
            "edge_escape": edge_escape,
            "path_risk": path_risk,
            "danger_valve": danger_valve,
            "gap_horizon": gap_horizon,
            "escape_commit": escape_commit,
            "laser_blind_fix": laser_blind_fix,
            "laser_ring": laser_ring,
            "wall_commit": wall_commit,
            "dense_wall": dense_wall,
            "wall_danger": wall_danger,
            # R4.1/R4.2: no-bomb mode uses the repurposed bomb_now evade
            # trigger (threshold 0.55) + harness edge exile — recorded for
            # provenance.
            "no_bomb_evade": no_bomb,
            "status": r.status, "frames": r.frames, "deaths": r.deaths,
            "bombs_used": r.bombs_used, "score": r.score,
            "laya_calls": r.laya_calls, "laya_failures": r.laya_failures,
            "coverage": cov, "taint": r.taint, "wall_secs": wall,
            "replay": replay_path, "carry": None,
        }
        if r.status == STATUS_WON:
            v = sim.get_state()
            carry = Agent.carry_over(v)
            if no_bomb:
                carry["initial_bombs"] = 0
                carry["initial_bomb_fragments"] = 0
            cp["carry"] = carry
        cp_path = os.path.join(DATA, "checkpoints", "%s-stage%d.json" % (tag, stage))
        with open(cp_path, "w", encoding="utf-8") as f:
            json.dump(cp, f, indent=1)

        print("\n== stage %d: %s frames=%d deaths=%d bombs=%d score=%d "
              "cov=%.2f%% taint=%s wall=%.1fs%s =="
              % (stage,
                 {2: "WON", 3: "LOST", 4: "ABORTED"}.get(r.status, r.status),
                 r.frames, r.deaths, r.bombs_used, r.score, 100 * cov,
                 r.taint, wall, "" if ok_stage else "  <-- FAIL"), flush=True)
        if r.status != STATUS_WON:
            print("campaign stopped at stage", stage)
            break

    sim.destroy()
    sim.global_shutdown()

    total_wall = time.perf_counter() - t_game0
    print("\n== campaign totals: deaths=%d bombs=%d score=%d wall=%.1f min =="
          % (totals["deaths"], totals["bombs"], totals["score"], total_wall / 60))
    # M3 gate: all 6 stages WON with full coverage, and the run uses a NORMAL
    # amount of resources (not farming/inflating). The strict "3 lives/3 bombs,
    # no inflation" clean-run bar is the M4 Lunatic target, not the Easy milestone.
    ok = (all_ok and totals["deaths"] <= 9
          and (totals["bombs"] == 0 if no_bomb else totals["bombs"] <= 9))
    print("M3 G3 %s (6 stages WON, coverage>=99%% each, untainted; "
          "resource sanity deaths<=9, bombs<=9)" % ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
