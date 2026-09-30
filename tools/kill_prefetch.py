"""Kill the stale prefetch_wraps.py process (system python), if still running."""
import subprocess

r = subprocess.run(
    ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
    capture_output=True, text=True)
for line in r.stdout.splitlines():
    if "prefetch_wraps" in line:
        pid = line.strip().split(",")[1]
        k = subprocess.run(["taskkill", "/f", "/pid", pid], capture_output=True, text=True)
        print("killed", pid, "ok" if k.returncode == 0 else "FAIL")
print("done (wmic rc=%s)" % r.returncode)
