@echo off
title MediCloud Local Backend

echo.
echo  ==========================================
echo   MediCloud Local Backend - Starting...
echo  ==========================================
echo.

if not exist .env (
    echo  [ERROR] .env file not found!
    echo  Please copy .env.example to .env
    echo.
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found!
    echo  Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

if not exist venv (
    echo  [INFO] Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo  [INFO] Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo  [INFO] Your local IP addresses:
ipconfig | findstr /i "IPv4"
echo.
echo  [INFO] Starting MediCloud backend on http://0.0.0.0:8001
echo  [INFO] Devices page : http://localhost:8001/devices
echo  [INFO] Status page  : http://localhost:8001/status
echo  [INFO] API Docs     : http://localhost:8001/docs
echo  [INFO] Press Ctrl+C to stop
echo.

REM Open devices page in browser after 3 seconds
start /b cmd /c "timeout /t 3 >nul && start http://localhost:8001/devices"

uvicorn main:app --host 0.0.0.0 --port 8001 --reload

pause
