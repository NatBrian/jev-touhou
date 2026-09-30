"""Inspect the mingw64 index for the right compiler base names."""
import importlib.util
import os
import re
import sys

spec = importlib.util.spec_from_file_location(
    "fm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_mingw.py"))
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

by_base, by_full = fm.load_db()
# by_full maps full -> base; invert to full -> pkg via by_base is lossy, so
# rebuild a full->pkg map directly from the index:
import io, tarfile
# (reuse module pieces)
def all_pkgs():
    data = fm.dl(fm.DB_URL)
    if data[:4] == b"\x28\xb5\x2f\xfd":
        data = zstd.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
    pkgs = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r|") as tf:
        for m in tf:
            if not m.name.endswith("/desc") or not m.isreg():
                continue
            f = tf.extractfile(m)
            if not f:
                continue
            d = fm.parse_desc(f.read().decode("utf-8", "replace"))
            if d.get("NAME"):
                pkgs[d["NAME"]] = d
    return pkgs

import zstandard as zstd
pkgs = all_pkgs()
terms = ["gcc", "g++", "libstdc++", "libgomp", "libwinpthread", "cc-libs", "libgcc", "binutils"]
for term in terms:
    hits = sorted(n for n in pkgs if term in n and n.count("-") <= 4)
    print("== %s" % term)
    for n in hits:
        print("  %s  (deps: %s)" % (n, " ".join(pkgs[n].get("DEPENDS", "").split())))
