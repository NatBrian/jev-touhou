"""Probe MSYS2 repo layout and find current gettext tool packages."""
import re
import urllib.request

CANDIDATES = [
    "https://repo.msys2.org/mingw/w64/",
    "https://mirror.msys2.org/mingw/w64/",
    "https://repo.msys2.org/mingw/core.w64.db",
]
for url in CANDIDATES:
    try:
        r = urllib.request.urlopen(url, timeout=60)
        data = r.read()
        print(url, "->", r.status, len(data), "bytes")
        t = data.decode("utf-8", "replace")
        names = sorted(set(re.findall(r'href="(mingw-w64-x86_64-gettext[^"]*?\.pkg\.tar\.zst)"', t)))
        if names:
            print("GETTEXT PACKAGES:")
            print("\n".join(names))
        elif "db" in url:
            # .db is a tar of yaml; just confirm reachability
            print("reachable (db file)")
        else:
            print("no gettext pkg names; sample:", t[:200].replace("\n", " "))
    except Exception as e:
        print(url, "-> ERROR", e)
