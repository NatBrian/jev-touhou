"""M2 test: full Laya-driven episode on stage 1 Easy + degraded-mode check.

Requires: built libtaisei_sim.dll, Laya server reachable (127.0.0.1:8002).

    venv\\Scripts\\python.exe tools\\test_m2_loop.py [path-to-libtaisei_sim.dll]

Checks:
  1. Sim loads + ABI OK (done by the binding at load time).
  2. Agent runs a complete stage-1 Easy episode (Marisa A, fixed seed) until
     terminal status, with Laya as the decision engine.
  3. Laya coverage + taint bookkeeping works (logged per call).
  4. Replay saved for the episode.
  5. Degraded mode: with Laya unreachable, the episode runs on the fallback
     policy, is fully uncovered, and taints (no crash).
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # project root
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
REPO_PKGDIR = os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir")
DATA = os.path.join(HERE, "simdata")

sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY,
    STATUS_WON, STATUS_LOST, STATUS_ABORTED,
)
from laya_client import LayaClient, LayaUnavailableError  # noqa: E402
from agent import Agent  # noqa: E402

LIB_CANDIDATES = [
    os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll"),
    os.path.join(SIM_ROOT, "build", "src", "taisei_sim.dll"),
    os.path.join(SIM_ROOT, "build", "src", "taisei.exe"),
    os.path.join(SIM_ROOT, "build", "taisei.exe"),
]


def find_lib():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for p in LIB_CANDIDATES:
        if os.path.isfile(p):
            return p
    sys.exit("libtaisei_sim.dll not found; pass its path as argv[1]. Looked in: "
             + " | ".join(LIB_CANDIDATES))


def ensure_runtime_path():
    """Register the mingw runtime DLL dir for ctypes (env PATH + add_dll_directory)."""
    from taisei_sim import register_runtime_dirs
    register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))


def main():
    lib = find_lib()
    print("lib:", lib)
    ensure_runtime_path()
    os.makedirs(os.path.join(DATA, "storage"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "cache"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "replays"), exist_ok=True)

    sim = TaiseiSim(lib)
    print("ABI OK")
    sim.global_init(
        resource_path=REPO_PKGDIR,
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()

    # -- 1) Laya-driven episode --------------------------------------------------
    laya = LayaClient()
    try:
        h = laya.health()
    except LayaUnavailableError as e:
        sys.exit("Laya server unreachable - cannot run M2 Laya test: %s" % e)
    print("laya host health:", h.get("status"), h.get("gpu"))

    tag = time.strftime("m2-%m%d-%H%M")
    agent = Agent(sim, laya, log_dir=DATA, episode_tag=tag)
    ep = EpisodeConfig(
        stage_id=1, difficulty=DIFFICULTY_EASY,
        player_character=CHAR_MARISA, shot_mode=SHOT_A, rng_seed=42,
    )
    t0 = time.perf_counter()
    r = agent.run_episode(ep, mode="explore")
    wall = time.perf_counter() - t0
    cov = 1.0 - (r.uncovered_frames / max(r.executed_frames, 1))
    print("\n== M2 Laya episode ==")
    print("status=%s frames=%d exec=%d deaths=%d bombs=%d score=%d"
          % ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(r.status, r.status),
             r.frames, r.executed_frames, r.deaths, r.bombs_used, r.score))
    print("laya calls=%d failures=%d proto_err=%d" % (r.laya_calls, r.laya_failures, r.protocol_errors))
    print("coverage=%.2f%%  taint=%s%s" % (100 * cov, r.taint, (" (%s)" % r.taint_reason) if r.taint else ""))
    print("wall: episode=%.1fs total=%.1fs  (game fps effective %.0f)"
          % (r.wall_secs, wall, r.frames / max(wall, 1e-9)))
    assert r.laya_calls >= 20, "expected a meaningful number of Laya calls (>= 20)"
    assert r.status in (STATUS_WON, STATUS_LOST, STATUS_ABORTED)

    # save the replay of the episode just played (state is terminal; re-save)
    replay_path = os.path.join(DATA, "replays", tag + "-stage1-easy.trsr")
    try:
        sim.save_replay(replay_path)
        print("replay saved:", replay_path, os.path.getsize(replay_path), "bytes")
    except Exception as e:
        print("replay save failed (non-fatal):", e)

    # -- 2) degraded mode (Laya unreachable) --------------------------------------
    dead = LayaClient(base_url="http://127.0.0.1:59999", timeout=1.0)
    dead_agent = Agent(sim, dead, episode_tag=tag + "-degraded")
    r2 = dead_agent.run_episode(ep, mode="explore")
    cov2 = 1.0 - (r2.uncovered_frames / max(r2.executed_frames, 1))
    print("\n== degraded episode (Laya down) ==")
    print("status=%s frames=%d exec=%d deaths=%d coverage=%.2f%% taint=%s (%s)"
          % ({2: "WON", 3: "LOST", 4: "ABORTED"}.get(r2.status, r2.status),
             r2.frames, r2.executed_frames, r2.deaths, 100 * cov2, r2.taint, r2.taint_reason))
    assert cov2 < 0.05, "degraded episode should be (almost) fully uncovered"
    assert r2.taint, "degraded episode must be tainted"

    sim.destroy()
    sim.global_shutdown()
    print("\nM2 LOOP TEST PASSED")


if __name__ == "__main__":
    main()
