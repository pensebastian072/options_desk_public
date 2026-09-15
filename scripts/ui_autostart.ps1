# Start the options_desk loopback UI if it is not already up. Idempotent: checks
# 127.0.0.1:8078 first so login autostart + manual launch never double-run it.
# ASCII-only (PS 5.1). Launched hidden via _ui.vbs.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
$port = 8078

$up = $false
try {
    $c = New-Object Net.Sockets.TcpClient
    $c.Connect("127.0.0.1", $port); $up = $c.Connected; $c.Close()
} catch { $up = $false }

if ($up) { Write-Output "UI already up on 127.0.0.1:$port"; return }

Set-Location $repo
$env:PYTHONPATH = $repo
$runs = Join-Path $repo "journal\runs"
New-Item -ItemType Directory -Force -Path $runs | Out-Null
$log = Join-Path $runs "ui.log"
Start-Process -FilePath $py -ArgumentList "-m","ui.app" -WorkingDirectory $repo `
    -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError (Join-Path $runs "ui.err.log")
Write-Output "started UI -> http://127.0.0.1:$port/"
