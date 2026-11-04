@echo off
cd /d "%~dp0"
set "PATH=%PATH%;%USERPROFILE%\.local\bin"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0main.py"
) else (
    uv run pythonw "%~dp0main.py"
)
