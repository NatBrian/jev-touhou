"""Offline A/B probe for executor variants (2026-09-26, R4.5.1 search).

Replays a recorded campaign stage deterministically (trace macro sequence,
same seed/carry, NO Laya calls) with a configurable executor variant and
reports deaths / death positions / band occupancy.

Variant = the c_hor horizon term of _candidate_cost:
  V0: single snapshot at THREAT_HORIZON (36)      (current behavior)
  V1: min over t in (12, 24, 36)
  V2: min over t in (8, 16, 24, 32, 40, 48)
  V3: min over t in (4, 8, ..., 48)
The min-over-time form is gap-aware: in a dense fast swarm every position
is covered at the single t=36 snapshot, but a gap passes each column at
some t within the window; the min sees it.

    venv\Scripts\python.exe tools\probe_evader.py <tag> <stage> [--variant V2] [--gate] [diff]

Caveats:
- The replay re-resolves macro targets with the CURRENT agent code, so runs
  predating R4.2-v2 / R4.4 have small target divergences (exile/sidestep
  frames only). V0 without --gate otherwise matches the live executor.
- Deaths come from v.raw.deaths increments (ground truth from the sim).
"""
import json
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))

import executor as executor_module  # noqa: E402
from executor import (  # noqa: E402
    ReflexExecutor, C2_WEIGHT, DODGE_ROLLOUT_FRAMES, DODGE_ROLLOUT_WEIGHT,
    PATH_RISK_FRAMES, PATH_RISK_WEIGHT, PX_MIN, PX_MAX, PY_MIN, PY_MAX,
    WALL_DIST, MOVES,
)
from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING,
)
from macros import resolve_macro_target  # noqa: E402
from dump_probe_states import (  # noqa: E402
    TraceMacro, load_trace_seq, load_trace_seq_full)
from agent import Agent  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")

# Window of extra snapshots for the gap-search min term.
GAP_WINDOW = (8, 16, 24, 32, 40, 48)


def _v0(c_snap, c_min):
    return c_snap


def _v1(c_snap, c_min):
    return min(c_snap, c_min)


def _va4(c_snap, c_min):
    return c_snap if c_snap < 4.0 else min(c_snap, c_min)


def _va8(c_snap, c_min):
    return c_snap if c_snap < 8.0 else min(c_snap, c_min)


def _va16(c_snap, c_min):
    return c_snap if c_snap < 16.0 else min(c_snap, c_min)


def _vb(c_snap, c_min):
    return max(c_min, 0.5 * c_snap)


def _vc(c_snap, c_min):
    return 0.5 * c_snap + 0.5 * c_min


def _va2(c_snap, c_min):
    return c_snap if c_snap < 2.0 else min(c_snap, c_min)


VARIANTS = {
    "V0": _v0, "V1": _v1, "VA2": _va2, "VA4": _va4, "VA4w": _va4,
    "VA4l": _va4, "VA4x": _va4,
    "VA8": _va8, "VA16": _va16, "VB": _vb, "VC": _vc,
}


def corner_factor(nx, ny, dist=40.0):
    """(1 - d/dist)^2 for d = distance to the nearest corner, else 0."""
    best = None
    for cx in (PX_MIN, PX_MAX):
        for cy in (PY_MIN, PY_MAX):
            d = ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5
            if d < dist and (best is None or d < best):
                best = d
    if best is None:
        return 0.0
    u = 1.0 - best / dist
    return u * u


def lateral_factor(nx, dist=30.0):
    """(1 - d/dist)^2 for d = distance to the nearest LEFT/RIGHT wall,
    else 0. (The lateral edges trap: escape runs along the wall close in
    in two directions; G1.5 S3 deaths at x=16.)"""
    d = min(nx - PX_MIN, PX_MAX - nx)
    if d >= dist:
        return 0.0
    u = 1.0 - d / dist
    return u * u


