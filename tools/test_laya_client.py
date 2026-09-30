"""Quick validation of harness/laya_client.py against the Laya host server.

    venv\Scripts\python.exe tools/test_laya_client.py
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))
from laya_client import LayaClient, LayaUnavailableError, LayaProtocolError  # noqa: E402

STATE = {
    "scene": "boss fight, stage 1",
    "player": "pos (240,420), 1 life, 1 bomb, power 2/5, moving slowly",
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
    c = LayaClient()
    try:
        h = c.health()
        print("health:", h)
    except LayaUnavailableError as e:
        print("health UNAVAILABLE (tunnel down?):", e)
        print("client unavailable-path OK")
        return

    resp = c.predict(STATE, QUESTIONS)
    print("routing:", resp.get("routing", {}).get("model"))
    print("usage:", resp.get("usage"))
    print("_server_ms:", resp.get("_server_ms"), " _wall_ms:", round(resp["_wall_ms"], 1))
    for name, a in resp["answers"].items():
        if a["type"] == "choice":
            print(f"{name}: choice={a['choice']!r} conf={a['confidence']:.3f}")
        elif a["type"] == "score":
            print(f"{name}: score={a['score']:.3f}")
        else:
            print(f"{name}: noul={a['noul']:.3f}")

    # error path: bad base url must raise LayaUnavailableError
    bad = LayaClient(base_url="http://127.0.0.1:59999", timeout=3.0)
    try:
        bad.health()
        print("ERROR: expected LayaUnavailableError")
    except LayaUnavailableError as e:
        print("unavailable-path OK:", str(e)[:80])
    print("CLIENT OK")


if __name__ == "__main__":
    main()
