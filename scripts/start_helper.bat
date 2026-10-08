@echo off
rem ---------------------------------------------------------------------------
rem rime-en-gloss - start the OPTIONAL local translation helper.
rem
rem The helper is only needed for long-tail words (3+ characters) that the
rem CC-CEDICT table does not contain. rime-en-gloss shows English for everything
rem else without it.
rem
rem Console output is deliberately ASCII-only: cmd.exe renders this file with the
rem active code page and non-ASCII text would be mangled.
rem ---------------------------------------------------------------------------
setlocal

set "SERVER=%APPDATA%\Rime\tools\optional_mt_server.py"

if not exist "%SERVER%" (
    echo [rime-en-gloss] optional_mt_server.py not found:
    echo                   run scripts\install.ps1 from the repository first.
    exit /b 1
)

where pythonw >nul 2>nul
if errorlevel 1 (
    echo [rime-en-gloss] pythonw.exe is not on PATH. Install Python 3.9+ and retry.
    exit /b 1
)

rem Duplicate instances are harmless: they share the same mailbox directory.
start "" /min pythonw "%SERVER%" --no-http

echo [rime-en-gloss] helper started in the background.
echo [rime-en-gloss] first start loads the model, give it ~20 seconds.
echo [rime-en-gloss] log: %TEMP%\rime_argos\service.log

endlocal
