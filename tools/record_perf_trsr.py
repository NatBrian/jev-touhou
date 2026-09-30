"""record_perf_trsr.py — re-record a campaign stage's .trsr with PER-FRAME
desync check events (TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY=1), using the EXACT
same replay setup as render_jev_showcase.py / dump_replay_scores.py (trace
macro sequence + VA4/blind/ring executor, build-gl33 DLL, seed 12345+stage,
checkpoint carry).

The resulting trsr lets a taisei.exe replay verify its (rng^points) digest
against the recording at EVERY frame, so the first divergence frame of a
gl33 capture run is logged precisely.

    venv\Scripts\python.exe tools\record_perf_trsr.py <tag> <stage> <out.trsr>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")
sys.path.insert(0, os.path.join(HERE, "harness"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# MUST be set before the stage starts (read at stage frame-state init).
os.environ["TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY"] = "1"

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
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    tag, stage = sys.argv[1], int(sys.argv[2])
    out = sys.argv[3]

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

    di = 0
    cur_macro = None
    frames = 0
    while True:
        v = sim.get_state()
        lf = int(v.raw.logical_frame)
        st = int(v.raw.episode_status)

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

        frames = lf
        if terminal:
            break
        ex._view = v
        sim.step(buttons=ex.execute(cur_macro, v))

    sim.save_replay(os.path.abspath(out))
    print("recorded %s frames=%d decisions=%d death_hits=%s -> %s"
          % (tag, frames, len(decisions), death_hits, out))
    sim.destroy()
    sim.global_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
