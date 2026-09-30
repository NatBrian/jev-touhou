"""Verify a replay with the fork's own executable and per-frame checks.

The replay was produced by the fork's sim DLL, so the fidelity gate must use
the matching fork executable rather than the stock release.  The environment
variable makes Taisei emit/check a desync event every frame.

    venv\\Scripts\\python.exe tools\\verify_fork_replay.py replay.trsr log.txt
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(HERE, "third_party", "taisei-sim", "build-gl33", "src", "taisei.exe")
MINGW_BIN = os.path.join(HERE, "third_party", "mingw", "mingw64", "bin")


def main():
    if len(sys.argv) not in (2, 3):
        print("usage: verify_fork_replay.py <replay.trsr> [output.log]")
        return 2
    replay = os.path.abspath(sys.argv[1])
    log_path = os.path.abspath(sys.argv[2]) if len(sys.argv) == 3 else None
    if not os.path.isfile(EXE):
        print("fork executable not found:", EXE)
        return 2
    if not os.path.isfile(replay):
        print("replay not found:", replay)
        return 2

    env = os.environ.copy()
    env["TAISEI_REPLAY_DESYNC_CHECK_FREQUENCY"] = "1"
    env["PATH"] = MINGW_BIN + os.pathsep + env.get("PATH", "")
    cmd = [EXE, "--verify-replay", replay, "--renderer", "null"]
    print("verifying with:", EXE)
    print("replay:", replay)
    print("command:", " ".join(cmd))
    result = subprocess.run(
        cmd, cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8", newline="") as f:
            f.write(result.stdout)
    print(result.stdout, end="")
    print("verify exit:", result.returncode)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
