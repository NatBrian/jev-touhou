"""Fetch taisei-sim wrap subprojects as codeload tarballs (robust to flaky git).

meson's wrap system does FULL `git clone`, which keeps failing on this
connection ("invalid index-pack output" / "server closed abruptly"). GitHub
codeload tarballs are a single retriable HTTP GET, so we download the pinned
revision as a tarball and extract it into `subprojects/<directory>`, which is
exactly the layout meson's wrap system would produce. meson then sees the
directory already populated and skips its own download.

Idempotent: skips a subproject if its directory already exists and contains a
build file (meson.build or CMakeLists.txt).

    venv\\Scripts\\python.exe tools\\fetch_wraps_tarball.py
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

SP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "third_party", "taisei-sim", "subprojects")
TMP = os.path.join(SP, ".dl")
BUILD_FILES = ("meson.build", "CMakeLists.txt")
RETRIES = 5
SLEEP = 4


def parse_wrap(path):
    t = open(path, encoding="utf-8").read()
    if "[wrap-git]" not in t:
        return None
    d = re.search(r"directory\s*=\s*(\S+)", t)
    url = re.search(r"url\s*=\s*(\S+)", t)
    rev = re.search(r"revision\s*=\s*(\S+)", t)
    if not (d and url and rev):
        return None
    # https://github.com/OWNER/REPO(.git)  ->  codeload.github.com/OWNER/REPO
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?$", url.group(1))
    if not m:
        print("  !! cannot parse url:", url.group(1))
        return None
    owner, repo = m.group(1), m.group(2)
    return d.group(1), owner, repo, rev.group(1)


def has_buildfile(d):
    return any(os.path.isfile(os.path.join(d, b)) for b in BUILD_FILES)


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            if os.path.getsize(dest) > 0:
                return True
        except Exception as e:
            print("    attempt %d/%d failed: %s" % (attempt, RETRIES, e))
        time.sleep(SLEEP)
    return False


def extract(tar_path, target):
    """Extract tarball into `target`, flattening the single top-level dir."""
    os.makedirs(target, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as tf:
        # find the top-level dir name (codeload: <repo>-<ref>)
        tops = set(m.path.split("/")[0] for m in tf.getmembers() if m.name)
        tf.extractall(TMP)
    extracted = os.path.join(TMP, sorted(tops)[0])
    for name in os.listdir(extracted):
        src = os.path.join(extracted, name)
        dst = os.path.join(target, name)
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
            shutil.move(src, dst)
        else:
            shutil.move(src, dst)
    shutil.rmtree(TMP, ignore_errors=True)


def main():
    os.makedirs(TMP, exist_ok=True)
    done, skip, fail = [], [], []
    for f in sorted(os.listdir(SP)):
        if not f.endswith(".wrap"):
            continue
        parsed = parse_wrap(os.path.join(SP, f))
        if not parsed:
            continue
        directory, owner, repo, revision = parsed
        target = os.path.join(SP, directory)
        if os.path.isdir(target) and has_buildfile(target):
            skip.append(directory)
            continue
        url = "https://codeload.github.com/%s/%s/tar.gz/%s" % (owner, repo, revision)
        print("fetch %s  <-  %s" % (directory, url), flush=True)
        # clear any stale/partial dir (best effort; locked files left in place)
        if os.path.isdir(target) and not has_buildfile(target):
            shutil.rmtree(target, ignore_errors=True)
        tar_path = os.path.join(TMP, directory + ".tar.gz")
        if not download(url, tar_path):
            fail.append(directory)
            continue
        try:
            extract(tar_path, target)
        finally:
            if os.path.isfile(tar_path):
                os.remove(tar_path)
        if has_buildfile(target):
            done.append(directory)
        else:
            print("  !! no build file after extract (expected for plain libs?)")
            done.append(directory + " (NO BUILD FILE)")
    shutil.rmtree(TMP, ignore_errors=True)
    print("\n== already present ==")
    for s in skip:
        print("  " + s)
    print("== fetched ==")
    for d in done:
        print("  " + d)
    print("== FAILED ==")
    for x in fail:
        print("  " + x)
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
