"""Inspect the subprojects/basis_universal + koishi entries and test symlink capability."""
import os
import subprocess

base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "third_party", "taisei-sim")
for p in ("subprojects/basis_universal", "subprojects/koishi"):
    full = os.path.join(base, p)
    print(p, "| isfile:", os.path.isfile(full), "| isdir:", os.path.isdir(full))
    if os.path.isfile(full):
        print("   content:", repr(open(full, encoding="utf-8", errors="replace").read()))

r = subprocess.run(["git", "-C", base, "config", "core.symlinks"], capture_output=True, text=True)
print("core.symlinks =", r.stdout.strip() or "(unset)")

try:
    test = os.path.join(base, "subprojects", "_symlink_test")
    os.symlink("..\\external\\koishi", test)
    print("symlink creation: OK (isdir:", os.path.isdir(test), ")")
    os.remove(test)
except Exception as e:
    print("symlink creation: FAIL", e)
