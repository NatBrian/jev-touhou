"""State compiler: taisei-sim snapshot -> compact Laya text state.

Design rules (doc/research-laya.md, doc/research-jev-ai.md):
  - All geometry is precomputed HERE in code (distances, relative directions,
    threat estimates). Laya never does arithmetic.
  - Keep the whole state <= ~300 tokens (English checkpoint budget ~512 tok/
    question including the question text).
  - Literal, self-contained sentences. No indirection ("the bullet above"
    must say where "above" is).

Coordinates: 480x560, (0,0) top-left, +x right, +y down. The player is near
the bottom; the boss near the top.
"""

from __future__ import annotations

import math

from taisei_sim import (
    StateView,
    VIEWPORT_WIDTH, VIEWPORT_HEIGHT,
    PROJ_ENEMY, PROJ_PLAYER,
    STATUS_RUNNING,
    PHASE_NONSPELL, PHASE_MOVE, PHASE_SPELL, PHASE_SURVIVAL, PHASE_EXTRA,
)
from macros import PX_MIN, PX_MAX, PY_MIN, PY_MAX

# player collision radius (taisei default ~4px) — used for threat margins
PLAYER_RADIUS = 4.0

# threat window: bullets projected this far ahead (game frames @ 60fps)
THREAT_HORIZON = 15  # 0.25 s

# how many nearest enemy bullets to enumerate in text.
# R4.6 (2026-09-26): 10 -> 6 — the server input cap is 2048 tokens and
# campaign content costs ~1.0 token/char (doc/research-laya-token-budget.md);
# the 10-bullet list (~800 chars) pushed dense states (1468-1575 chars)
# over the cap at p50 (tail = lasers + items truncated). 6 bullets
# (~480 chars) brings dense states to ~1100-1315 chars; _trim's 1280-char
# budget then guarantees worst case ~2000 input tokens (< 2048 cap).
NEAREST_BULLETS = 6

# R1 (2026-09-26): action-oriented dodge line — the macro cadence is ~50
# frames and the old state had no absolute position, no time-to-hit, and no
# edge-trap signal, so Laya could not request proactive lateral setup
# (doc/research-prompt-harness-input-audit.md §2).
TTH_WINDOW = 45        # frames — report time-to-hit only when closer
PRESSURE_RADIUS = 90.0 # px — per-side bullet pressure box
EDGE_BAND = 40.0       # px — edge-proximity band (matches the executor's
                       # wall band, doc/plan-lunatic-no-bomb.md R1)

# item types worth mentioning
ITEM_NAMES = {
    1: "PIV", 2: "points", 3: "mini power", 4: "power",
    5: "surge", 6: "voltage", 7: "bomb frag", 8: "life frag",
    9: "BOMB", 10: "LIFE",
}

# Touhou extra-life score thresholds (taisei player.c:1692-1695):
# 5,000,000 * (n^2 + n + 2) / 2 -> 5M, 10M, 20M, 35M, 55M, 80M, 110M, 145M, ...
# (gaps grow by 5M each step). Crossing a threshold grants +1 life
# (player_add_points, player.c:1590-1599).
def _extra_life_hint(score: int) -> str:
    # initial threshold is f(0) (player_init calls it with extralives_given=0);
    # each grant uses f(n+1) via pre-increment (player.c:1594)
    n, t = -1, 0
    while t < 1_000_000_000:
        n += 1
        t = 5_000_000 * (n * n + n + 2) // 2
        if score < t:
            return (f" — an extra life is granted when your score "
                    f"crosses {t:,} ({t - score:,} points to go)")
    return ""


def _dir8(dx: float, dy: float) -> str:
    """Compass-8 direction from player to point, in player-facing terms."""
    if abs(dx) < 12 and abs(dy) < 12:
        return "on top of the player"
    ang = math.atan2(dy, dx)  # +x right, +y down
    deg = math.degrees(ang)
    # screen directions: 0deg=right, 90=down, 180=left, -90=up
    names = [
        (0, "right of"), (45, "down-right of"), (90, "below"), (135, "down-left of"),
        (180, "left of"), (-135, "up-left of"), (-90, "above"), (-45, "up-right of"),
    ]
    best = min(names, key=lambda kv: min(abs(deg - kv[0]), 360 - abs(deg - kv[0])))
    return best[1] + " the player"


def _v2(p):
    return (p.x, p.y)


