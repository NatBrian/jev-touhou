"""R5.2 trap-center anomaly diagnostic (2026-09-26).

Replays a stage with the trace macros (base evader + gap horizon, matching
the live flags) and dumps:
  * player position over [plo, phi]  (trap-spawn window)
  * every laser over [llo, lhi]: spawn_id, L.origin, point_count,
    collision_active, median distance origin->point, point bounding box
    and point centroid.

Goal: determine whether L.origin of the S5 lasertrap ring equals the
player position at trap spawn (C code says it must: lasertrap takes
cwclamp(global.plr.pos, 0, vp) as its center; sim.c:519 reports
laser->pos as the snapshot origin) or carries a systematic offset.

    venv\\Scripts\\python.exe tools\\diag_origins.py <tag> <stage> <plo-phi> <llo-lhi> [diff] [carry.json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING,
)
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from probe_evader import TraceMacro, load_trace_seq, DIFFS, LIB  # noqa: E402


def _range(s):
    a, b = s.split("-")
    return int(a), int(b)


def main():
    args = sys.argv[1:]
    tag, stage = args[0], int(args[1])
    plo, phi = _range(args[2])
    llo, lhi = _range(args[3])
    diff = DIFFS.get(args[4] if len(args) > 4 else "normal", DIFFICULTY_NORMAL)
    carry_file = args[5] if len(args) > 5 else None

    carry = {}
    if carry_file:
        cp_in = json.load(open(carry_file, encoding="utf-8"))
        carry = dict(cp_in.get("carry") or
                     (cp_in if "initial_score" in cp_in else {}))
        print("CARRY loaded: %s" % carry)

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
    ex = ReflexExecutor(allow_bombs=False, gap_horizon=True)
    ex.reset()

    seq = load_trace_seq(tag, stage)
    seq_idx = 0
    cur_macro = None
    frames = 0
    while frames < 30000:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, mid, foc = seq[seq_idx]
            cur_macro = TraceMacro(mid, foc, _f, resolve_macro_target(mid, v))
            seq_idx += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))
        px = float(v.raw.player.position.x)
        py = float(v.raw.player.position.y)

        if plo <= lf <= phi:
            print("player f=%d pos=(%.2f, %.2f) alive=%s invuln=%s" %
                  (lf, px, py, v.raw.player.alive,
                   v.raw.player.invulnerable))
        if llo <= lf <= lhi:
            lps = v.laser_points
            for L in v.lasers:
                if L.point_count == 0:
                    continue
                ox, oy = float(L.origin.x), float(L.origin.y)
                end = min(L.first_point + L.point_count, len(lps))
                xs, ys, rs = [], [], []
                for i in range(L.first_point, end):
                    ptx = float(lps[i].position.x)
                    pty = float(lps[i].position.y)
                    xs.append(ptx)
                    ys.append(pty)
                    rs.append(((ptx - ox) ** 2 + (pty - oy) ** 2) ** 0.5)
                rs.sort()
                med = rs[len(rs) // 2]
                print("f=%d laser id=%d origin=(%.1f, %.1f) npts=%d "
                      "active=%s med_r=%.1f bbox=(%.0f..%.0f, %.0f..%.0f) "
                      "pt_cen=(%.1f, %.1f) player_d=%.0f" %
                      (lf, L.spawn_id, ox, oy, L.point_count,
                       L.collision_active, med,
                       min(xs), max(xs), min(ys), max(ys),
                       sum(xs) / len(xs), sum(ys) / len(ys),
                       ((ox - px) ** 2 + (oy - py) ** 2) ** 0.5))
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))
        frames += 1
        if lf > max(phi, lhi) + 50:
            break
    sim.destroy()
    sim.global_shutdown()
    print("== done: frames=%d ==" % frames)


if __name__ == "__main__":
    main()
