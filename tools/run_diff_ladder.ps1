# Difficulty ladder: Mica vs Laya on Hard + Lunatic (2026-09-27, M5b).
# Same flags as the Medium A/B (promoted executor combo, no-bomb, build-gl33,
# Marisa A, seed 12345+stage). Sequential (shared simdata cache/storage).
#   powershell -File tools\run_diff_ladder.ps1
$ErrorActionPreference = "Continue"
$py = "venv\Scripts\python.exe"
$flags = @("--no-bomb", "--gap-horizon", "--laser-blind-fix", "--laser-ring",
           "--build-dir", "build-gl33")

Write-Output "### [1/4] Mica HARD"
& $py tools\test_m3_campaign.py --diff hard @flags --engine mica *>&1 |
    Tee-Object -FilePath logs\run-2026-09-27-mica-hard.log
Write-Output "### [2/4] Mica LUNATIC"
& $py tools\test_m3_campaign.py --diff lunatic @flags --engine mica *>&1 |
    Tee-Object -FilePath logs\run-2026-09-27-mica-lunatic.log
Write-Output "### [3/4] Laya HARD (new executor; old-executor baseline: S1 WON 2 / S2 LOST 1)"
& $py tools\test_m3_campaign.py --diff hard @flags --engine laya *>&1 |
    Tee-Object -FilePath logs\run-2026-09-27-laya-hard.log
Write-Output "### [4/4] Laya LUNATIC (new executor)"
& $py tools\test_m3_campaign.py --diff lunatic @flags --engine laya *>&1 |
    Tee-Object -FilePath logs\run-2026-09-27-laya-lunatic.log
Write-Output "### ladder done"
