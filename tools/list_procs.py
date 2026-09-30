"""List python + git processes with command lines (to find the loop spawner)."""
import subprocess

out = subprocess.run(["tasklist", "/fo", "csv", "/nh", "/v"], capture_output=True, text=True).stdout
rows = {}
for line in out.splitlines():
    parts = [p.strip('"') for p in line.split('",')]
    if len(parts) >= 2 and parts[0].lower() in ("python.exe", "git.exe", "git-remote-https.exe"):
        rows.setdefault(parts[0], []).append((parts[1], parts[10] if len(parts) > 10 else "?"))
for name, lst in rows.items():
    print("==", name, len(lst))
    for pid, win in lst:
        print("  ", pid, win[:110])

# command lines via wmic if available
r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='git.exe'\" | "
                    "ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"],
                   capture_output=True, text=True)
print("---- command lines ----")
print(r.stdout[:4000])
