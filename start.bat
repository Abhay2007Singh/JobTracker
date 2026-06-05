@echo off
title JobTracker
cd /d "%~dp0"

echo [1/3] Checking virtual environment...
if not exist ".venv\Scripts\python.exe" (
    echo      Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment. Is Python installed?
        pause
        exit /b 1
    )
)

echo [2/3] Installing / verifying dependencies...
.venv\Scripts\pip.exe install -q -r requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo [3/3] Starting JobTracker...
echo.
.venv\Scripts\python.exe run.py

pause
