# Daily worker: build + publish the options-desk candidate flag and the read-only quote
# request, and track estimates -- SILENTLY (no Telegram). This task is unattended and
# cannot reach session-scoped Robinhood MCP, so it must not send a message at all: the
# 09:35 Codex run owns the ONE morning Telegram (live Robinhood), 10:00 sends progress,
# and the watchdog covers a miss. Sending an unattended "status only" line here just
# duplicated the morning and confused "why is Robinhood skipped" (it can't reach it).
# Reads the qlib_lab vol_desk signal flag (produced ~08:55 by PreOpenVolDesk); does NOT
# fetch/train. ASCII-only (PowerShell 5.1 cp1252).
# Called by _run_desk.vbs (hidden) from Task Scheduler OptionsDeskDaily.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
Set-Location $repo
$env:PYTHONPATH = $repo

$runs = Join-Path $repo "journal\runs"
New-Item -ItemType Directory -Force -Path $runs | Out-Null
$log = Join-Path $runs ("options_desk_" + (Get-Date -Format "yyyyMMdd") + ".log")

"[{0}] options desk start" -f (Get-Date -Format s) | Out-File -FilePath $log -Append -Encoding utf8
# cmd so >> / 2>&1 are native (avoids PowerShell wrapping python stderr in ErrorRecords).
# NO --telegram: this run is silent; the 09:35 Codex live run sends the morning alert.
& cmd.exe /c "`"$py`" -m desk.run_desk --once >> `"$log`" 2>&1"
"[{0}] options desk done" -f (Get-Date -Format s) | Out-File -FilePath $log -Append -Encoding utf8
