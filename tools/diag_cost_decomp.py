"""Forensic cost decomposition at recorded death frames (2026-09-26).

Re-runs one stage deterministically (same seed/carry/build) driven by the
EXACT macro + focus sequence recovered from a campaign trace
(simdata/laya-<tag>.jsonl), then prints, for each recorded death_hit frame,
the player position, nearby bullets, the compiler's dodge line, and the
executor cost decomposition per heading (c_now / c_hor / c_2 / wall).

    venv\Scripts\python.exe tools\diag_cost_decomp.py <tag> <stage> [diff]

Use after a campaign to check what the executor actually saw at the hit.
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
from macros import MacroTarget  # noqa: E402
from executor import ReflexExecutor, MOVES  # noqa: E402
from state_compiler import _dodge_hint  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")


class TraceMacro:
    macro_id = "guard"
    source = "fallback"
    bomb = False
    danger_score = -1.0

    def __init__(self, focus, issued_frame):
        self.focus = focus
        self.issued_frame = issued_frame
        self.target = MacroTarget(kind="below_boss")


def load_trace_seq(tag, stage):
    """(frame -> (macro_id, focus)) for the given stage segment, plus the
    recorded death_hit frames."""
    path = os.path.join(DATA, "laya-%s.jsonl" % tag)
    rows = [json.loads(x) for x in open(path, encoding="utf-8")
            if x.strip()]
    # split at frame decreases
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
    seg = segs[stage - 1]
    seq = []
    deaths = []
    for r in seg:
        if r.get("status") == "ok":
            seq.append((int(r["frame"]), r.get("macro", "guard"),
                        bool(r.get("focus_eff", False))))
        elif r.get("status") == "death_hit":
            deaths.append(int(r["frame"]))
    seq.sort()
    return seq, deaths


def main():
    tag = sys.argv[1]
    stage = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    diff_name = sys.argv[3] if len(sys.argv) > 3 else "normal"
    seed = 12345
    diff = DIFFS.get(diff_name, DIFFICULTY_NORMAL)

    # carry from the stage-1 (or previous) checkpoint
    carry = {}
    cp_path = os.path.join(DATA, "checkpoints",
                           "%s-stage%d.json" % (tag, stage - 1))
    if stage > 1 and os.path.exists(cp_path):
        cp = json.load(open(cp_path, encoding="utf-8"))
        if cp.get("carry"):
            carry = cp["carry"]
    seq, deaths = load_trace_seq(tag, stage)
    print("tag=%s stage=%d decisions=%d death_frames=%s carry=%s"
          % (tag, stage, len(seq), deaths, carry), flush=True)

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
        shot_mode=SHOT_A, rng_seed=seed + stage, **carry,
    ))
    ex = ReflexExecutor(allow_bombs=False)
    ex.reset()

    def decomp(v, px, py, speed):
        hazards, segs_now, segs_full = ex._collect_hazards(v, px, py, False)
        names = ["stay", "up", "down", "left", "right",
                 "up-left", "up-right", "down-left", "down-right"]
        out = []
        for i, (unit, _b) in enumerate(MOVES):
            dx, dy = unit
            nx, ny = ex._clamp_position(px + dx * speed, py + dy * speed)
            c_now = (ex._risk_at(nx, ny, hazards, 0.0, ex.player_radius)
                     + ex._laser_risk(nx, ny, segs_now, ex.player_radius)
                     + ex._swept_risk(px, py, nx, ny, hazards, ex.player_radius))
            c_hor = (ex._risk_at(nx, ny, hazards, 36.0, ex.player_radius)
                     + ex._laser_risk(nx, ny, segs_full, ex.player_radius))
            nx2, ny2 = ex._clamp_position(nx + dx * speed, ny + dy * speed)
            c_2 = (ex._risk_at(nx2, ny2, hazards, 0.0, ex.player_radius)
                   + ex._laser_risk(nx2, ny2, segs_now, ex.player_radius))
            wall = ex._wall_cost(nx, ny)
            out.append((names[i], round(c_now, 2), round(0.5 * c_hor, 2),
                        round(0.2 * c_2, 2), round(wall, 3),
                        round(c_now + 0.5 * c_hor + 0.2 * c_2 + wall, 2)))
        return out

    seq_idx = 0
    cur_focus = False
    f = 0
    max_frames = 20000
    while f < max_frames:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            print("END status=%s frame=%d deaths=%d" % (
                {2: "WON", 3: "LOST"}.get(v.raw.episode_status,
                                          v.raw.episode_status),
                v.raw.logical_frame, v.raw.deaths), flush=True)
            break
        lf = int(v.raw.logical_frame)
        if seq and seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, mid, foc = seq[seq_idx]
            cur_focus = foc
            seq_idx += 1
            while seq_idx < len(seq) and seq[seq_idx][0] <= lf:
                _f, mid, foc = seq[seq_idx]
                cur_focus = foc
                seq_idx += 1
        macro = TraceMacro(cur_focus, lf)
        if lf in deaths:
            pl = v.raw.player
            px, py = float(pl.position.x), float(pl.position.y)
            enemies = [p for p in v.projectiles
                       if p.category == PROJ_ENEMY and p.flags & 16]
            near = sorted(
                ({"d": round(((p.position.x - px) ** 2
                              + (p.position.y - py) ** 2) ** 0.5, 1),
                  "vx": round(float(p.velocity.x), 1),
                  "vy": round(float(p.velocity.y), 1),
                  "r": round(float(max(p.collision_size.x,
                                       p.collision_size.y)), 1)}
                 for p in enemies
                 if ((p.position.x - px) ** 2
                     + (p.position.y - py) ** 2) ** 0.5 < 250),
                key=lambda h: h["d"])
            print("\n=== DEATH FRAME %d pos=(%.1f, %.1f) ===" % (lf, px, py))
            print("dodge line: " + _dodge_hint(enemies, px, py))
            print("near<250: n=%d" % len(near))
            for h in near[:12]:
                print("   d=%-6s v=(%s,%s) r=%s" % (h["d"], h["vx"], h["vy"], h["r"]))
            speed = 2.75 if cur_focus else 6.25
            for row in decomp(v, px, py, speed):
                print("   %-9s now=%-8s hor=%-8s c2=%-7s wall=%-5s total=%s"
                      % row)
        buttons = ex.execute(macro, v)
        sim.step(buttons=buttons)
        f += 1
    sim.destroy()
    sim.global_shutdown()


if __name__ == "__main__":
    main()
