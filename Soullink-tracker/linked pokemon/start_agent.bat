@echo off
where python >nul 2>nul
if errorlevel 1 (
    echo Python ist nicht installiert. Bitte von python.org installieren.
    pause
    exit /b 1
)
python -m pip install --quiet requests
python "%~dp0agent.py"
pause
