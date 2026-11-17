@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up FlowWriter Studio Python environment...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
    if errorlevel 1 goto :failed
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :failed
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m flowwriter
if errorlevel 1 goto :failed
exit /b 0
:failed
echo FlowWriter startup failed. Check Python 3.11+ and package installation.
pause
exit /b 1
