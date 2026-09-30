"""Fetch a minimal MSYS2 MinGW-w64 (mingw64) GCC toolchain into third_party/mingw/.

Why: taisei's C code uses VLAs + GCC idioms; MSVC refuses to compile it. The
official Taisei Windows releases are MinGW-built, so MinGW GCC is the
toolchain with the highest prior probability of working.

Approach (2026 MSYS2 layout):
  1. Download the mingw64 repo index: a zstd-compressed TAR of
     per-package metadata dirs, each containing a `desc` file with
     %FILENAME%, %NAME% (arch-qualified), %BASE% (short name), %DEPENDS%.
  2. Resolve the dependency closure of the seed packages (by BASE name).
  3. Download each <...>.pkg.tar.zst and extract (zstd + tar) into
     third_party/mingw/ (layout: mingw64/bin, mingw64/lib, ...).

Idempotent: already-extracted packages are recorded in third_party/mingw/.installed.txt.

    venv\Scripts\python.exe tools\fetch_mingw.py
"""

import io
import os
import sys
import tarfile
import tempfile
import time
import urllib.request
import zstandard as zstd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "third_party", "mingw")
REPO = "https://repo.msys2.org/mingw/mingw64"
DB_URL = REPO + "/mingw64.db"

# FULL package names (the %NAME% field; arch-qualified). 2026 MSYS2 layout:
# GCC 16.x merged the C++ front end into the `gcc` package; libstdc++-v3 was
# renamed libstdc++; gcc-libs -> cc-libs (+ gcc-libs compat wrapper).
SEEDS = [
    "mingw-w64-x86_64-gcc",            # C + C++ front ends (gcc, g++ drivers)
    "mingw-w64-x86_64-binutils",       # ld, ar
    "mingw-w64-x86_64-crt",            # mingw-w64 C runtime
    "mingw-w64-x86_64-headers",        # CRT headers
    "mingw-w64-x86_64-libwinpthread",
    "mingw-w64-x86_64-libstdc++",
    "mingw-w64-x86_64-libgomp",
    "mingw-w64-x86_64-gcc-libs",       # pulls cc-libs (libgcc runtime support)
    "mingw-w64-x86_64-gettext-tools",  # xgettext/msgfmt (taisei po/ build requirement)
    "mingw-w64-x86_64-libpng",         # main.c includes <png.h> (dep_png detection)
]

MARKER = os.path.join(DEST, ".installed.txt")


def dl(url, retries=5):
    last = None
    for i in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jev-touhou-build/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            print("  attempt %d/%d failed for %s: %s" % (i, retries, url, e), flush=True)
            time.sleep(2 * i)
    raise RuntimeError("download failed: %s (%s)" % (url, last))


def parse_desc(text):
    fields = {}
    key = None
    lines = []
    for line in text.splitlines():
        if line.startswith("%") and line.endswith("%") and len(line) > 2:
            if key is not None:
                fields[key] = "\n".join(lines).strip()
            key = line[1:-1]
            lines = []
        else:
            lines.append(line)
    if key is not None:
        fields[key] = "\n".join(lines).strip()
    return fields


def _strip_dep_constraint(dep):
    """'mingw-w64-x86_64-libgcc=16.2.0-4' -> 'mingw-w64-x86_64-libgcc'."""
    for sep in (">=", "<=", "=", ">", "<"):
        if sep in dep:
            return dep.split(sep)[0]
    return dep


def load_db():
    """Return pkgs: FULL name -> pkg dict (deps stripped of version constraints)."""
    print("downloading package index ...", flush=True)
    data = dl(DB_URL)
    if data[:4] == b"\x28\xb5\x2f\xfd":  # zstd frame
        data = zstd.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
    pkgs = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r|") as tf:
        for m in tf:
            if not m.name.endswith("/desc") or not m.isreg():
                continue
            f = tf.extractfile(m)
            if not f:
                continue
            d = parse_desc(f.read().decode("utf-8", "replace"))
            name = d.get("NAME", "")
            if not name:
                continue
            pkgs[name] = {
                "name": name,
                "base": d.get("BASE", ""),
                "file": d.get("FILENAME", ""),
                "deps": [_strip_dep_constraint(x) for x in d.get("DEPENDS", "").split()],
                "isize": int(d.get("ISIZE", "0") or 0),
                "csize": int(d.get("CSIZE", "0") or 0),
            }
    return pkgs


def resolve(pkgs, seeds):
    todo, seen = list(seeds), set()
    while todo:
        name = todo.pop()
        if name in seen or name not in pkgs:
            continue
        seen.add(name)
        todo.extend(pkgs[name]["deps"])
    missing = [s for s in seeds if s not in pkgs]
    if missing:
        print("WARNING: seeds not found in index: %s" % missing)
    return sorted(seen)


def installed_set():
    if os.path.isfile(MARKER):
        with open(MARKER, encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    return set()


def main():
    os.makedirs(DEST, exist_ok=True)
    pkgs = load_db()
    print("index packages: %d" % len(pkgs), flush=True)

    want = resolve(pkgs, SEEDS)
    have = installed_set()
    todo = [n for n in want if n not in have]
    isize = sum(pkgs[n]["isize"] for n in todo)
    csize = sum(pkgs[n]["csize"] for n in todo)
    print("resolved %d packages (%d to fetch), install ~%.0f MB, download ~%.0f MB:"
          % (len(want), len(todo), isize / 1e6, csize / 1e6), flush=True)
    for n in want:
        mark = "(have) " if n in have else "        "
        print("  %s%s" % (mark, n), flush=True)

    dctx = zstd.ZstdDecompressor()
    for name in todo:
        url = REPO + "/" + pkgs[name]["file"]
        print("fetch %s" % name, flush=True)
        blob = dl(url)
        if blob[:4] == b"\x28\xb5\x2f\xfd":
            blob = dctx.stream_reader(io.BytesIO(blob)).read()
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r|") as tf:
            tf.extractall(DEST, filter="data")
        with open(MARKER, "a", encoding="utf-8") as f:
            f.write(name + "\n")

    bin_dir = os.path.join(DEST, "mingw64", "bin")
    for exe in ("gcc.exe", "g++.exe", "ld.exe", "ar.exe"):
        p = os.path.join(bin_dir, exe)
        print("%-10s %s" % (exe, "OK" if os.path.isfile(p) else "MISSING"), flush=True)
    print("== mingw fetch done ==")


if __name__ == "__main__":
    sys.exit(main())
