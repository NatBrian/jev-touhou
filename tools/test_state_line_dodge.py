"""R1 gate (2026-09-26; R4.6 2026-09-26): the state compiler must emit the
action-oriented dodge line (absolute position, exact time-to-hit, per-side
pressure, edge proximity) and stay inside the 1280-char budget (2048-token
cap, ~1.0 token/char + ~720 fixed overhead).

    venv\Scripts\python.exe tools\test_state_line_dodge.py
"""
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_EASY, STATUS_RUNNING, PROJ_ENEMY,
)
from state_compiler import (  # noqa: E402
    compile_state, _dodge_hint, _time_to_hit,
    TTH_WINDOW, PRESSURE_RADIUS, EDGE_BAND,
)

LIB = os.path.join(SIM_ROOT, "build", "src", "sim", "libtaisei_sim.dll")


def bullet(x, y, vx=0.0, vy=0.0, r=4.0):
    return SimpleNamespace(
        position=SimpleNamespace(x=x, y=y),
        velocity=SimpleNamespace(x=vx, y=vy),
        collision_size=SimpleNamespace(x=r, y=r),
    )


def synthetic_checks():
    # time-to-hit math: 100 px away, closing at 5 px/f, radius margin 8
    t = _time_to_hit(240, 470, 340, 470, -5.0, 0.0, 8.0)
    assert t is not None and 18.0 <= t <= 19.0, t
    # a receding bullet never hits
    assert _time_to_hit(240, 470, 340, 470, 5.0, 0.0, 8.0) is None
    # an already-overlapping bullet hits now
    assert _time_to_hit(240, 470, 241, 470, 0.0, 0.0, 8.0) == 0.0

    # 80 px away, closing at 5 px/f -> ~14 frames; inside the 90 px box
    line = _dodge_hint([bullet(320, 470, vx=-5.0)], 240.0, 470.0)
    assert "You are at (240, 470)" in line
    assert "will hit you in about 14 frames" in line, line
    assert "pressure up/down/left/right: 0/0/0/1" in line, line
    assert "edge" not in line, line

    # no approaching bullets -> the window statement
    line = _dodge_hint([bullet(240, 40, vy=-1.0)], 240.0, 470.0)
    assert "No bullet will hit you within %d frames" % TTH_WINDOW in line

    # edge proximity: 4 px from the bottom clamp, 1 px from the right clamp
    line = _dodge_hint([], 463.0, 540.0)
    assert "bottom 4 px" in line and "right 1 px" in line, line

    # pressure counts both sides of a diagonal bullet
    line = _dodge_hint([bullet(280, 430)], 240.0, 470.0)
    assert "pressure up/down/left/right: 1/0/0/1" in line, line

    print("synthetic dodge-line checks passed")


def sim_checks():
    from executor import ReflexExecutor
    from macros import MacroTarget
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
    ep = EpisodeConfig(stage_id=1, difficulty=DIFFICULTY_EASY,
                       player_character=CHAR_MARISA, shot_mode=SHOT_A,
                       rng_seed=12345)
    ex = ReflexExecutor()
    ex.reset()
    sim.reset(ep)
    # drive the player toward the guard point with the reflex executor so the
    # samples sit inside real bullet patterns (not the empty opening)
    class M:
        macro_id = "guard"
        source = "fallback"
        focus = False
        bomb = False
        def __init__(self, issued_frame):
            self.target = MacroTarget(kind="point", point=(240.0, 470.0))
            self.issued_frame = issued_frame
    sampled = 0
    busy = 0
    for f in range(2400):
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        if f in (700, 1300, 1900, 2350):
            sampled += 1
            text = compile_state(v)
            hazards = len([p for p in v.projectiles
                           if p.category == PROJ_ENEMY and p.flags & 16])
            # R4.6: hard budget 1280 (2048-token cap, ~1.0 token/char)
            assert len(text) <= 1280, "state over budget: %d chars" % len(text)
            assert "You are at (" in text, "position line missing"
            assert ("will hit you in about" in text
                    or "No bullet will hit you within %d frames" % TTH_WINDOW
                    in text), "time-to-hit line missing"
            assert "Bullet pressure up/down/left/right:" in text, \
                "pressure line missing (trim cut the dodge line?)"
            pressure = text.split("Bullet pressure up/down/left/right: ")[1][:14]
            if hazards > 0 and ("will hit you in about" in text
                                or pressure.split(".")[0] != "0/0/0/0"):
                busy += 1
            print("--- f%d (%d chars, %d hazards):" % (f, len(text), hazards))
            idx = text.index("You are at (")
            print("   " + text[idx:].split(". You are near")[0][:280])
        buttons = ex.execute(M(f), v)
        sim.step(buttons=buttons)
    assert sampled >= 2, "episode ended before 2 sample frames"
    assert busy >= 1, "no sample frame had real bullet pressure"
    sim.destroy()
    sim.global_shutdown()
    print("sim dodge-line checks passed")


if __name__ == "__main__":
    synthetic_checks()
    sim_checks()
    print("STATE LINE DODGE TEST PASSED")
