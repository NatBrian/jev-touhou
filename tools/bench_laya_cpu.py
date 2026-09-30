"""Benchmark local Laya (CPU) on this PC: is it compatible, and how fast?

Mirrors the Laya-host smoke-test workload from logs/run-2026-09-24-laya-smoke.md:
a ~60-token danmaku state + 3 typed questions (choice / score / noul),
the pattern the harness will use (one batched call per decision cycle).

All HuggingFace downloads are kept inside the project folder (AGENTS.md S1):
set HF_HOME to <project>/cache/hf before the model is fetched.

Usage:
    venv\Scripts\python.exe tools\bench_laya_cpu.py
"""

import json
import os
import platform
import statistics
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_HOME", os.path.join(PROJECT, "cache", "hf"))

# Same state shape as the 2026-09-24 Laya-host smoke test (4 fields, ~60 tokens).
STATE = {
    "scene": "boss fight, stage 1",
    "player": "pos (240,420), 1 life, 1 bomb, power 2/5, moving slowly",
    "nearest_bullets": "6 enemy bullets within 90px, dense cluster closing from upper-left, gap at upper-left of player",
    "boss": "boss at (240,120), spell 'Mystic Light Ring' 12s left, dealing heavy damage",
}

# Same 3-question set as the smoke test (1 choice, 1 score, 1 noul).
QUESTIONS = {
    # NOTE: local SDK 0.3.20 takes choice options as `criteria` (label -> description).
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
    print(f"Python {platform.python_version()} | {platform.machine()} | "
          f"CPUs (logical): {os.cpu_count()}")
    print(f"HF_HOME -> {os.environ['HF_HOME']}")

    t0 = time.perf_counter()
    from laya import Router
    router = Router(preload=False)
    print(f"router init: {time.perf_counter() - t0:.1f} s")

    # First call includes the ~900 MB checkpoint download.
    t0 = time.perf_counter()
    first = router.predict(STATE, QUESTIONS)
    first_ms = (time.perf_counter() - t0) * 1000
    print(f"first predict (incl. model download): {first_ms:.0f} ms")
    print("routing:", json.dumps(first.get("routing", {}), ensure_ascii=False))
    print("usage:  ", json.dumps(first.get("usage", {}), ensure_ascii=False))

    # Warmup (weights resident, CPU caches warm).
    for _ in range(3):
        router.predict(STATE, QUESTIONS)

    # 3-question batch (one decision cycle, one forward pass) — the harness pattern.
    batch = []
    for _ in range(20):
        t0 = time.perf_counter()
        r = router.predict(STATE, QUESTIONS)
        batch.append((time.perf_counter() - t0) * 1000)
        assert r["answers"]["move"]["choice"] in QUESTIONS["move"]["criteria"]

    # Single question (reference: lower bound per call).
    single = []
    for _ in range(10):
        t0 = time.perf_counter()
        router.predict(STATE, {"move": QUESTIONS["move"]})
        single.append((time.perf_counter() - t0) * 1000)

    def report(name, xs):
        xs_sorted = sorted(xs)
        med = statistics.median(xs)
        p95 = xs_sorted[int(0.95 * (len(xs_sorted) - 1))]
        print(f"{name}: n={len(xs)} median={med:.0f} ms  p95={p95:.0f} ms  "
              f"min={min(xs):.0f} ms  max={max(xs):.0f} ms  -> {1000 / med:.1f} calls/s")

    print()
    print("== local Laya CPU benchmark (english checkpoint, 390-token equivalent workload) ==")
    report("3-question batch (1 decision cycle)", batch)
    report("single question (reference)", single)
    print()
    print(f"Decision budget at batch cadence: ~{1000 / statistics.median(batch):.1f} decision cycles/s wall")
    print("(Laya host GPU reference: ~3-5 decision cycles/s wall through the SSH tunnel)")


if __name__ == "__main__":
    main()
