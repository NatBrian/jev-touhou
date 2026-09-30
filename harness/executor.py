"""M3 reflex executor v5 — 60 Hz, in-process, pure code.

Converts a Laya macro into frame-exact button presses while dodging. It never
vetoes the macro: it picks the lowest-risk execution *within* the macro's
intent (requirements-decisions.md §7 "Laya is final").

Model (doc/design-m3-reflex-and-macros.md §4; v5 ground truth verified in
doc/research-video-fidelity-source-of-truth.md §7):
  * Player speed (px/frame): full 6.25, focus 2.75 (Marisa A); diagonals are
    normalized (taisei player.c `direction /= cabs(direction)`), so every
    direction moves at the same speed.
  * Hazards: enemy bullets (category=ENEMY, ACTIVE_HAZARD bit 1<<4), harmful
    enemy bodies, the boss body, and — v5 — collision-active lasers as
    per-beam POLYLINES from ALL snapshot points (break at the DISCONTINUITY
    flag / large gaps), modeled with the engine's exact collision:
    centerline capsule radius max(half_width - 4, 2) per segment
    (laser.c:576-586 `ucapsule_dist_from_point < 0`) PLUS a motion-crossing
    kill — the candidate's movement segment (prev -> next) intersecting the
    centerline is a hit ("prevent phasing", laser.c:571-574). Beam time:
    pt.time is NEGATED laser time — the drawn beam is pt.time <= 0, future
    growth pt.time > 0 (appears |time| frames from now; laser.c:270,
    sim.c:349); the threat set = drawn body + growth within the horizon,
    capped at the beam's death.
  * Risk at a candidate next position q:
        risk(q) = sum_h w_h * g(dist(q, h) - r_h - r_p)
    g(u) = 1 + 10*|u|        if u < 0   (overlap: steep penalty)
           exp(-u / 6)       if 0 <= u < G_RANGE
           0                otherwise
    (laser segments use the same g() on the point-to-capsule distance)
  * cost(c) = risk_now(q1) + 0.5 * risk_horizon(q1) + 0.2 * risk_now(q2)
    + wall_proximity(q1) + laser_crossing_kill(prev -> q1)
    (v3: q2 = the 2-frame-ahead position along the same direction — catches
    threats arriving in the direction of travel). v5 wall term: quadratic
    within ~40 px of the playfield bounds (the v1.4.6 Easy campaign deaths
    were at the x=16/464 edges with dense bullet walls there).
  * score(c) = cost(c) - BETA * intent(c)           (evasion first, then intent)
  * Hysteresis: keep the current direction while its cost <= EPS_SAFE.
  * Shot: Marisa A fires fixed upward regardless of movement direction
    (verified tools/diag_shot_dir.py) -> always hold ACTION_SHOT.
  * Bomb (v5): (a) hit-time death-bomb safety net — fire the moment a hit is
    registered (pl.death_timer >= 0, the engine's 12-frame death window,
    player.c:1020): a bomb during the window cancels the death (total cost 2
    bombs, player.c:685-692). It only fires after the hit already happened —
    it cannot change what Laya chose to do. (b) Laya's macro bomb fires
    IMMEDIATELY (age <= 10 f) or when the best candidate's cost >= ~1.0 —
    bomb_now is a NOW decision, not a "safe/early" one — at most once per
    macro.
"""

from __future__ import annotations

import collections
import math

from taisei_sim import (
    ACTION_FOCUS, ACTION_SHOT, ACTION_BOMB,
    ACTION_UP, ACTION_DOWN, ACTION_LEFT, ACTION_RIGHT,
    PROJ_ENEMY,
)
from macros import (MacroTarget, PX_MIN, PX_MAX, PY_MIN, PY_MAX,
                    GUARD_Y, GUARD_X_MIN, GUARD_X_MAX)

ACTIVE_HAZARD = 1 << 4

# NOTE (2026-09-25): an executor-level "item assist" (curve toward valuable
# items near the path) was tried and REMOVED: even a tiny bias (beta 0.15,
# radius 60 px) flipped stage 3 Easy from WON/1 death to LOST/3 deaths — the
# evader's trajectory is critically sensitive in dense boss patterns. Item
# pickup is owned by Laya's item_sweep macro (macros.ITEM_CHASE_WEIGHT) and
# happens passively when items drift through the guard zone.

PLAYER_RADIUS = 4.0
THREAT_HORIZON = 36            # frames (0.60 s) — measured v6 sweep: best Stage 5
                                # Easy control (1 death/4 bombs); 48/60 regressed
# R4.7 (2026-09-26): adaptive gap horizon (opt-in, --gap-horizon).
# The t=36 snapshot term is a single future snapshot: in a dense fast swarm
# (G2 S2: 339-397 bullets, speed 2.5-3.0) every position is covered at
# t+36, so the term is a constant and the argmin is decided by the current
# field — the temporal gap (a gap passes each column at some t) is invisible
# and the wall-row gap-track fails (3 S2 deaths at y=544). When the snapshot
# cost is >= GAP_HORIZON_SNAP_AT (position covered at t+36), also look at
# min risk over GAP_HORIZON_TTS and keep the min (the gap that will pass).
# When the snapshot is cheaper, keep it unchanged (in sparse rain the gap
# min is uniformly low and non-discriminating — it must not fire; measured
# with tools/probe_evader.py: V1-style always-min broke G1.5 S1 0 -> 2
# deaths, VA4 kept S1 0 / S2 3 -> 0).
GAP_HORIZON_TTS = (8, 16, 24, 32, 40, 48)
GAP_HORIZON_SNAP_AT = 4.0
# R4.8 (2026-09-26): escape commit (opt-in, --escape-commit).
# A tracking convergence storm (G2.91 m3cam-0926-163143 S1 f12297: 96
# bullets, speed 2.5, radius 12, re-aimed at the player's CURRENT position
# with a 14-40 frame lag) puts a kill disk of ~16 px radius around the aim
# point. A single 6.25 px frame step cannot exit the disk, and the per-frame
# argmin oscillates (hold/diagonal mix — measured: 3 holds in 6 frames), so
# the player stalls at the aim point and dies. While the cheapest heading is
# in severe danger (min cost >= ESCAPE_COMMIT_AT), pin the choice to the
# cheapest FULL-DISPLACEMENT heading (wall-clamped headings excluded — they
# would pin the player at the wall where the storm re-aims) for
# ESCAPE_COMMIT_FRAMES frames — a straight-line escape long enough to clear
# the disk radius. Re-armed on every severe frame; decays when the danger
# clears. No-op in sparse states.
ESCAPE_COMMIT_AT = 40.0
ESCAPE_COMMIT_FRAMES = 4
# R7c (2026-09-27): committed-path escape. The R4.8 commit picks the
# cheapest FULL-DISPLACEMENT heading by the MYOPIC current cost (2-frame
# lookahead), so in a dense field it commits to a heading that looks cheap
# now but runs into bullets 10 frames later.  When COMMIT_PATH_WEIGHT > 0
# the commit instead picks the heading with the lowest CUMULATIVE risk over
# COMMIT_PATH_FRAMES frames (the safest straight-line path through the
# dense field) and follows it for ESCAPE_COMMIT_FRAMES frames.  Opt-in via
# --commit + the probe's --commit-path flag; 0 = the R4.8 behavior.
COMMIT_PATH_WEIGHT = 0.0
COMMIT_PATH_FRAMES = 40
G_SIGMA = 6.0
G_RANGE = 56.0                 # px — v2: wider danger perception
C2_WEIGHT = 0.20               # v3: weight of the 2-frame-ahead risk term
# intent weight per target kind (evasion first; near-miss risk is accepted to
# make progress, but the overlap penalty is large enough that nothing overrides
# an actual hit). hold stays lazy; point/band push through light pressure.
BETA_BY_KIND = {"hold": 0.25, "point": 0.8, "below_boss": 0.8, "band_x": 0.8,
                "orbit": 0.6, "item": 0.6}
EPS_SAFE = 0.05                # hysteresis: safe-enough threshold
HYSTERESIS_NUDGE = 0.02        # tie-break bonus for keeping the current direction
BOSS_RADIUS = 32.0
R_SCAN = 150.0                 # hazard pre-filter radius (px) — v2: wider scan
R_SCAN2 = R_SCAN * R_SCAN

# v5 (2026-09-25): laser + wall + bomb constants (ground truth in
# doc/research-video-fidelity-source-of-truth.md §7)
LASER_DISCONTINUITY = 1 << 0   # TAISEI_SIM_LASER_POINT_FLAG_DISCONTINUITY (taisei_sim.h:101)
LASER_BREAK_GAP = 14.0         # px — break the beam polyline beyond this gap
                               # (snapshot step = 8 px, sim.c:965)
LASER_CROSS_PENALTY = 4.0      # cost per centerline crossing (motion-kill, laser.c:571-574)
WALL_DIST = 40.0               # px — wall-proximity band
WALL_K = 0.5                   # wall cost at the wall (quadratic falloff to 0)
BOMB_NOW_COST = 1.0            # fire a macro bomb when the best candidate costs >= this
EDGE_ESCAPE_PENALTY = 1000.0   # opt-in no-bomb emergency: leave a hard wall
# R4.5 (2026-09-26): replaces the R4.3 positional ramp with a THREAT-GATED
# step. The positional penalty (step or ramp) destroys the edge-row survival
# resource: in a full-screen downward rain the bottom edge row is the safe
# position (only the bottom row can overlap the player; the evader gap-
# tracks it), and any positional penalty drags the player into the dense
# rows (G2.5 band-top floor y=504-509; G2.8 mid-band sink death at
# y=529). The penalty now applies ONLY when the player is pinned-in-danger:
# in the 40 px wall band, a hazard will overlap the player's CURRENT
# position within EDGE_GATE_TTH frames, and the cheapest base heading is
# toward the wall (gap tracking has failed / the edge row is covered).
# Purely lateral headings are never penalized — they are the gap-track
# escape (the old step's dy>=0 rule penalized left/right at the bottom and
# pushed the player straight up into the densest rows).
EDGE_GATE_TTH = 12.0           # frames — threat window for the wall penalty

