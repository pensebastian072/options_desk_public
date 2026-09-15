# Install (or remove) the login-autostart shortcut for the options_desk UI. Creates
# a .lnk in the user's Startup folder targeting wscript.exe -> _ui.vbs (hidden), so
# the loopback dashboard comes up at login. No admin/UAC (per-user Startup). ASCII-only.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Uninstall
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "OptionsDesk UI.lnk"

if ($Uninstall) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
    Write-Output "removed $lnk"
    return
}

$vbs = Join-Path $repo "scripts\_ui.vbs"
if (-not (Test-Path $vbs)) { throw "missing $vbs" }

$sh = New-Object -ComObject WScript.Shell
$sc = $sh.CreateShortcut($lnk)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = '"' + $vbs + '"'
$sc.WorkingDirectory = $repo
$sc.WindowStyle = 7          # minimized (wscript itself runs the ps1 hidden)
$sc.Description = "options_desk loopback UI autostart"
$sc.Save()
Write-Output "installed $lnk"
Write-Output "UI will start at next login; launch now: wscript `"$vbs`""
