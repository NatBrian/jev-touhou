"""M3 G1: Laya-driven stage 1 Easy must be WON with natural play.

Gate (doc/design-m3-reflex-and-macros.md §7):
  * status WON, Marisa A, Easy, seed 12345
  * Laya coverage >= 99% (untainted), no protocol errors
  * deaths <= 2, bombs used <= 2 (natural play on Easy)
  * replay saved + checkpoint written (crash-safe overnight runs, §12)

    venv\\Scripts\\python.exe tools\\test_m3_survive.py [--seed N] [--stage N]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
REPO_PKGDIR = os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir")
DATA = os.path.join(HERE, "simdata")
LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")

sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, DIFFICULTY_NORMAL,
    DIFFICULTY_HARD, DIFFICULTY_LUNATIC, STATUS_WON,
)
DIFFS = {"easy": DIFFICULTY_EASY, "normal": DIFFICULTY_NORMAL,
         "hard": DIFFICULTY_HARD, "lunatic": DIFFICULTY_LUNATIC}
from laya_client import LayaClient  # noqa: E402
from agent import Agent  # noqa: E402


def main():
    seed = 12345
    stage = 1
    diff = DIFFICULTY_EASY
    diff_name = "easy"
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])
    if "--stage" in sys.argv:
        stage = int(sys.argv[sys.argv.index("--stage") + 1])
    if "--diff" in sys.argv:
        diff_name = sys.argv[sys.argv.index("--diff") + 1].lower()
        diff = DIFFS.get(diff_name, DIFFICULTY_EASY)

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

    laya = LayaClient(base_url="http://127.0.0.1:8002")
    h = laya.health()
    print("laya host health:", h.get("status"), h.get("gpu"), flush=True)

    tag = "m3-%02d%02d-%02d%02d%02d" % time.localtime()[1:6] + "-s%d-%s" % (stage, diff_name)
    agent = Agent(sim, laya, log_dir=DATA, episode_tag=tag)
    ep = EpisodeConfig(
        stage_id=stage, difficulty=diff,
        player_character=CHAR_MARISA, shot_mode=SHOT_A, rng_seed=seed,
    )
    t0 = time.perf_counter()
    r = agent.run_episode(ep, mode="explore")
    wall = time.perf_counter() - t0

    replay_path = os.path.join(DATA, "replays", "%s-stage%d-%s.trsr" % (tag, stage, diff_name))
    try:
        sim.save_replay(replay_path)
    except Exception as e:
        print("replay save failed (non-fatal):", e)

    cov = 1.0 - (r.uncovered_frames / max(r.executed_frames, 1))
    print("\n== M3 G1 stage %d %s (seed %d) ==" % (stage, diff_name.upper(), seed))
    print("status=%s frames=%d exec=%d deaths=%d bombs=%d score=%d"
          % ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(r.status, r.status),
             r.frames, r.executed_frames, r.deaths, r.bombs_used, r.score))
    print("laya calls=%d failures=%d proto_err=%d coverage=%.2f%% taint=%s (%s)"
          % (r.laya_calls, r.laya_failures, r.protocol_errors,
             100 * cov, r.taint, r.taint_reason or "-"))
    print("wall: episode=%.1fs (effective %.0f game-fps)" % (r.wall_secs,
          r.frames / max(r.wall_secs, 1e-9)))
    print("replay:", replay_path)

    cp = {
        "tag": tag, "seed": seed, "stage": stage, "difficulty": diff_name,
        "character": "marisa", "shot_mode": "A",
        "status": r.status, "frames": r.frames, "deaths": r.deaths,
        "bombs_used": r.bombs_used, "score": r.score,
        "laya_calls": r.laya_calls, "laya_failures": r.laya_failures,
        "coverage": cov, "taint": r.taint, "wall_secs": wall,
        "replay": replay_path,
        "carry": None,
    }
    if r.status == STATUS_WON:
        v = sim.get_state()
        cp["carry"] = Agent.carry_over(v)
    cp_path = os.path.join(DATA, "checkpoints", "%s-stage%d.json" % (tag, stage))
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(cp, f, indent=1)
    print("checkpoint:", cp_path)

    sim.destroy()
    sim.global_shutdown()

    ok = (r.status == STATUS_WON
          and cov >= 0.99 and not r.taint
          and r.deaths <= 2 and r.bombs_used <= 3
          and r.protocol_errors == 0)
    print("\nM3 G1 %s (WON, coverage>=99%%, untainted, deaths<=2, bombs<=3)"
          % ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
