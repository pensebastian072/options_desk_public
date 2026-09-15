# Register the OptionsDeskWatchdog Task Scheduler job -- checks that today's ETF lane
# actually completed and Telegram-alerts a miss (no trade ideas). Runs after the 09:35
# live Codex window. Current user, normal (Limited) run level -- no admin, no UAC.
# ASCII-only. Runs wscript -> _run_watchdog.vbs (hidden). Default 10:15 local weekdays.
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_watchdog.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register_watchdog.ps1 -At 10:30
#   powershell -ExecutionPolicy Bypass -File scripts\register_watchdog.ps1 -Unregister
param(
    [string]$At = "10:15",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$taskName = "OptionsDeskWatchdog"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "unregistered $taskName"
    return
}

$vbs = Join-Path $repo "scripts\_run_watchdog.vbs"
if (-not (Test-Path $vbs)) { throw "missing $vbs" }

$action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
# Weekdays only -- no market open on Sat/Sun.
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# No -Principal: runs as the registering user, Limited run level, only when logged on.
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null
Write-Output "registered '$taskName' weekdays at $At"
Write-Output "run now to test: Start-ScheduledTask -TaskName $taskName"
Write-Output "log: journal\runs\options_watchdog_<YYYYMMDD>.log"
