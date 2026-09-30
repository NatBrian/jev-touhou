"""Probe the Mica server contract (port 8010) against the harness payload.

Usage: python tools/probe_mica_contract.py [base_url]
  - posts the REAL no-bomb question set with synthetic states of several sizes
  - reports status / latency / input tokens / answer sanity
  - prints one full response for the realistic (1280-char) state

Stdlib only.
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "harness")
from agent import NO_BOMB_QUESTIONS  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"


def post(payload):
    req = urllib.request.Request(
        BASE + "/v1/decide",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return None, (time.perf_counter() - t0) * 1000, f"HTTP {e.code}: {e.read()[:300]!r}"
    except Exception as e:  # noqa: BLE001
        return None, (time.perf_counter() - t0) * 1000, f"{e!r}"
    wall = (time.perf_counter() - t0) * 1000
    try:
        return json.loads(body), wall, None
    except json.JSONDecodeError as e:
        return None, wall, f"non-JSON: {body[:300]!r} ({e})"


def main():
    h = json.loads(urllib.request.urlopen(BASE + "/health", timeout=10).read())
    print("health:", h)

    bullet = " (123.4,234.5) r8 v(1.2,-3.4)"
    state = ("You are at (240, 464); the playable field is x 16-464, y 16-544. "
             "You have 3 lives, 0 bombs. Score 4,300,000; next extra life at 5,000,000.")
    while len(state) < 1240:
        state += " bullet" + bullet
    state1280 = state[:1280]

    for label, st in [
        ("S1280 (realistic)", state1280),
        ("S4000", (state1280 + " bullet" + bullet * 300)[:4000]),
        ("S8000", (state1280 + " bullet" + bullet * 620)[:8000]),
        ("S16000", (state1280 + " bullet" + bullet * 1240)[:16000]),
        ("S32000", (state1280 + " bullet" + bullet * 2480)[:32000]),
    ]:
        j, wall, err = post({"state": st, "questions": NO_BOMB_QUESTIONS})
        if err:
            print(f"{label}: ERR wall={wall:.0f}ms {err}")
            continue
        a = j.get("answers", {})
        ok = all(k in a for k in NO_BOMB_QUESTIONS)
        print(f"{label}: OK wall={wall:.0f}ms server={j.get('latency_ms')}ms "
              f"in_tok={j['usage']['input_tokens']} answers_ok={ok} "
              f"move={a.get('move', {}).get('choice')} "
              f"bomb_now={a.get('bomb_now', {}).get('noul'):.2f} "
              f"focus={a.get('focus', {}).get('noul'):.2f} "
              f"danger={a.get('danger', {}).get('score')}")

    # second realistic call: print full response (cold-start vs steady check)
    j, wall, err = post({"state": state1280, "questions": NO_BOMB_QUESTIONS})
    if err:
        print("FULL (2nd realistic): ERR", err)
    else:
        print("\nFULL RESPONSE (2nd realistic call):")
        print(json.dumps(j, indent=2)[:3000])


if __name__ == "__main__":
    main()
