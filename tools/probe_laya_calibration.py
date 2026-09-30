"""Probe Laya answer calibration across checkpoint models, question names,
and state texts (2026-09-26).

Questions a single batch of predict calls:
  * `bomb_now`   (noul)  - the EVADE criteria under the in-distribution name
  * `evade`      (noul)  - the same criteria under a NEW name
  * `evade_choice` (choice) - stay vs evade, NEW name, 2 options
  * `move`       (choice) - the stock 8-way macro choice (guard_p reference)

    venv\Scripts\python.exe tools\probe_laya_calibration.py [model ...]

Defaults to probing auto/english/typed-decisions/multilingual over four
state texts (safe / mid / dangerous-bottom / heavy-pressure) plus a
repeat-noise check on the dangerous state.
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from laya_client import LayaClient  # noqa: E402
from agent import QUESTIONS  # noqa: E402

EVADE_INSTRUCTIONS = (
    "Must the player leave the guard position RIGHT NOW to avoid a hit? "
    "Use the state line and answer YES only when at least one of these is "
    "true: (a) the nearest bullet will hit you in fewer than about 30 "
    "frames; (b) you are within 40 px of any edge with bullet pressure "
    "toward that edge; (c) the bullet pressure in any direction is 8 or "
    "more. Otherwise answer NO. Do NOT answer YES just because bullets "
    "exist — answer YES only when staying put will get you hit."
)

STATES = {
    "safe": ("Frame 100 of stage 2 (Normal). You have 2 life(s) and 0 bomb(s). "
             "You are at (240, 470); the playable field is x 16-464, y 16-544. "
             "No bullet will hit you within 45 frames. "
             "Bullet pressure up/down/left/right: 0/0/0/1."),
    "mid": ("Frame 100 of stage 2 (Normal). You have 2 life(s) and 0 bomb(s). "
            "You are at (240, 460); the playable field is x 16-464, y 16-544. "
            "The nearest bullet will hit you in about 35 frames. "
            "Bullet pressure up/down/left/right: 4/1/3/2."),
    "danger-bottom": ("Frame 100 of stage 2 (Normal). You have 2 life(s) and "
                      "0 bomb(s). You are at (348, 510); the playable field "
                      "is x 16-464, y 16-544. The nearest bullet will hit "
                      "you in about 4 frames. "
                      "Bullet pressure up/down/left/right: 6/2/4/4. You are "
                      "near the bottom 34 px edge(s)."),
    "heavy-pressure": ("Frame 100 of stage 2 (Normal). You have 2 life(s) "
                       "and 0 bomb(s). You are at (240, 400); the playable "
                       "field is x 16-464, y 16-544. The nearest bullet will "
                       "hit you in about 20 frames. "
                       "Bullet pressure up/down/left/right: 12/2/9/10."),
}


def build_questions():
    q = copy.deepcopy(QUESTIONS)
    q["bomb_now"]["instructions"] = EVADE_INSTRUCTIONS
    q["evade"] = {"type": "noul", "instructions": EVADE_INSTRUCTIONS}
    q["evade_choice"] = {
        "type": "choice",
        "instructions": (
            "Where should the player be for the next moment? STAY: hold the "
            "guard position. EVADE: leave the guard position now, because "
            "staying there will get you hit soon (a bullet hits within about "
            "30 frames, you are within 40 px of an edge with pressure "
            "toward it, or pressure in any direction is 8 or more)."),
        "criteria": {
            "stay": "Hold the guard position (the safe default when open space is around you)",
            "evade": "Leave the guard position now to avoid a hit",
        },
    }
    return q


def main():
    models = sys.argv[1:] or ["auto", "english", "typed-decisions",
                              "multilingual"]
    q = build_questions()
    c = LayaClient(base_url="http://127.0.0.1:8002")
    print("health:", c.health().get("status"))
    for mname in models:
        model = None if mname == "auto" else mname
        for sname, state in STATES.items():
            try:
                r = c.predict(state, q, model=model)
            except Exception as e:  # noqa: BLE001
                print("%-16s %-16s ERROR %s" % (mname, sname, e))
                continue
            a = r["answers"]
            routed = (r.get("routing") or {}).get("model")
            bn = (a.get("bomb_now") or {}).get("noul")
            ev = (a.get("evade") or {}).get("noul")
            ec = (a.get("evade_choice") or {}).get("choice")
            ecp = (a.get("evade_choice") or {}).get("probabilities") or {}
            mv = (a.get("move") or {}).get("choice")
            mvp = (a.get("move") or {}).get("probabilities") or {}
            print("%-16s %-16s routed=%-16s bomb_now(eva)=%s evade=%s "
                  "choice=%s(ev %.2f) move=%s(guard %.2f)" % (
                      mname, sname, routed,
                      None if bn is None else round(bn, 3),
                      None if ev is None else round(ev, 3),
                      ec, ecp.get("evade", -1),
                      mv, mvp.get("guard", -1)))
    # repeat-noise check on the dangerous state
    print("--- repeat noise (danger-bottom, 4x each) ---")
    for mname in ("auto", "typed-decisions"):
        model = None if mname == "auto" else mname
        vals = []
        for _ in range(4):
            r = c.predict(STATES["danger-bottom"], q, model=model)
            a = r["answers"]
            vals.append((round((a.get("bomb_now") or {}).get("noul", -1), 3),
                         (a.get("evade_choice") or {}).get("choice")))
        print("%-16s bomb_now/choice: %s" % (mname, vals))


if __name__ == "__main__":
    main()
