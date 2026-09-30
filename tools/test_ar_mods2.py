#!/usr/bin/env python3
"""Isolate the ar @rsp failure (build-gl33 blocker B), part 2.

Test matrix (all cwd=build-gl33, fresh archive names):
  1) ar csrDT t1.a @rsp
  2) ar csr   t2.a @rsp
  3) ar csrDT t3.a <first 10 inline paths>
  4) ar csrDT t4.a <all 305 inline paths>
  5) ar csr   t5.a <all 305 inline paths>
Also reports: member count in rsp, missing members, rsp line length.
"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AR = os.path.join(ROOT, "third_party", "mingw", "mingw64", "bin", "ar.exe")
BUILDDIR = os.path.join(ROOT, "third_party", "taisei-sim", "build-gl33")
RSP = os.path.join(BUILDDIR, "src", "libtaisei.a.rsp")

text = open(RSP, encoding="utf-8", errors="replace").read()
members = text.split()
print("rsp chars: %d, members: %d" % (len(text), len(members)))
missing = [m for m in members if not os.path.exists(os.path.join(BUILDDIR, m))]
print("missing members: %d" % len(missing))
for m in missing[:5]:
    print("  MISSING: %s" % m)

def run(args):
    p = subprocess.run([AR] + args, cwd=BUILDDIR, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=180)
    out = (p.stdout or "") + (p.stderr or "")
    first = out.strip().splitlines()[0][:100] if out.strip() else ""
    print("ar %s... -> rc=%d %s" % (args[1][:12], p.returncode, first))
    return p.returncode

run(["csrDT", "t1.a", "@src/libtaisei.a.rsp"])
run(["csr", "t2.a", "@src/libtaisei.a.rsp"])
run(["csrDT", "t3.a"] + members[:10])
run(["csrDT", "t4.a"] + members)
run(["csr", "t5.a"] + members)

# inspect t1/t2 if created
for t in ("t1.a", "t2.a", "t4.a", "t5.a"):
    p = os.path.join(BUILDDIR, t)
    if os.path.exists(p):
        magic = open(p, "rb").read(8)
        print("%s: magic=%r size=%d" % (t, magic, os.path.getsize(p)))
