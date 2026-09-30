"""Replay a measured stage and inspect the evader's laser pipeline at the
requested frames (2026-09-26, S4/S6 laser-death forensics).

For each requested frame prints, per collision-active laser:
  age/speed/timespan/deathtime/timeshift, the executor's t_max, point
  time min/max, and the closest point to the player.  Then the evader's
  _collect_hazards output: seg counts and _laser_risk at the player pos
  and the 9 candidate positions for segs_now / segs_full.

    venv\Scripts\python.exe tools\diag_laser.py <tag> <stage> <f1,f2,...> <carry-json>
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
from macros import MacroTarget, resolve_macro_target  # noqa: E402
from executor import ReflexExecutor, THREAT_HORIZON  # noqa: E402

LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")

DIRS = [(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0),
        (-1, -1), (1, -1), (-1, 1), (1, 1)]


class TraceMacro:
    source = "trace"
    bomb = False
    danger_score = -1.0

    def __init__(self, macro_id, focus, issued_frame, target):
        self.macro_id = macro_id
        self.focus = focus
        self.issued_frame = issued_frame
        self.target = target


def load_trace_seq(tag):
    path = os.path.join(DATA, "laya-%s.jsonl" % tag)
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    seq = [(int(r["frame"]), r.get("macro", "guard"),
            bool(r.get("focus_eff", False)))
           for r in rows if r.get("status") == "ok"]
    seq.sort()
    return seq


def main():
    tag, stage = sys.argv[1], int(sys.argv[2])
    frames = sorted(set(int(x) for x in sys.argv[3].split(",")))
    carry = json.load(open(sys.argv[4], encoding="utf-8"))
    if "--lives" in sys.argv:
        carry["initial_lives"] = int(sys.argv[sys.argv.index("--lives") + 1])

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
        stage_id=stage, difficulty=DIFFICULTY_NORMAL,
        player_character=CHAR_MARISA, shot_mode=SHOT_A,
        rng_seed=12345 + stage, **carry,
    ))
    ex = ReflexExecutor(allow_bombs=False, gap_horizon=True)
    ex.reset()

    seq = load_trace_seq(tag)
    todo = set(frames)
    seq_idx, cur_macro, f = 0, None, 0
    while f < 40000 and todo:
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
        if lf in todo:
            px, py = (float(v.raw.player.position.x),
                      float(v.raw.player.position.y))
            print("== f%d  player=(%.1f, %.1f)  beams=%d"
                  % (lf, px, py, sum(1 for L in v.lasers
                                     if L.collision_active)))
            lps = v.laser_points
            for i, L in enumerate(v.lasers):
                if not L.collision_active:
                    continue
                end = min(L.first_point + L.point_count, len(lps))
                times = [lps[j].time for j in range(L.first_point, end)]
                dmin, dpt = 1e9, None
                for j in range(L.first_point, end):
                    dx = lps[j].position.x - px
                    dy = lps[j].position.y - py
                    d = (dx * dx + dy * dy) ** 0.5
                    if d < dmin:
                        dmin, dpt = d, (float(lps[j].position.x),
                                         float(lps[j].position.y))
                if L.death_time > 0:
                    tmax = min(THREAT_HORIZON,
                               L.death_time + L.time_shift - L.age_frames)
                else:
                    tmax = THREAT_HORIZON
                print("  beam%-3d pts=%-4d t=[%+.1f,%+.1f] tmax=%+.1f  "
                      "age=%d speed=%.2f span=%.1f death=%.1f shift=%.1f"
                      "  closest pt dist=%.1f at (%.0f,%.0f) width=%.1f"
                      % (i, L.point_count,
                         min(times) if times else 0,
                         max(times) if times else 0, tmax,
                         L.age_frames, L.speed, L.timespan,
                         L.death_time, L.time_shift,
                         dmin, *(dpt or (0, 0)), L.width))
            hazards, segs_now, segs_full = ex._collect_hazards(v, px, py, False)
            print("  evader: hazards=%d segs_now=%d segs_full=%d"
                  % (len(hazards), len(segs_now), len(segs_full)))
            print("  laser_risk @player  now=%.2f  full=%.2f"
                  % (ex._laser_risk(px, py, segs_now, ex.player_radius),
                     ex._laser_risk(px, py, segs_full, ex.player_radius)))
            for (dx, dy) in DIRS:
                nx = max(16, min(464, px + dx * 6.25))
                ny = max(16, min(544, py + dy * 6.25))
                print("    cand(%+d,%+d) now=%.2f full=%.2f"
                      % (dx, dy,
                         ex._laser_risk(nx, ny, segs_now, ex.player_radius),
                         ex._laser_risk(nx, ny, segs_full,
                                        ex.player_radius)))
            todo.discard(lf)
        sim.step(buttons=ex.execute(cur_macro, v))
        f += 1
    if todo:
        print("WARNING: frames never reached:", sorted(todo))
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
