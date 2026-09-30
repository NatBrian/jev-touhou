"""R4.6 verification (2026-09-26): compile the CURRENT state compiler
output on dense frames of a recorded campaign and measure the server's
`usage.input_tokens` against the 2048 cap.

Replays a stage with the recorded macro sequence (no Laya macro calls;
Laya is only queried with the freshly compiled state text) and prints,
per sampled frame: state chars (new compiler) and measured input_tokens.

    venv\Scripts\python.exe tools\check_state_tokens.py <tag> <stage> [f1,f2,...] [normal]

Target (G2.95 gate): max input_tokens < 2048 on the densest frames.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))
sys.path.insert(0, os.path.join(HERE, "tools"))

from taisei_sim import (  # noqa: E402
    TaiseiSim, EpisodeConfig, register_runtime_dirs, PROJ_ENEMY,
    CHAR_MARISA, SHOT_A, DIFFICULTY_NORMAL, STATUS_RUNNING)
from state_compiler import compile_state  # noqa: E402
from macros import resolve_macro_target  # noqa: E402
from executor import ReflexExecutor  # noqa: E402
from laya_client import LayaClient  # noqa: E402
from agent import NO_BOMB_QUESTIONS  # noqa: E402
from dump_probe_states import (  # noqa: E402
    DIFFS, LIB, TraceMacro, load_trace_seq)

SIM_ROOT = os.path.join(HERE, "third_party", "taisei-sim")
DATA = os.path.join(HERE, "simdata")


def main():
    tag, stage = sys.argv[1], int(sys.argv[2])
    frames = sorted(int(x) for x in sys.argv[3].split(",")) if len(sys.argv) > 3 \
        else []
    diff = DIFFS.get(sys.argv[4] if len(sys.argv) > 4 else "normal",
                     DIFFICULTY_NORMAL)
    if not frames:
        # default: a spread across the stage
        frames = [500, 1500, 3000, 5000, 7000, 9000, 11000]

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
    ex = ReflexExecutor(allow_bombs=False, gap_horizon=True)
    ex.reset()

    c = LayaClient()
    print("health:", json.dumps(c.health())[:120])

    todo = set(frames)
    max_tokens, max_chars, max_len = 0, 0, 0
    seen = {}
    seq_idx = 0
    cur_macro = None
    while int(sim.get_state().raw.logical_frame) < 30000:
        v = sim.get_state()
        if v.raw.episode_status != STATUS_RUNNING:
            break
        lf = int(v.raw.logical_frame)
        while seq_idx < len(seq) and lf >= seq[seq_idx][0]:
            _f, _mid, foc = seq[seq_idx]
            cur_macro = TraceMacro(_mid, foc, _f,
                                   resolve_macro_target(_mid, v))
            seq_idx += 1
        if cur_macro is None:
            cur_macro = TraceMacro("guard", False, lf,
                                   resolve_macro_target("guard", v))
        if lf in todo:
            text = compile_state(v)
            hazards = len([p for p in v.projectiles
                           if p.category == PROJ_ENEMY and p.flags & 16])
            seen[lf] = (len(text), hazards, text)
            todo.discard(lf)
        sim.step(buttons=ex.execute(cur_macro, v))
    sim.destroy()
    sim.global_shutdown()

    print("== measured input_tokens (new compiler, no-bomb schema) ==")
    for lf in sorted(seen):
        n, hz, text = seen[lf]
        r = c.predict(text, NO_BOMB_QUESTIONS)
        tok = r["usage"]["input_tokens"]
        max_tokens, max_chars, max_len = (max(max_tokens, tok),
                                          max(max_chars, n), max(max_len, hz))
        print("f%-6d state_chars=%4d hazards=%3d -> input_tokens=%d %s"
              % (lf, n, hz, tok,
                 "(AT CAP)" if tok >= 2048 else ""))
    print("MAX: input_tokens=%d (cap 2048), state_chars=%d"
          % (max_tokens, max_chars))


if __name__ == "__main__":
    main()
