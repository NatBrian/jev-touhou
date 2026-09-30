"""Thread-count sweep for local Laya CPU inference on this PC.

Question: is the 5.8 s/batch dominated by thread contention on 4 physical cores?
Loads the english checkpoint once, then times 3-question batches at several
torch thread counts (5 measured iterations each after warmup).

Usage: venv\Scripts\python.exe tools\bench_laya_threads.py
"""

import os
import statistics
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_HOME", os.path.join(PROJECT, "cache", "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

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
    import torch
    from laya import Router

    router = Router(preload=False)
    router.predict(STATE, QUESTIONS)  # load weights

    print(f"{'threads':>8} | {'median ms':>10} | {'min ms':>8} | {'max ms':>8} | {'calls/s':>8}")
    results = {}
    for n in (1, 2, 4, 8):
        torch.set_num_threads(n)
        for _ in range(2):
            router.predict(STATE, QUESTIONS)  # warmup at this thread count
        xs = []
        for _ in range(5):
            t0 = time.perf_counter()
            router.predict(STATE, QUESTIONS)
            xs.append((time.perf_counter() - t0) * 1000)
        results[n] = statistics.median(xs)
        print(f"{n:>8} | {statistics.median(xs):>10.0f} | {min(xs):>8.0f} | {max(xs):>8.0f} | {1000 / statistics.median(xs):>8.2f}")

    best = min(results, key=results.get)
    print(f"\nbest: {best} threads -> {1000 / results[best]:.2f} decision cycles/s "
          f"({results[best]:.0f} ms per 3-question batch)")


if __name__ == "__main__":
    main()
