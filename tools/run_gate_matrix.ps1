# Gate A/B (2026-09-27): blind + ring + threat-gated edge penalty (--gate).
# The matrix-0927 wall-commit variant was net negative; the gate is the
# other untested wall lever (R4.5 _pinned_gate: +EDGE_ESCAPE_PENALTY to
# toward-wall headings only when in-band AND death within 12 frames AND
# the argmin is toward the wall).
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$outdir = Join-Path $root "logs\probe-matrix"
$log = Join-Path $outdir "matrix-gate-0927.log"
Set-Content -Path $log -Value "gate matrix started $(Get-Date -Format s)"

$stages = @(
    @{ tag = "m3cam-0926-183317"; n = 1; carry = "" },
    @{ tag = "m3cam-0926-183317"; n = 2; carry = "" },
    @{ tag = "m3cam-0926-172908"; n = 3; carry = "" },
    @{ tag = "m3cam-0926-184353"; n = 4; carry = "simdata\carry\s4-measure.json" },
    @{ tag = "m3cam-0926-185159"; n = 5; carry = "simdata\carry\s5-measure.json" },
    @{ tag = "m3cam-0926-185445"; n = 6; carry = "simdata\carry\s6-measure.json" }
)

foreach ($st in $stages) {
    $name = "s$($st.n)-gate"
    $flog = Join-Path $outdir "$name.log"
    $t0 = Get-Date
    $args2 = @("tools\probe_evader.py", $st.tag, [string]$st.n,
               "--variant", "VA4", "normal",
               "--gate", "--laser-blind-fix", "--laser-ring", "--lives", "8")
    if ($st.carry) { $args2 += @("--carry", $st.carry) }
    $out = & venv\Scripts\python.exe $args2 2>&1
    $dur = (Get-Date) - $t0
    $out | Set-Content -Path $flog -Encoding utf8
    $sum = ($out | Select-String -Pattern "frames=|DEATH f=" | ForEach-Object { $_.Line.Trim() }) -join " | "
    Add-Content -Path $log -Value ("{0,-10} {1,6}  {2}" -f $name, $dur.ToString("hh\:mm\:ss"), $sum)
    Write-Host ("{0,-10} {1,6}  {2}" -f $name, $dur.ToString("hh\:mm\:ss"), $sum)
}
Add-Content -Path $log -Value "gate matrix finished $(Get-Date -Format s)"
Write-Host "done; log: $log"