# R4.9 (2026-09-26): steer-to-safe-zone. The G2.92 S3 wall gauntlet
# (576-721 bullets r12, wall band ~160 px thick at the bottom) traps the
# player: every heading's c_now is a full wall (613-774) so the argmin
# shuffles laterally IN the wall row and dies, even though the upper half
# of the field is safe (field map, tools/diag_cost_field.py f5320). In
# those states the cheap escape is a committed climb toward the safe
# zone. Steer = -W*(1-cos(heading, dir_to_safe_centroid)) added to each
# heading cost while the player sits in a thick wall (best-of-9 base cost
# >= STEER_GATE_AT) and a safe sample exists (< STEER_SAFE_AT).
STEER_SAMPLES = (
    (240.0, 280.0),
    (40.0, 56.0), (448.0, 56.0), (40.0, 520.0), (448.0, 520.0),
    (240.0, 56.0), (240.0, 520.0), (40.0, 280.0), (448.0, 280.0),
    (140.0, 140.0), (340.0, 140.0), (140.0, 420.0), (340.0, 420.0),
)
STEER_GATE_AT = 60.0   # best-of-9 base cost at the player (thick wall)
STEER_SAFE_AT = 25.0   # sample cost below this counts as safe zone
STEER_LOCAL_FUTURE_AT = 40.0  # local t=36 wall below this = transient wave


def _steer_target(ex, px, py, speed, hazards, segs_now, segs_full, r_p,
                  debug=False):
    """Weighted centroid of the 3 safest sample points, or None when the
    player is not in a thick wall / no safe sample exists."""
    best_here = None
    best_future = None
    for m in MOVES:
        dx, dy = m[0]
        nx, ny = ex._clamp_position(px + dx * speed, py + dy * speed)
        c_now = (ex._risk_at(nx, ny, hazards, 0.0, r_p)
                 + ex._laser_risk(nx, ny, segs_now, r_p))
        c_hor = (ex._risk_at(nx, ny, hazards, 36.0, r_p)
                 + ex._laser_risk(nx, ny, segs_full, r_p))
        c = c_now + 0.5 * c_hor + ex._wall_cost(nx, ny)
        best_here = c if best_here is None else min(best_here, c)
        best_future = (c_hor if best_future is None
                       else min(best_future, c_hor))
    if best_here < STEER_GATE_AT:
        if debug:
            print("   steer: gate OFF best_here=%.1f local_future=%.1f"
                  % (best_here, best_future))
        return None
    # Local persistence gate: only climb when the local region is STILL a
    # wall at t=36 (persistent band, G2.92 S3 wall gauntlet). A transient
    # coverage wave (G2 S2 swarm: the safe row re-forms within ~36 f)
    # clears locally -> the normal gap-track handles it; climbing there
    # runs INTO the incoming swarm (0 -> 3 LOST regression).
    if best_future < STEER_LOCAL_FUTURE_AT:
        if debug:
            print("   steer: local gate OFF best_here=%.1f "
                  "local_future=%.1f" % (best_here, best_future))
        return None
    v = getattr(ex, "_view", None)
    if v is None:
        return None
    scored = []
    for gx, gy in STEER_SAMPLES:
        hz, _, _ = ex._collect_hazards(v, gx, gy, False)
        # The climb takes ~40-60 frames: the sample must be safe when the
        # player ARRIVES, not just at t=36 (a descending swarm reads safe
        # at t=36 and arrives by t=72 — S2 regression 0 -> 3 LOST).
        c = max(ex._risk_at(gx, gy, hz, 36.0, r_p),
                ex._risk_at(gx, gy, hz, 72.0, r_p))
        c += ex._laser_risk(gx, gy, segs_full, r_p)
        scored.append((c, gx, gy))
    if debug:
        print("   steer: gate ON best_here=%.1f local_future=%.1f samples:"
              % (best_here, best_future))
        for c, gx, gy in sorted(scored)[:6]:
            print("      (%.0f,%.0f) c36_72=%.1f %s"
                  % (gx, gy, c, "SAFE" if c < STEER_SAFE_AT else ""))
    scored.sort()
    safe = [t for t in scored if t[0] < STEER_SAFE_AT]
    if not safe:
        return None
    wsum = wx = wy = 0.0
    for c, gx, gy in safe[:3]:
        w = 1.0 / (1.0 + c)
        wsum += w
        wx += w * gx
        wy += w * gy
    if debug:
        print("      -> target (%.0f, %.0f)" % (wx / wsum, wy / wsum))
    return (wx / wsum, wy / wsum)


