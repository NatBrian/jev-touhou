"""Kill stray git processes (stalled wrap clones)."""
import subprocess

out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
killed = []
for line in out.splitlines():
    parts = [p.strip('"') for p in line.split('",')]
    if parts and parts[0].lower() in ("git.exe", "git-remote-https.exe"):
        r = subprocess.run(["taskkill", "/f", "/pid", parts[1]], capture_output=True, text=True)
        killed.append("%s %s %s" % (parts[0], parts[1], "ok" if r.returncode == 0 else "FAIL"))
print("\n".join(killed) if killed else "none left")
