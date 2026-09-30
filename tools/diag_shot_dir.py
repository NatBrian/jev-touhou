"""Empirical: which way do player bullets go for a given movement+shot input?"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY,
    ACTION_SHOT, ACTION_RIGHT, ACTION_UP, ACTION_DOWN, ACTION_LEFT,
    PROJ_PLAYER,
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
                   player_character=CHAR_MARISA, shot_mode=SHOT_A, rng_seed=7)

def shot_dir_for(buttons, label):
    sim.reset(ep)
    for _ in range(150):
        sim.step(buttons=buttons)
    v = sim.get_state()
    dirs = []
    for p in v.projectiles:
        if p.category == PROJ_PLAYER:
            x, y = p.velocity.x, p.velocity.y
            if abs(x) + abs(y) > 0.5:
                dirs.append((round(x, 1), round(y, 1)))
    from collections import Counter
    c = Counter(dirs)
    top = c.most_common(3)
    pl = v.player
    print("%-22s player=(%.0f,%.0f) n_pbullets=%d top vel: %s"
          % (label, pl.position.x, pl.position.y, len(dirs), top))

shot_dir_for(ACTION_SHOT | ACTION_RIGHT, "SHOT|RIGHT")
shot_dir_for(ACTION_SHOT | ACTION_UP, "SHOT|UP")
shot_dir_for(ACTION_SHOT | ACTION_UP | ACTION_RIGHT, "SHOT|UP|RIGHT (diag)")
shot_dir_for(ACTION_SHOT | ACTION_DOWN, "SHOT|DOWN")
shot_dir_for(ACTION_SHOT, "SHOT only (no move)")

# what does a SHOT-only player do after moving right then holding?
sim.reset(ep)
for _ in range(60):
    sim.step(buttons=ACTION_SHOT | ACTION_RIGHT)
for _ in range(90):
    sim.step(buttons=ACTION_SHOT)
v = sim.get_state()
dirs = [(round(p.velocity.x, 1), round(p.velocity.y, 1)) for p in v.projectiles
        if p.category == PROJ_PLAYER and abs(p.velocity.x) + abs(p.velocity.y) > 0.5]
from collections import Counter
print("move-right-then-hold   top vel:", Counter(dirs).most_common(3))
sim.destroy()
sim.global_shutdown()
