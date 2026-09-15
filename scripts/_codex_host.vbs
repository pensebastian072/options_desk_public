' Launch the Codex-host starter HIDDEN (window style 0) via PowerShell. Keeps the local
' Codex desktop app runner available for the 09:35 local-project automation.
Set sh = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ps1 = dir & "start_codex_host.ps1"
sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """", 0, False
