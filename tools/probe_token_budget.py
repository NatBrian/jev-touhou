"""Probe the Laya server's token budget and truncation behavior.

    venv\Scripts\python.exe tools\probe_token_budget.py

Questions answered:
  1. How many input tokens does the bare question schema cost (baseline)?
  2. How do state chars scale to tokens?
  3. Where is the cap, and when exceeded, which end is truncated (state
     tail or questions)? Markers at the state head/middle/tail plus a
     choice question asking which markers are visible reveal the order.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))
from laya_client import LayaClient  # noqa: E402
from agent import NO_BOMB_QUESTIONS  # noqa: E402


def main():
    c = LayaClient()
    h = c.health()
    print("health:", json.dumps(h)[:160])

    # 1. baseline: trivial state + full no-bomb schema
    r = c.predict("test", NO_BOMB_QUESTIONS)
    base = r["usage"]["input_tokens"]
    print("baseline (state='test')  input_tokens=%s server_ms=%s"
          % (base, r.get("_server_ms")))

    # 2. scaling: pad the state with repeated tokens
    for n in (200, 600, 1000, 1400, 1800, 2200):
        pad = "alpha " * (n // 6)
        r = c.predict(pad, NO_BOMB_QUESTIONS)
        print("state %5d chars (%5d tokens est) -> input_tokens=%s cap_reached=%s"
              % (len(pad), len(pad) // 4, r["usage"]["input_tokens"],
                 r["usage"]["input_tokens"] >= 2048))

    # 3. truncation order: markers at head/middle/tail of a >cap state
    head = "MARK_HEAD visible."
    tail = "MARK_TAIL visible."
    mid = "MARK_MID visible."
    filler = "noise padding sentence for length. " * 160   # ~4480 chars
    state = head + " " + filler[:1200] + " " + mid + " " + filler[:1200] + " " + tail
    q = {
        "markers": {
            "type": "choice",
            "instructions": ("List which of the markers MARK_HEAD, MARK_MID, "
                             "MARK_TAIL you can see in the state text. Choose "
                             "the option that best matches."),
            "criteria": {
                "all_three": "all three markers are visible",
                "head_mid": "only MARK_HEAD and MARK_MID are visible",
                "head_only": "only MARK_HEAD is visible",
                "none": "none of the markers are visible",
            },
        },
        "q2": {"type": "noul",
               "instructions": "Is the string MARK_TAIL present in the state?"},
    }
    r = c.predict(state, q)
    print("marker state %d chars -> input_tokens=%s"
          % (len(state), r["usage"]["input_tokens"]))
    print("  markers choice: %s probs=%s"
          % (r["answers"]["markers"].get("choice"),
             json.dumps(r["answers"]["markers"].get("probabilities"))))
    print("  q2 noul: %s" % r["answers"]["q2"].get("noul"))
    print("  usage:", json.dumps(r.get("usage")))


if __name__ == "__main__":
    main()
