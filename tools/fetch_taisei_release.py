"""Download stock Taisei v1.4.6 (portable zip) for replay playback / final video.

Asset per doc/requirements-decisions.md S6 (user-specified release).
"""
import os
import urllib.request

URL = "https://github.com/taisei-project/taisei/releases/download/v1.4.6/Taisei-1.4.6-windows-x86_64.zip"
DEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "third_party", "taisei-1.4.6.zip",
)

if os.path.isfile(DEST) and os.path.getsize(DEST) > 200_000_000:
    print("already downloaded:", DEST, os.path.getsize(DEST))
    raise SystemExit(0)

print("downloading", URL)
urllib.request.urlretrieve(URL, DEST)
print("done:", DEST, os.path.getsize(DEST), "bytes")
