' Launch the options_desk UI autostart HIDDEN (window style 0) via python.exe through
' the PowerShell helper. NOT pythonw.exe -- Norton 360 blocks pythonw.exe in a venv
' Scripts dir on this box (norton-blocks-pythonw-venv).
Set sh = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ps1 = dir & "ui_autostart.ps1"
sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """", 0, False
