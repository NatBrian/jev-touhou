# capture_game_replay.ps1 — record a real-art taisei.exe replay to mp4 via ffmpeg gdigrab.
#
# Usage:
#   powershell -NoProfile -File tools\capture_game_replay.ps1 `
#     -Replay simdata\replays\m3cam-0927-160014-stage1-normal.trsr `
#     -Out simdata\cache\game-capture-laya.mp4 -Seconds 270
#
# Launches taisei.exe (gl33) playing the .trsr at 1280x720, waits for the window,
# then ffmpeg-gdigrab-captures the window at 60 fps for $Seconds, then kills the game.
# The capture includes the loading screen + full stage + the clear screen; the
# gameplay-start frame is detected in post-processing.

param(
  [Parameter(Mandatory)][string]$Replay,
  [Parameter(Mandatory)][string]$Out,
  [int]$Seconds = 260,
  [int]$Width = 1280,
  [int]$Height = 720,
  [string]$Title = "Taisei Project v1.4.6-2-g3c962767-dirty-sim-on-v146"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Exe  = Join-Path $Root "third_party\taisei-sim\build-gl33\src\taisei.exe"
$Log  = Join-Path $Root "simdata\cache\capture-run.log"

function Log($m) { $t = (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"); Add-Content -Path $Log -Value "[$t] $m"; Write-Host "[$t] $m" }

if (-not (Test-Path $Exe)) { throw "exe not found: $Exe" }
if (-not (Test-Path $Replay)) { throw "replay not found: $Replay" }

# Kill any stale taisei
Get-Process taisei -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

Log "=== capture start ==="
Log "exe    = $Exe"
Log "replay = $Replay"
Log "out    = $Out"
Log "secs   = $Seconds  ${Width}x${Height}"

$proc = Start-Process -FilePath $Exe `
  -ArgumentList @('-r', $Replay, '--renderer', 'gl33', '-W', "$Width", '-H', "$Height") `
  -WorkingDirectory $Root -PassThru
Log "launched pid=$($proc.Id)"

# Wait for the window title to appear (up to 120 s). The exact -Title is used
# when it matches; otherwise we fall back to any "Taisei Project ..." window of
# the launched process, because the version string depends on the git describe
# of the local build (e.g. "Taisei Project v1.4.6-g<sha>...").
$winT0 = Get-Date
$seen = $false
for ($i = 0; $i -lt 240; $i++) {
  Start-Sleep -Milliseconds 500
  $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
  if (-not $p) { Log "WARN: process died during window wait"; break }
  if ($p.MainWindowTitle -eq $Title) { $seen = $true; break }
}
if (-not $seen) {
  $p = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
  if ($p -and $p.MainWindowTitle -like 'Taisei Project*') {
    $Title = $p.MainWindowTitle
    $seen = $true
    Log "exact -Title not seen; using discovered window title '$Title'"
  }
}
if (-not $seen) { Log "ERROR: window title not seen in 120 s"; Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue; exit 1 }
$winMs = [int]((Get-Date) - $winT0).TotalMilliseconds
Log "window up after ${winMs} ms (title='$Title')"

# Small settle so the window is fully painted, then capture.
Start-Sleep -Milliseconds 400
$capT0 = Get-Date
Log "starting ffmpeg capture for ${Seconds}s ..."

# ffmpeg gdigrab: force 60 fps output, crf18, yuv420p.
& ffmpeg -y -loglevel error -f gdigrab -framerate 60 -i "title=$Title" `
  -t "$Seconds" -c:v libx264 -crf 18 -pix_fmt yuv420p -preset veryfast "$Out"
$ffrc = $LASTEXITCODE
$capMs = [int]((Get-Date) - $capT0).TotalMilliseconds
Log "ffmpeg done rc=$ffrc after ${capMs} ms"

Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
Log "=== capture done ==="
exit $ffrc
