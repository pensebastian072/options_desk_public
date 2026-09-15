# Register the OptionsDeskDaily Task Scheduler job -- builds + publishes + Telegram-
# pushes the option-candidate alert before the 09:30 open, AFTER qlib PreOpenVolDesk
# (08:55) has written the signal. Runs as the current user at normal (Limited) run
# level -- no admin, no UAC. ASCII-only. Runs wscript -> _run_desk.vbs (hidden).
# Default 09:05 local weekdays (box is on 08:00-20:00).
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_desk.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_desk.ps1 -At 09:05
#   powershell -ExecutionPolicy Bypass -File scripts\register_desk.ps1 -Unregister
param(
    [string]$At = "09:05",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$taskName = "OptionsDeskDaily"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "unregistered $taskName"
    return
}

$vbs = Join-Path $repo "scripts\_run_desk.vbs"
if (-not (Test-Path $vbs)) { throw "missing $vbs" }

$action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
# Weekdays only -- no market open on Sat/Sun.
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

# No -Principal: runs as the registering user, Limited run level, only when logged on.
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName' weekdays at $At"
Write-Output "run now to test: Start-ScheduledTask -TaskName $taskName"
Write-Output "log: journal\runs\options_desk_<YYYYMMDD>.log"
Write-Output "NOTE: needs secrets\telegram.json {bot_token,chat_id} for the push."
