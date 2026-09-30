"""dump_replay_scores.py — headless dump of the sim score trajectory for a
recorded campaign stage, using the EXACT same replay setup as
render_jev_showcase.py (trace macro sequence + VA4/blind/ring executor,
build-gl33 DLL, seed 12345+stage, checkpoint carry).

Prints (frame, score, power, piv, graze, lives, deaths) every N frames +
around every death + at the terminal frame. Used to compare the sim's
ground-truth trajectory against the HUD of a taisei.exe replay capture.

    venv\\Scripts\\python.exe tools\\dump_replay_scores.py <tag> <stage> [N]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING,
)
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from agent import Agent  # noqa: E402
from dump_probe_states import TraceMacro  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
LIB = os.path.join(SIM_ROOT, "build-gl33", "src", "sim", "libtaisei_sim.dll")


def start_carry(tag, cp):
    """Start-of-stage carry from the checkpoint's "carried_from"
    (None=fresh, int=prev-stage checkpoint, str=carry file). The
    checkpoint's own "carry" field is the END-of-stage carry."""
    cf = cp.get("carried_from")
    if cf is None:
        return {}
    if isinstance(cf, int):
        prev = json.load(open(os.path.join(DATA, "checkpoints",
                                           "%s-stage%d.json" % (tag, cf)),
                              encoding="utf-8"))
        return dict(prev.get("carry") or {})
    with open(cf, encoding="utf-8") as f:
        d = json.load(f)
    return dict(d.get("carry") or (d if "initial_score" in d else {}))


def load_stage(tag, stage):
    path = os.path.join(DATA, "laya-%s.jsonl" % tag)
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    segs, cur, prev = [], [], None
    for r in rows:
        f_ = r.get("frame")
        if prev is not None and isinstance(f_, int) and f_ < prev:
            segs.append(cur)
            cur = []
        cur.append(r)
        prev = f_
    if cur:
        segs.append(cur)
    seg = segs[0] if len(segs) == 1 else segs[stage - 1]
    decisions = [r for r in seg if r.get("status") == "ok"
                 and r.get("state_sha1")]
    decisions.sort(key=lambda r: r["frame"])
    death_hits = sorted(r["frame"] for r in seg
                        if r.get("status") == "death_hit")
    cp = json.load(open(os.path.join(DATA, "checkpoints",
                                     "%s-stage%d.json" % (tag, stage)),
                         encoding="utf-8"))
    return seg, decisions, death_hits, cp


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    tag, stage = sys.argv[1], int(sys.argv[2])
    N = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    seg, decisions, death_hits, cp = load_stage(tag, stage)
    # difficulty from the checkpoint (S6: support non-normal stages)
    diff_name = cp.get("difficulty", "normal")
    diff = DIFFS.get(diff_name, DIFFICULTY_NORMAL)
    carry = start_carry(tag, cp)
    if cp.get("no_bomb"):
        carry.update(initial_bombs=0, initial_bomb_fragments=0)

    register_runtime_dirs(
        os.path.join(HERE, "third_party", "mingw", "mingw64", "bin"))
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
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=False,
                        gap_horizon=True, laser_blind_fix=True,
                        laser_ring=True)
    ex.reset()

    print("tag=%s stage=%d diff=%s decisions=%d death_hits=%s"
          % (tag, stage, diff_name, len(decisions), death_hits))
    print("%8s %12s %8s %8s %8s %6s %7s"
          % ("frame", "score", "power", "piv", "graze", "lives", "deaths"))
    # (power = stored_power, as shown in the HUD "Power: XXX/400")

    di = 0
    cur_macro = None
    last_reported = -1
    death_reported = set()
    prev_deaths = 0

    while True:
        v = sim.get_state()
        lf = int(v.raw.logical_frame)
        st = int(v.raw.episode_status)
        pl = v.raw.player
        dcount = int(v.raw.deaths)

        terminal = st != STATUS_RUNNING
        if not terminal:
            while di < len(decisions) and lf >= decisions[di]["frame"]:
                row = decisions[di]
                mid, foc = row.get("macro", "guard"), bool(row.get("focus_eff"))
                if row.get("exile_eff") or row.get("evade_eff"):
                    tgt = Agent._evade_target(None, v)[0]
                else:
                    tgt = resolve_macro_target(mid, v)
                cur_macro = TraceMacro(mid, foc, row["frame"], tgt)
                di += 1
            if cur_macro is None:
                cur_macro = TraceMacro("guard", False, lf,
                                       resolve_macro_target("guard", v))

        if lf - last_reported >= N or terminal or lf in (1, 2, 3):
            last_reported = lf
            print("%8d %12d %8d %8d %8d %6d %7d%s"
                  % (lf, int(v.raw.score), int(pl.stored_power),
                     int(pl.point_item_value), int(pl.graze),
                     int(pl.lives) + 1, dcount,
                     "   <- TERMINAL" if terminal else ""))

        if dcount > prev_deaths:
            for dh in death_hits:
                if dh not in death_reported and lf >= dh:
                    death_reported.add(dh)
                    print("%8d %12d %8d %8d %8d %6d %7d   <- DEATH hit f%d"
                          % (lf, int(v.raw.score), int(pl.stored_power),
                             int(pl.point_item_value), int(pl.graze),
                             int(pl.lives) + 1, dcount, dh))
            prev_deaths = dcount

        if terminal:
            break
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))

    sim.destroy()
    sim.global_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