# R7b (2026-09-27): per-wall bullet danger (opt-in `--wall-danger`). The
# wall pin is the dominant residual death class across S3/S4/S5/S6: the
# cost model treats off-screen as safe (WALL_K is only 0.5 vs bullet cost
# 200-774), so when in danger the player runs to the nearest wall and dies
# there, because the KILLING BULLETS ARE AT THE WALL.  The R4.5 gate is
# threat-gated (EDGE_GATE_TTH=12 f) and fires too late.  This term fires
# EARLIER: whenever the player is in the 40 px wall band AND there are
# bullets in that band (near the wall, near the player), it penalizes the
# heading that moves TOWARD that wall (so the player is pushed out of the
# band into the open field before it is pinned).  Off by default; per-wall
# so a safe wall (no bullets) is still usable for gap tracking.
WALL_DANGER_COUNT = 5.0        # bullets in the band to arm the wall danger
WALL_DANGER_R = 70.0           # px — radius around the player to count bullets
WALL_DANGER_DIST = 80.0        # px — band width (fires EARLIER than the
                               # 40 px WALL_DIST so the player is pushed out
                               # before it is pinned, not after)
WALL_DANGER_K = 400.0          # cost added to the toward-wall heading
                               # (must dominate the bullet cost 200-774 to
                               # override the off-screen-is-safe pull)

# R5.2 (2026-09-26, refined 2026-09-27): converging-laser-ring escape
# (opt-in `--laser-ring`).  S5 lasertrap (stage5/timeline.c:718), Medium
# (traptime=160, boomdelay=30):
#   preradius = 120 + 160*4 = 760, centered on the player at spawn
#   (cwclamp(global.plr.pos) — verified against the sim: L.origin equals
#   the player position at spawn exactly, sim.c:519), 5 arcs x 72 deg,
#   width 18, shrink 4 px/frame while NON-collidable (laser_charge
#   charge_delay=160 -> collision_active from t=161 at r=116, kill radius
#   2; full width 18 at t=170, kill radius 5; beam fades to inactive at
#   t=199, deleted at t=210).  The lethal band sweeps d=116 -> 0 (r=0 at
#   t=190) — its MAX outer edge is 118 (t=161).  5 pp_souls (kill radius
#   36) track the arc start points from t=0 to t=190.  The 8 x 28 pp_balls
#   (kill radius 12.6) spawn at BOOMTIME t=190, NOT t=0: common_charge
#   (common_tasks.c:142) YIELDs one frame at a time for boomtime frames
#   and BLOCKS the lasertrap task body before the ball loop.  The balls
#   spiral outward (move_asymptotic(6*aim, -2*aim*perp, 2^-1/30)) and form
#   a thick cage band that sweeps outward (reaching d ~ 136 at t ~ 225) —
#   the normal cost model sees them as ordinary moving hazards (R_SCAN)
#   and dodges the gaps.
# => the player must be at d >= 121 by t=161 and STAY there while the beam
# is active (t=161-199).  Detection fires at t ~ 131-143 (two arcs
# on-screen with >= 4 points + 3 frames of rate history); from d ~ 25 the
# player reaches RING_SAFE_R = 136 in ~18 frames (t ~ 153-161).  HOLD:
# once on the circle the override does NOT release — the guard anchor
# (~22 px from the trap center) would walk the player back through the
# collapsing band / into the t=190 ball spawn (measured: probe deaths
# f5547/f5555 at d ~ 49-90 from center, pulled in after release).  The
# player keeps walking along the circle (nearest point >= 8 px away,
# re-aimed per frame, walls + large hazards skipped) until the beam is
# inactive (last detection + RING_ACTIVE_FRAMES ~ t=204 > t=199); the
# cage (t=190+) is then handled by the cost model.
# A stationary player dies to every trap. The detector groups snapshot
# beams by their circle origin (las_circle lasers report the center as
# L.origin, sim.c:519); the snapshot only contains ON-SCREEN points
# (quantize culls off-screen segments, laser.c:262-267), so the ring
# first becomes visible at r ~ 454 (t ~ 77) with two arcs — the detector
# needs >= 2 same-origin shrinking beams near the player, not full
# coverage. All arcs of one ring share the SAME radius r(t)
# (RING_RADIUS_SPREAD ~ 0), which rejects unrelated same-origin beam
# pairs with DIFFERENT radii; the measured f3769 false positive
# (m3cam-0926-185159: two beams, both med r ~ 248) has equal radii but
# shrinks at only 2.1 px/f, so RING_SHRINK_RATE = 3.0 (trap: exactly
# 4 px/f) is the second discriminator.
#
# Escape = walk to the nearest reachable point on the safe circle
# (RING_SAFE_R around the trap center) that lies inside the largest
# angular gap and not inside a large hazard (the pp_soul r=36 discs cross
# the circle at t ~ 145-167 — aim for a gap between them).  Target-point
# selection (instead of a pure direction) is what keeps the player off
# the walls: a "through the gap" direction aimed at the gap center ran
# the probe player into the bottom wall at f5428 (S5) and left them
# pinned at r ~ 56 inside the lethal sweep.
RING_ORIGIN_TOL = 10.0        # px — beams group when origins are this close
RING_PLAYER_TOL = 350.0       # px — group origin must be this near the player
RING_MIN_BEAMS = 2            # beams in the group (on-screen arcs)
RING_MIN_RADIUS = 40.0        # px — ignore groups that are already tiny
RING_MAX_RADIUS = 760.0       # px — the lasertrap spawn radius
RING_SHRINK_RATE = 3.0        # px/frame — required group shrink speed (trap: 4.0)
RING_RADIUS_SPREAD = 0.10     # max per-beam radius deviation from group median
RING_HISTORY = 16             # frames of per-beam radius history
RING_SAFE_R = 136.0           # px — hold radius (band max outer edge 118 + margin;
                              #      hold floor ~ SAFE_R - 10 >= 121)
RING_DANGER_R = 185.0         # px — escape override only while closer than this
RING_ACTIVE_FRAMES = 24       # ring escape stays hot this long after last detection
RING_SEAL_DEG = 330.0         # coverage above this: no gap — run for the safe circle
RING_HAZ_TOL = 14.0           # px — skip target points this close to a large hazard
# Target-point wall clearance: candidates closer than RING_WALL_MARGIN to a
# wall are penalized (score += RING_WALL_W * (MARGIN - clearance)), so a
# corner trap center (safe circle mostly clipped by the walls) sends the
# player to the open part of the circle instead of back to the corner
# (probe s5-ring, 2026-09-27: six corner deaths at (464, 544)).
RING_WALL_MARGIN = 24.0       # px from a wall where the penalty starts
RING_WALL_W = 2.0             # penalty weight (px of equivalent distance)

# R7 (2026-09-27): dense-wall "stay up" bias (opt-in `--dense-wall`). The
# per-frame argmin + 8-48 f gap horizon (VA4) wiggles INSIDE a dense bullet
# mass and dies: the S3 f~5300 gauntlet (three swarm waves 576->639->721
# bullets, r12, speed 2-4.7, a thick bottom-third wall) kills EVERY variant
# (matrix 2026-09-27: base 5 / blind 4 / ring 4 / wall 7 / gate 7). The
# fix is to detect a dense bullet band at the bottom edge (UNFILTERED — the
# R_SCAN=150 hazard list is empty when the player is safely up top, which is
# exactly when we need the bias) and penalize downward headings so the
# argmin keeps the player in the open top third while the wave sweeps the
# bottom. The penalty is on the downward component only (no upward bonus),
# so the player drifts up and can then gap-track laterally along the top
# instead of pinning to the top wall. Off by default.
DENSE_BAND = 220.0            # px from the bottom edge to scan (the bottom third)
DENSE_THRESHOLD = 80.0        # bullets in the band to ARM the dense wall (armed
                              # while the wave is APPROACHING, before it peaks,
                              # so the player reaches the safe zone early)
DENSE_PERSIST = 10            # consecutive frames >= threshold before arming
DENSE_RELEASE = 30.0          # bullets below which the dense wall may disarm
DENSE_RELEASE_PERSIST = 90    # consecutive frames < release before disarming
                              # (spans the ~370-560 f gaps between gauntlet waves)
# The bias is TWO-SIDED (2026-09-27, probe S3): a one-sided "push up" bias
# (penalize downward only) drove the player to the TOP edge, where it pinned
# and died (f5785 y=16, f9587 top-right corner — 9 deaths vs 4 baseline).
# The top is not safe. The safe zone is the open middle-top: push UP while
# below DENSE_SAFE_Y (in the gauntlet) and push DOWN while above
# DENSE_TOP_Y (at the top edge), so the player converges to the open band
# between them and gap-tracks there.
DENSE_SAFE_Y = 300.0          # push up while py > this (inside the gauntlet)
DENSE_TOP_Y = 60.0            # push down while py < this (at the top edge)
DENSE_DOWN_PENALTY = 60.0     # cost added per unit toward-wall dy while armed