def make_candidate_cost(ex, hor_fn, window=GAP_WINDOW, corner_k=0.0,
                        lateral_k=0.0, dump_at=None, steer_w=0.0):
    steer_cache = {}
    """Reimplementation of ReflexExecutor._candidate_cost with the c_hor
    term replaced by hor_fn(c_snap, c_min), where c_snap = the original
    single t=36 snapshot term and c_min = min over the window (V0 ==
    original); optional corner_k * corner_factor added (R4.7b). With
    dump_at=<frame>, records the per-heading cost breakdown at that frame
    on ex._cost_dump (for forensics)."""
    def _candidate_cost(self, px, py, dx, dy, speed, hazards,
                        segs_now, segs_full):
        r_p = ex.player_radius
        nx, ny = ex._clamp_position(px + dx * speed, py + dy * speed)
        c_now = (ex._risk_at(nx, ny, hazards, 0.0, r_p)
                 + ex._laser_risk(nx, ny, segs_now, r_p)
                 + ex._swept_risk(px, py, nx, ny, hazards, r_p))
        c_snap = (ex._risk_at(nx, ny, hazards, 36.0, r_p)
                  + ex._laser_risk(nx, ny, segs_full, r_p))
        c_min = None
        for t in window:
            c = (ex._risk_at(nx, ny, hazards, float(t), r_p)
                 + ex._laser_risk(nx, ny, segs_full, r_p))
            c_min = c if c_min is None else min(c_min, c)
        if (dump_at is not None and getattr(self, "_dump_frame", None)
                is not None and self._dump_frame in dump_at):
            self._cost_dump.append(
                (c_now, c_snap, c_min, (nx, ny)))
        c_hor = hor_fn(c_snap, c_min)
        nx2, ny2 = ex._clamp_position(nx + dx * speed, ny + dy * speed)
        c_2 = (ex._risk_at(nx2, ny2, hazards, 0.0, r_p)
               + ex._laser_risk(nx2, ny2, segs_now, r_p))
        cost = (c_now + 0.5 * c_hor + C2_WEIGHT * c_2
                + ex._wall_cost(nx, ny))
        if dx != 0.0 or dy != 0.0:
            cost += ex._laser_cross(px, py, nx, ny, segs_now)
        if DODGE_ROLLOUT_WEIGHT > 0.0:
            future = []
            for frame in range(2, DODGE_ROLLOUT_FRAMES + 1):
                qx, qy = ex._clamp_position(px + dx * speed * frame,
                                            py + dy * speed * frame)
                future.append(ex._risk_at(qx, qy, hazards, float(frame), r_p)
                              + ex._laser_risk(qx, qy, segs_full, r_p)
                              + ex._wall_cost(qx, qy))
            cost += DODGE_ROLLOUT_WEIGHT * (sum(future) / len(future))
        if PATH_RISK_WEIGHT > 0.0:
            path_risks = []
            for frame in range(1, PATH_RISK_FRAMES + 1):
                qx, qy = ex._clamp_position(px + dx * speed * frame,
                                            py + dy * speed * frame)
                path_risks.append(
                    ex._risk_at(qx, qy, hazards, float(frame), r_p)
                    + ex._laser_risk(qx, qy, segs_full, r_p))
            if path_risks:
                cost += PATH_RISK_WEIGHT * max(path_risks)
        if corner_k > 0.0:
            cost += corner_k * corner_factor(nx, ny)
        if lateral_k > 0.0:
            cost += lateral_k * lateral_factor(nx)
        if steer_w > 0.0:
            key = (round(px, 1), round(py, 1))
            if getattr(ex, "_steer_debug", False):
                # fresh computation on debug frames (a hold frame reuses the
                # cached key and would skip the debug print)
                target = _steer_target(ex, px, py, speed, hazards,
                                       segs_now, segs_full, r_p,
                                       debug=True)
                ex._steer_debug = None
                steer_cache[key] = target
            elif key in steer_cache:
                target = steer_cache[key]
            else:
                target = _steer_target(ex, px, py, speed, hazards,
                                       segs_now, segs_full, r_p)
                if len(steer_cache) > 128:
                    steer_cache.clear()
                steer_cache[key] = target
            if target is not None:
                tx, ty = target[0] - px, target[1] - py
                tlen = (tx * tx + ty * ty) ** 0.5
                if tlen > 8.0:
                    hl = (dx * dx + dy * dy) ** 0.5
                    c = ((dx * tx + dy * ty) / (tlen * hl)
                         if hl > 1e-6 else 0.0)
                    cost += steer_w * (1.0 - c)
        return cost
    return _candidate_cost


