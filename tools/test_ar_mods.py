#!/usr/bin/env python3
"""Empirical test of the `ar` modifier-string behavior (build-gl33 blocker B).

Reproduces the meson STATIC_LINKER_RSP failure:
    "ar" "csrDT" src/libtaisei.a @src/libtaisei.a.rsp
        -> ar: src/libtaisei.a: No such file or directory

Tests each candidate ar binary, each modifier variant, and the exact failing
invocation, from inside build-gl33 (so relative paths match ninja's cwd).
Writes an ASCII report to stdout (no Unicode).
"""
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINGW = os.path.join(ROOT, "third_party", "mingw", "mingw64", "bin")
BUILDDIR = os.path.join(ROOT, "third_party", "taisei-sim", "build-gl33")

def run(cmd, cwd):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return -1, "EXC: %s" % e

def main():
    out = []
    def w(s=""):
        out.append(s)
        print(s)

    # 1) candidate ar binaries: name, size, identity
    w("=== ar candidates in mingw64/bin ===")
    for name in ("ar.exe", "gcc-ar.exe", "x86_64-w64-mingw32-ar.exe", "ranlib.exe"):
        p = os.path.join(MINGW, name)
        if os.path.exists(p):
            st = os.stat(p)
            w("%-32s %10d bytes" % (name, st.st_size))
        else:
            w("%-32s (absent)" % name)

    # 2) version + help for plain ar and gcc-ar
    for name in ("ar.exe", "gcc-ar.exe"):
        p = os.path.join(MINGW, name)
        if not os.path.exists(p):
            continue
        w("\n=== %s --version ===" % name)
        rc, txt = run([p, "--version"], cwd=BUILDDIR)
        w(txt.strip().splitlines()[0] if txt.strip() else "(no output)")
        w("\n=== %s -h (modifier table) ===" % name)
        rc, txt = run([p, "-h"], cwd=BUILDDIR)
        w(txt[:1500])
        w("  [D] in help: %s   [T] in help: %s" % ("[D]" in txt, "[T]" in txt))

    # 3) modifier variants on a real object file
    objdir = os.path.join(BUILDDIR, "src", "libtaisei.a.p")
    objs = [f for f in os.listdir(objdir) if f.endswith(".obj")][:2]
    w("\n=== modifier variants (test archive in build-gl33) ===")
    for mods in ("csr", "csD", "csT", "cDT", "csrDT", "csrD", "csrT"):
        t = "t_%s.a" % mods
        rc, txt = run([os.path.join(MINGW, "ar.exe"), mods, t] +
                      [os.path.join(objdir, f) for f in objs], cwd=BUILDDIR)
        exists = os.path.exists(os.path.join(BUILDDIR, t))
        w("ar %-6s -> rc=%d exists=%s %s" % (
            mods, rc, exists, (txt.strip().splitlines()[0][:90] if txt.strip() else "")))

    # 4) the EXACT failing invocation (rsp file), cwd = build-gl33
    w("\n=== exact ninja invocation: ar csrDT src/libtaisei.a @src/libtaisei.a.rsp ===")
    rsp = os.path.join(BUILDDIR, "src", "libtaisei.a.rsp")
    w("rsp exists: %s" % os.path.exists(rsp))
    rc, txt = run([os.path.join(MINGW, "ar.exe"), "csrDT", "src/libtaisei.a",
                   "@src/libtaisei.a.rsp"], cwd=BUILDDIR)
    w("rc=%d" % rc)
    w(txt[:800])
    a = os.path.join(BUILDDIR, "src", "libtaisei.a")
    if os.path.exists(a):
        with open(a, "rb") as f:
            magic = f.read(8)
        w("archive magic: %r  size=%d" % (magic, os.path.getsize(a)))

    # 5) same with plain csr (the intended fix)
    w("\n=== fix candidate: ar csr src/libtaisei.a @src/libtaisei.a.rsp ===")
    rc, txt = run([os.path.join(MINGW, "ar.exe"), "csr", "src/libtaisei.a",
                   "@src/libtaisei.a.rsp"], cwd=BUILDDIR)
    w("rc=%d %s" % (rc, txt.strip().splitlines()[0][:120] if txt.strip() else ""))
    if os.path.exists(a):
        with open(a, "rb") as f:
            magic = f.read(8)
        w("archive magic: %r  size=%d" % (magic, os.path.getsize(a)))
        rc2, txt2 = run([os.path.join(MINGW, "ar.exe"), "t", "src/libtaisei.a"],
                        cwd=BUILDDIR)
        lines = txt2.strip().splitlines()
        w("ar t: rc=%d, %d members listed (first: %s)" % (
            rc2, len(lines), lines[0][:60] if lines else "-"))

if __name__ == "__main__":
    main()
