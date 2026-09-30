"""Download + extract MSYS2 gettext (tools + runtime) into third_party/gettext/.

MSYS2 .pkg.tar.zst = zstd-compressed tarball. Extract with the `zstandard` wheel.
Yields usr/bin/{xgettext,msgfmt,msgmerge,...}.exe + usr/bin/libintl-*.dll.
"""
import io
import os
import tarfile
import urllib.request

import zstandard

BASE = "https://repo.msys2.org/mingw/mingw64/"
PKGS = [
    "mingw-w64-x86_64-gettext-tools-1.0-1-any.pkg.tar.zst",
    "mingw-w64-x86_64-gettext-runtime-1.0-1-any.pkg.tar.zst",
]

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
DEST = os.path.join(HERE, "third_party", "gettext")
os.makedirs(DEST, exist_ok=True)

for pkg in PKGS:
    url = BASE + pkg
    print("downloading", url)
    raw = urllib.request.urlopen(url, timeout=120).read()
    print("  got", len(raw), "bytes")
    dctx = zstandard.ZstdDecompressor()
    tar_bytes = dctx.decompress(raw, max_output_size=200 * 1024 * 1024)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
        tf.extractall(DEST)
    print("  extracted to", DEST)

# Verify the tools we need are present.
bindir = os.path.join(DEST, "usr", "bin")
for tool in ("xgettext", "msgfmt", "msgmerge", "msguniq"):
    exe = os.path.join(bindir, tool + ".exe")
    print(("FOUND " if os.path.isfile(exe) else "MISSING ") + exe)
print("bin dir:", bindir, os.path.isdir(bindir))
