"""M3 macro list v1: Laya's choice vocabulary + target resolution.

Each macro is a *tactical intent* the 60 Hz reflex executor can execute while
dodging (doc/design-m3-reflex-and-macros.md §3). The executor never vetoes the
macro — it picks the lowest-risk execution within the intent
(requirements-decisions.md §7).

Resolution: `resolve_macro_target(macro_id, state_view)` converts a macro id
plus the current snapshot into a `MacroTarget` (the executor's per-frame goal).
Anchors that move (boss, items) are re-resolved by the executor every frame.
"""

from __future__ import annotations

from dataclasses import dataclass

# playfield + measured player clamp bounds (tools/diag_shot_dir.py)
VIEW_W, VIEW_H = 480.0, 560.0
PX_MIN, PX_MAX = 16.0, 464.0
PY_MIN, PY_MAX = 16.0, 544.0

# 'guard' position: lower center, tracking the boss's x so the fixed-upward
# shot keeps hitting the boss. Validated executor-only: WON stage 1 Easy with
# 0 deaths / 0 bombs (tools/test_guard_strategy.py, 2026-09-25).
GUARD_Y = 470.0
GUARD_X_MIN, GUARD_X_MAX = 60.0, 420.0

# item types worth chasing (taisei item.h: PIV=1, points=2, power_mini=3,
# power=4, surge=5, voltage=6 (bomb frag), bomb_fragment=7, life_fragment=8,
# BOMB=9, LIFE=10)
ITEM_CHASE_WEIGHT = {
    9: 10.0, 10: 10.0,        # full BOMB / LIFE
    8: 3.0, 7: 3.0, 6: 3.0,   # life fragment / bomb fragment / voltage
    3: 1.0, 4: 1.0,           # mini power / power
    5: 0.5,                   # surge
    2: 0.5,                   # points
    1: 0.3,                   # PIV
}


@dataclass
class MacroTarget:
    kind: str = "hold"        # hold | point | band_x | orbit | item
    point: tuple = (240.0, 510.0)
    band: tuple = (PX_MIN, PX_MAX, PY_MIN, PY_MAX)   # x0, x1, y0, y1
    center: tuple = (240.0, 120.0)
    radius: float = 150.0
    sign: int = -1            # -1 = counter-clockwise on screen, +1 = clockwise
    item_spawn: int = -1
    boss_anchored: bool = False   # point follows the live boss position


# (id, one-line description) — the `criteria` of the Laya `move` choice.
# `guard` is the recommended default for Marisa A: her shot fires straight up
# from her x-position, so staying low and roughly below the boss keeps the shot
# on target while remaining safe. Validated: WON stage 1 Easy, 0 deaths/0 bombs.
MACRO_CHOICES = [
    ("guard", "Stay low, centered under the boss, and shoot (the default, safest play)"),
    ("hold", "Stay in the lower safe zone and shoot (same as guard, less repositioning)"),
    ("retreat", "Back away toward the very bottom of the screen"),
    ("sidestep_left", "Shift a bit left, keep your height"),
    ("sidestep_right", "Shift a bit right, keep your height"),
    ("item_sweep", "Collect a nearby item drop (prioritize LIFE and BOMB items)"),
    ("clear_spell", "Stay low and wait out the spell"),
    ("bomb_setup", "Get to a clean spot to use a bomb"),
]
# Removed (v3, 2026-09-25): hug_left / hug_right / advance / orbit_left /
# orbit_right — these pull the player to the edges or up into the boss's dense
# bullets where the fixed-upward shot also misses, and Laya picked them in
# dangerous moments, costing lives across stages. resolve_macro_target still
# handles their ids (robustness) but Laya no longer sees them.


def _boss_point(v):
    b = v.raw.boss
    if b.active:
        return (float(b.position.x), float(b.position.y))
    return (240.0, 100.0)


def resolve_macro_target(macro_id: str, v) -> MacroTarget:
    """Resolve a macro id to a target descriptor from the current snapshot."""
    t = MacroTarget()
    b = _boss_point(v)
    if macro_id in ("guard", "hold"):
        # lower center, tracking the boss's x (re-anchored per frame by executor).
        # 'hold' also maps here so the player stays in the safe zone whether Laya
        # picks guard or hold (both mean "stay low and shoot").
        t.kind = "below_boss"
    elif macro_id == "advance":
        t.kind, t.point = "point", b
        t.boss_anchored = True
    elif macro_id == "retreat":
        t.kind, t.point = "point", (240.0, 510.0)
    elif macro_id == "sidestep_left":
        pl = v.raw.player
        t.kind, t.point = "point", (max(PX_MIN + 8, pl.position.x - 120),
                                    float(pl.position.y))
    elif macro_id == "sidestep_right":
        pl = v.raw.player
        t.kind, t.point = "point", (min(PX_MAX - 8, pl.position.x + 120),
                                    float(pl.position.y))
    elif macro_id == "hug_left":
        t.kind, t.point = "point", (PX_MIN + 12, 430.0)
    elif macro_id == "hug_right":
        t.kind, t.point = "point", (PX_MAX - 12, 430.0)
    elif macro_id in ("orbit_left", "orbit_right"):
        t.kind = "orbit"
        t.center = b
        t.radius = 150.0
        t.sign = -1 if macro_id == "orbit_left" else 1
    elif macro_id == "item_sweep":
        pl = v.raw.player
        px, py = float(pl.position.x), float(pl.position.y)
        best, best_score = None, 0.0
        for it in v.items:
            w = ITEM_CHASE_WEIGHT.get(int(it.item_type), 0.2)
            if w <= 0:
                continue
            dx = it.position.x - px
            dy = it.position.y - py
            d = (dx * dx + dy * dy) ** 0.5
            if d > 250:
                continue
            s = w / (1.0 + d / 100.0)
            if s > best_score:
                best, best_score = it, s
        if best is not None:
            t.kind = "item"
            t.item_spawn = int(best.spawn_id)
        # else: nothing in reach -> hold
    elif macro_id == "clear_spell":
        t.kind, t.band = "band_x", (PX_MIN, PX_MAX, 380.0, PY_MAX)
    # hold / bomb_setup / unknown -> hold
    return t
