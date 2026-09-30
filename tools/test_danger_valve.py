"""R3 gate (2026-09-26): the opt-in no-bomb danger valve must relax the
guard-anchor pull when Laya rates danger high — without ever choosing a
direction on its own, and without touching bomb-allowed mode.

Scenario: the player is at (240,470), the guard anchor is 80 px to the right
(at the boss's x). Five stationary bullets sit 28-44 px to the right, so the
anchor side costs ~0.43 more than staying put — enough for the beta=0.8 anchor
to win, not enough to beat the min-cost heading outright. With the valve
(beta=0.4 in no-bomb mode) the min-cost heading must win.

    venv\Scripts\python.exe tools\test_danger_valve.py
"""
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import PROJ_ENEMY  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from macros import MacroTarget  # noqa: E402

MOVE_STAY, MOVE_LEFT, MOVE_RIGHT = 0, 3, 4


def bullet(x, y, r=4.0):
    return SimpleNamespace(
        category=PROJ_ENEMY, flags=16,
        position=SimpleNamespace(x=x, y=y),
        velocity=SimpleNamespace(x=0.0, y=0.0),
        collision_size=SimpleNamespace(x=r, y=r),
    )


def view(bullets, px=240.0, py=470.0, boss_x=320.0):
    player = SimpleNamespace(
        alive=True, death_timer=-1, bombs=0, bomb_active=False,
        invulnerable=False, position=SimpleNamespace(x=px, y=py),
        velocity=SimpleNamespace(x=0.0, y=0.0), input_flags=0,
    )
    boss = SimpleNamespace(
        active=True, invulnerable=False,
        position=SimpleNamespace(x=boss_x, y=100.0),
        velocity=SimpleNamespace(x=0.0, y=0.0),
    )
    raw = SimpleNamespace(player=player, boss=boss, logical_frame=0)
    return SimpleNamespace(raw=raw, projectiles=bullets, enemies=[],
                           lasers=[], laser_points=[], items=[])


class Macro:
    def __init__(self, danger):
        self.macro_id = "guard"
        self.focus = False
        self.bomb = False
        self.source = "laya"
        self.issued_frame = 0
        self.danger_score = danger
        self.target = MacroTarget(kind="below_boss", point=(320.0, 470.0))


def run(danger, valve, no_bomb, xs):
    bl = [bullet(x, 470.0) for x in xs]
    ex = ReflexExecutor(allow_bombs=not no_bomb, danger_valve=valve)
    ex.reset()
    ex.execute(Macro(danger), view(bl))
    return ex.last_move_idx


# the anchor-side cluster: 28..44 px right of the player
CLUSTER = [268.0, 272.0, 276.0, 280.0, 284.0]


def main():
    # 1. bomb-allowed mode: the anchor wins (beta 0.8, high cost accepted).
    assert run(1.5, False, False, CLUSTER) == MOVE_RIGHT
    # 2. valve must NOT affect bomb-allowed mode.
    assert run(1.5, True, False, CLUSTER) == MOVE_RIGHT
    # 3. no-bomb without the valve: the anchor still wins (unchanged default).
    assert run(1.5, False, True, CLUSTER) == MOVE_RIGHT
    # 4. no-bomb + valve + Laya danger 1.5: the min-cost heading wins.
    assert run(1.5, True, True, CLUSTER) == MOVE_LEFT
    # 5. below the 1.4 danger threshold the valve must not trigger.
    assert run(1.3, True, True, CLUSTER) == MOVE_RIGHT
    # 6. with no hazards the valve must never invent a direction on its own:
    #    equal costs -> the anchor still wins.
    assert run(1.5, True, True, []) == MOVE_RIGHT

    print("DANGER VALVE TEST PASSED")


if __name__ == "__main__":
    main()
