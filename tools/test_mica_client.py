"""Quick validation of harness/laya_client.MicaClient against the Mica server
on the Laya host
server (mica-v0.1-4b, :8010). Mirrors tools/test_laya_client.py.

    venv\Scripts\python.exe tools/test_mica_client.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))
from laya_client import MicaClient, LayaUnavailableError  # noqa: E402

STATE = {
    "scene": "boss fight, stage 1",
    "player": "pos (240,420), 3 lives, 0 bombs, power 2/5, moving slowly",
    "nearest_bullets": "6 enemy bullets within 90px, dense cluster closing from upper-left, gap at upper-left of player",
    "boss": "boss at (240,120), spell 'Mystic Light Ring' 12s left, dealing heavy damage",
}
QUESTIONS = {
    "move": {
        "type": "choice",
        "instructions": "Pick the best movement macro for the player right now.",
        "criteria": {
            "hold_center": "Stay near center and keep shooting",
            "drift_upleft": "Drift toward the open gap at upper-left",
            "retreat_down": "Back away toward the bottom of the screen",
            "circle_boss": "Orbit around the boss to stay off-axis",
        },
    },
    "danger": {
        "type": "score",
        "instructions": "Rate how immediately dangerous the bullets are to the player.",
        "criteria": ["safe: open space everywhere",
                      "moderate: avoidable with normal movement",
                      "severe: will die without immediate action or a bomb"],
    },
    "bomb_now": {
        "type": "noul",
        "instructions": "Should the player use a bomb right now to survive?",
    },
}


def main():
    c = MicaClient()
    try:
        h = c.health()
        print("health:", h)
        assert h.get("status") == "ok"
    except LayaUnavailableError as e:
        print("health UNAVAILABLE (tunnel down?):", e)
        return 1

    resp = c.predict(STATE, QUESTIONS)
    print("model:", resp.get("model"))
    print("usage:", resp.get("usage"))
    print("_server_ms (normalized from latency_ms):", resp.get("_server_ms"),
          " _wall_ms:", round(resp["_wall_ms"], 1))
    for name, a in resp["answers"].items():
        if a["type"] == "choice":
            print(f"{name}: choice={a['choice']!r} conf={a['confidence']:.3f}")
        elif a["type"] == "score":
            print(f"{name}: score={a['score']} (float()={float(a['score']):.3f})")
        else:
            print(f"{name}: noul={a['noul']:.3f}")

    # error path: bad base url must raise LayaUnavailableError
    bad = MicaClient(base_url="http://127.0.0.1:59999", timeout=3.0)
    try:
        bad.health()
        print("ERROR: expected LayaUnavailableError")
        return 1
    except LayaUnavailableError as e:
        print("unavailable-path OK:", str(e)[:80])
    print("MICA CLIENT OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
