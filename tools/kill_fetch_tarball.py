"""Kill the stale fetch_wraps_tarball.py process."""
import subprocess

out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
# find python PIDs
pids = [p.strip('"').split('",')[1] for p in out.splitlines()
        if p.strip('"').startswith('"python.exe"')]
killed = 0
for pid in pids:
    # check command line via powershell Get-CimInstance
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter 'ProcessId=%s').CommandLine" % pid],
        capture_output=True, text=True)
    if "fetch_wraps_tarball" in r.stdout:
        k = subprocess.run(["taskkill", "/f", "/pid", pid], capture_output=True, text=True)
        print("killed", pid, "ok" if k.returncode == 0 else "FAIL")
        killed += 1
print("killed total:", killed)
