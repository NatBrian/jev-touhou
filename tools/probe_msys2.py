import re
import urllib.request

t = urllib.request.urlopen("https://repo.msys2.org/mingw/mingw64/", timeout=120).read().decode("utf-8", "replace")
names = sorted(set(re.findall(r'href="(mingw-w64-x86_64-gettext[^"]*?\.pkg\.tar\.zst)"', t)))
print("GETTEXT PKGS:", len(names))
print("\n".join(names))