# Dodge-first correction (2026-09-25; doc/research-dodge-improvement-plan.md):
# look a few frames farther along each already-allowed heading.  This is a
# short fixed rollout, not a second planner or a cross-macro override.
DODGE_ROLLOUT_FRAMES = 8
# The Lunatic Laya A/B did not meet acceptance; keep both experimental
# adjustments disabled by default until an isolated controlled comparison.
DODGE_ROLLOUT_WEIGHT = 0.0
DANGER_INTENT_FACTOR = 1.0
# R3 (2026-09-26): opt-in no-bomb danger valve (doc/plan-lunatic-no-bomb.md).
# When enabled it ONLY relaxes the guard-anchor pull (beta): (a) the
# local-severe branch uses NOBOMB_DANGER_INTENT_FACTOR instead of the no-op
# DANGER_INTENT_FACTOR; (b) when Laya itself rates danger >= LAYA_DANGER_VALVE_AT
# on a guard/hold macro, beta is halved so the executor can leave the anchor
# before the local candidates collapse. It never chooses a direction — the
# min-cost heading still wins outright — and it is off by default.
NOBOMB_DANGER_INTENT_FACTOR = 0.5
LAYA_DANGER_VALVE_AT = 1.4
LAYA_DANGER_VALVE = 0.5
# Phase 11 (2026-09-26): opt-in intermediate fixed-heading path risk. This is
# deliberately separate from the rejected/default-disabled rollout weight: it
# samples the existing candidate path and uses the existing hazard model, but
# has no effect unless explicitly enabled by a diagnostic.
PATH_RISK_FRAMES = 12
PATH_RISK_WEIGHT = 0.0

# R6.1 (2026-09-26, refined 2026-09-27): wall commit (opt-in
# `--wall-commit`). Inside a wall — in the 40 px wall band AND every
# heading already pays >= WALL_COMMIT_AT (the per-frame argmin is pinned
# to noise: measured death-frame costs 200-700 across all 9 headings) —
# the per-frame wiggle never commits to a crossing, so the player dies in
# place.  When that state persists (WALL_COMMIT_PERSIST frames), lock the
# eligible heading (see WALL_COMMIT_END_CAP) with the lowest MAX-over-path
# risk (WALL_COMMIT_PATH frames of straight-line rollout) for
# WALL_COMMIT_FRAMES: walk the thinnest part of the wall.  R4.8 (per-frame
# cheapest) and R4.9 (steer bias) both failed for lack of a real path
# objective; this is that objective, triggered only in walls.
WALL_COMMIT_AT = 60.0         # min base cost over all 9 headings => in the wall
WALL_COMMIT_PERSIST = 6       # consecutive wall frames before committing
WALL_COMMIT_FRAMES = 24       # locked-heading duration (~150 px at full speed)
WALL_COMMIT_PATH = 36         # rollout length for the max-over-path score
# Lock eligibility (2026-09-27, probe S5 f653): the wall class is a THIN
# band at the edge — a 36-frame straight line must LEAVE the danger (the
# path endpoint stays below WALL_COMMIT_END_CAP).  In a uniform dense
# field (S5 opening) every endpoint is still deep in danger, so no
# heading qualifies and the per-frame wiggle stays in control (it got
# the probe player to f1409 vs f653 under a blind lock).
WALL_COMMIT_END_CAP = 8.0     # max endpoint (frame-36) risk to lock a heading
# Secondary escape valve: release the lock if the locked heading's actual
# per-frame cost runs this far above the best wiggle (a bullet crossed
# into the committed path — the projection was wrong).  Resetting
# _wall_frames costs 6 frames of re-persistence — a natural cooldown.
WALL_COMMIT_BREAK_MARGIN = 100.0

# (unit displacement per frame, buttons)
MOVES = [
    ((0.0, 0.0), 0),
    ((0.0, -1.0), ACTION_UP),
    ((0.0, 1.0), ACTION_DOWN),
    ((-1.0, 0.0), ACTION_LEFT),
    ((1.0, 0.0), ACTION_RIGHT),
    ((-0.7071, -0.7071), ACTION_UP | ACTION_LEFT),
    ((0.7071, -0.7071), ACTION_UP | ACTION_RIGHT),
    ((-0.7071, 0.7071), ACTION_DOWN | ACTION_LEFT),
    ((0.7071, 0.7071), ACTION_DOWN | ACTION_RIGHT),
]


