"""Laya-driven single-stage exact-carry diagnostic.

Runs final-mode Laya control on the same build-gl33 DLL while overriding one
policy threshold. It is intended to test whether proactive bomb decisions can
preserve a zero-life campaign carry before another six-stage campaign.

    venv\\Scripts\\python.exe tools\\diag_laya_exact_carry.py 5 12350 0.65 out.log
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")
REPO_PKGDIR = os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir")

sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, DIFFICULTY_NORMAL,
    DIFFICULTY_HARD, DIFFICULTY_LUNATIC,
)
import agent as agent_module  # noqa: E402
from agent import Agent  # noqa: E402
from laya_client import LayaClient  # noqa: E402

DIFFS = {"easy": DIFFICULTY_EASY, "normal": DIFFICULTY_NORMAL,
         "hard": DIFFICULTY_HARD, "lunatic": DIFFICULTY_LUNATIC}


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    stage = int(sys.argv[1])
    seed = int(sys.argv[2])
    bomb_threshold = float(sys.argv[3])
    result_log = os.path.abspath(sys.argv[4]) if len(sys.argv) > 4 else None
    diff_name = sys.argv[5].lower() if len(sys.argv) > 5 else "easy"
    focus_threshold = None

    # Campaign-4 Stage-4 carry by default; optional JSON overrides keep the
    # tool reusable without embedding a second campaign runner.
    carry = {
        "initial_lives": 0, "initial_bombs": 2,
        "initial_life_fragments": 0, "initial_bomb_fragments": 0,
        "initial_power": 600, "initial_point_item_value": 26354,
        "initial_score": 16279993, "initial_graze": 4125,
    }
    # Optional sixth argument is a carry JSON path; an optional seventh is a
    # focus threshold. If no carry file is supplied, the sixth argument may be
    # the focus threshold directly.
    if len(sys.argv) > 6:
        if os.path.isfile(sys.argv[6]):
            carry.update(json.load(open(sys.argv[6], encoding="utf-8")))
            if len(sys.argv) > 7:
                focus_threshold = float(sys.argv[7])
        else:
            focus_threshold = float(sys.argv[6])

    agent_module.BOMB_NOUL_THRESHOLD = bomb_threshold
    if focus_threshold is not None:
        agent_module.FOCUS_NOUL_THRESHOLD = focus_threshold
    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    for d in ("storage", "cache", "replays"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)

    sim = TaiseiSim(LIB)
    sim.global_init(resource_path=REPO_PKGDIR,
                    storage_path=os.path.join(DATA, "storage"),
                    cache_path=os.path.join(DATA, "cache"))
    sim.create()
    laya = LayaClient(base_url="http://127.0.0.1:8002")
    print("laya host health:", laya.health(), flush=True)
    focus_tag = "default" if focus_threshold is None else str(focus_threshold).replace(".", "")
    tag = "diag-laya-s%d-b%s-f%s-%s" % (
        stage, str(bomb_threshold).replace(".", ""), focus_tag,
        time.strftime("%m%d%H%M%S"))
    agent = Agent(sim, laya, log_dir=DATA, episode_tag=tag)
    ep = EpisodeConfig(stage_id=stage, difficulty=DIFFS[diff_name],
                       player_character=CHAR_MARISA, shot_mode=SHOT_A,
                       rng_seed=seed, **carry)
    print("START stage=%d seed=%d bomb_threshold=%.3f focus_threshold=%s carry=%s" %
          (stage, seed, bomb_threshold, focus_threshold, carry), flush=True)
    result = agent.run_episode(ep, mode="final")
    terminal = sim.get_state().raw
    print("TERMINAL_CARRY lives=%d bombs=%d life_frags=%d bomb_frags=%d "
          "power=%d piv=%d score=%d graze=%d" %
          (terminal.player.lives, terminal.player.bombs,
           terminal.player.life_fragments, terminal.player.bomb_fragments,
           terminal.player.stored_power, terminal.player.point_item_value,
           terminal.score, terminal.graze), flush=True)
    print("END status=%s frame=%d deaths=%d bombs_used=%d score=%d "
          "coverage=%.2f%% taint=%s laya_calls=%d failures=%d" %
          ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(result.status, result.status),
           result.frames, result.deaths, result.bombs_used, result.score,
           100.0 * (1.0 - result.uncovered_frames / max(result.executed_frames, 1)),
           result.taint, result.laya_calls, result.laya_failures), flush=True)
    sim.destroy()
    sim.global_shutdown()
    return 0 if result.status == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
