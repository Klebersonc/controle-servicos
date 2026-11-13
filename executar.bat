@echo off
cd /d "%~dp0"
set "PATH=%PATH%;%USERPROFILE%\.local\bin"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
) else (
    where uv >nul 2>nul
    if %errorlevel%==0 (
        start "" uv run pythonw "%~dp0main.py"
    ) else (
        start "" pythonw "%~dp0main.py"
    )
)
