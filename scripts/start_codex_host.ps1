# Ensure the local Codex runner is alive so the cloud-scheduled "Options Desk Morning"
# automation (weekdays 09:35) can dispatch to this machine. On Windows the runner is
# hosted by the installed OpenAI Codex desktop app. This launches the packaged app;
# the app then starts its own codex app-server runner.
#
# It does NOT run the automation, bypass approvals, or touch Robinhood. It only makes the
# host available; Codex runs the user's existing read-only automation under its own
# settings. Idempotent: if the runner is already up, it does nothing. ASCII-only (PS 5.1).
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$runs = Join-Path $repo "journal\runs"
New-Item -ItemType Directory -Force -Path $runs | Out-Null
$log = Join-Path $runs "codex_host.log"
function Log($m) { "[{0}] {1}" -f (Get-Date -Format s), $m | Out-File -FilePath $log -Append -Encoding utf8 }

# Already running? Check the packaged desktop app itself, not a VS Code extension host.
$running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -ieq 'ChatGPT.exe' -and
        $_.ExecutablePath -match '\\WindowsApps\\OpenAI\.Codex_'
    }
if ($running) { Log "Codex desktop app already up (pid $($running.ProcessId -join ','))"; return }

# Resolve the version-independent packaged-app identity registered with Windows.
$app = Get-StartApps -ErrorAction SilentlyContinue |
    Where-Object { $_.AppID -match '^OpenAI\.Codex_.*!App$' } |
    Select-Object -First 1
if (-not $app) { Log "OpenAI Codex desktop app is not registered"; return }

# Launch through AppsFolder so Windows resolves the current package version.
$target = "shell:AppsFolder\$($app.AppID)"
Start-Process -FilePath "$env:WINDIR\explorer.exe" -ArgumentList $target -WindowStyle Hidden
Log "launched Codex desktop host: $($app.AppID)"
