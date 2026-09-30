"""Probe Laya answers over REAL full-state texts (from a campaign replay)
across checkpoint models (2026-09-26). Companion to
tools/probe_laya_calibration.py, which used synthetic short states.

For every state file in the directory and every model it prints:
  * `bomb_now` repurposed to the EVADE criteria (in-distribution name)
  * `evade` (new name, same criteria) and `evade_dir` (R4 set)
  * `move` choice + guard probability
  * the ORIGINAL bomb-allowed question set for reference (bomb_now orig)

    venv\Scripts\python.exe tools\probe_laya_states.py <states-dir> [model ...]
"""
import copy
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from laya_client import LayaClient  # noqa: E402
from agent import QUESTIONS, NO_BOMB_QUESTIONS  # noqa: E402

EVADE_INSTRUCTIONS = (
    "Must the player leave the guard position RIGHT NOW to avoid a hit? "
    "Use the state line and answer YES only when at least one of these is "
    "true: (a) the nearest bullet will hit you in fewer than about 30 "
    "frames; (b) you are within 40 px of any edge with bullet pressure "
    "toward that edge; (c) the bullet pressure in any direction is 8 or "
    "more. Otherwise answer NO. Do NOT answer YES just because bullets "
    "exist — answer YES only when staying put will get you hit."
)


def no_bomb_evade_set():
    """Current no-bomb set with bomb_now REPURPOSED to the evade criteria."""
    q = copy.deepcopy(NO_BOMB_QUESTIONS)
    q["bomb_now"]["instructions"] = EVADE_INSTRUCTIONS
    return q


def main():
    dirpath = sys.argv[1]
    models = sys.argv[2:] or ["english", "typed-decisions", "multilingual"]
    files = sorted(glob.glob(os.path.join(dirpath, "f*.txt")),
                   key=lambda p: int(re.search(r"f(\d+)", p).group(1)))
    if not files:
        print("no state files in", dirpath)
        return
    q_nb = no_bomb_evade_set()
    c = LayaClient(base_url="http://127.0.0.1:8002")
    print("health:", c.health().get("status"), "files:", len(files))
    for fpath in files:
        name = os.path.basename(fpath)
        state = open(fpath, encoding="utf-8").read()
        i = state.find("You are at (")
        summary = state[i:state.find(". You", i + 10)] if i >= 0 else ""
        print("== %s (%d chars) %s" % (name, len(state), summary[:120]))
        for mname in models:
            try:
                r = c.predict(state, q_nb, model=mname)
                a = r["answers"]
            except Exception as e:  # noqa: BLE001
                print("   %-16s ERROR %s" % (mname, e))
                continue
            bn = (a.get("bomb_now") or {}).get("noul")
            ev = (a.get("evade") or {}).get("noul")
            ed = (a.get("evade_dir") or {}).get("choice")
            mv = (a.get("move") or {}).get("choice")
            g = (a.get("move") or {}).get("probabilities") or {}
            try:
                r2 = c.predict(state, QUESTIONS, model=mname)
                bno = ((r2.get("answers") or {}).get("bomb_now")
                       or {}).get("noul")
            except Exception as e:  # noqa: BLE001
                bno = "ERR"
            print("   %-16s bomb_now(eva)=%s evade=%s dir=%-14s "
                  "move=%-14s guard_p=%.2f | orig bomb_now=%s" % (
                      mname,
                      None if bn is None else round(bn, 3),
                      None if ev is None else round(ev, 3),
                      ed, mv, g.get("guard", -1),
                      None if bno is None else round(bno, 3)))


if __name__ == "__main__":
    main()