def compile_state(v: StateView, macro_context: str | None = None) -> str:
    """Build the compact text state from a StateView.

    macro_context: optional one-liner describing the currently held macro
    (e.g. "held macro: drift to the gap above-right") so Laya sees continuity.
    """
    pl = v.player
    px, py = pl.position.x, pl.position.y

    parts: list[str] = []

    # --- scene ----------------------------------------------------------------
    frame = int(v.raw.logical_frame)
    diff_names = {1: "Easy", 2: "Normal", 3: "Hard", 4: "Lunatic"}
    diff = diff_names.get(int(v.raw.difficulty), v.raw.difficulty)
    # NOTE: pl.lives is the sim's continue count (total lives - 1); the
    # in-game display and Laya's mental model use total lives.
    parts.append(f"Frame {frame} of stage {v.raw.stage_id} "
                 f"({diff}). "
                 f"You have {pl.lives + 1} life(s) and {pl.bombs} bomb(s). "
                 f"Power {pl.effective_power}. Score {v.raw.score}"
                 f"{_extra_life_hint(int(v.raw.score))}. "
                 f"Deaths so far: {v.raw.deaths}.")
    if macro_context:
        parts.append(f"Currently held macro: {macro_context}")

    # --- boss ------------------------------------------------------------------
    if v.boss.active:
        b = v.boss
        bpx, bpy = b.position.x, b.position.y
        phase_names = {
            PHASE_NONSPELL: "normal attack", PHASE_MOVE: "positioning",
            PHASE_SPELL: "spellcard", PHASE_SURVIVAL: "survival spell",
            PHASE_EXTRA: "extra spell",
        }
        phase = phase_names.get(b.phase_type, "unknown phase")
        hp_pct = (100.0 * b.hp / b.max_hp) if b.max_hp > 0 else 0.0
        line = (f"The boss is {phase}, at ({bpx:.0f},{bpy:.0f}) "
                f"({_dir8(bpx - px, bpy - py)}), HP {hp_pct:.0f}%.")
        if b.spell_active and b.remaining_timeout_frames > 0:
            t = b.remaining_timeout_frames / 60.0
            line += f" Spell timer: {t:.1f}s left. "
        if b.recent_damage > 0.001:
            line += f" It dealt {b.recent_damage:.1f} recent damage to you."
        parts.append(line)
    else:
        parts.append("No boss on screen (normal-attack section).")

    # --- bullets -----------------------------------------------------------------
    enemies = [p for p in v.projectiles if p.category == PROJ_ENEMY and p.flags & 16]
    # flags & 16 == ACTIVE_HAZARD (bit 4)
    all_enemy = [p for p in v.projectiles if p.category == PROJ_ENEMY]
    if not all_enemy:
        parts.append("No enemy bullets on screen.")
    else:
        # nearest hazards (active = can hurt you)
        hazards = sorted(
            enemies,
            key=lambda p: (p.position.x - px) ** 2 + (p.position.y - py) ** 2,
        )[:NEAREST_BULLETS]
        if hazards:
            descs = []
            for p in hazards:
                dx, dy = p.position.x - px, p.position.y - py
                dist = math.hypot(dx, dy)
                # closing speed: dot(vel, to_player) > 0 means approaching
                to_p = (-dx / dist, -dy / dist) if dist > 1e-6 else (0.0, 0.0)
                closing = p.velocity.x * to_p[0] + p.velocity.y * to_p[1]
                speed = math.hypot(p.velocity.x, p.velocity.y)
                r = max(p.collision_size.x, p.collision_size.y)
                verb = "closing in on" if closing > 0.5 else (
                    "drifting past" if speed > 0.1 else "sitting")
                descs.append(
                    f"bullet {verb} you at {dist:.0f}px away "
                    f"({_dir8(dx, dy)}, radius {r:.0f}, speed {speed:.1f})")
            parts.append(
                f"{len(enemies)} hazardous enemy bullet(s) total; nearest: "
                + "; ".join(descs) + ".")
        else:
            parts.append(
                f"{len(all_enemy)} enemy bullet(s) on screen but none "
                f"hazardous to you right now.")
        # density / gap hint: coarse 3x3 occupancy around the player
        cells = _gap_hint(all_enemy, px, py)
        parts.append(cells)
    # R1: action-oriented dodge line (position, time-to-hit, per-side
    # pressure, edge proximity) — always emitted (even with no bullets) and
    # kept in the early part of the text so _trim always retains it.
    parts.append(_dodge_hint(enemies, px, py))

    # --- lasers ------------------------------------------------------------------
    lasers_active = [L for L in v.lasers if L.collision_active]
    if lasers_active:
        lps = v.laser_points
        near = []
        for L in lasers_active:
            end = min(int(L.first_point) + int(L.point_count), len(lps))
            d_beam, beam_pt = None, None
            for i in range(int(L.first_point), end):
                pt = lps[i]
                if pt.time > 0:
                    continue  # not drawn yet (tip = 0, drawn body < 0)
                d = math.hypot(float(pt.position.x) - px,
                               float(pt.position.y) - py) \
                    - (float(pt.half_width) if pt.half_width > 0 else 0.0)
                if d_beam is None or d < d_beam:
                    d_beam = d
                    beam_pt = (float(pt.position.x), float(pt.position.y))
            if d_beam is not None and d_beam <= 150:
                near.append((d_beam, beam_pt, L))
        near.sort(key=lambda t: t[0])
        if near:
            descs = []
            for d, (bx, by), L in near[:2]:
                rel = _dir8(bx - px, by - py).replace(" of the player", "")
                growing = L.age_frames * L.speed < L.timespan
                descs.append(
                    f"beam {d:.0f}px away ({rel}, width {L.width:.0f}"
                    f"{', still growing' if growing else ''})")
            parts.append(f"{len(lasers_active)} laser beam(s) on screen; "
                         "nearest: " + "; ".join(descs) + ".")
        else:
            parts.append(f"{len(lasers_active)} laser beam(s) on screen, "
                         "all far from you.")

    # --- items -------------------------------------------------------------------
    if v.items:
        near = sorted(
            v.items,
            key=lambda it: (it.position.x - px) ** 2 + (it.position.y - py) ** 2,
        )[:3]
        idescs = [
            f"{ITEM_NAMES.get(it.item_type, 'item')} at "
            f"{math.hypot(it.position.x - px, it.position.y - py):.0f}px "
            f"{_dir8(it.position.x - px, it.position.y - py)}"
            for it in near
        ]
        parts.append("Items nearby: " + ", ".join(idescs) + ".")
        # emphasize the survival-critical items (full BOMB/LIFE, life fragments)
        valuable = [it for it in v.items if it.item_type in (9, 10, 8)]
        if valuable:
            it = min(valuable,
                     key=lambda it: (it.position.x - px) ** 2 + (it.position.y - py) ** 2)
            d = math.hypot(it.position.x - px, it.position.y - py)
            if d <= 300:
                parts.append(
                    f"Note: a {ITEM_NAMES.get(it.item_type, 'item')} item is at "
                    f"{d:.0f}px {_dir8(it.position.x - px, it.position.y - py)} — "
                    f"worth a short detour to collect (item_sweep).")

    # --- player state ---------------------------------------------------------------
    if pl.invulnerable:
        parts.append("You are currently invulnerable (just respawned/bombed).")
    if pl.bomb_active:
        parts.append("Your bomb is active right now.")

    text = " ".join(parts)
    return _trim(text)