def main():
    args = sys.argv[1:]
    variant = "V0"
    gate = False
    commit = False
    commit_policy = "full"
    corner_k = 0.0
    lateral_k = 0.0
    steer_w = 0.0
    steer_debug_frames = set()
    dump_frames = set()
    pos_frames = False
    laser_blind_fix = False
    laser_ring = False
    path_risk = False
    path_frames = 0
    carry_file = None
    ring_dbg_lo, ring_dbg_hi = 0, 10 ** 9
    pos_ranges = []
    wall_commit = False
    dense_wall = False
    wall_danger = False
    dodge_frames = None
    dodge_weight = None
    g_sigma = None
    g_range = None
    commit_path_weight = None
    dense_penalty = None
    dense_thresh = None
    dense_safe_y = None
    dense_top_y = None
    lives_override = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--variant":
            variant = args[i + 1]
            i += 2
        elif a == "--gate":
            gate = True
            i += 1
        elif a == "--commit":
            commit = True
            i += 1
        elif a == "--commit-policy":
            commit_policy = args[i + 1]
            i += 2
        elif a == "--corner-k":
            corner_k = float(args[i + 1])
            i += 2
        elif a == "--lateral-k":
            lateral_k = float(args[i + 1])
            i += 2
        elif a == "--steer":
            steer_w = float(args[i + 1])
            i += 2
        elif a == "--steer-debug":
            steer_debug_frames = set(int(x) for x in args[i + 1].split(","))
            i += 2
        elif a == "--dump-costs":
            dump_frames = set(int(x) for x in args[i + 1].split(","))
            i += 2
        elif a == "--pos-frames":
            pos_ranges = []
            for part in args[i + 1].split(","):
                a2, b2 = part.split("-")
                pos_ranges.append((int(a2), int(b2)))
            pos_frames = True
            i += 2
        elif a == "--laser-blind-fix":
            laser_blind_fix = True
            i += 1
        elif a == "--laser-ring":
            laser_ring = True
            i += 1
        elif a == "--wall-commit":
            wall_commit = True
            i += 1
        elif a == "--dense-wall":
            dense_wall = True
            i += 1
        elif a == "--dense-penalty":
            dense_penalty = float(args[i + 1])
            i += 2
        elif a == "--dense-thresh":
            dense_thresh = float(args[i + 1])
            i += 2
        elif a == "--dense-safe-y":
            dense_safe_y = float(args[i + 1])
            i += 2
        elif a == "--dense-top-y":
            dense_top_y = float(args[i + 1])
            i += 2
        elif a == "--wall-danger":
            wall_danger = True
            i += 1
        elif a == "--lives":
            lives_override = int(args[i + 1])
            i += 2
        elif a == "--path-risk":
            path_risk = True
            i += 1
        elif a == "--path-frames":
            path_frames = int(args[i + 1])
            i += 2
        elif a == "--dodge-frames":
            dodge_frames = int(args[i + 1])
            i += 2
        elif a == "--dodge-weight":
            dodge_weight = float(args[i + 1])
            i += 2
        elif a == "--g-sigma":
            g_sigma = float(args[i + 1])
            i += 2
        elif a == "--g-range":
            g_range = float(args[i + 1])
            i += 2
        elif a == "--commit-path":
            commit_path_weight = float(args[i + 1])
            i += 2
        elif a == "--carry":
            carry_file = args[i + 1]
            i += 2
        elif a == "--ring-debug":
            ring_dbg_lo, ring_dbg_hi = (int(x) for x in args[i + 1].split("-"))
            i += 2
        else:
            rest.append(a)
            i += 1
    tag, stage = rest[0], int(rest[1])
    diff = DIFFS.get(rest[2] if len(rest) > 2 else "normal", DIFFICULTY_NORMAL)

    carry = {}
    if carry_file:
        cp_in = json.load(open(carry_file, encoding="utf-8"))
        carry = dict(cp_in.get("carry") or
                     (cp_in if "initial_score" in cp_in else {}))
        print("CARRY loaded from %s: %s" % (carry_file, carry))
    else:
        cp_path = os.path.join(DATA, "checkpoints",
                               "%s-stage%d.json" % (tag, stage - 1))
        if stage > 1 and os.path.exists(cp_path):
            cp = json.load(open(cp_path, encoding="utf-8"))
            if cp.get("carry"):
                carry = cp["carry"]
    if lives_override is not None:
        # measurement mode: enough lives to observe the FULL death
        # distribution of the stage (a campaign carry dies out earlier)
        carry["initial_lives"] = lives_override
        print("LIVES override: initial_lives=%d" % lives_override)
    seq = load_trace_seq_full(tag, stage)

    register_runtime_dirs(
        os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
    for d in ("storage", "cache"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    sim = TaiseiSim(LIB)
    sim.global_init(
        resource_path=os.path.join(SIM_ROOT, "resources", "00-taisei.pkgdir"),
        storage_path=os.path.join(DATA, "storage"),
        cache_path=os.path.join(DATA, "cache"),
    )
    sim.create()
    sim.reset(EpisodeConfig(
        stage_id=stage, difficulty=diff, player_character=CHAR_MARISA,
        shot_mode=SHOT_A, rng_seed=12345 + stage, **carry,
    ))
    if path_risk:
        executor_module.PATH_RISK_WEIGHT = 0.35
        globals()["PATH_RISK_WEIGHT"] = 0.35
    if path_frames:
        executor_module.PATH_RISK_FRAMES = path_frames
    # R7: dodge-rollout tuning overrides (longer horizon + mean aggregator)
    if dodge_weight is not None:
        executor_module.DODGE_ROLLOUT_WEIGHT = dodge_weight
    if dodge_frames is not None:
        executor_module.DODGE_ROLLOUT_FRAMES = dodge_frames
    # R7: risk-falloff tuning overrides (wider Gaussian = less myopic)
    if g_sigma is not None:
        executor_module.G_SIGMA = g_sigma
    if g_range is not None:
        executor_module.G_RANGE = g_range
    # R7c: committed-path escape weight
    if commit_path_weight is not None:
        executor_module.COMMIT_PATH_WEIGHT = commit_path_weight
    # R7 dense-wall tuning overrides (sweep without editing the executor)
    if dense_penalty is not None:
        executor_module.DENSE_DOWN_PENALTY = dense_penalty
    if dense_thresh is not None:
        executor_module.DENSE_THRESHOLD = dense_thresh
    if dense_safe_y is not None:
        executor_module.DENSE_SAFE_Y = dense_safe_y
    if dense_top_y is not None:
        executor_module.DENSE_TOP_Y = dense_top_y
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=gate,
                        escape_commit=commit,
                        escape_commit_policy=commit_policy,
                        laser_blind_fix=laser_blind_fix,
                        laser_ring=laser_ring,
                        wall_commit=wall_commit,
                        dense_wall=dense_wall,
                        wall_danger=wall_danger)
    ex.reset()
    windows = {
        "VA4w": tuple(range(4, 61, 4)),
        # longer windows for the dense wall class (G2.92 S3: 576-721
        # bullets r12 speed 2-4.7 — gaps pass faster than the 48 f window)
        "VA4l": (8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 96),
        "VA4x": tuple(range(4, 97, 4)),
    }
    ex._view = None
    ex._candidate_cost = types.MethodType(
        make_candidate_cost(ex, VARIANTS[variant],
                            windows.get(variant, GAP_WINDOW),
                            corner_k=corner_k, lateral_k=lateral_k,
                            dump_at=frozenset(dump_frames),
                            steer_w=steer_w), ex)
    ex._dump_frames = dump_frames
    ex._dump_frame = None
    ex._cost_dump = []
    if ring_dbg_lo != 0 or ring_dbg_hi != 10 ** 9:
        ex._ring_debug_frames = (ring_dbg_lo, ring_dbg_hi)

    t0 = time.time()
    deaths = []
    prev_deaths = 0
    prev_px, prev_py = 240.0, 590.0
    in_band_frames = 0
    frames = 0
    final_status = None
    seq_idx = 0
    cur_macro = None
    # 45000: S6 (final stage) runs past 30000 frames when the player
    # survives (measured 2026-09-27: s6-blind alive at f30000)
    while frames < 45000:
        v = sim.get_state()
        st = v.raw.episode_status
        if st != STATUS_RUNNING:
            final_status = st
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, mid, foc, xeff, eeff = seq[seq_idx]
            # Fidelity (2026-09-27): the live no-bomb agent rewrites the
            # macro target to exile/sidestep via Agent._evade_target when
            # exile_eff/evade_eff — reproduce that, not a bare macro id.
            if xeff or eeff:
                tgt = Agent._evade_target(None, v)[0]
            else:
                tgt = resolve_macro_target(mid, v)
            cur_macro = TraceMacro(mid, foc, _f, tgt)
            seq_idx += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))
        px = float(v.raw.player.position.x)
        py = float(v.raw.player.position.y)
        d = int(v.raw.deaths)
        if d > prev_deaths:
            # deaths increments at respawn; the last seen position (before
            # the death cutscene reset the player) is the death position
            for _ in range(prev_deaths, d):
                deaths.append((lf, prev_px, prev_py))
            prev_deaths = d
        if frames > 0:
            prev_px, prev_py = px, py
        if (py >= PY_MAX - WALL_DIST or py <= PY_MIN + WALL_DIST
                or px <= PX_MIN + WALL_DIST or px >= PX_MAX - WALL_DIST):
            in_band_frames += 1
        ex._view = v
        ex._steer_debug = lf in steer_debug_frames
        ex._dump_frame = lf if lf in dump_frames else None
        if pos_frames and any(lo2 <= lf <= hi2
                              for lo2, hi2 in pos_ranges):
            print("   pos f=%d (%.2f, %.2f) deaths=%d alive=%s" %
                  (lf, px, py, d, v.raw.player.alive))
        sim.step(buttons=ex.execute(cur_macro, v))
        if lf in dump_frames:
            names = ("hold", "up", "down", "left", "right",
                     "UL", "UR", "DL", "DR")
            print("   cost dump f=%d pos=(%.1f, %.1f)" %
                  (lf, px, py))
            for i, (cn, cs, cm, (cnx, cny)) in enumerate(ex._cost_dump):
                print("   h%-5s c_now=%8.2f c_snap=%8.2f c_min=%8.2f "
                      "-> (%.1f, %.1f)" %
                      (names[i], cn, cs, cm, cnx, cny))
            ex._cost_dump = []
            ex._dump_frame = None
        frames += 1
    sim.destroy()
    sim.global_shutdown()

    in_band = "%.1f%%" % (100.0 * in_band_frames / max(frames, 1))
    print("== %s stage %d variant=%s gate=%s commit=%s/%s corner_k=%.1f "
          "lateral_k=%.1f steer_w=%.0f blind_fix=%s ring=%s wall_commit=%s "
          "dense_wall=%s wall_danger=%s path_risk=%s path_frames=%d "
          "dodge_f=%s dodge_w=%s g_sigma=%s g_range=%s diff=%s ==" %
          (tag, stage, variant, gate, commit, commit_policy, corner_k,
           lateral_k, steer_w, laser_blind_fix, laser_ring, wall_commit,
           dense_wall, wall_danger, path_risk, path_frames,
           dodge_frames, dodge_weight, g_sigma, g_range,
           {1: "easy", 2: "normal", 3: "hard", 4: "lunatic"}[diff]))
    print("   frames=%d  status=%s  deaths=%d  in_band(40px)=%d (%s)" %
          (frames, final_status, prev_deaths, in_band_frames, in_band))
    for f, x, y in deaths:
        edge = []
        if y >= PY_MAX - 41:
            edge.append("bottom-%.0fpx" % (PY_MAX - y))
        if y <= PY_MIN + 41:
            edge.append("top")
        if x <= PX_MIN + 41:
            edge.append("left")
        if x >= PX_MAX - 41:
            edge.append("right")
        print("   DEATH f=%d pos=(%.1f, %.1f) %s" %
              (f, x, y, " ".join(edge) or "open-field"))
    print("   wall=%.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
