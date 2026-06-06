@echo off
title MediCloud — Docker Start

echo.
echo  ==========================================
echo   MediCloud Local Backend — Docker Start
echo  ==========================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Docker is not running!
    echo  Please start Docker Desktop first, then run this again.
    echo.
    pause
    exit /b 1
)

REM Check if .env exists
if not exist .env (
    echo  [ERROR] .env file not found!
    echo  Please copy .env.example to .env first.
    echo.
    pause
    exit /b 1
)

REM ── Kill anything already using port 8001 ─────────────────
echo  [INFO] Checking if port 8001 is free...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8001 ^| findstr LISTENING') do (
    echo  [INFO] Port 8001 used by PID %%a — killing it...
    taskkill /PID %%a /F >nul 2>&1
)

REM ── Stop any existing MediCloud container ─────────────────
echo  [INFO] Stopping any existing container...
docker-compose down >nul 2>&1

REM Wait a moment for port to free up
timeout /t 2 >nul

echo  [INFO] Building and starting MediCloud backend...
echo  [INFO] First time may take 2-3 minutes
echo.

REM Build and start in background
docker-compose up -d --build

if errorlevel 1 (
    echo.
    echo  [ERROR] Docker failed to start.
    echo.
    echo  Try these steps:
    echo  1. Open Task Manager - end any python.exe or uvicorn processes
    echo  2. Run this file again
    echo.
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo   MediCloud Backend is RUNNING!
echo  ==========================================
echo.
echo  Status Page : http://localhost:8001/status
echo  Devices Page: http://localhost:8001/devices
echo  API Docs    : http://localhost:8001/docs
echo.
echo  Your LAN IP addresses:
ipconfig | findstr /i "IPv4"
echo.

REM Open browser after 3 seconds
start /b cmd /c "timeout /t 3 >nul && start http://localhost:8001/devices"

echo  [INFO] Backend is running in background.
echo  [INFO] Close this window — backend keeps running.
echo  [INFO] To stop: run docker-stop.bat
echo.
pause
