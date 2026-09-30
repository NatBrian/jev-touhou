"""Diagnose the S5 lasertrap ball field (2026-09-26, R5.2).

Replays the given stage with the base evader (no ring escape) and dumps,
per frame, the player position, the count of enemy projectiles inside
150 px, and the 4 nearest projectiles (distance, collision radius, speed).
This reveals WHEN the trap balls appear, their radius, how close they get
to the player, and the exact death frame/cause.

    venv\\Scripts\\python.exe tools\\diag_trap.py <tag> <stage> <lo> <hi>
    (optional 5th arg = difficulty, default normal)

Prints one line per frame in [lo, hi] where either deaths changed or the
nearby-projectile count >= 6, plus always the first/last frame of the range.
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
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING, PROJ_ENEMY,
)
from macros import MacroTarget, resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from probe_evader import TraceMacro, load_trace_seq, DIFFS, LIB, DATA as PDATA  # noqa: E402


class Macro:
    def __init__(self, mid, focus, f, target):
        self.macro_id = mid
        self.focus = focus
        self.issued_frame = f
        self.target = target
        self.bomb = False


def main():
    args = sys.argv[1:]
    tag, stage, lo, hi = args[0], int(args[1]), int(args[2]), int(args[3])
    diff = DIFFS.get(args[4] if len(args) > 4 else "normal", DIFFICULTY_NORMAL)
    carry_file = args[5] if len(args) > 5 else None
    dump_hazards = len(args) > 6 and args[6] == "hazards"
    print_all = len(args) > 7 and args[7] == "all"

    carry = {}
    if carry_file:
        cp_in = json.load(open(carry_file, encoding="utf-8"))
        carry = dict(cp_in.get("carry") or
                     (cp_in if "initial_score" in cp_in else {}))
        print("CARRY loaded: %s" % carry)

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
    sim.reset(EpisodeConfig(
        stage_id=stage, difficulty=diff, player_character=CHAR_MARISA,
        shot_mode=SHOT_A, rng_seed=12345 + stage, **carry,
    ))
    ex = ReflexExecutor(allow_bombs=False)
    ex.reset()

    seq = load_trace_seq(tag, stage)
    seq_idx = 0
    cur_macro = None
    prev_deaths = 0
    printed = 0
    frames = 0
    prev_px, prev_py = 240.0, 496.0
    ring_center = None
    while frames < 30000:
        v = sim.get_state()
        st = v.raw.episode_status
        if st != STATUS_RUNNING:
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, mid, foc = seq[seq_idx]
            cur_macro = Macro(mid, foc, _f, resolve_macro_target(mid, v))
            seq_idx += 1
        if cur_macro is None:
            cur_macro = Macro("guard", False, lf,
                              resolve_macro_target("guard", v))
        px = float(v.raw.player.position.x)
        py = float(v.raw.player.position.y)
        d = int(v.raw.deaths)

        # track the trap center (the laser with the most points = the ring)
        best_laser_pts = 0
        for L in v.lasers:
            if L.point_count > best_laser_pts:
                best_laser_pts = L.point_count
                ring_center = (float(L.origin.x), float(L.origin.y))

        # collect nearby enemy projectiles
        near = []
        # ball-ring radius from the trap center (largest same-origin group)
        cx_ring, cy_ring, n_ring, rmin, rmax = (None, None, 0, 0.0, 0.0)
        if ring_center is not None and best_laser_pts >= 40:
            cx_ring, cy_ring = ring_center
            for p in v.projectiles:
                if p.category != PROJ_ENEMY:
                    continue
                dx = p.position.x - cx_ring
                dy = p.position.y - cy_ring
                dd = (dx * dx + dy * dy) ** 0.5
                if dd > 400:
                    continue
                n_ring += 1
                rmin = dd if rmin == 0 else min(rmin, dd)
                rmax = max(rmax, dd)
        for p in v.projectiles:
            if p.category != PROJ_ENEMY:
                continue
            dx = p.position.x - px
            dy = p.position.y - py
            dd = dx * dx + dy * dy
            if dd > 150.0 * 150.0:
                continue
            r = max(p.collision_size.x, p.collision_size.y)
            sp = (p.velocity.x * p.velocity.x + p.velocity.y * p.velocity.y) ** 0.5
            near.append((dd ** 0.5, r, sp))
        near.sort()

        if lo <= lf <= hi:
            death_mark = "  <-- DEATH" if d > prev_deaths else ""
            ring_str = ""
            if ring_center is not None and n_ring > 0:
                dpx = px - cx_ring
                dpy = py - cy_ring
                d_ring = (dpx * dpx + dpy * dpy) ** 0.5
                ring_str = (" | ring c=(%.0f,%.0f) d_ring=%.0f "
                            "ballR=%.0f-%.0f(n=%d)" %
                            (cx_ring, cy_ring, d_ring, rmin, rmax, n_ring))
            if print_all or d > prev_deaths or len(near) >= 6 or printed == 0:
                nstr = " | ".join(
                    "d=%.0f r=%.0f sp=%.1f" % (a, b, c) for a, b, c in near[:3])
                print("f=%-5d p=(%6.1f,%6.1f) deaths=%d near150=%d%s  %s%s" %
                      (lf, px, py, d, len(near), ring_str, nstr, death_mark))
                printed += 1
            if d > prev_deaths and dump_hazards:
                # full hazard + laser dump at the death, relative to the
                # death position (the frame before the respawn cutscene)
                dx0, dy0 = prev_px, prev_py
                print("  -- HAZARDS at death f=%d p=(%.1f, %.1f) --" %
                      (lf, dx0, dy0))
                for p in v.projectiles:
                    if p.category != PROJ_ENEMY:
                        continue
                    dx = p.position.x - dx0
                    dy = p.position.y - dy0
                    dd = (dx * dx + dy * dy) ** 0.5
                    if dd > 200:
                        continue
                    r = max(p.collision_size.x, p.collision_size.y)
                    sp = (p.velocity.x * p.velocity.x + p.velocity.y * p.velocity.y) ** 0.5
                    print("    proj (%.1f, %.1f) d=%.0f r=%.0f sp=%.1f" %
                          (p.position.x, p.position.y, dd, r, sp))
                lps = v.laser_points
                for L in v.lasers:
                    if L.point_count == 0:
                        continue
                    ox, oy = float(L.origin.x), float(L.origin.y)
                    end = min(L.first_point + L.point_count, len(lps))
                    dmin = 9999.0
                    for i in range(L.first_point, end):
                        ptx = lps[i].position.x - dx0
                        pty = lps[i].position.y - dy0
                        dmin = min(dmin, (ptx * ptx + pty * pty) ** 0.5)
                    if dmin < 200:
                        print("    laser origin=(%.1f, %.1f) npts=%d "
                              "active=%s dmin=%.0f" %
                              (ox, oy, L.point_count, L.collision_active, dmin))
        prev_deaths = d
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))
        frames += 1
        if frames > 0:
            prev_px, prev_py = px, py
        if lf > hi + 50:
            break
    sim.destroy()
    sim.global_shutdown()
    print("== done: frames=%d deaths=%d ==" % (frames, prev_deaths))


if __name__ == "__main__":
    main()
