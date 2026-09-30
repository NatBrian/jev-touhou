"""M2: the Laya control loop (harness brain).

Architecture (doc/requirements-decisions.md §5, §7, §10):

    while episode running:
        state  = sim.get_state()              # frame N snapshot
        if decision due (every decide_every game frames):
            text   = compile_state(state)
            resp   = laya.predict(text, QUESTIONS)   # sync; sim FROZEN during call
            macro  = parse_macro(resp)               # 'laya'-sourced
        buttons  = executor(macro, state)            # 60 Hz, in-process, frame-exact
        sim.step(buttons)

Consequences:
  * The sim never advances while a Laya call is in flight, so a response always
    applies to the exact frame it was computed from (staleness ~ 0). Laya wall
    latency only costs wall-clock time.
  * decide_every adapts to latency: slow Laya -> longer macro, fewer calls
    (clamp: 30..300 game frames). The 60 Hz executor always re-evaluates the
    current frame; the macro is only a coarse tactical bias.
  * On Laya unavailability: hold the last Laya macro up to GRACE frames, then
    run the pure-code fallback policy; those frames are 'uncovered'.
  * Taint: episode is tainted (not clean-clear eligible) if uncovered fraction
    > 1% or a death occurs on an uncovered frame.

Run modes:
  * 'explore'  - continue through outages (fallback policy), taint-tag the run.
  * 'final'    - pause and wait for Laya (sleep + retry) instead of falling back.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import copy
from dataclasses import dataclass, field
from types import SimpleNamespace

from taisei_sim import (
    TaiseiSim, EpisodeConfig,
    PROJ_ENEMY,
    STATUS_RUNNING, STATUS_WON, STATUS_LOST, STATUS_ABORTED, STATUS_ERROR,
    CHAR_MARISA, SHOT_A, DIFFICULTY_LUNATIC,
)
from laya_client import LayaClient, LayaUnavailableError, LayaProtocolError
from state_compiler import compile_state, pressure_sides, EDGE_BAND
from macros import (
    MACRO_CHOICES, resolve_macro_target, MacroTarget,
    PX_MIN, PX_MAX, PY_MIN, PY_MAX, GUARD_Y,
)
from executor import ReflexExecutor, PLAYER_RADIUS

# --- decision-cycle knobs ----------------------------------------------------

DECIDE_EVERY_MIN = 30      # 0.5 s of game time - finest macro
DECIDE_EVERY_MAX = 300     # 5.0 s of game time - coarsest macro (bias still fine-grained via executor)
GRACE_FRAMES = 90          # 1.5 s: hold last Laya macro after a failed call before fallback
TAINT_UNCOVERED_FRACTION = 0.01
DEFAULT_DECIDE_EVERY = 30
BOMB_NOUL_THRESHOLD = 0.80   # v2 (G1 fix): 0.70 still gave 22.5% bomb calls; want rare (human: 0-3/stage)
FOCUS_NOUL_THRESHOLD = 0.80  # v2 (G3 fix): focus = half speed (2.75 px/f); 56-66% focus time
                             # was fatal (executor-only stage 2: no-focus 1 death/WON vs
                             # forced-focus 3 deaths/LOST). Focus must be rare.
MACRO_IDS = {mid for mid, _ in MACRO_CHOICES}
# R4.1 (2026-09-26): no-bomb evade decision. The 8-way move choice's guard
# prior cannot be overridden by prose (G1: guard on 100% of decisions while
# the dodge line said "hit in ~4 frames"). Calibration probes on REAL full
# states (doc/research-laya-calibration-probe.md) showed the auto-routed
# `english` checkpoint discriminates the numeric evade criteria on the
# in-batch `bomb_now` question: death-adjacent frames 0.60-0.67, safe frames
# <= 0.49 -> threshold 0.55. The direction is resolved by the harness from
# the same pressure data the dodge line shows Laya (the model's own
# direction prior is not state-based).
EVADE_NOUL_THRESHOLD = 0.55
# R4.2 (2026-09-26): harness-side edge exile (no-bomb only). G1.5
# (m3cam-0926-113108) showed the model trigger alone is insufficient: in
# dense Stage 3 the `english` answer compresses to 0.25-0.45 even when the
# state line says "hit in about 0 frames / at the bottom 0 px edge" (deaths
# f5323/f9682), and the R4.1 direction rule sent a left-edge player deeper
# into the wall (S2 f13507: pressure l=0/r=8 -> "sidestep_left"). So no-bomb
# mode also exiles on the harness side: within EDGE_BAND of any edge with a
# hazard hitting within EXILE_TTH_MAX frames -> the macro target becomes
# EXILE_DIST px away from that edge, regardless of Laya's answers. Bounded
# reflex; promoted only if the G2 campaign measures it effective.
EXILE_TTH_MAX = 25.0     # frames — hazard must hit within this many
EXILE_DIST = 50.0        # px — target offset away from the edge
# R4.4 (2026-09-26): the model-evade sidestep is 120 px relative to the
# CURRENT position, and _ask_laya re-issues it at every decision while the
# answer stays above EVADE_NOUL_THRESHOLD.  Uncapped, a chain of sidesteps
# walks the player to the 8 px clamp at the wall and into the corner, where
# the corner pattern closes in (G2.75 m3cam-0926-144755: both S2 deaths at
# (53,500)/(428,502) after repeated sidestep_left/right).  Sidestep targets
# are capped to stay at least this far from a wall; the cap is inactive in
# the open field (a 120 px step from x>=208 / x<=352 is unaffected).
SIDESTEP_WALL_MARGIN = 96.0   # px — min wall distance for a sidestep target

# --- Laya questions v1 (batched, one HTTP round trip) ---------------------------

QUESTIONS = {
    "move": {
        "type": "choice",
        "instructions": (
            "Choose the player's coarse position for the next moment. CRITICAL: a "
            "fast reflex layer handles ALL bullet dodging for you — you NEVER need "
            "to move in order to dodge or to 'get safe'; repositioning to escape "
            "bullets is useless and harmful. Your one job is to hold the guard "
            "position: lower center, roughly below the boss, so your upward shot "
            "keeps hitting the boss. Deviate from guard ONLY to collect a valuable "
            "item drop (item_sweep) or to set up a bomb (bomb_setup). IMPORTANT: "
            "grab LIFE and BOMB items when they drop near you — they add to your "
            "reserves and let you survive more hits, so they are worth a short "
            "detour. ALSO: you gain an extra life each time your score crosses "
            "5,000,000, then 10,000,000, 20,000,000, 35,000,000, 55,000,000, "
            "80,000,000 (the state line shows how close you are to the next "
            "one) — so PIV and "
            "point items are worth a short detour too, especially near a "
            "threshold. Do NOT hug the edges, do NOT advance toward the boss, and do "
            "NOT hover in place — each trades the safe position for danger. The "
            "right answer most of the time is guard. Default when unsure: guard."
        ),
        "criteria": dict(MACRO_CHOICES),
    },
    "focus": {
        "type": "noul",
        "instructions": (
            "Should the player hold focus right now? Focus HALVES her movement "
            "speed (precise but slow). Do NOT use focus to dodge — at full speed "
            "she dodges much better, so in dense bullet patterns the answer is NO. "
            "Answer YES only when she must thread an extremely narrow gap that "
            "full-speed movement would overshoot. Most of the time: NO."
        ),
    },
    "bomb_now": {
        "type": "noul",
        "instructions": (
            "Should the player use a bomb right now? The player has only 3 bombs "
            "for the whole stage. A bomb clears all bullets for about 5 seconds AND "
            "unleashes a huge laser that deals massive damage to the boss, so it is "
            "both an escape tool and a damage burst. Default is NO. Answer YES only "
            "if (a) the player will be hit within the next half-second with no safe "
            "move, or (b) the boss is on screen and a damage burst now clearly helps "
            "win the fight or a spell phase. A good player bombs a few times per "
            "stage, not constantly. Otherwise NO."
        ),
    },
    "danger": {
        "type": "score",
        "instructions": "Rate how immediately dangerous the current bullets are to the player.",
        "criteria": [
            "safe: open space, no pressure",
            "moderate: must move to stay safe",
            "severe: will be hit without immediate evasive action or a bomb",
        ],
    },
}

NO_BOMB_QUESTIONS = copy.deepcopy(QUESTIONS)
# R2/R4.1 (2026-09-26): the no-bomb questions are aligned with the
# action-oriented dodge line in state_compiler._dodge_hint (position,
# time-to-hit, per-side pressure, edge proximity). G1 showed the 8-way move
# choice's guard prior cannot be overridden by prose; calibration probes
# (doc/research-laya-calibration-probe.md) showed the in-batch `bomb_now`
# question repurposed with numeric escape criteria is the discriminative
# trigger, so the question set stays at four (move/focus/bomb_now/danger)
# and the move vocabulary shrinks to the six choices that matter without
# bombs.
NO_BOMB_MOVE_CRITERIA = [
    ("guard", "Stay low, centered under the boss, and shoot (the default, safest play)"),
    ("hold", "Stay in the lower safe zone and shoot (same as guard, less repositioning)"),
    ("retreat", "Back away toward the very bottom of the screen"),
    ("sidestep_left", "Shift a bit left, keep your height"),
    ("sidestep_right", "Shift a bit right, keep your height"),
    ("item_sweep", "Collect a nearby item drop (prioritize LIFE items)"),
]
NO_BOMB_QUESTIONS["move"]["instructions"] = (
    "Choose the player's coarse position for the next moment. Bombs are "
    "forbidden, so survival must come from movement and shooting. The state "
    "line tells you your exact position, how many frames until the nearest "
    "bullet hits you, the bullet pressure in each direction, and your "
    "distance from each edge. A separate question asks whether you must "
    "escape right now; if it is YES, this answer is ignored. guard or hold "
    "is correct ONLY when the nearest bullet will not hit you for at "
    "least about 40 frames, pressure is low in every direction, and you are "
    "not near any edge. Otherwise choose sidestep_left or sidestep_right "
    "toward the direction with the lower pressure, or retreat if the bottom "
    "is the open side. The local reflex layer handles frame-level dodging. "
    "Default in genuinely open space: guard."
)
NO_BOMB_QUESTIONS["move"]["criteria"] = dict(NO_BOMB_MOVE_CRITERIA)
# R4.1 (2026-09-26): the in-batch `bomb_now` question carries the numeric
# escape criteria (probe: identical criteria under a new question name
# return identical answers, and `english` discriminates this text on real
# full states — death frames 0.60-0.67 vs <= 0.49 safe, threshold 0.55;
# doc/research-laya-calibration-probe.md). Bombs are still forbidden: the
# parsed `bomb` is forced False in no-bomb mode; only the evade meaning is
# used.
NO_BOMB_QUESTIONS["bomb_now"]["instructions"] = (
    "Must the player leave the guard position RIGHT NOW to avoid a hit? "
    "Use the state line and answer YES only when at least one of these is "
    "true: (a) the nearest bullet will hit you in fewer than about 30 "
    "frames; (b) you are within 40 px of any edge with bullet pressure "
    "toward that edge; (c) the bullet pressure in any direction is 8 or "
    "more. Otherwise answer NO. Do NOT answer YES just because bullets "
    "exist — answer YES only when staying put will get you hit."
)
NO_BOMB_QUESTIONS["danger"]["instructions"] = (
    "Rate immediate bullet danger assuming bombs are unavailable; judge only "
    "the movement needed to survive. Use the state line: score 2 (severe) "
    "when the nearest bullet will hit you in under about 20 frames or you are "
    "near an edge with pressure toward that edge, 1 (moderate) when you must "
    "move soon, 0 (safe) when space around you is open."
)
NO_BOMB_QUESTIONS["danger"]["criteria"] = [
    "safe: open space, no pressure",
    "moderate: must move soon to stay safe",
    "severe: will be hit within about 20 frames without evasive movement",
]

@dataclass
class Macro:
    macro_id: str = "hold"        # Laya's tactical intent (vocabulary in macros.py)
    target: MacroTarget = field(default_factory=MacroTarget)
    focus: bool = False
    bomb: bool = False
    danger_score: float = -1.0
    source: str = "fallback"      # 'laya' | 'fallback'
    issued_frame: int = 0
    raw: dict = field(default_factory=dict)
    # R0 telemetry (2026-09-26): the exact compiled state text this macro was
    # computed from, kept so traces can show what Laya actually saw.
    state_text: str = ""
    # R4.1 (2026-09-26): no-bomb evade decision. evade_raw is the raw
    # `bomb_now` noul (repurposed escape criteria); evade_dir/evade_eff are
    # the harness-resolved direction and whether the override applied.
    evade_raw: float = -1.0
    evade_dir: str = ""
    evade_eff: bool = False
    # R4.2 (2026-09-26): harness edge exile fired (edge band + hit within
    # EXILE_TTH_MAX) — independent of the model's evade answer.
    exile_eff: bool = False


@dataclass
class EpisodeResult:
    stage_id: int
    status: int
    frames: int                # final logical_frame reported by the sim
    deaths: int
    bombs_used: int
    score: int
    laya_calls: int
    laya_failures: int
    protocol_errors: int
    uncovered_frames: int
    died_uncovered: bool
    wall_secs: float
    taint: bool
    taint_reason: str = ""
    # frames the agent actually stepped — the coverage denominator. Includes the
    # game-over tail, during which logical_frame is frozen while the episode
    # status is still RUNNING, so it can exceed `frames`.
    executed_frames: int = 0


# --- agent --------------------------------------------------------------------

class Agent:
    def __init__(self, sim: TaiseiSim, laya: LayaClient,
                 decide_every: int = DEFAULT_DECIDE_EVERY,
                 log_dir: str | None = None,
                 episode_tag: str = "ep", allow_bombs: bool = True,
                 allow_focus: bool = True, allow_edge_escape: bool = False,
                 danger_valve: bool = False, gap_horizon: bool = False,
                 escape_commit: bool = False,
                 laser_blind_fix: bool = False, laser_ring: bool = False,
                 wall_commit: bool = False,
                 dense_wall: bool = False, wall_danger: bool = False):
        self.sim = sim
        self.laya = laya
        self.decide_every = decide_every
        self.log_dir = log_dir
        self.episode_tag = episode_tag
        self.allow_bombs = allow_bombs
        self.allow_focus = allow_focus
        self.allow_edge_escape = allow_edge_escape
        self.danger_valve = danger_valve
        self.gap_horizon = gap_horizon
        self.escape_commit = escape_commit
        self.laser_blind_fix = laser_blind_fix
        self.laser_ring = laser_ring
        self.wall_commit = wall_commit
        self.dense_wall = dense_wall
        self.wall_danger = wall_danger
        self.questions = QUESTIONS if allow_bombs else NO_BOMB_QUESTIONS
        self.executor = ReflexExecutor(
            allow_bombs=allow_bombs, allow_edge_escape=allow_edge_escape,
            danger_valve=danger_valve, gap_horizon=gap_horizon,
            escape_commit=escape_commit,
            laser_blind_fix=laser_blind_fix, laser_ring=laser_ring,
            wall_commit=wall_commit, dense_wall=dense_wall,
            wall_danger=wall_danger)
        self._step_fps = 600.0          # moving estimate of sim frames per wall-second
        self._step_acc_t = 0.0
        self._step_acc_n = 0

    # -- R4.1/R4.2 (2026-09-26): no-bomb escape trigger + target resolution ------
    def _edge_exile(self, v) -> bool:
        """R4.2 harness trigger: the player is within EDGE_BAND of a playfield
        edge AND a hazardous bullet will overlap the player within
        EXILE_TTH_MAX frames. That is the pinned-at-the-wall situation the
        local evader cannot recover from: the wall removes half the escape
        directions, and off-screen space holds no bullets, so the cost
        landscape pulls the player to the wall. G1.5 S3 deaths f5323/f9682
        were exactly this, with the model's evade answer below threshold."""
        px, py = float(v.raw.player.position.x), float(v.raw.player.position.y)
        if not (py >= PY_MAX - EDGE_BAND or py <= PY_MIN + EDGE_BAND or
                px <= PX_MIN + EDGE_BAND or px >= PX_MAX - EDGE_BAND):
            return False
        return self._death_within(v, EXILE_TTH_MAX)

    def _evade_target(self, v):
        """R4.1/R4.2: resolve the escape target for no-bomb mode. Returns
        (MacroTarget, direction_label).

        * Within EDGE_BAND of an edge: the target is EXILE_DIST px away from
          that edge (a corner covers both), keeping the other coordinate —
          the minimum move that restores the escape room the wall removed
          (R4.1's "retreat to (240, 510)" re-pinned the bottom case: 510 is
          still inside the 40 px band).
        * Open field (model-triggered only): a 120 px sidestep to the
          LOWER-pressure side (90 px box; 180 px rescan breaks ties; a full
          tie goes left) — the same pressure data the dodge line shows Laya.

        Laya decides WHETHER to escape (the calibrated bomb_now answer);
        this is target resolution of the coarse intent, exactly like
        guard -> below-boss.
        """
        px, py = float(v.raw.player.position.x), float(v.raw.player.position.y)
        edges = []
        if py >= PY_MAX - EDGE_BAND:
            edges.append("bottom")
        if py <= PY_MIN + EDGE_BAND:
            edges.append("top")
        if px <= PX_MIN + EDGE_BAND:
            edges.append("left")
        if px >= PX_MAX - EDGE_BAND:
            edges.append("right")
        if not edges:
            # Open field (model-triggered only): 120 px sidestep to the
            # LOWER-pressure side (90 px box; 180 px rescan breaks ties; a
            # full tie goes left).
            enemies = [p for p in v.projectiles
                       if p.category == PROJ_ENEMY and p.flags & 16]
            u, d, l, r = pressure_sides(enemies, px, py)
            if l == r:
                u, d, l, r = pressure_sides(enemies, px, py, radius=180.0)
            if l <= r:
                return (MacroTarget(kind="point",
                                    point=(max(PX_MIN + SIDESTEP_WALL_MARGIN,
                                               px - 120.0), py)),
                        "sidestep_left")
            return (MacroTarget(kind="point",
                                point=(min(PX_MAX - SIDESTEP_WALL_MARGIN,
                                           px + 120.0), py)),
                    "sidestep_right")
        if "left" in edges or "right" in edges:
            # Horizontal edge (or a corner touching one): move AWAY from the
            # wall (the R4.2 direction fix — a lower-pressure comparison picks
            # the wall side, since no bullets exist past the wall). A corner
            # also returns to the guard height (GUARD_Y) so it leaves the
            # vertical edge too.
            tx, ty = px, py
            if "left" in edges:
                tx = min(PX_MAX - 16.0, px + EXILE_DIST)
            if "right" in edges:
                tx = max(PX_MIN + 16.0, px - EXILE_DIST)
            if "bottom" in edges or "top" in edges:
                ty = GUARD_Y
            return (MacroTarget(kind="point", point=(tx, ty)),
                    "exile_" + "_".join(edges))
        # Vertical edge only (bottom and/or top): return to the guard anchor.
        # G2 (m3cam-0926-121236) showed a 50 px-up point target that keeps the
        # player's x is worse than the guard anchor: the player died in its own
        # x column (death x 288/374/242 vs boss x 193/347/335). The guard
        # anchor re-centers and pulls 74 px up. (In a dangerous state the
        # executor ignores the macro target anyway — beta*intent <= 0.8 vs
        # bullet costs of 250-320 — so actually leaving the cost valley needs
        # the per-frame --edge-escape penalty, not a target.)
        return (resolve_macro_target("guard", v),
                "exile_" + "_".join(edges))

    # -- Laya decision -----------------------------------------------------------
    def _ask_laya(self, v, frame: int, current_macro: Macro | None = None):
        """One batched Laya call. Returns (Macro|None, status_str, resp|None)."""
        text = compile_state(v, macro_context=self._macro_context(current_macro))
        try:
            resp = self.laya.predict(text, self.questions)
        except LayaUnavailableError:
            return None, "unavailable", None
        except LayaProtocolError:
            return None, "protocol_error", None

        a = resp["answers"]
        m = Macro(source="laya", issued_frame=frame)
        move = a["move"]["choice"]
        m.macro_id = move if move in MACRO_IDS else "hold"
        m.target = resolve_macro_target(m.macro_id, v)
        m.focus = (self.allow_focus and
                   a["focus"]["noul"] >= FOCUS_NOUL_THRESHOLD)
        m.bomb = (self.allow_bombs and
                  a["bomb_now"]["noul"] >= BOMB_NOUL_THRESHOLD)
        if not self.allow_bombs and m.macro_id == "bomb_setup":
            m.macro_id = "guard"
            m.target = resolve_macro_target("guard", v)
        m.danger_score = float(a["danger"]["score"])
        if not self.allow_bombs:
            # R4.1: the repurposed bomb_now answer is the escape decision —
            # a calibrated probability, not an 8-way argmax (G1 finding +
            # probe: death frames 0.60-0.67 vs safe <= 0.49, threshold 0.55).
            # R4.2: the harness ALSO exiles when the player is pinned near
            # an edge with a hit imminent, regardless of the model answer
            # (G1.5: dense-stage answers compress below the threshold).
            # Either way the harness resolves WHERE; Laya decides WHETHER.
            m.evade_raw = float((a.get("bomb_now") or {}).get("noul", 0.0))
            m.evade_eff = m.evade_raw >= EVADE_NOUL_THRESHOLD
            m.exile_eff = self._edge_exile(v)
            if m.evade_eff or m.exile_eff:
                m.target, m.evade_dir = self._evade_target(v)
                m.macro_id = m.evade_dir
        m.raw = {k: (dict(vv) if isinstance(vv, dict) else vv) for k, vv in a.items()}
        m.state_text = text
        return m, "ok", resp

    def _macro_context(self, m: Macro | None) -> str | None:
        if m is None:
            return None
        if m.source != "laya":
            return "none (degraded mode, no Laya macro)"
        parts = [m.macro_id]
        if m.focus:
            parts.append("focus on")
        if self.allow_bombs and m.bomb:
            parts.append("bomb armed")
        return ", ".join(parts)

    @staticmethod
    def _snapshot_context(v) -> dict:
        """Boss/player context for the call log (DPS + death analysis)."""
        pl = v.raw.player
        b = v.raw.boss
        rec = {
            "player": [round(float(pl.position.x), 1), round(float(pl.position.y), 1)],
            "deaths": int(v.raw.deaths),
            "lives": int(pl.lives),
            "life_frags": int(pl.life_fragments),
            "bombs_left": int(pl.bombs),
            "bomb_frags": int(pl.bomb_fragments),
            "power": int(pl.effective_power),
            "boss_active": bool(b.active),
            "boss_hp_frac": (float(b.hp) / float(b.max_hp)) if b.active and b.max_hp > 0 else None,
            "boss_phase": int(b.phase_type) if b.active else None,
            "boss_spell": bool(b.spell_active) if b.active else None,
        }
        return rec

    def _log_call(self, frame, status, resp=None, macro=None, v=None):
        if not self.log_dir:
            return
        rec = {
            "frame": frame,
            "status": status,
            "wall_ms": resp.get("_wall_ms") if resp else None,
            "server_ms": resp.get("_server_ms") if resp else None,
            "routing": (resp.get("routing") or {}).get("model") if resp else None,
            "input_tokens": (resp.get("usage") or {}).get("input_tokens") if resp else None,
            "macro": macro.macro_id if macro else None,
            "focus": (macro.raw.get("focus") or {}).get("noul") if macro else None,
            "bomb_now": (macro.raw.get("bomb_now") or {}).get("noul") if macro else None,
            "danger": (macro.raw.get("danger") or {}).get("score") if macro else None,
        }
        if macro is not None:
            # R0 telemetry (2026-09-26): the RAW Laya move answer, not just
            # the parsed (possibly no-bomb-remapped) macro id.
            raw_move = (macro.raw.get("move") or {}).get("choice")
            rec["raw_move"] = raw_move
            rec["move_probs"] = (macro.raw.get("move") or {}).get("probabilities")
            rec["move_remapped"] = (raw_move is not None
                                    and raw_move != macro.macro_id)
            rec["focus_eff"] = bool(macro.focus)
            # R4.1/R4.2: the raw escape probability is the `bomb_now` field
            # above; these carry the harness decision on top of it.
            rec["evade_dir"] = getattr(macro, "evade_dir", "")
            rec["evade_eff"] = bool(getattr(macro, "evade_eff", False))
            rec["exile_eff"] = bool(getattr(macro, "exile_eff", False))
            rec["target_kind"] = getattr(macro.target, "kind", None)
            rec["state_chars"] = len(macro.state_text)
            rec["state_sha1"] = (hashlib.sha1(macro.state_text.encode("utf-8"))
                                 .hexdigest() if macro.state_text else None)
        rec["decide_every"] = self.decide_every
        if v is not None:
            rec.update(self._snapshot_context(v))
        path = os.path.join(self.log_dir, f"laya-{self.episode_tag}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    # -- R0.1 (2026-09-26): immutable entity snapshots -------------------------
    # TaiseiSim.get_state() returns entity lists that reference PERSISTENT C
    # buffers rewritten in place by every step() (harness/taisei_sim.py
    # get_state: list(self._buf["projectiles"][:count])). A held StateView
    # therefore shows the LATEST frame's entities; only its `raw` struct is
    # a value copy. Death forensics must use a plain-Python snapshot taken
    # BEFORE the step that processes the hit.
    @staticmethod
    def _snapshot_hazards(v) -> dict:
        px, py = float(v.raw.player.position.x), float(v.raw.player.position.y)
        bullets = [
            (float(p.position.x), float(p.position.y),
             float(p.velocity.x), float(p.velocity.y),
             float(max(p.collision_size.x, p.collision_size.y)),
             int(p.flags))
            for p in v.projectiles if p.category == PROJ_ENEMY
        ]
        enemies = [
            (float(e.position.x), float(e.position.y),
             float(e.velocity.x), float(e.velocity.y),
             float(e.hurt_radius))
            for e in v.enemies if e.harmful
        ]
        lasers = [
            (int(L.first_point), int(L.point_count),
             float(L.origin.x), float(L.origin.y),
             float(L.width), int(L.age_frames),
             float(L.speed), float(L.timespan),
             float(L.death_time), float(L.time_shift))
            for L in v.lasers if L.collision_active
        ]
        laser_points = (
            [(float(pt.time), float(pt.position.x), float(pt.position.y),
              float(pt.half_width), int(pt.flags)) for pt in v.laser_points]
            if lasers else []
        )
        items = [
            (int(it.item_type), float(it.position.x), float(it.position.y),
             int(it.spawn_id))
            for it in v.items
        ]
        return {"px": px, "py": py, "bullets": bullets, "enemies": enemies,
                "lasers": lasers, "laser_points": laser_points, "items": items}

    @staticmethod
    def _view_from_snapshot(raw, snap: dict):
        """Read-only StateView-shaped object from raw (value copy) + an
        immutable snapshot — everything compile_state needs."""
        def P(x, y):
            return SimpleNamespace(x=x, y=y)
        proj = [SimpleNamespace(category=PROJ_ENEMY, flags=f,
                                position=P(x, y), velocity=P(vx, vy),
                                collision_size=P(r, r))
                for (x, y, vx, vy, r, f) in snap["bullets"]]
        en = [SimpleNamespace(harmful=True, position=P(x, y),
                              velocity=P(vx, vy), hurt_radius=r)
              for (x, y, vx, vy, r) in snap["enemies"]]
        ls = [SimpleNamespace(collision_active=True, first_point=fp,
                              point_count=pc, origin=P(ox, oy), width=w,
                              age_frames=age, speed=s, timespan=ts,
                              death_time=dt, time_shift=tsh)
              for (fp, pc, ox, oy, w, age, s, ts, dt, tsh) in snap["lasers"]]
        lps = [SimpleNamespace(time=t, position=P(x, y), half_width=hw,
                               flags=fl)
               for (t, x, y, hw, fl) in snap["laser_points"]]
        its = [SimpleNamespace(item_type=t, position=P(x, y), spawn_id=sid)
               for (t, x, y, sid) in snap["items"]]
        return SimpleNamespace(raw=raw, player=raw.player, boss=raw.boss,
                               projectiles=proj, enemies=en, lasers=ls,
                               laser_points=lps, items=its)

    def _log_death_hit(self, v_pre, macro, v_now=None, snap: dict | None = None):
        """Lethal-hit forensics: the state at the START of the hit frame.

        taisei's player_death (player.c) sets deathtime = hit_frame + window
        and, on the hit frame itself, immediately clears ALL hazards
        (player_update: stage_clear_hazards(CLEAR_HAZARDS_ALL | NOW)). The
        player then sits invulnerable at the death position for the ~12-frame
        deathbomb window until player_realdeath teleports them to (240, 590)
        and increments the deaths counter. So the killer only exists in the
        state BEFORE the hit frame's step. R0.1 (2026-09-26): entity data
        comes from `snap`, an IMMUTABLE snapshot taken before that step —
        the StateView's entity lists reference persistent C buffers that
        step() rewrites in place, so a held view shows the post-clear world.
        `v_pre.raw` remains the value copy of the hit frame's scalars.
        """
        if not self.log_dir:
            return
        src = v_pre
        if snap is None:
            snap = self._snapshot_hazards(src)
        pl = src.raw.player
        px, py = snap["px"], snap["py"]
        near = []
        for (bx, by, vx, vy, r, flags) in snap["bullets"]:
            if not (flags & 16):
                continue
            d = math.hypot(bx - px, by - py)
            if d < 160:
                near.append({
                    "d": round(d, 1),
                    "vx": round(vx, 1),
                    "vy": round(vy, 1),
                    "r": round(r, 1),
                })
        near.sort(key=lambda h: h["d"])
        # harmful enemy bodies near the player (body-contact kills, transition
        # moments when bullets=0)
        ennear = []
        for (exx, ey, vx, vy, hr) in snap["enemies"]:
            d = math.hypot(exx - px, ey - py)
            if d < 160:
                ennear.append({
                    "d": round(d, 1),
                    "pos": [round(exx, 1), round(ey, 1)],
                    "vx": round(vx, 1),
                    "vy": round(vy, 1),
                    "r": round(hr, 1),
                })
        ennear.sort(key=lambda h: h["d"])
        # active lasers: for beam hits the killer is identified by the CLOSEST
        # APPROACH of the beam body to the player (sampled laser points with
        # half_width — same model as the executor), not by origin distance
        lasers = []
        lps = snap["laser_points"]
        frame_now = int(src.raw.logical_frame)
        for (fp, pc, ox, oy, w, age, _spd, _ts, dt, tsh) in snap["lasers"]:
            d0 = math.hypot(ox - px, oy - py)
            d_beam, beam_pt = None, None
            t_dead = dt + tsh if dt > 0 else float("inf")
            end = min(fp + pc, len(lps))
            for i in range(fp, end):
                t, bx, by, hw, _fl = lps[i]
                if t < tsh or t > min(t_dead, frame_now):
                    continue
                d = math.hypot(bx - px, by - py) - (hw if hw > 0 else 0.0)
                if d_beam is None or d < d_beam:
                    d_beam = d
                    beam_pt = (bx, by)
            lasers.append({
                "d_beam": round(d_beam, 1) if d_beam is not None else None,
                "d_origin": round(d0, 1),
                "origin": [round(ox, 1), round(oy, 1)],
                "beam_pt": [round(beam_pt[0], 1), round(beam_pt[1], 1)] if beam_pt else None,
                "width": round(w, 1),
                "age": age,
            })
        lasers.sort(key=lambda h: h["d_beam"] if h["d_beam"] is not None else 10 ** 9)
        rec = {
            "frame": int(src.raw.logical_frame),
            "status": "death_hit",
            "macro": macro.macro_id if macro else None,
            "focus": bool(macro.focus) if macro else None,
            "bomb_now": (macro.raw.get("bomb_now") or {}).get("noul") if macro else None,
            "player": [round(px, 1), round(py, 1)],
            "player_vel": [round(float(src.raw.player.velocity.x), 2),
                           round(float(src.raw.player.velocity.y), 2)],
            "input_flags": int(src.raw.player.input_flags),
            "bombs_left": int(src.raw.player.bombs),
            "bomb_active": bool(src.raw.player.bomb_active),
            "bullets": len([b for b in snap["bullets"] if b[5] & 16]),
            "enemies_harmful": len(snap["enemies"]),
            "lasers_active": len(snap["lasers"]),
            "boss": (bool(src.raw.boss.active),
                     round(float(src.raw.boss.position.x), 1),
                     round(float(src.raw.boss.position.y), 1),
                     round(float(src.raw.boss.hp) / float(src.raw.boss.max_hp), 3)
                     if src.raw.boss.max_hp > 0 else None) if src.raw.boss.active else None,
            "nearest_hazards": near[:8],
            "enemies_near": ennear[:8],
            "lasers_near": lasers[:6],
            "executor_move_idx": self.executor.last_move_idx,
            "executor_cost": (round(float(self.executor.last_cost), 4)
                              if self.executor.last_cost is not None else None),
            "executor_costs": ([round(float(c), 4)
                                for c in self.executor.last_costs]
                               if self.executor.last_costs is not None else None),
            "executor_buttons": int(self.executor.last_buttons),
        }
        if macro is not None:
            # R0 telemetry: raw Laya answer for the macro active at the hit.
            rec["raw_move"] = (macro.raw.get("move") or {}).get("choice")
            rec["move_remapped"] = (rec["raw_move"] is not None
                                    and rec["raw_move"] != macro.macro_id)
            rec["focus_eff"] = bool(macro.focus)
            rec["evade_eff"] = bool(getattr(macro, "evade_eff", False))
            rec["exile_eff"] = bool(getattr(macro, "exile_eff", False))
            rec["target_kind"] = getattr(macro.target, "kind", None)
        # The state Laya WOULD have seen at the start of the hit frame — the
        # exact input a same-frame decision would have compiled (R0), built
        # from the immutable snapshot (R0.1) so the cleared bullet field is
        # not what gets compiled.
        hit_view = self._view_from_snapshot(src.raw, snap)
        hit_text = compile_state(hit_view,
                                 macro_context=self._macro_context(macro))
        rec["hit_state_text"] = hit_text
        rec["hit_state_chars"] = len(hit_text)
        path = os.path.join(self.log_dir, f"laya-{self.episode_tag}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def _log_death_real(self, frame, macro, v):
        """Player actually died (lives-- + respawn): slim record.

        Lands ~12 frames (deathbomb window) after the death_hit record,
        unless the death was averted with a bomb (then no record at all).
        The state is already cleared + teleported, so no hazard forensics.
        """
        if not self.log_dir:
            return
        pl = v.raw.player
        rec = {
            "frame": frame,
            "status": "death",
            "macro": macro.macro_id if macro else None,
            "player": [round(float(pl.position.x), 1), round(float(pl.position.y), 1)],
            "lives": int(pl.lives),
            "bombs": int(pl.bombs),
            "power": int(pl.effective_power),
            "score": int(v.raw.score),
        }
        path = os.path.join(self.log_dir, f"laya-{self.episode_tag}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    # -- executor (60 Hz, in-process) ---------------------------------------------
    def _execute(self, macro: Macro, v) -> int:
        """Frame-exact buttons for the current frame (reflex evader; §7)."""
        return self.executor.execute(macro, v)

    def _fallback_macro(self, v) -> Macro:
        """Degraded pure-code policy (Laya absent): guard + reflex dodging +
        shoot + conserve bombs. Bomb only when death is predicted inside the
        locked 12-frame deathbomb window (requirements §3, §7 exception)."""
        pl = v.raw.player
        m = Macro(macro_id="guard", source="fallback",
                  issued_frame=int(v.raw.logical_frame),
                  target=resolve_macro_target("guard", v))
        if pl.bomb_active or not pl.alive:
            return m
        if self.allow_bombs and pl.bombs > 0 and self._death_within(v, 12.0):
            m.bomb = True
        return m

    def _death_within(self, v, t_max: float) -> bool:
        """True if any active hazard overlaps the player within t_max frames."""
        pl = v.raw.player
        px, py = float(pl.position.x), float(pl.position.y)
        for p in v.projectiles:
            if p.category != PROJ_ENEMY or not (p.flags & 16):
                continue
            r = max(p.collision_size.x, p.collision_size.y, 3.0)
            t = self._time_to_overlap(px, py, float(p.position.x),
                                      float(p.position.y),
                                      float(p.velocity.x), float(p.velocity.y),
                                      r + PLAYER_RADIUS)
            if t is not None and t <= t_max:
                return True
        return False

    @staticmethod
    def _time_to_overlap(px, py, hx, hy, vx, vy, r):
        """Smallest t >= 0 with |h + v t - p| <= r, or None if it never does."""
        dx, dy = hx - px, hy - py
        a = vx * vx + vy * vy
        if a < 1e-9:
            return 0.0 if dx * dx + dy * dy <= r * r else None
        b = 2.0 * (dx * vx + dy * vy)
        c = dx * dx + dy * dy - r * r
        if c <= 0:
            return 0.0
        disc = b * b - 4 * a * c
        if disc < 0:
            return None
        t = (-b - disc ** 0.5) / (2 * a)
        return t if t >= 0 else None

    # -- adaptive decision cadence ---------------------------------------------------
    def _adapt_decide_every(self, wall_s: float):
        # requirements-decisions.md §5: DECIDE_EVERY = max(min_frames, latency_in_frames),
        # where latency_in_frames = Laya wall latency expressed in GAME frames
        # (60 fps game clock — a 5 s call = 300 frames, game runs at ~1/10x real time).
        latency_frames = wall_s * 60.0
        self.decide_every = max(DECIDE_EVERY_MIN, min(DECIDE_EVERY_MAX, int(latency_frames) or DECIDE_EVERY_MIN))

    # -- main loop --------------------------------------------------------------------
    def run_episode(self, episode: EpisodeConfig, mode: str = "explore") -> EpisodeResult:
        assert mode in ("explore", "final")
        self.sim.reset(episode)
        self.executor.reset()

        macro = Macro(macro_id="hold", source="fallback",
                      target=MacroTarget(kind="hold"))
        last_decision_frame = -10 ** 9
        laya_silent_frames = 0
        res = EpisodeResult(
            stage_id=episode.stage_id, status=STATUS_RUNNING, frames=0,
            deaths=0, bombs_used=0, score=0,
            laya_calls=0, laya_failures=0, protocol_errors=0,
            uncovered_frames=0, died_uncovered=False, wall_secs=0.0, taint=False,
        )
        prev_deaths = 0
        prev_death_timer = -1
        prev_v = None           # state before the last executed step
        prev_snap = None        # R0.1: immutable entity snapshot at prev_v
        t0 = time.perf_counter()

        while True:
            v = self.sim.get_state()
            st = v.raw
            res.frames = int(st.logical_frame)
            res.deaths = int(st.deaths)
            res.bombs_used = int(st.bombs_used)
            res.score = int(st.score)
            # lethal-hit forensics: death_timer (deathtime - frames) flips
            # -1 -> >= 0 the frame after the hit; the killer only exists in
            # prev_v (start of the hit frame), since hazards are cleared on
            # the hit frame itself (see _log_death_hit)
            death_timer = int(st.player.death_timer)
            if death_timer >= 0 and prev_death_timer < 0 and prev_v is not None:
                self._log_death_hit(prev_v, macro, v, snap=prev_snap)
            prev_death_timer = death_timer
            if res.deaths > prev_deaths:
                if macro.source != "laya":
                    res.died_uncovered = True
                self._log_death_real(res.frames, macro, v)
            prev_deaths = res.deaths

            if st.episode_status != STATUS_RUNNING:
                res.status = st.episode_status
                break

            # --- decision cycle (sim frozen during the call) ---
            if res.frames - last_decision_frame >= self.decide_every:
                last_decision_frame = res.frames
                while True:
                    dt0 = time.perf_counter()
                    new_macro, status, resp = self._ask_laya(v, res.frames, macro)
                    call_wall = time.perf_counter() - dt0
                    res.laya_calls += 1
                    self._log_call(res.frames, status, resp=resp, macro=new_macro, v=v)
                    if status == "ok" and new_macro is not None:
                        macro = new_macro
                        laya_silent_frames = 0
                        self._adapt_decide_every(call_wall)
                        break
                    if status == "protocol_error":
                        res.protocol_errors += 1
                    res.laya_failures += 1
                    if mode == "final":
                        # pause and wait for the tunnel, then re-call at this same frame
                        self._wait_for_laya()
                        v = self.sim.get_state()
                        continue
                    laya_silent_frames += self.decide_every
                    if laya_silent_frames > GRACE_FRAMES:
                        macro = self._fallback_macro(v)
                    break

            # --- coverage bookkeeping ---
            res.executed_frames += 1
            if macro.source != "laya":
                res.uncovered_frames += 1

            # --- execute + step (measure step fps) ---
            buttons = self._execute(macro, v)
            st0 = time.perf_counter()
            # R0.1: capture immutable entity data BEFORE step() rewrites the
            # persistent C buffers (a held StateView would go stale).
            prev_snap = self._snapshot_hazards(v)
            self.sim.step(buttons=buttons)
            prev_v = v           # state before the step we just executed
            st1 = time.perf_counter()
            self._step_acc_t += st1 - st0
            self._step_acc_n += 1
            if self._step_acc_n >= 300:
                self._step_fps = self._step_acc_n / max(self._step_acc_t, 1e-9)
                self._step_acc_t = 0.0
                self._step_acc_n = 0

        res.wall_secs = time.perf_counter() - t0
        total = max(res.executed_frames, 1)
        frac = res.uncovered_frames / total
        if frac > TAINT_UNCOVERED_FRACTION:
            res.taint, res.taint_reason = True, f"uncovered {frac:.2%}"
        elif res.died_uncovered:
            res.taint, res.taint_reason = True, "death during uncovered frames"
        return res

    def _wait_for_laya(self, poll_s: float = 2.0, max_s: float = 6 * 3600):
        """'final' mode: pause and wait for the tunnel to recover."""
        waited = 0.0
        while not self.laya.is_available():
            time.sleep(poll_s)
            waited += poll_s
            if waited > max_s:
                raise RuntimeError("Laya unreachable for > %ds in final mode" % max_s)

    # -- 6-stage clean-run chaining -----------------------------------------------------
    @staticmethod
    def carry_over(v) -> dict:
        """State to carry from a WON episode into the next stage."""
        pl = v.raw.player
        return {
            "initial_lives": pl.lives,
            "initial_bombs": pl.bombs,
            "initial_life_fragments": pl.life_fragments,
            "initial_bomb_fragments": pl.bomb_fragments,
            "initial_power": pl.stored_power,
            "initial_point_item_value": pl.point_item_value,
            "initial_score": v.raw.score,
            "initial_graze": v.raw.graze,
        }

    def run_game(self, rng_seed: int, difficulty: int = DIFFICULTY_LUNATIC,
                 mode: str = "explore", stages=(1, 2, 3, 4, 5, 6)) -> list[EpisodeResult]:
        results = []
        carry = {}
        for i, stage in enumerate(stages):
            ep = EpisodeConfig(
                stage_id=stage,
                difficulty=difficulty,
                player_character=CHAR_MARISA,
                shot_mode=SHOT_A,
                rng_seed=rng_seed + stage,
                **carry,
            )
            r = self.run_episode(ep, mode=mode)
            results.append(r)
            if r.status != STATUS_WON:
                break
            v = self.sim.get_state()
            carry = self.carry_over(v)
        return results
