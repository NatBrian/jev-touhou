"""Estimate the R4.2 edge-exile trigger rate from a recorded campaign
(2026-09-26). Replays each stage exactly (same seed/carry + the trace's
macro/focus sequence, targets re-pinned at decision frames) and evaluates,
at every decision frame, the two halves of the exile condition:

  * edge band: player within 40 px of any playfield edge
  * imminent hit: min quadratic time-to-hit over hazardous bullets < 25 f

Prints per stage: decision count, band-only rate, tth<25 rate, and the
combined exile rate (what R4.2 would have fired). Also prints the exile
outcomes on the decision frames immediately before each recorded death.

    venv\Scripts\python.exe tools\diag_exile_rate.py <tag> [stage ...]
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING, PROJ_ENEMY,
)
from macros import MacroTarget, resolve_macro_target  # noqa: E402
from executor import ReflexExecutor, PLAYER_RADIUS  # noqa: E402

EDGE_BAND = 40.0
EXILE_TTH_MAX = 25.0
PX_MIN, PX_MAX, PY_MIN, PY_MAX = 16.0, 464.0, 16.0, 544.0
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")


class TraceMacro:
    source = "trace"
    bomb = False
    danger_score = -1.0

    def __init__(self, macro_id, focus, issued_frame, target):
        self.macro_id = macro_id
        self.focus = focus
        self.issued_frame = issued_frame
        self.target = target


def load_stage(tag, stage):
    path = os.path.join(DATA, "laya-%s.jsonl" % tag)
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    segs, cur, prev = [], [], None
    for r in rows:
        f = r.get("frame")
        if prev is not None and isinstance(f, int) and f < prev:
            segs.append(cur)
            cur = []
        cur.append(r)
        prev = f
    if cur:
        segs.append(cur)
    if stage - 1 >= len(segs):
        return None, None
    seg = segs[stage - 1]
    seq = [(int(r["frame"]), r.get("macro", "guard"),
            bool(r.get("focus_eff", False)))
           for r in seg if r.get("status") == "ok"]
    deaths = [r["frame"] for r in seg if r.get("status") == "death_hit"]
    return seq, deaths


def tth_min(px, py, projectiles):
    best = None
    for p in projectiles:
        if p.category != PROJ_ENEMY or not (p.flags & 16):
            continue
        r = max(p.collision_size.x, p.collision_size.y, 3.0) + PLAYER_RADIUS
        dx, dy = p.position.x - px, p.position.y - py
        vx, vy = p.velocity.x, p.velocity.y
        a = vx * vx + vy * vy
        if a < 1e-9:
            t = 0.0 if dx * dx + dy * dy <= r * r else None
        else:
            b = 2.0 * (dx * vx + dy * vy)
            c = dx * dx + dy * dy - r * r
            if c <= 0:
                t = 0.0
            else:
                disc = b * b - 4.0 * a * c
                if disc < 0:
                    t = None
                else:
                    t = (-b - disc ** 0.5) / (2.0 * a)
                    if t is not None and t < 0:
                        t = None
        if t is not None and (best is None or t < best):
            best = t
    return best


def main():
    tag = sys.argv[1]
    stages = [int(x) for x in sys.argv[2:]] or [1, 2, 3]
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
    ex = ReflexExecutor(allow_bombs=False)

    for stage in stages:
        seq, deaths = load_stage(tag, stage)
        if seq is None:
            print("S%d: no trace segment" % stage)
            continue
        carry = {}
        cp_path = os.path.join(DATA, "checkpoints",
                               "%s-stage%d.json" % (tag, stage - 1))
        if stage > 1 and os.path.exists(cp_path):
            cp = json.load(open(cp_path, encoding="utf-8"))
            if cp.get("carry"):
                carry = cp["carry"]
        sim.reset(EpisodeConfig(
            stage_id=stage, difficulty=DIFFICULTY_NORMAL,
            player_character=CHAR_MARISA, shot_mode=SHOT_A,
            rng_seed=12345 + stage, **carry))
        ex.reset()

        n_dec = n_band = n_tth = n_exile = 0
        dec_frames = [f for f, _m, _fo in seq]
        pre_death = {}
        for df in deaths or []:
            prevs = [f for f in dec_frames if f < df]
            if prevs:
                pre_death[prevs[-1]] = df

        seq_idx = 0
        cur_macro = None
        f = 0
        while f < 40000:
            v = sim.get_state()
            if v.raw.episode_status != STATUS_RUNNING:
                break
            lf = int(v.raw.logical_frame)
            while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
                _f, _mid, foc = seq[seq_idx]
                cur_macro = TraceMacro(_mid, foc, _f,
                                       resolve_macro_target(_mid, v))
                seq_idx += 1
                px, py = (float(v.raw.player.position.x),
                          float(v.raw.player.position.y))
                in_band = (py >= PY_MAX - EDGE_BAND or
                           py <= PY_MIN + EDGE_BAND or
                           px <= PX_MIN + EDGE_BAND or
                           px >= PX_MAX - EDGE_BAND)
                t = tth_min(px, py, v.projectiles)
                n_dec += 1
                n_band += int(in_band)
                n_tth += int(t is not None and t < EXILE_TTH_MAX)
                n_exile += int(in_band and t is not None
                                and t < EXILE_TTH_MAX)
                if lf in pre_death:
                    print("  pre-death decision f=%d (death f=%d): pos=(%.0f,%.0f) "
                          "band=%s tth=%s -> %s" % (
                              lf, pre_death[lf], px, py, in_band,
                              None if t is None else round(t, 1),
                              "EXILE" if (in_band and t is not None
                                          and t < EXILE_TTH_MAX)
                              else "no exile"))
            if cur_macro is None:
                cur_macro = TraceMacro("guard", False, lf,
                                       resolve_macro_target("guard", v))
            sim.step(buttons=ex.execute(cur_macro, v))
            f += 1
        if n_dec:
            print("S%d: decisions=%d  edge_band=%.1f%%  tth<25=%.1f%%  "
                  "EXILE=%.1f%% (%d)" % (
                      stage, n_dec, 100.0 * n_band / n_dec,
                      100.0 * n_tth / n_dec, 100.0 * n_exile / n_dec,
                      n_exile))
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
