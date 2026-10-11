@echo off
rem Starts the Referee server and the Word helper whenever you log in to Windows.
rem Run once from the repository folder: scripts\install-windows.bat
rem To remove: delete "Referee.vbs" from your Startup folder (Win+R, shell:startup).

set REPO=%~dp0..
for %%I in ("%REPO%") do set REPO=%%~fI
set PY=%REPO%\.venv\Scripts\pythonw.exe
if not exist "%PY%" (
  echo Create the virtual environment first: python -m venv .venv ^&^& .venv\Scripts\pip install -r server\requirements.txt pywin32
  exit /b 1
)

set VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Referee.vbs
(
  echo Set shell = CreateObject^("WScript.Shell"^)
  echo shell.CurrentDirectory = "%REPO%\server"
  echo shell.Run """%PY%"" -m uvicorn main:app --port 8000", 0, False
  echo shell.CurrentDirectory = "%REPO%\word-helper"
  echo shell.Run """%PY%"" helper.py", 0, False
) > "%VBS%"

wscript "%VBS%"
echo Referee installed: the server and Word helper start when you log in, and are running now.
