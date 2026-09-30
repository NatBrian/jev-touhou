# Probe A/B matrix (2026-09-27): 4 variants x 6 measured stages.
#   base : VA4 + fidelity fix (the G2.93 R4.6 configuration)
#   blind: + --laser-blind-fix        (R5.1)
#   ring : + --laser-blind-fix --laser-ring          (R5.2)
#   wall : + --laser-blind-fix --laser-ring --wall-commit (R5.1+R5.2+R6.1)
# --lives 8 => observation mode: full death distribution per stage.
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$outdir = Join-Path $root "logs\probe-matrix"
if (!(Test-Path $outdir)) { New-Item -ItemType Directory -Path $outdir | Out-Null }
$log = Join-Path $outdir "matrix-0927.log"
Set-Content -Path $log -Value "probe matrix started $(Get-Date -Format s)"

$stages = @(
    @{ tag = "m3cam-0926-183317"; n = 1; carry = "" },
    @{ tag = "m3cam-0926-183317"; n = 2; carry = "" },
    @{ tag = "m3cam-0926-172908"; n = 3; carry = "" },
    @{ tag = "m3cam-0926-184353"; n = 4; carry = "simdata\carry\s4-measure.json" },
    @{ tag = "m3cam-0926-185159"; n = 5; carry = "simdata\carry\s5-measure.json" },
    @{ tag = "m3cam-0926-185445"; n = 6; carry = "simdata\carry\s6-measure.json" }
)
$variants = @(
    @{ name = "base"; flags = @() },
    @{ name = "blind"; flags = @("--laser-blind-fix") },
    @{ name = "ring"; flags = @("--laser-blind-fix", "--laser-ring") },
    @{ name = "wall"; flags = @("--laser-blind-fix", "--laser-ring", "--wall-commit") }
)

foreach ($st in $stages) {
    foreach ($v in $variants) {
        $name = "s$($st.n)-$($v.name)"
        $flog = Join-Path $outdir "$name.log"
        $t0 = Get-Date
        $args2 = @("tools\probe_evader.py", $st.tag, [string]$st.n,
                   "--variant", "VA4", "normal") + $v.flags
        if ($st.carry) { $args2 += @("--carry", $st.carry) }
        $args2 += @("--lives", "8")
        $out = & venv\Scripts\python.exe $args2 2>&1
        $dur = (Get-Date) - $t0
        $out | Set-Content -Path $flog -Encoding utf8
        $sum = ($out | Select-String -Pattern "frames=|DEATH f=|CARRY loaded|LIVES override" | ForEach-Object { $_.Line.Trim() }) -join " | "
        Add-Content -Path $log -Value ("{0,-10} {1,6}  {2}" -f $name, $dur.ToString("hh\:mm\:ss"), $sum)
        Write-Host ("{0,-10} {1,6}  {2}" -f $name, $dur.ToString("hh\:mm\:ss"), $sum)
    }
}
Add-Content -Path $log -Value "probe matrix finished $(Get-Date -Format s)"
Write-Host "done; log: $log"
