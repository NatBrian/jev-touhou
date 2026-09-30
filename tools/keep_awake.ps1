# keep_awake.ps1 — hold ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED for $Seconds
# so Windows does not idle-sleep the machine OR turn the display off during
# long taisei captures (battery plan: standby 300 s, DISPLAY OFF 180 s; agent
# runs send no physical input). Display-off matters because gdigrab of a GL
# window with the display off captures BLACK frames (S6 2026-09-30: the Laya
# Hard S1 capture was all-black until ES_DISPLAY_REQUIRED was added).
#
# Usage: powershell -NoProfile -File tools\keep_awake.ps1 -Seconds 350
param([int]$Seconds = 360)

# Do the set/sleep/release inside C# so the ES_* flag constants (0x80000003,
# 0x80000000) are never parsed by PowerShell as negative Int32 literals.
$src = @'
using System;
using System.Runtime.InteropServices;
public class KA {
  [DllImport("kernel32.dll", SetLastError = true)]
  private static extern uint SetThreadExecutionState(uint esFlags);
  const uint ES_CONTINUOUS = 0x80000000;
  const uint ES_SYSTEM_REQUIRED = 0x00000001;
  const uint ES_DISPLAY_REQUIRED = 0x00000002;
  public static void Hold(int seconds) {
    SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED);
    System.Threading.Thread.Sleep(seconds * 1000);
    SetThreadExecutionState(ES_CONTINUOUS);
  }
}
'@
Add-Type $src
Write-Host ("keep-awake: holding ES_SYSTEM_REQUIRED|ES_DISPLAY_REQUIRED for {0}s" -f $Seconds)
[KA]::Hold($Seconds)
Write-Host "keep-awake: released"