def _time_to_hit(px, py, hx, hy, vx, vy, r):
    """Smallest t >= 0 with |h + v t - p| <= r, or None if it never gets
    within r. Same quadratic as Agent._time_to_overlap (duplicated to keep
    the compiler dependency-free)."""
    dx, dy = hx - px, hy - py
    a = vx * vx + vy * vy
    if a < 1e-9:
        return 0.0 if dx * dx + dy * dy <= r * r else None
    b = 2.0 * (dx * vx + dy * vy)
    c = dx * dx + dy * dy - r * r
    if c <= 0:
        return 0.0
    disc = b * b - 4.0 * a * c
    if disc < 0:
        return None
    t = (-b - disc ** 0.5) / (2.0 * a)
    return t if t >= 0 else None


def pressure_sides(enemies, px: float, py: float,
                   radius: float = PRESSURE_RADIUS) -> tuple:
    """Per-side hazardous-bullet counts (R4.1, 2026-09-26): used by the dodge
    line AND by the no-bomb evade-direction resolution so both see the same
    numbers. A diagonal bullet counts toward both its axis sides."""
    u = d = l = r = 0
    for p in enemies:
        dx, dy = p.position.x - px, p.position.y - py
        if abs(dx) > radius or abs(dy) > radius:
            continue
        if dy < -20:
            u += 1
        elif dy > 20:
            d += 1
        if dx < -20:
            l += 1
        elif dx > 20:
            r += 1
    return u, d, l, r


