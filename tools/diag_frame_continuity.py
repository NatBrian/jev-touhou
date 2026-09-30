"""Diagnostic: track logical_frame continuity across an episode with a
pure-fallback policy (no Laya). Reveals why uncovered_frames can exceed
the final logical_frame (suspected: frame counter resets/skips around
deaths or the game-over sequence)."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, STATUS_RUNNING,
)

lib = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")
register_runtime_dirs(os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
os.makedirs(os.path.join(DATA, "storage"), exist_ok=True)
os.makedirs(os.path.join(DATA, "cache"), exist_ok=True)

sim = TaiseiSim(lib)
sim.global_init(
    resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
    storage_path=os.path.join(DATA, "storage"),
    cache_path=os.path.join(DATA, "cache"),
)
sim.create()
ep = EpisodeConfig(stage_id=1, difficulty=DIFFICULTY_EASY,
                   player_character=CHAR_MARISA, shot_mode=SHOT_A, rng_seed=12345)
sim.reset(ep)

prev_frame = None
prev_deaths = 0
prev_status = None
anomalies = []
running_iters = 0
terminal = None
for i in range(60 * 120):
    st = sim.get_state().raw
    f = int(st.logical_frame)
    d = int(st.deaths)
    s = int(st.episode_status)
    if prev_frame is not None and f != prev_frame + 1:
        anomalies.append((i, prev_frame, f, d, s, "frame jump"))
    if d != prev_deaths:
        anomalies.append((i, f, f, d, s, "deaths %d -> %d" % (prev_deaths, d)))
    prev_frame, prev_deaths = f, d
    if s != STATUS_RUNNING:
        terminal = (i, f, s)
        break
    running_iters += 1
    sim.step(buttons=0)  # stand still, no input

print("terminal at python-iter=%s logical_frame=%s status=%s" % terminal)
print("RUNNING iterations (bookkeeping count) =", running_iters)
print("final logical_frame =", terminal[1])
print("diff = bookkeeping - final_frame =", running_iters - terminal[1])
print("\nanomalies (iter, prev_frame, frame, deaths, status, note):")
for a in anomalies[:40]:
    print("  ", a)
sim.destroy()
sim.global_shutdown()
