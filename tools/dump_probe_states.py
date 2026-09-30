"""Dump full compiled state texts at selected frames of a recorded campaign
stage (2026-09-26). Replays the stage deterministically (same seed/carry,
exact macro+focus sequence from the trace) and writes compile_state(v) for
each requested frame, for Laya calibration probes.

    venv\Scripts\python.exe tools\dump_probe_states.py <tag> <stage> <f1,f2,...> [diff] [outdir]

Files land in <outdir>/f<frame>.txt (default simdata/probe-states/<tag>-s<stage>/).
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
from executor import ReflexExecutor  # noqa: E402
from state_compiler import compile_state, _dodge_hint  # noqa: E402

DIFFS = {"easy": 1, "normal": DIFFICULTY_NORMAL, "hard": 3, "lunatic": 4}
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


def load_trace_seq_full(tag, stage):
    """Trace decisions as 5-tuples (frame, macro, focus_eff, exile_eff,
    evade_eff).  The `macro` field is the REWRITTEN id (e.g.
    'exile_bottom' / 'sidestep_left') exactly as the live agent executed
    it; exile_eff/evade_eff tell the probe to resolve the target with
    Agent._evade_target instead of resolve_macro_target (fidelity fix
    2026-09-27: the live no-bomb agent rewrites macros to exile/sidestep
    targets, and a bare macro-id resolution drifts from the first exile)."""
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
    # a standalone stage run (--start-stage N) produces a single-segment
    # trace: the frame-decrease split never fires, so position-based
    # indexing would look up the wrong segment
    seg = segs[0] if len(segs) == 1 else segs[stage - 1]
    seq = [(int(r["frame"]), r.get("macro", "guard"),
            bool(r.get("focus_eff", False)),
            bool(r.get("exile_eff", False)),
            bool(r.get("evade_eff", False)))
           for r in seg if r.get("status") == "ok"]
    seq.sort()
    return seq


def load_trace_seq(tag, stage):
    """3-tuple wrapper (frame, macro, focus_eff) for consumers that do not
    need the exile/evade flags."""
    return [(f, m, foc) for f, m, foc, _e, _ev in load_trace_seq_full(tag, stage)]


def main():
    args = [a for a in sys.argv[1:]
            if a not in ("--edge-escape", "--gap-horizon")]
    edge_escape = "--edge-escape" in sys.argv
    gap_horizon = "--gap-horizon" in sys.argv
    tag = args[0]
    stage = int(args[1])
    frames = sorted(int(x) for x in args[2].split(","))
    diff = DIFFS.get(args[3] if len(args) > 3 else "normal",
                     DIFFICULTY_NORMAL)
    outdir = (args[4] if len(args) > 4
              else os.path.join(DATA, "probe-states", "%s-s%d" % (tag, stage)))
    os.makedirs(outdir, exist_ok=True)

    carry = {}
    cp_path = os.path.join(DATA, "checkpoints",
                           "%s-stage%d.json" % (tag, stage - 1))
    if stage > 1 and os.path.exists(cp_path):
        cp = json.load(open(cp_path, encoding="utf-8"))
        if cp.get("carry"):
            carry = cp["carry"]
    seq = load_trace_seq(tag, stage)

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
    ex = ReflexExecutor(allow_bombs=False, allow_edge_escape=edge_escape,
                        gap_horizon=gap_horizon)
    ex.reset()

    todo = set(frames)
    seq_idx = 0
    cur_mid = "guard"
    cur_focus = False
    cur_macro = None      # resolved target is pinned at the decision frame
    f = 0
    while f < 30000:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, _mid, foc = seq[seq_idx]
            cur_mid, cur_focus = _mid, foc
            # Re-pin the target from the state at THIS frame, exactly as the
            # live agent does at decision time (below_boss re-anchors per
            # frame inside the executor; point targets stay fixed).
            cur_macro = TraceMacro(cur_mid, cur_focus, _f,
                                   resolve_macro_target(cur_mid, v))
            seq_idx += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))
        if lf in todo:
            text = compile_state(v)
            out = os.path.join(outdir, "f%d.txt" % lf)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text)
            px, py = (float(v.raw.player.position.x),
                      float(v.raw.player.position.y))
            from taisei_sim import PROJ_ENEMY
            enemies = [p for p in v.projectiles
                       if p.category == PROJ_ENEMY and p.flags & 16]
            dl = _dodge_hint(enemies, px, py)
            i = dl.find("The nearest")
            if i < 0:
                i = dl.find("No bullet")
            print("f%-6d %4d chars  %s  macro=%s" % (lf, len(text), dl[i:],
                                                     cur_mid))
            todo.discard(lf)
            if not todo:
                f = 10 ** 9
        sim.step(buttons=ex.execute(cur_macro, v))
        f += 1
    if todo:
        print("WARNING: frames never reached:", sorted(todo))
    sim.destroy()
    sim.global_shutdown()
    print("wrote", outdir)


if __name__ == "__main__":
    main()
