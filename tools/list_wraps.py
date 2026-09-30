"""List which taisei wraps use git vs file downloads (so we can pre-fetch the git ones)."""
import os
import re

SP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "third_party", "taisei-sim", "subprojects")
for f in sorted(os.listdir(SP)):
    if not f.endswith(".wrap"):
        continue
    t = open(os.path.join(SP, f), encoding="utf-8").read()
    kind = "git" if "[wrap-git]" in t else ("file" if "[wrap-file]" in t else "other")
    url = re.search(r"url\s*=\s*(\S+)", t)
    rev = re.search(r"(?:revision|source-filename)\s*=\s*(\S+)", t)
    u = url.group(1) if url else "-"
    r = rev.group(1) if rev else ""
    print("%-28s %-5s %-70s %s" % (f, kind, u, r))
