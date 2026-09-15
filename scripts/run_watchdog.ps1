# Watchdog worker: verify today's ETF lane actually completed and alert on Telegram if
# the live 09:35 read-only validation was missed. Sends NO trade ideas by policy.
# Idempotent (at most one miss alert per day). ASCII-only (PowerShell 5.1 cp1252).
# Called by _run_watchdog.vbs (hidden) from Task Scheduler OptionsDeskWatchdog.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
Set-Location $repo
$env:PYTHONPATH = $repo

$runs = Join-Path $repo "journal\runs"
New-Item -ItemType Directory -Force -Path $runs | Out-Null
$log = Join-Path $runs ("options_watchdog_" + (Get-Date -Format "yyyyMMdd") + ".log")

"[{0}] watchdog start" -f (Get-Date -Format s) | Out-File -FilePath $log -Append -Encoding utf8
& cmd.exe /c "`"$py`" -m desk.watchdog --telegram >> `"$log`" 2>&1"
"[{0}] watchdog done" -f (Get-Date -Format s) | Out-File -FilePath $log -Append -Encoding utf8
