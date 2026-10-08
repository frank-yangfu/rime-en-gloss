' rime-en-gloss - launch the optional helper with no console window at all.
' Useful for the Startup folder (shell:startup).
'
' Usage:  wscript //nologo start_helper_hidden.vbs
Option Explicit

Dim fso, sh, server, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

server = sh.ExpandEnvironmentStrings("%APPDATA%") & "\Rime\tools\optional_mt_server.py"

If Not fso.FileExists(server) Then
    WScript.Echo "[rime-en-gloss] optional_mt_server.py not found, run scripts\install.ps1 first."
    WScript.Quit 1
End If

cmd = "pythonw.exe """ & server & """ --no-http"
sh.Run cmd, 0, False
