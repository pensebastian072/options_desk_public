# Install (or remove) a login-autostart shortcut that keeps the local Codex runner alive
# so the cloud-scheduled "Options Desk Morning" automation (weekdays 09:35) can dispatch
# to this machine. On Windows the supported local-project host is the installed OpenAI
# Codex desktop app, so the shortcut launches that packaged app at login through a hidden
# wscript/PowerShell chain. No admin/UAC (per-user Startup). ASCII-only.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_codex_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_codex_autostart.ps1 -Uninstall
#
# NOTE: this only makes the host AVAILABLE. The automation itself is scheduled and run by
# Codex (read-only Robinhood by the user's config). The machine must be awake and the
# Codex desktop app signed in at 09:35 - Windows autostart does not wake a sleeping PC.
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "Codex Runner (Options Desk).lnk"

if ($Uninstall) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
    Write-Output "removed $lnk"
    return
}

$vbs = Join-Path $repo "scripts\_codex_host.vbs"
if (-not (Test-Path $vbs)) { throw "missing $vbs" }

$sh = New-Object -ComObject WScript.Shell
$sc = $sh.CreateShortcut($lnk)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = '"' + $vbs + '"'
$sc.WorkingDirectory = $repo
$sc.WindowStyle = 7
$sc.Description = "Keep the Codex desktop app up for the 09:35 Options Desk automation"
$sc.Save()
Write-Output "installed $lnk"
Write-Output "test now (opens the Codex desktop app if it is not already up):"
Write-Output "  wscript `"$vbs`""
