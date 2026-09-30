"""Diag: verify the new death_hit forensics (pre-hit state capture).

Runs stage 3 (seed 12348) with a fake-unavailable Laya -> pure fallback
policy at full sim speed, then prints every death_hit / death record.

    venv\Scripts\python.exe tools\diag_death_hit.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY,
)
from laya_client import LayaUnavailableError  # noqa: E402
from agent import Agent  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")
TAG = "diag-death-hit"


class DeadLaya:
    def predict(self, text, questions):
        raise LayaUnavailableError("diag: Laya disabled")


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
    agent = Agent(sim, DeadLaya(), log_dir=DATA, episode_tag=TAG)
    res = agent.run_episode(ep, mode="explore")
    print("status=%s frames=%d deaths=%d bombs=%d score=%d"
          % (res.status, res.frames, res.deaths, res.bombs_used, res.score))

    path = os.path.join(DATA, "laya-%s.jsonl" % TAG)
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r.get("status") not in ("death_hit", "death"):
            continue
        print(json.dumps(r, indent=1))
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
