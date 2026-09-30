# S6.1 validation matrix (2026-09-30): fresh single-stage runs (no --carry,
# 3 lives), no-bomb, final executor combo (VA4 gap-horizon + laser-blind-fix
# + laser-ring), build-gl33, seed 12345 (per-stage rng_seed = 12345+stage).
#
# Finds each engine's best (difficulty, stage) it can still WIN as a direct
# single-stage run (WON needs <= 2 deaths with 3 lives):
#   Laya  Hard S2 / S3   (campaign prior: S1=2d, S2=1d WON-class, S3 unknown)
#   Mica  Normal S2 / S3 (campaign prior: S1=1d, S2=2d WON-class, S3 unknown)
#
# Logs: logs\s6-validation-<name>.log   (per-stage result line: "== stage N:
# WON/LOST frames=.. deaths=.. bombs=.. score=.. ==" + checkpoint JSON)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$base = @("--build-dir", "build-gl33", "--seed", "12345", "--no-bomb",
          "--gap-horizon", "--laser-blind-fix", "--laser-ring")
$jobs = @(
    @("laya-hard-s2", @("--diff", "hard", "--start-stage", "2", "--end-stage", "2")),
    @("laya-hard-s3", @("--diff", "hard", "--start-stage", "3", "--end-stage", "3")),
    @("mica-norm-s2", @("--diff", "normal", "--engine", "mica", "--start-stage", "2", "--end-stage", "2")),
    @("mica-norm-s3", @("--diff", "normal", "--engine", "mica", "--start-stage", "3", "--end-stage", "3"))
)
foreach ($j in $jobs) {
    $name = $j[0]
    $ja = $j[1]
    $log = "logs\s6-validation-$name.log"
    "== S6 validation: $name : base(" + ($base -join " ") + ") args(" + ($ja -join " ") + ") : " +
        (Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Out-File $log -Encoding utf8
    & venv\Scripts\python.exe tools\test_m3_campaign.py @base @ja 2>&1 |
        Tee-Object -FilePath $log -Append
    "exit=$LASTEXITCODE" | Out-File $log -Append -Encoding utf8
}
"== S6 validation matrix complete: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =="
