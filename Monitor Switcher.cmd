@echo off
REM Launches the Monitor Workspace Switcher GUI without a console window.
cd /d "%~dp0"
start "" pythonw "%~dp0app.py"
