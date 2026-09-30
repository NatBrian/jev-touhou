"""Pre-clone all taisei-sim wrap subprojects (shallow, at exact revision).

meson's wrap system does FULL git clones, which is slow and hit a transient
"invalid index-pack output" failure on this connection. Shallow-cloning the
wraps ourselves at the pinned revision lets meson reuse the directories.

Idempotent: skips subprojects that already exist.
"""
import os
import re
import shutil
import subprocess
import sys

SP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "third_party", "taisei-sim", "subprojects")


def parse_wrap(path):
    t = open(path, encoding="utf-8").read()
    if "[wrap-git]" not in t:
        return None
    d = re.search(r"directory\s*=\s*(\S+)", t)
    url = re.search(r"url\s*=\s*(\S+)", t)
    rev = re.search(r"revision\s*=\s*(\S+)", t)
    return d.group(1), url.group(1), rev.group(1)


def main():
    todo, skip = [], []
    for f in sorted(os.listdir(SP)):
        if not f.endswith(".wrap"):
            continue
        parsed = parse_wrap(os.path.join(SP, f))
        if not parsed:
            continue
        directory, url, revision = parsed
        dest = os.path.join(SP, directory)
        if os.path.isdir(os.path.join(dest, ".git")):
            # complete repo? (a failed meson clone leaves a partial .git)
            ok = subprocess.run(
                ["git", "-C", dest, "rev-parse", "--verify", "HEAD"],
                capture_output=True).returncode == 0
            if ok:
                skip.append(directory)
                continue
            shutil.rmtree(dest, ignore_errors=True)
        elif os.path.exists(dest):
            shutil.rmtree(dest, ignore_errors=True)
        todo.append((directory, url, revision))

    print("already present:", skip or "none")
    for directory, url, revision in todo:
        dest = os.path.join(SP, directory)
        print(f"cloning {directory} ({url} @ {revision}) ...", flush=True)
        for attempt in range(1, 4):
            r = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", revision, url, dest])
            if r.returncode == 0:
                break
            print(f"  attempt {attempt} failed (rc={r.returncode}), retrying...")
            shutil.rmtree(dest, ignore_errors=True)
        else:
            sys.exit(f"FAILED to clone {directory}")
    print("all wraps present")


if __name__ == "__main__":
    main()