class ReflexExecutor:
    def __init__(self, speed_full: float = 6.25, speed_focus: float = 2.75,
                 player_radius: float = PLAYER_RADIUS,
                 allow_bombs: bool = True, allow_edge_escape: bool = False,
                 danger_valve: bool = False, gap_horizon: bool = False,
                 escape_commit: bool = False,
                 escape_commit_policy: str = "full",
                 laser_blind_fix: bool = False, laser_ring: bool = False,
                 wall_commit: bool = False,
                 dense_wall: bool = False, wall_danger: bool = False):
        self.speed_full = speed_full
        self.speed_focus = speed_focus
        self.player_radius = player_radius
        self.allow_bombs = allow_bombs
        self.allow_edge_escape = allow_edge_escape
        self.danger_valve = danger_valve
        self.gap_horizon = gap_horizon
        self.escape_commit = escape_commit
        self.laser_blind_fix = laser_blind_fix
        self.laser_ring = laser_ring
        self.wall_commit = wall_commit
        self.dense_wall = dense_wall
        self.wall_danger = wall_danger
        # R4.8 policy: "full" = cheapest full-displacement heading;
        # "lateral_band" = in the top/bottom band prefer pure lateral
        # (gap-track ALONG the wall — the measured survivor behavior) over
        # up/down/oblique escapes.
        self.escape_commit_policy = escape_commit_policy
        self.last_move_idx = 0
        self.last_cost = None
        self.last_costs = None
        self.last_buttons = ACTION_SHOT
        self._bomb_macro_id = -1
        self._bomb_fired = False
        self._escape_commit_left = 0
        self._escape_heading = 0
        # R5.2 ring-escape state
        self._ring_hist = {}            # spawn_id -> deque[(frame, radius)]
        self._ring_last_seen = -10 ** 9
        self._ring_center = None        # (x, y) trap center (group centroid)
        self._ring_gap = None           # empty gap bins (None = sealed/any)
        self._ring_frame = -10 ** 9     # frame of the last detection
        # R6.1 wall-commit state
        self._wall_frames = 0           # consecutive in-wall frames
        self._wall_commit_left = 0
        self._wall_heading = 0
        # R7 dense-wall state
        self._dense_frames = 0          # consecutive frames >= DENSE_THRESHOLD
        self._dense_release = 0         # consecutive frames < DENSE_RELEASE
        self._dense_armed = False       # armed until DENSE_RELEASE_PERSIST quiet

    def reset(self):
        self.last_move_idx = 0
        self.last_cost = None
        self.last_costs = None
        self.last_buttons = ACTION_SHOT
        self._bomb_macro_id = -1
        self._bomb_fired = False
        self._escape_commit_left = 0
        self._escape_heading = 0
        self._ring_hist = {}
        self._ring_last_seen = -10 ** 9
        self._ring_center = None
        self._ring_gap = None
        self._ring_frame = -10 ** 9
        self._wall_frames = 0
        self._wall_commit_left = 0
        self._wall_heading = 0
        self._dense_frames = 0
        self._dense_release = 0
        self._dense_armed = False

    # -- hazards ----------------------------------------------------------------
    def _collect_hazards(self, v, px: float, py: float, bomb_active: bool):
        """Return (hazards, segs_now, segs_full). Bomb wave clears hazards.

        hazards: list of (x, y, vx, vy, r, w) — bullets / enemies / boss.
        segs_*:  laser polyline segments (x1, y1, r1, x2, y2, r2, w) built
                 from ALL snapshot points of each collision-active beam
                 (v5, 2026-09-25; ground truth: laser.c:571-586).
                 segs_now  = the DRAWN beam (pt.time <= 0 both ends) — what
                             can kill this frame (capsule + motion crossing).
                 segs_full = drawn beam + growth within the threat horizon.
        """
        hazards = []
        segs_now: list = []
        segs_full: list = []
        if not bomb_active:
            for p in v.projectiles:
                if p.category != PROJ_ENEMY or not (p.flags & ACTIVE_HAZARD):
                    continue
                dx = p.position.x - px
                dy = p.position.y - py
                if dx * dx + dy * dy > R_SCAN2:
                    continue
                r = max(p.collision_size.x, p.collision_size.y)
                if r <= 0:
                    r = 3.0
                hazards.append((p.position.x, p.position.y,
                                p.velocity.x, p.velocity.y, r, 1.0))
            for e in v.enemies:
                if not e.harmful:
                    continue
                dx = e.position.x - px
                dy = e.position.y - py
                if dx * dx + dy * dy > R_SCAN2:
                    continue
                r = e.hit_radius if e.hit_radius > 0 else 12.0
                hazards.append((e.position.x, e.position.y,
                                e.velocity.x, e.velocity.y, r, 1.5))
            b = v.raw.boss
            if b.active and not b.invulnerable:
                hazards.append((float(b.position.x), float(b.position.y),
                                float(b.velocity.x), float(b.velocity.y),
                                BOSS_RADIUS, 1.5))
            lps = v.laser_points
            for L in v.lasers:
                if not L.collision_active:
                    continue
                # Laser-point `time` is NEGATED laser time (laser.c:270):
                # the engine stores .time = {-t0, -t} for the drawn range,
                # whose laser-time values are >= 0 — so EVERY snapshot point
                # has time <= 0 (base ~ 0, tip most negative), and the trace
                # contains the drawn beam only (no future-growth points).
                # R5.1 (2026-09-26): the old t_max cap (min(36,
                # death_time + time_shift - age)) was built for growth that
                # does not exist in the trace; in the beam's retraction
                # window (age > death + shift, while laser.c:495 keeps the
                # beam alive and lethal until age > death + span*speed) it
                # went negative and dropped the whole beam (the S4/S6
                # blind-window deaths — research-laser-blind-window.md).
                # With the fix, keep every point of every collision-active
                # beam; bit-identical outside that window.
                if not self.laser_blind_fix:
                    if L.death_time > 0:
                        t_max = min(THREAT_HORIZON,
                                    L.death_time + L.time_shift
                                    - L.age_frames)
                    else:
                        t_max = THREAT_HORIZON
                    if t_max < 0:
                        continue
                end = min(L.first_point + L.point_count, len(lps))
                last = None  # (x, y, half_width, time)
                for i in range(L.first_point, end):
                    pt = lps[i]
                    # Break the polyline at discontinuities. A
                    # discontinuity point is itself the FIRST valid point
                    # of the new stroke; do not discard it (doing so hid
                    # beam origins/short segments in v5).
                    if (not self.laser_blind_fix and pt.time > t_max):
                        last = None
                        continue
                    x = float(pt.position.x)
                    y = float(pt.position.y)
                    hw = pt.half_width
                    if pt.flags & LASER_DISCONTINUITY:
                        last = (x, y, hw, pt.time)
                        continue
                    if last is not None:
                        dx = x - last[0]
                        dy = y - last[1]
                        if dx * dx + dy * dy <= LASER_BREAK_GAP * LASER_BREAK_GAP:
                            # engine collision radius = max(half_width - 4, 2)
                            # per segment endpoint (laser.c:578-579)
                            r1 = max(last[2] - 4.0, 2.0)
                            r2 = max(hw - 4.0, 2.0)
                            seg = (last[0], last[1], r1, x, y, r2, 1.0)
                            segs_full.append(seg)
                            if last[3] <= 0.0 and pt.time <= 0.0:
                                segs_now.append(seg)
                    last = (x, y, hw, pt.time)
        # pre-filter: only segments that can reach a candidate position
        maxd = R_SCAN + 60.0
        if segs_now or segs_full:
            def keep(segs):
                out = []
                for s in segs:
                    d, _ = self._pt_seg(px, py, s[0], s[1], s[3], s[4])
                    if d < maxd:
                        out.append(s)
                return out
            segs_now = keep(segs_now)
            segs_full = keep(segs_full)
        return hazards, segs_now, segs_full

    # -- risk -------------------------------------------------------------------
    @staticmethod
    def _risk_at(qx: float, qy: float, hazards, project: float, r_p: float) -> float:
        s = 0.0
        if project:
            for hx, hy, vx, vy, r, w in hazards:
                dx = qx - (hx + vx * project)
                dy = qy - (hy + vy * project)
                u = (dx * dx + dy * dy) ** 0.5 - r - r_p
                if u < 0:
                    s += w * (1.0 - 10.0 * u)
                elif u < G_RANGE:
                    s += w * math.exp(-u / G_SIGMA)
        else:
            for hx, hy, vx, vy, r, w in hazards:
                dx = qx - hx
                dy = qy - hy
                u = (dx * dx + dy * dy) ** 0.5 - r - r_p
                if u < 0:
                    s += w * (1.0 - 10.0 * u)
                elif u < G_RANGE:
                    s += w * math.exp(-u / G_SIGMA)
        return s

    @staticmethod
    def _swept_risk(px: float, py: float, qx: float, qy: float,
                    hazards, r_p: float) -> float:
        """Risk from a hazard crossing the player's movement segment.

        Taisei checks enemy projectiles with a relative-motion line segment
        (`projectile.c:359-383`), not only at the post-step endpoints. A fast
        bullet can therefore cross the player between two snapshots while
        both endpoint distances are safe. Model that same first-order sweep
        for the candidate frame; this is especially important in the dense
        Stage 5 opening at zero lives.
        """
        s = 0.0
        for hx, hy, vx, vy, r, w in hazards:
            # Relative vector player - hazard at the current and next frame.
            ax, ay = px - hx, py - hy
            bx, by = qx - (hx + vx), qy - (hy + vy)
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            if l2 > 1e-12:
                t = -(ax * dx + ay * dy) / l2
                t = max(0.0, min(1.0, t))
            else:
                t = 0.0
            rx, ry = ax + dx * t, ay + dy * t
            u = (rx * rx + ry * ry) ** 0.5 - r - r_p
            if u < 0:
                s += w * (1.0 - 10.0 * u)
            elif u < G_RANGE:
                s += w * math.exp(-u / G_SIGMA)
        return s

    # -- laser geometry (v5) ----------------------------------------------------
    @staticmethod
    def _pt_seg(qx: float, qy: float, ax: float, ay: float,
                bx: float, by: float):
        """(distance from q to segment ab, closest factor f in [0, 1])."""
        abx, aby = bx - ax, by - ay
        l2 = abx * abx + aby * aby
        if l2 < 1e-12:
            dx, dy = qx - ax, qy - ay
            return (dx * dx + dy * dy) ** 0.5, 0.0
        f = ((qx - ax) * abx + (qy - ay) * aby) / l2
        if f < 0.0:
            f = 0.0
        elif f > 1.0:
            f = 1.0
        dx = qx - (ax + abx * f)
        dy = qy - (ay + aby * f)
        return (dx * dx + dy * dy) ** 0.5, f

    @staticmethod
    def _seg_intersect(ax: float, ay: float, bx: float, by: float,
                       cx: float, cy: float, dx: float, dy: float) -> bool:
        """Strict segment-segment intersection (bounding-box precheck +
        orientation test)."""
        if (max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx) or
                max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by)):
            return False

        def orient(x1: float, y1: float, x2: float, y2: float,
                   x3: float, y3: float) -> float:
            return (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)

        o1 = orient(ax, ay, bx, by, cx, cy)
        o2 = orient(ax, ay, bx, by, dx, dy)
        o3 = orient(cx, cy, dx, dy, ax, ay)
        o4 = orient(cx, cy, dx, dy, bx, by)
        return o1 * o2 < 0 and o3 * o4 < 0

    def _laser_risk(self, qx: float, qy: float, segs, r_p: float) -> float:
        """Engine-faithful beam risk: point-to-uneven-capsule distance with
        the same g() as circular hazards (laser.c:576-586)."""
        s = 0.0
        for x1, y1, r1, x2, y2, r2, w in segs:
            d, f = self._pt_seg(qx, qy, x1, y1, x2, y2)
            u = d - (r1 + (r2 - r1) * f) - r_p
            if u < 0:
                s += w * (1.0 - 10.0 * u)
            elif u < G_RANGE:
                s += w * math.exp(-u / G_SIGMA)
        return s

    def _laser_cross(self, px: float, py: float, nx: float, ny: float,
                     segs) -> float:
        """Motion-crossing kill: the candidate's movement segment intersecting
        a beam centerline is a hit ("prevent phasing", laser.c:571-574)."""
        s = 0.0
        for x1, y1, _r1, x2, y2, _r2, w in segs:
            if self._seg_intersect(px, py, nx, ny, x1, y1, x2, y2):
                s += w * LASER_CROSS_PENALTY
        return s

    @staticmethod
    def _wall_cost(nx: float, ny: float) -> float:
        """Quadratic proximity cost near the playfield bounds (the v1.4.6 Easy
        campaign's stage-3 deaths were at the x=16/464 edges)."""
        d = min(nx - PX_MIN, PX_MAX - nx, ny - PY_MIN, PY_MAX - ny)
        if d >= WALL_DIST:
            return 0.0
        u = (WALL_DIST - d) / WALL_DIST
        return WALL_K * u * u

    @staticmethod
    def _clamp_position(nx: float, ny: float):
        """Clamp a candidate to the same playfield bounds as the sim."""
        return (max(PX_MIN, min(PX_MAX, nx)),
                max(PY_MIN, min(PY_MAX, ny)))

    def _candidate_cost(self, px: float, py: float, dx: float, dy: float,
                        speed: float, hazards, segs_now, segs_full) -> float:
        """Score one allowed heading, including the short dodge rollout.

        The first-frame terms are the v5 terms unchanged.  The additional
        rollout follows the same heading for a few frames and reuses the
        existing projectile, laser, and wall risk functions.  Projectile
        positions advance by the projected frame number; laser geometry is
        already represented by the existing drawn/full snapshot sets.
        """
        nx, ny = self._clamp_position(px + dx * speed, py + dy * speed)
        c_now = (self._risk_at(nx, ny, hazards, 0.0, self.player_radius)
                 + self._laser_risk(nx, ny, segs_now, self.player_radius)
                 + self._swept_risk(px, py, nx, ny, hazards,
                                    self.player_radius))
        c_snap = (self._risk_at(nx, ny, hazards, THREAT_HORIZON,
                                self.player_radius)
                  + self._laser_risk(nx, ny, segs_full, self.player_radius))
        if self.gap_horizon:
            # R4.7: adaptive gap horizon — see the GAP_HORIZON_* comments.
            c_min = None
            for t in GAP_HORIZON_TTS:
                c = (self._risk_at(nx, ny, hazards, float(t),
                                   self.player_radius)
                     + self._laser_risk(nx, ny, segs_full,
                                        self.player_radius))
                c_min = c if c_min is None else min(c_min, c)
            c_hor = (c_snap if c_snap < GAP_HORIZON_SNAP_AT
                     else min(c_snap, c_min))
        else:
            c_hor = c_snap

        # Existing v3 two-frame lookahead, retained as-is.
        nx2, ny2 = self._clamp_position(nx + dx * speed, ny + dy * speed)
        c_2 = (self._risk_at(nx2, ny2, hazards, 0.0, self.player_radius)
               + self._laser_risk(nx2, ny2, segs_now, self.player_radius))
        cost = (c_now + 0.5 * c_hor + C2_WEIGHT * c_2
                + self._wall_cost(nx, ny))

        # Motion-crossing is an engine-faithful first-frame kill check. Keep
        # it separate from the projected point risk so the existing laser
        # behavior is not weakened by the rollout.
        if dx != 0.0 or dy != 0.0:
            cost += self._laser_cross(px, py, nx, ny, segs_now)

        future = []
        for frame in range(2, DODGE_ROLLOUT_FRAMES + 1):
            qx, qy = self._clamp_position(px + dx * speed * frame,
                                          py + dy * speed * frame)
            future.append(
                self._risk_at(qx, qy, hazards, float(frame),
                              self.player_radius)
                + self._laser_risk(qx, qy, segs_full, self.player_radius)
                + self._wall_cost(qx, qy))
        if future:
            cost += DODGE_ROLLOUT_WEIGHT * (sum(future) / len(future))

        # Optional intermediate path check. Unlike the endpoint-only horizon
        # term, this catches a moving hazard crossing a fixed-heading path
        # before the horizon endpoint. Keep it disabled in normal gameplay;
        # Phase 11 enables it only through tools/diag_guard_stage.py.
        if PATH_RISK_WEIGHT > 0.0:
            path_risks = []
            for frame in range(1, PATH_RISK_FRAMES + 1):
                qx, qy = self._clamp_position(px + dx * speed * frame,
                                              py + dy * speed * frame)
                path_risks.append(
                    self._risk_at(qx, qy, hazards, float(frame),
                                  self.player_radius)
                    + self._laser_risk(qx, qy, segs_full,
                                       self.player_radius))
            if path_risks:
                cost += PATH_RISK_WEIGHT * max(path_risks)
        return cost

    def _wall_path_score(self, i: int, px: float, py: float, speed: float,
                         hazards, segs_full):
        """R6.1: (max risk, endpoint risk) along a straight-line rollout of
        WALL_COMMIT_PATH frames along heading i. Reuses the same
        hazard-projection + laser-capsule risk the candidate cost uses
        (projected bullet positions, segs_full), so the scores are
        comparable across headings.  The endpoint is the exit test (the
        line must LEAVE the danger); the max is the crossing test (the
        argmin over eligible headings is the thinnest part of the wall)."""
        dx, dy = MOVES[i][0]
        m = 0.0
        e = 0.0
        for frame in range(1, WALL_COMMIT_PATH + 1):
            qx, qy = self._clamp_position(px + dx * speed * frame,
                                          py + dy * speed * frame)
            c = (self._risk_at(qx, qy, hazards, float(frame),
                               self.player_radius)
                 + self._laser_risk(qx, qy, segs_full, self.player_radius))
            if c > m:
                m = c
            if frame == WALL_COMMIT_PATH:
                e = c
        return (m, e)

    def _path_risk(self, i: int, px: float, py: float, speed: float,
                   hazards, segs_full):
        """R7c: cumulative risk along a straight-line rollout of
        COMMIT_PATH_FRAMES frames along heading i (projected bullet
        positions + laser capsule, same model as the candidate cost).
        Lower = the safer straight-line path through the dense field."""
        dx, dy = MOVES[i][0]
        total = 0.0
        for frame in range(1, COMMIT_PATH_FRAMES + 1):
            qx, qy = self._clamp_position(px + dx * speed * frame,
                                          py + dy * speed * frame)
            total += (self._risk_at(qx, qy, hazards, float(frame),
                                    self.player_radius)
                      + self._laser_risk(qx, qy, segs_full,
                                         self.player_radius))
        return total

    def _escape_threat(self, px: float, py: float, hazards, segs_now) -> bool:
        """R4.5: True when a hazard will overlap the player's CURRENT
        position within EDGE_GATE_TTH frames, or a drawn laser beam already
        does. The local evader's 36-frame horizon normally escapes such
        threats; this window marks the imminent-pin case."""
        r_p = self.player_radius
        for x1, y1, r1, x2, y2, r2, w in segs_now:
            d, f = self._pt_seg(px, py, x1, y1, x2, y2)
            if d - (r1 + (r2 - r1) * f) - r_p <= 0.0:
                return True
        for hx, hy, vx, vy, r, w in hazards:
            rr = r + r_p
            dx, dy = hx - px, hy - py
            a = vx * vx + vy * vy
            if a < 1e-9:
                if dx * dx + dy * dy <= rr * rr:
                    return True
                continue
            b = 2.0 * (dx * vx + dy * vy)
            c = dx * dx + dy * dy - rr * rr
            if c <= 0.0:
                return True
            disc = b * b - 4.0 * a * c
            if disc < 0.0:
                continue
            t = (-b - disc ** 0.5) / (2.0 * a)
            if 0.0 <= t <= EDGE_GATE_TTH:
                return True
        return False

    @staticmethod
    def _toward_wall(px: float, py: float, dx: float, dy: float) -> bool:
        """R4.5: STRICT toward-wall for a heading at the player's position.
        Hold counts as toward every wall it is in (staying put does not
        escape); pure lateral motion is FREE (the gap-track escape); only
        motion into the wall (or hold) is penalized.
        """
        hold = (dx == 0.0 and dy == 0.0)
        if hold:
            return ((py >= PY_MAX - WALL_DIST or py <= PY_MIN + WALL_DIST)
                    or (px <= PX_MIN + WALL_DIST or px >= PX_MAX - WALL_DIST))
        if dy > 0.0 and py >= PY_MAX - WALL_DIST:
            return True
        if dy < 0.0 and py <= PY_MIN + WALL_DIST:
            return True
        if dx < 0.0 and px <= PX_MIN + WALL_DIST:
            return True
        if dx > 0.0 and px >= PX_MAX - WALL_DIST:
            return True
        return False

    def _pinned_gate(self, px: float, py: float, hazards, segs_now,
                     costs) -> bool:
        """R4.5: True when the wall penalty should apply this frame.

        Pinned-in-danger = in the 40 px wall band AND a hazard reaches the
        player's current position within EDGE_GATE_TTH frames AND the
        cheapest base heading is toward the wall (the cost landscape itself
        holds the player at the wall — gap tracking has failed). In a
        full-screen rain the cheapest heading at the edge is the lateral
        gap-track, so the gate stays OFF and the edge row remains usable.
        """
        in_band = ((py >= PY_MAX - WALL_DIST or py <= PY_MIN + WALL_DIST)
                   or (px <= PX_MIN + WALL_DIST or px >= PX_MAX - WALL_DIST))
        if not in_band:
            return False
        if not self._escape_threat(px, py, hazards, segs_now):
            return False
        i = min(range(len(MOVES)), key=lambda k: costs[k])
        dx, dy = MOVES[i][0]
        return self._toward_wall(px, py, dx, dy)

    # -- R5.2: converging laser ring ---------------------------------------------
    def _ring_state(self, v, px: float, py: float, frame: int):
        """R5.2: detect a laser ring converging on the player.

        Returns (detected, (cx, cy), gap_bins).  Snapshot beams are grouped
        by their origin (a las_circle laser reports its circle CENTER as
        L.origin, sim.c:519).  A group qualifies when >= RING_MIN_BEAMS
        beams share an origin (within RING_ORIGIN_TOL), the origin is
        within RING_PLAYER_TOL of the player, the per-beam on-screen radius
        (median distance origin -> point) is in [RING_MIN_RADIUS,
        RING_MAX_RADIUS], and the radii are shrinking at >=
        RING_SHRINK_RATE px/frame (per-beam history matched by the stable
        spawn_id).  The snapshot contains ON-SCREEN points only (the
        quantizer culls off-screen segments, laser.c:262-267), so the
        lasertrap ring first appears at r ~ 454 with two arcs — full 360
        coverage is never observable before the ring turns lethal.  All
        arcs of one ring share the same radius r(t) (RING_RADIUS_SPREAD),
        which rejects unrelated same-origin beam pairs.  The third return
        value is the escape gap: the empty 12° bins of the largest angular
        gap (trimmed by one bin per side), or None when the ring is
        (nearly) sealed — the safe circle is reachable in any direction.
        """
        lps = v.laser_points
        # per-beam: median on-screen radius + point angles around the origin
        beams = []
        for L in v.lasers:
            if L.point_count == 0:
                continue
            ox, oy = float(L.origin.x), float(L.origin.y)
            end = min(L.first_point + L.point_count, len(lps))
            step = max(1, L.point_count // 48)
            radii, angles = [], []
            for i in range(L.first_point, end, step):
                pt = lps[i]
                dx = float(pt.position.x) - ox
                dy = float(pt.position.y) - oy
                d2 = dx * dx + dy * dy
                if d2 < 1.0:
                    continue
                d = d2 ** 0.5
                if d > RING_MAX_RADIUS + 60.0:
                    continue
                radii.append(d)
                angles.append(math.degrees(math.atan2(dy, dx)) % 360.0)
            if len(radii) < 4:
                continue
            radii.sort()
            med = radii[len(radii) // 2]
            if not (RING_MIN_RADIUS <= med <= RING_MAX_RADIUS):
                continue
            beams.append((L.spawn_id, ox, oy, med, angles))
            hist = self._ring_hist.setdefault(
                L.spawn_id, collections.deque(maxlen=RING_HISTORY + 8))
            hist.append((frame, med))
        # prune dead beams
        for bid in [b for b, h in self._ring_hist.items()
                    if frame - h[-1][0] > RING_HISTORY + 8]:
            del self._ring_hist[bid]
        if not beams:
            return False, None, None
        # group by quantized origin
        groups = {}
        for bid, ox, oy, med, angles in beams:
            key = (int(round(ox / RING_ORIGIN_TOL)),
                   int(round(oy / RING_ORIGIN_TOL)))
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"ox": 0.0, "oy": 0.0, "n": 0,
                                   "meds": [], "angles": [], "rates": []}
            g["ox"] += ox
            g["oy"] += oy
            g["n"] += 1
            g["meds"].append(med)
            g["angles"].extend(angles)
            hist = self._ring_hist.get(bid)
            if hist and len(hist) >= 3:
                f0, r0 = hist[0]
                if frame - f0 >= 3:
                    g["rates"].append((r0 - med) / (frame - f0))
        best = None
        for g in groups.values():
            if g["n"] < RING_MIN_BEAMS:
                continue
            cx, cy = g["ox"] / g["n"], g["oy"] / g["n"]
            dx, dy = px - cx, py - cy
            if dx * dx + dy * dy > RING_PLAYER_TOL * RING_PLAYER_TOL:
                continue
            rates = sorted(g["rates"])
            med_rate = rates[len(rates) // 2] if rates else -99.0
            if med_rate < RING_SHRINK_RATE:
                continue
            meds = sorted(g["meds"])
            med = meds[len(meds) // 2]
            # all arcs of one ring share the same radius r(t); unrelated
            # same-origin beam pairs generally do not
            if max(med - meds[0], meds[-1] - med) > RING_RADIUS_SPREAD * med:
                continue
            g["cx"], g["cy"] = cx, cy
            if best is None or g["n"] > best["n"]:
                best = g
        dbg = getattr(self, "_ring_debug_frames", None)
        if dbg is not None and dbg[0] <= frame <= dbg[1]:
            ginfo = []
            for g in groups.values():
                ginfo.append("n=%d med=%.0f rate=%s" % (
                    g["n"],
                    sorted(g["meds"])[len(g["meds"]) // 2] if g["meds"] else 0,
                    ("%.1f" % sorted(g["rates"])[len(g["rates"]) // 2])
                    if g["rates"] else "-"))
            binfo = ["%d:(%.0f,%.0f) r=%.0f" % (bid, ox, oy, med)
                     for bid, ox, oy, med, _ang in beams]
            pl_dbg = v.raw.player
            cstr = ("(%.0f, %.0f)" % (best["cx"], best["cy"])
                    if best else "-")
            print("   [ring] f=%d pos=(%.1f, %.1f) invuln=%s alive=%s "
                  "beams=%d groups=%s best=%s center=%s last_seen=%d" %
                  (frame, px, py, pl_dbg.invulnerable, pl_dbg.alive,
                   len(beams), ginfo or "-",
                   "n=%d med=%.0f" % (
                       best["n"],
                       sorted(best["meds"])[len(best["meds"]) // 2])
                   if best else "-", cstr, self._ring_last_seen))
            print("   [ring]   beams=%s" % binfo)
        if best is None:
            return False, None, None
        # escape target: the empty bins of the largest angular gap, trimmed
        # by one bin (12 deg) on each side for arc margin.  None = the ring
        # is (nearly) sealed — the safe circle is reachable in any direction.
        bins = [False] * 30
        for a in best["angles"]:
            bins[int(a // 12.0) % 30] = True
        covered = sum(bins)
        gap_bins = None
        if not (covered >= 30 or covered * 12.0 >= RING_SEAL_DEG):
            doubled = bins + bins
            best_run, best_start, run, start = 0, 0, 0, -1
            for i in range(60):
                if not doubled[i]:
                    if run == 0:
                        start = i
                    run += 1
                    if run > best_run:
                        best_run, best_start = run, start
                else:
                    run = 0
            gap_bins = [(best_start + k) % 30
                        for k in range(1, best_run - 1)]
            if not gap_bins:
                gap_bins = None
        return True, (best["cx"], best["cy"]), gap_bins

    def _ring_target_dir(self, px: float, py: float, cx: float, cy: float,
                         safe_r: float, gap_bins, hazards=None,
                         hold: bool = False):
        """Unit vector toward the nearest reachable point on the circle of
        radius safe_r around the trap center, preferring angles inside the
        given empty gap bins (None/empty = any angle).  Points that would
        land in the wall are skipped, so a walled-off gap automatically
        falls through to a lateral direction.  Points inside
        (hazard_r + RING_HAZ_TOL) of a large hazard (r >= 20: the trap
        souls, r = 36) are skipped too, so the player aims for a gap
        BETWEEN the souls.

        hold=True (the lethal window): never release while standing on the
        circle — the guard anchor would pull the player back through the
        collapsing band.  Instead of returning None at best[0] < 8, keep
        walking to the nearest point >= 8 px away (along the circle); the
        per-frame re-aim corrects the 8-way heading drift and pins d near
        safe_r.  Falls back to radial outward if no candidate remains."""
        dxc, dyc = px - cx, py - cy
        d = (dxc * dxc + dyc * dyc) ** 0.5
        if d >= safe_r + 24.0:
            return None

        big_haz = ([(hx, hy, r) for hx, hy, _vx, _vy, r, _w in hazards
                    if r >= 20.0] if hazards else [])

        def _scan(ks, min_dist: float = 0.0):
            best = None
            for k in ks:
                a = math.radians(k * 12.0 + 6.0)
                x = cx + safe_r * math.cos(a)
                y = cy + safe_r * math.sin(a)
                if (x < PX_MIN + 4 or x > PX_MAX - 4
                        or y < PY_MIN + 4 or y > PY_MAX - 4):
                    continue
                if big_haz:
                    far = True
                    for hx, hy, hr in big_haz:
                        tol = hr + RING_HAZ_TOL
                        if (x - hx) * (x - hx) + (y - hy) * (y - hy) < tol * tol:
                            far = False
                            break
                    if not far:
                        continue
                dist = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
                if dist < min_dist:
                    continue
                # Wall clearance (2026-09-27, probe s5-ring): trap centers
                # sit at the player's position, so a trap near a wall or
                # corner has most of the safe circle clipped — the nearest
                # point lands back at the wall and the player pins to the
                # corner and dies repeatedly (six deaths at (464, 544)).
                # Penalize candidates near a wall so the target lands in
                # the open part of the circle.
                clear = min(x - (PX_MIN + 4.0), (PX_MAX - 4.0) - x,
                            y - (PY_MIN + 4.0), (PY_MAX - 4.0) - y)
                # R5.2 iter 5 (2026-09-27, probe s5-ring corner pin): the
                # NEAREST point on the circle dominated the score, so a trap
                # centered near a corner (safe circle mostly clipped by the
                # walls) sent the player back to the corner and it pinned at
                # (464, 544), dying repeatedly.  Prefer the OPEN-FIELD point
                # (max wall clearance) over the nearest point: score =
                # dist - RING_WALL_W * clear, so the open part of the circle
                # wins even when it is farther.  The souls skip (big_haz)
                # still keeps the target between the radius-36 discs.
                score = dist - RING_WALL_W * clear
                if best is None or score < best[0]:
                    best = (score, x, y)
            return best

        cand = gap_bins if gap_bins else None
        ks = cand if cand is not None else range(30)
        best = _scan(ks)
        if best is None and cand is not None:
            ks = range(30)
            best = _scan(ks)              # corner case: no gap point reachable
        if best is None:
            if hold and d > 4.0:
                return (dxc / d, dyc / d)  # last resort: radial outward
            return None
        if best[0] < 8.0:
            if not hold:
                return None
            best = _scan(ks, min_dist=8.0)
            if best is None:
                if d > 4.0:
                    return (dxc / d, dyc / d)
                return None
        dx, dy = best[1] - px, best[2] - py
        L = (dx * dx + dy * dy) ** 0.5
        return (dx / L, dy / L)

    # -- macro intent -----------------------------------------------------------
    def _resolve_point(self, target: MacroTarget, v, px: float, py: float):
        """Current anchor for point/item/below_boss targets (per frame)."""
        if target.kind == "item":
            for it in v.items:
                if it.spawn_id == target.item_spawn:
                    return float(it.position.x), float(it.position.y)
            return px, py                    # item gone -> hold in place
        if target.kind == "below_boss":
            b = v.raw.boss
            x = (max(GUARD_X_MIN, min(GUARD_X_MAX, float(b.position.x)))
                 if b.active else 240.0)
            return x, GUARD_Y
        if target.kind == "point" and target.point is not None:
            # re-anchor moving targets (boss) — `advance` keeps chasing the boss
            b = v.raw.boss
            if target.boss_anchored and b.active:
                return float(b.position.x), float(b.position.y)
            return target.point
        return px, py

    def _intent(self, target: MacroTarget, v, px: float, py: float,
                nx: float, ny: float) -> float:
        kind = target.kind
        if kind == "hold":
            return 1.0 if (nx, ny) == (px, py) else 0.25
        if kind in ("point", "item", "below_boss"):
            tx, ty = self._resolve_point(target, v, px, py)
            dx, dy = tx - px, ty - py
            D = (dx * dx + dy * dy) ** 0.5
            if D < 24:
                return 1.0
            cdx, cdy = nx - px, ny - py
            C = (cdx * cdx + cdy * cdy) ** 0.5
            if C < 1e-6:
                return 0.2
            return max(0.0, min(1.0, (cdx * dx + cdy * dy) / (C * D)))
        if kind == "band_x":
            x0, x1, y0, y1 = target.band
            dxs = max(x0 - nx, 0.0, nx - x1)
            dys = max(y0 - ny, 0.0, ny - y1)
            d = (dxs * dxs + dys * dys) ** 0.5
            return 1.0 if d < 8 else max(0.0, 1.0 - d / 120.0)
        if kind == "orbit":
            cx, cy = target.center
            rx, ry = px - cx, py - cy
            D = (rx * rx + ry * ry) ** 0.5
            if D < 1e-6:
                tx, ty = (0.0, 1.0) if target.sign > 0 else (0.0, -1.0)
                dx, dy = 0.0, 0.0
            else:
                ux, uy = rx / D, ry / D
                # screen coords (+y down): visual CCW tangent of u is (uy, -ux)
                if target.sign < 0:
                    tx, ty = uy, -ux
                else:
                    tx, ty = -uy, ux
                dr = D - target.radius          # >0: pull inward
                if dr > 0:
                    dx, dy = -ux, -uy
                elif dr < 0:
                    dx, dy = ux, uy
                else:
                    dx, dy = 0.0, 0.0
            mag = (0.7 * tx + 0.3 * dx) ** 2 + (0.7 * ty + 0.3 * dy) ** 2
            if mag < 1e-9:
                return 0.2
            mag = mag ** 0.5
            cdx, cdy = nx - px, ny - py
            C = (cdx * cdx + cdy * cdy) ** 0.5
            if C < 1e-6:
                return 0.2
            return max(0.0, min(1.0, (0.7 * tx + 0.3 * dx) * cdx / mag / C
                                + (0.7 * ty + 0.3 * dy) * cdy / mag / C))
        return 0.5

    # -- main entry -------------------------------------------------------------
    def execute(self, macro, v) -> int:
        """Frame-exact buttons for the current frame, biased by the macro."""
        pl = v.raw.player
        buttons = ACTION_SHOT                     # Marisa A: fixed upward fire
        if not pl.alive:
            self.last_move_idx = 0
            self.last_costs = None
            # v5: the hit-time death-bomb net must fire HERE, not in the main
            # path — player_is_alive() is false DURING the 12-frame death
            # window (deathtime >= 0), which is exactly when a bomb cancels
            # the death (player.c:685-692). While respawn is pending the
            # engine rejects the bomb (frames < respawntime, player_can_bomb),
            # so pressing it there is a harmless no-op.
            if (self.allow_bombs and pl.death_timer >= 0 and pl.bombs > 0
                    and not pl.bomb_active):
                buttons |= ACTION_BOMB
            return buttons

        px, py = float(pl.position.x), float(pl.position.y)
        target = getattr(macro, "target", None) or MacroTarget()
        bomb_active = bool(pl.bomb_active)
        speed = self.speed_focus if macro.focus else self.speed_full

        hazards, segs_now, segs_full = self._collect_hazards(
            v, px, py, bomb_active)

        # --- R7: dense-wall "stay up" detection (opt-in) ---
        # Count enemy bullets in the bottom band UNFILTERED (the R_SCAN
        # hazard list is empty when the player is safely up top, which is
        # exactly when the bias is needed). See the constants' comment.
        dense_active = False
        if self.dense_wall and not pl.invulnerable:
            band_top = PY_MAX - DENSE_BAND
            n = 0
            for p in v.projectiles:
                if p.category != PROJ_ENEMY or not (p.flags & ACTIVE_HAZARD):
                    continue
                if p.position.y > band_top:
                    n += 1
            if n >= DENSE_THRESHOLD:
                self._dense_frames += 1
                self._dense_release = 0
            elif n < DENSE_RELEASE:
                self._dense_release += 1
                self._dense_frames = 0
            if self._dense_frames >= DENSE_PERSIST:
                self._dense_armed = True
            if self._dense_release >= DENSE_RELEASE_PERSIST:
                self._dense_armed = False
            dense_active = self._dense_armed
        else:
            self._dense_frames = 0
            self._dense_release = 0
            self._dense_armed = False

        # --- R5.2: converging-laser-ring escape (opt-in) ---
        # Bypasses the cost model: the ring is invisible to it while it
        # converges (charging beams are not collision_active) and the
        # collapse is faster than the horizon can see.  Walk to the safe
        # circle through the angular gap, avoiding the soul discs, and
        # HOLD it (never release on arrival) until the beam is inactive —
        # the guard anchor would otherwise walk the player back through
        # the collapsing band / the t=190 ball spawn.  The post-boom cage
        # (t=190+, visible moving bullets) is left to the cost model.
        ring_escape_dir = None
        if self.laser_ring and not pl.invulnerable:
            frame = int(v.raw.logical_frame)
            detected, center, gap_bins = self._ring_state(v, px, py, frame)
            if detected:
                self._ring_last_seen = frame
                self._ring_center = center
                self._ring_gap = gap_bins
                self._ring_frame = frame
            if (self._ring_center is not None
                    and frame - self._ring_last_seen <= RING_ACTIVE_FRAMES):
                cx, cy = self._ring_center
                dxc, dyc = px - cx, py - cy
                d = (dxc * dxc + dyc * dyc) ** 0.5
                if d < RING_DANGER_R:
                    ring_escape_dir = self._ring_target_dir(
                        px, py, cx, cy, RING_SAFE_R, self._ring_gap,
                        hazards=hazards, hold=True)

        # --- candidate scoring ---
        costs = [0.0] * len(MOVES)
        for i, (unit, _btn) in enumerate(MOVES):
            dx, dy = unit
            if pl.invulnerable:
                costs[i] = 0.0
                continue
            costs[i] = self._candidate_cost(
                px, py, dx, dy, speed, hazards, segs_now, segs_full)
        base_min_cost = min(costs) if costs else 0.0
        # R4.5 (2026-09-26): threat-gated wall penalty (opt-in, no-bomb
        # only). Replaces the R4.3 positional ramp — see the constant's
        # comment. The +1000 step applies only while the player is
        # pinned-in-danger (band + tth<=EDGE_GATE_TTH + base argmin toward
        # the wall), penalizing strict toward-wall headings (hold counts;
        # pure lateral is the free gap-track escape).
        if (self.allow_edge_escape and not self.allow_bombs
                and not pl.invulnerable
                and self._pinned_gate(px, py, hazards, segs_now, costs)):
            for i in range(len(MOVES)):
                dx, dy = MOVES[i][0]
                if self._toward_wall(px, py, dx, dy):
                    costs[i] += EDGE_ESCAPE_PENALTY

        # R7 (2026-09-27): dense-wall "stay in the open band" bias — two-
        # sided (see the constants' comment). While the bottom-band wave is
        # armed: push UP when the player is in the gauntlet (py >
        # DENSE_SAFE_Y) and push DOWN when it is at the top edge (py <
        # DENSE_TOP_Y), so it converges to the open middle-top band and
        # gap-tracks there instead of pinning to either wall.
        if dense_active:
            for i in range(len(MOVES)):
                _dx, dy = MOVES[i][0]
                if py > DENSE_SAFE_Y and dy > 0:
                    costs[i] += DENSE_DOWN_PENALTY * dy
                elif py < DENSE_TOP_Y and dy < 0:
                    costs[i] += DENSE_DOWN_PENALTY * (-dy)

        # R7b (2026-09-27): per-wall bullet danger (opt-in). When the player
        # is in a wall's 40 px band AND there are bullets in that band near
        # the player, penalize the heading that moves TOWARD that wall —
        # push the player out of the band before it is pinned (the R4.5 gate
        # is threat-gated and fires too late).  hazards is R_SCAN-filtered
        # (150 px), which covers the WALL_DANGER_R (60 px) count radius.
        if self.wall_danger and not pl.invulnerable:
            r2 = WALL_DANGER_R * WALL_DANGER_R
            danger_walls = 0
            for wall in range(4):
                if wall == 0:
                    d_wall = PY_MAX - py
                elif wall == 1:
                    d_wall = py - PY_MIN
                elif wall == 2:
                    d_wall = px - PX_MIN
                else:
                    d_wall = PX_MAX - px
                if d_wall >= WALL_DANGER_DIST:
                    continue
                n = 0
                for hx, hy, _vx, _vy, _r, _w in hazards:
                    if wall == 0:
                        hw = PY_MAX - hy
                    elif wall == 1:
                        hw = hy - PY_MIN
                    elif wall == 2:
                        hw = hx - PX_MIN
                    else:
                        hw = PX_MAX - hx
                    if hw >= WALL_DANGER_DIST:
                        continue
                    dxh, dyh = hx - px, hy - py
                    if dxh * dxh + dyh * dyh <= r2:
                        n += 1
                if n >= WALL_DANGER_COUNT:
                    danger_walls |= (1 << wall)
            if danger_walls:
                for i in range(len(MOVES)):
                    dx, dy = MOVES[i][0]
                    toward = False
                    if (danger_walls & 1) and dy > 0:
                        toward = True
                    if (danger_walls & 2) and dy < 0:
                        toward = True
                    if (danger_walls & 4) and dx < 0:
                        toward = True
                    if (danger_walls & 8) and dx > 0:
                        toward = True
                    if toward:
                        costs[i] += WALL_DANGER_K

        # R4.8 (2026-09-26): escape commit — see the constants' comment.
        # In severe danger the per-frame argmin is pinned to the cheapest
        # non-stationary heading for a few frames (straight-line escape that
        # exceeds the ~16 px kill-disk radius of a tracking convergence
        # storm); a 6.25 px single-frame step cannot clear it and the raw
        # per-frame argmin oscillates into a stall at the aim point.
        commit_active = self._escape_commit_left > 0
        if commit_active:
            self._escape_commit_left -= 1
        if (self.escape_commit and not pl.invulnerable
                and costs and min(costs) >= ESCAPE_COMMIT_AT):
            # Escape candidates: non-stationary headings that move the
            # player at (almost) full displacement. Wall-clamped headings
            # (down at the bottom wall, diagonals in the band) would pin
            # the player at the wall exactly where the storm re-aims —
            # only full lateral/upward escape counts.
            best_e, best_i = None, None
            for i in range(len(MOVES)):
                if i == 0:
                    continue
                dx, dy = MOVES[i][0]
                nx, ny = self._clamp_position(
                    px + dx * speed, py + dy * speed)
                moved = ((nx - px) ** 2 + (ny - py) ** 2) ** 0.5
                full = (dx * dx + dy * dy) ** 0.5 * speed
                if moved < 0.9 * full:
                    continue
                # R7c: score the heading by the myopic cost PLUS the
                # cumulative path risk (the safer straight-line path), so
                # the commit does not run into bullets 10 frames later.
                score = costs[i]
                if COMMIT_PATH_WEIGHT > 0.0:
                    score += COMMIT_PATH_WEIGHT * self._path_risk(
                        i, px, py, speed, hazards, segs_full)
                if best_e is None or score < best_e:
                    best_e, best_i = score, i
            if (best_i is not None and self.escape_commit_policy
                    == "lateral_band"
                    and (py >= PY_MAX - 60.0 or py <= PY_MIN + 60.0)):
                # prefer the cheaper pure-lateral full-displacement heading
                lat = None
                for i in (3, 4):
                    dx, dy = MOVES[i][0]
                    nx, ny = self._clamp_position(
                        px + dx * speed, py + dy * speed)
                    if ((nx - px) ** 2 + (ny - py) ** 2) ** 0.5 \
                            >= 0.9 * speed:
                        if lat is None or costs[i] < costs[lat]:
                            lat = i
                if lat is not None:
                    best_i = lat
            if best_i is not None:
                self._escape_heading = best_i
                self._escape_commit_left = ESCAPE_COMMIT_FRAMES - 1
                commit_active = True

        # R6.1 (2026-09-26, refined 2026-09-27): wall commit — see the
        # constants' comments.  Gate: in the wall band AND min BASE cost
        # over all 9 headings >= WALL_COMMIT_AT for WALL_COMMIT_PERSIST
        # consecutive frames (the per-frame argmin wiggles on noise and
        # never commits).  Lock: the heading whose 36-frame straight line
        # LEAVES the danger (endpoint risk <= WALL_COMMIT_END_CAP) with the
        # lowest max-over-path risk; no eligible heading => no lock (a
        # uniform dense field — the wiggle stays in control).  If still in
        # the wall when the lock expires, re-lock (re-planning the path
        # from the new position).  Priority: ring escape > wall commit >
        # R4.8 commit.
        wall_commit_active = self._wall_commit_left > 0
        if wall_commit_active:
            self._wall_commit_left -= 1
            if (costs and costs[self._wall_heading] - base_min_cost
                    > WALL_COMMIT_BREAK_MARGIN):
                # The locked path is much worse than the wiggle now —
                # release early (see WALL_COMMIT_BREAK_MARGIN comment).
                self._wall_commit_left = 0
                self._wall_frames = 0
                wall_commit_active = False
        in_wall_band = (py >= PY_MAX - WALL_DIST or py <= PY_MIN + WALL_DIST
                        or px <= PX_MIN + WALL_DIST
                        or px >= PX_MAX - WALL_DIST)
        if (self.wall_commit and not pl.invulnerable and in_wall_band
                and base_min_cost >= WALL_COMMIT_AT):
            self._wall_frames += 1
            if (self._wall_frames >= WALL_COMMIT_PERSIST
                    and self._wall_commit_left == 0):
                best_w, best_i = None, None
                for i in range(1, len(MOVES)):
                    w, e = self._wall_path_score(
                        i, px, py, speed, hazards, segs_full)
                    if e > WALL_COMMIT_END_CAP:
                        continue
                    if best_w is None or w < best_w:
                        best_w, best_i = w, i
                if best_i is not None:
                    self._wall_heading = best_i
                    self._wall_commit_left = WALL_COMMIT_FRAMES - 1
                    wall_commit_active = True
        elif self.wall_commit:
            self._wall_frames = 0

        beta = BETA_BY_KIND.get(target.kind, 0.5)
        # If even the safest legal heading is already in severe danger, let
        # the safer escape beat the target anchor for this frame. This remains
        # inside Laya's selected macro; it only attenuates its intent term.
        if costs and min(costs) >= BOMB_NOW_COST:
            beta *= (NOBOMB_DANGER_INTENT_FACTOR
                     if (self.danger_valve and not self.allow_bombs)
                     else DANGER_INTENT_FACTOR)
        elif (self.danger_valve and not self.allow_bombs
              and target.kind in ("below_boss", "hold")):
            # R3 (b): Laya rates the situation severe but the local costs are
            # not yet — the pre-collapse window. Relax the anchor pull so the
            # executor is free to keep the player in the open lane.
            if getattr(macro, "danger_score", -1.0) >= LAYA_DANGER_VALVE_AT:
                beta *= LAYA_DANGER_VALVE
        best = None
        best_idx = 0
        for i in range(len(MOVES)):
            dx, dy = MOVES[i][0]
            nx, ny = self._clamp_position(px + dx * speed, py + dy * speed)
            intent = self._intent(target, v, px, py, nx, ny)
            score = costs[i] - beta * intent
            # hysteresis: a small tie-break bonus to keep a safe direction
            # (smooths the trace without overriding the macro's intent)
            if i == self.last_move_idx and costs[i] <= EPS_SAFE:
                score -= HYSTERESIS_NUDGE
            if best is None or score < best:
                best, best_idx = score, i
        if commit_active:
            best_idx = self._escape_heading
            best = costs[best_idx]
        if wall_commit_active:
            best_idx = self._wall_heading
            best = costs[best_idx]
        if ring_escape_dir is not None:
            # R5.2: full-speed escape — the non-stationary heading closest
            # to the escape direction; ignores the cost model and focus.
            best_dot, best_idx = -2.0, 1
            for i in range(1, len(MOVES)):
                dx, dy = MOVES[i][0]
                dot = dx * ring_escape_dir[0] + dy * ring_escape_dir[1]
                if dot > best_dot:
                    best_dot, best_idx = dot, i
            best = costs[best_idx]

        _move_dx, move_buttons = MOVES[best_idx]
        self.last_move_idx = best_idx
        self.last_cost = costs[best_idx]
        buttons |= move_buttons
        if macro.focus and ring_escape_dir is None:
            buttons |= ACTION_FOCUS

        # --- bomb (v5, 2026-09-25) ---
        # (a) Hit-time death-bomb safety net: fire the moment a hit is
        #     registered (pl.death_timer >= 0 — the engine's 12-frame death
        #     window, player.c:1020; the hit becomes visible one frame AFTER
        #     it lands, so 11 frames remain). A bomb during the window
        #     cancels the death (total cost 2 bombs, player.c:685-692). It
        #     only fires after the hit already happened — it cannot change
        #     what Laya chose to do, only the outcome of the hit.
        # (b) Laya's macro bomb: fire IMMEDIATELY (age <= 10 f) or when the
        #     best candidate's cost is high (>= BOMB_NOW_COST — in deep
        #     trouble): bomb_now is a NOW decision, not a "safe/early" one.
        #     At most once per macro.
        if self.allow_bombs and macro.bomb:
            if macro.issued_frame != self._bomb_macro_id:
                self._bomb_macro_id = macro.issued_frame
                self._bomb_fired = False
            age = int(v.raw.logical_frame) - int(macro.issued_frame)
            macro_fire = (not self._bomb_fired and pl.bombs > 0
                          and not bomb_active
                          and (age <= 10 or costs[best_idx] >= BOMB_NOW_COST))
        else:
            macro_fire = False
        death_fire = (self.allow_bombs and pl.death_timer >= 0
                      and pl.bombs > 0 and not bomb_active)
        if macro_fire or death_fire:
            buttons |= ACTION_BOMB
            self._bomb_fired = True
        self.last_costs = list(costs)
        self.last_buttons = buttons
        return buttons
