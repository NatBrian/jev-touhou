# fg_poll.ps1 — poll the foreground window title every 2s for $Seconds,
# appending to $Out. Used to check whether the taisei capture window ever
# gains (or holds) foreground focus during a run.
param([int]$Seconds = 240, [string]$Out = "simdata\cache\fg-poll.txt")
$src = @"
using System;
using System.Runtime.InteropServices;
public class FG {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
}
"@
Add-Type $src
$sw = [System.Diagnostics.Stopwatch]::StartNew()
while($sw.Elapsed.TotalSeconds -lt $Seconds) {
  $h = [FG]::GetForegroundWindow()
  $sb = New-Object System.Text.StringBuilder 512
  [void][FG]::GetWindowText($h, $sb, 512)
  Add-Content -Path $Out -Value ([DateTime]::Now.ToString("HH:mm:ss") + " " + $sb.ToString())
  Start-Sleep -Seconds 2
}