def _dodge_hint(enemies, px: float, py: float) -> str:
    """R1 (2026-09-26): one action-oriented line Laya can act on directly:
    absolute position, exact time-to-hit of the nearest hazardous bullet,
    per-side bullet pressure, and edge proximity.
    """
    line = ("You are at (%.0f, %.0f); the playable field is x %.0f-%.0f, "
            "y %.0f-%.0f." % (px, py, PX_MIN, PX_MAX, PY_MIN, PY_MAX))
    # time-to-hit: ALL hazardous bullets (nearest wins), not just the 10
    # enumerated above
    t_min = None
    for p in enemies:
        r = max(p.collision_size.x, p.collision_size.y, 3.0) + PLAYER_RADIUS
        t = _time_to_hit(px, py, p.position.x, p.position.y,
                         p.velocity.x, p.velocity.y, r)
        if t is not None and (t_min is None or t < t_min):
            t_min = t
    if t_min is not None and t_min < TTH_WINDOW:
        line += " The nearest bullet will hit you in about %.0f frames." % t_min
    else:
        line += " No bullet will hit you within %d frames." % TTH_WINDOW
    # per-side pressure: hazardous bullets inside the PRESSURE_RADIUS box
    u, d, l, r = pressure_sides(enemies, px, py)
    line += (" Bullet pressure up/down/left/right: %d/%d/%d/%d."
             % (u, d, l, r))
    # edge proximity (playfield clamp bounds, macros.py)
    edges = []
    if py >= PY_MAX - EDGE_BAND:
        edges.append("bottom %.0f px" % (PY_MAX - py))
    if py <= PY_MIN + EDGE_BAND:
        edges.append("top %.0f px" % (py - PY_MIN))
    if px >= PX_MAX - EDGE_BAND:
        edges.append("right %.0f px" % (PX_MAX - px))
    if px <= PX_MIN + EDGE_BAND:
        edges.append("left %.0f px" % (px - PX_MIN))
    if edges:
        line += " You are near the " + " and ".join(edges) + " edge(s)."
    return line


def _gap_hint(bullets, px: float, py: float) -> str:
    """Coarse 3x3 occupancy grid (60px cells) around the player -> 'open space' hint."""
    cell = 60
    occ = {}
    for b in bullets:
        cx = int((b.position.x - px) // cell)
        cy = int((b.position.y - py) // cell)
        if -2 <= cx <= 2 and -2 <= cy <= 2:
            occ[(cx, cy)] = occ.get((cx, cy), 0) + 1
    if not occ:
        return "Open space all around you."
    # find the emptiest adjacent cell
    candidates = [(cx, cy) for cx in (-1, 0, 1) for cy in (-1, 0, 1) if (cx, cy) != (0, 0)]
    emptiest = min(candidates, key=lambda c: occ.get(c, 0))
    ex, ey = emptiest
    dx, dy = ex * cell, ey * cell
    if occ.get(emptiest, 0) == 0:
        where = _dir8(dx, dy).replace(" the player", "")
        return f"The most open space is {where}."
    return "Bullets are dense around you; no clearly open adjacent cell."


def _trim(text: str, budget: int = 1280) -> str:
    """Hard char budget. R4.6 (2026-09-26): 1600 -> 1280. The old value
    assumed ~4 chars/token; campaign content measures ~1.0 token/char.
    Measured with tools/check_state_tokens.py (2026-09-26, no-bomb schema):
    fixed overhead (system+questions) ~700-733 tokens, so the 2048 cap
    allows ~1300-1340 chars of state; the densest frame measured (S3 f9750:
    383 hazards + spellcard + 21 beams + items = 1315 chars) came back at
    2033 tokens. Budget 1280 => worst case ~2000 tokens, margin ~50.
    doc/research-laya-token-budget.md."""
    if len(text) <= budget:
        return text
    # drop the least important sentences: keep scene+boss+bullets (first 4)
    kept = text[:budget]
    if not kept.endswith("."):
        kept = kept.rsplit(". ", 1)[0] + "."
    return kept
