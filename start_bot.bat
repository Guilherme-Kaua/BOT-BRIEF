@echo off
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Python\pythoncore-3.15-64\pythonw.exe" (
    start "" "%LOCALAPPDATA%\Python\pythoncore-3.15-64\pythonw.exe" -m app.main --open
) else (
    start "" pythonw -m app.main --open
)


