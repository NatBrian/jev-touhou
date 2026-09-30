"""Run the final-mode Lunatic campaign with temporary executor baseline terms.

This is an isolation diagnostic, not the normal executor configuration. It
keeps the committed code/defaults unchanged in the working process by setting
the imported executor module's values only in memory:

    venv\\Scripts\\python.exe tools\\run_dodge_baseline_diagnostic.py
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "harness"))

import executor  # noqa: E402

# Disable only the new rollout and severe-danger intent attenuation for this
# one diagnostic process. The committed defaults remain 0.35 and 0.25.
executor.DODGE_ROLLOUT_WEIGHT = 0.0
executor.DANGER_INTENT_FACTOR = 1.0

sys.argv = [
    os.path.join(HERE, "tools", "test_m3_campaign.py"),
    "--build-dir", "build-gl33",
    "--seed", "12345",
    "--diff", "lunatic",
]
runpy.run_path(sys.argv[0], run_name="__main__")
