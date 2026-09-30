"""Deterministic tests for the executor's short dodge rollout.

These tests use the executor's own candidate-cost and risk helpers. They do
not start Taisei or contact Laya; game controls are a separate planned phase.

    venv\\Scripts\\python.exe tools\\test_executor_rollout.py
"""

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

from executor import (  # noqa: E402
    DODGE_ROLLOUT_FRAMES,
    MOVES,
    PATH_RISK_FRAMES,
    ReflexExecutor,
)
import executor as executor_module  # noqa: E402


def assert_close_field(executor, px, py, speed=6.25):
    """Return raw costs for the nine headings in an empty field."""
    return [executor._candidate_cost(px, py, dx, dy, speed, [], [], [])
            for (dx, dy), _buttons in MOVES]


def main():
    ex = ReflexExecutor()
    assert DODGE_ROLLOUT_FRAMES == 8
    # Exercise the experimental rollout explicitly. Normal gameplay keeps its
    # weight disabled because the Lunatic Laya A/B has not passed acceptance.
    original_weight = executor_module.DODGE_ROLLOUT_WEIGHT
    executor_module.DODGE_ROLLOUT_WEIGHT = 0.35

    # 1) A bullet that is safe at the current point but arrives on the held
    # path makes the held heading costlier than a lateral escape.  The bullet
    # starts 50 px above the player and moves down into the held path at frame
    # 8, so it is not an immediate overlap.
    hazards = [(240.0, 100.0, 0.0, 6.25, 4.0, 1.0)]
    hold = ex._candidate_cost(240.0, 150.0, 0.0, 0.0, 6.25,
                              hazards, [], [])
    lateral = ex._candidate_cost(240.0, 150.0, 1.0, 0.0, 6.25,
                                 hazards, [], [])
    assert hold > lateral, "rollout did not prefer a lateral escape"
    print("PASS future bullet rollout: hold=%.3f lateral=%.3f" %
          (hold, lateral))

    # 2) A first-frame movement crossing a laser centerline keeps the
    # existing motion-crossing penalty, even when the endpoint is clear.
    laser = [(246.0, 100.0, 2.0, 246.0, 200.0, 2.0, 1.0)]
    crossing = ex._candidate_cost(240.0, 150.0, 1.0, 0.0, 6.25,
                                  [], laser, laser)
    clear = ex._candidate_cost(240.0, 150.0, 0.0, 0.0, 6.25,
                               [], laser, laser)
    assert crossing >= 4.0 and crossing > clear, \
        "laser crossing penalty was not retained"
    print("PASS laser crossing: crossing=%.3f clear=%.3f" %
          (crossing, clear))

    # 3) In a clear field, the rollout adds no risk and therefore does not
    # make a safe candidate jitter by itself.
    # Use the middle of the field so the pre-existing wall term is also zero.
    costs = assert_close_field(ex, 240.0, 280.0)
    assert max(costs) == 0.0, "clear field introduced nonzero risk"
    assert costs.count(min(costs)) == len(MOVES), \
        "clear-field candidates should remain tied"
    print("PASS clear field: all candidate risk costs remain zero")

    # 4) Future wall proximity is included in the rollout. A rightward path
    # from x=400 reaches the wall band, while holding stays clear of it now
    # and throughout the short rollout.
    right = ex._candidate_cost(400.0, 300.0, 1.0, 0.0, 6.25,
                               [], [], [])
    hold = ex._candidate_cost(400.0, 300.0, 0.0, 0.0, 6.25,
                              [], [], [])
    assert right > hold, "future wall cost did not reject edge trajectory"
    print("PASS future wall: right=%.3f hold=%.3f" % (right, hold))

    # 5) The opt-in intermediate path term catches a crossing that is not
    # represented by the single horizon endpoint. Keep the default disabled.
    original_path_weight = executor_module.PATH_RISK_WEIGHT
    executor_module.PATH_RISK_WEIGHT = 0.35
    assert PATH_RISK_FRAMES == 12
    # Starts 75 px above the player and reaches y=25 at sample 12.
    crossing_hazard = [(240.0, -50.0, 0.0, 6.25, 4.0, 1.0)]
    path_hold = ex._candidate_cost(240.0, 25.0, 0.0, 0.0, 6.25,
                                   crossing_hazard, [], [])
    path_lateral = ex._candidate_cost(240.0, 25.0, 1.0, 0.0, 6.25,
                                      crossing_hazard, [], [])
    assert path_hold > path_lateral, \
        "intermediate path risk did not reject the crossing heading"
    print("PASS intermediate path: hold=%.3f lateral=%.3f" %
          (path_hold, path_lateral))
    executor_module.PATH_RISK_WEIGHT = original_path_weight

    print("\nEXECUTOR ROLLOUT TEST PASSED")
    executor_module.DODGE_ROLLOUT_WEIGHT = original_weight


if __name__ == "__main__":
    main()
