@echo off
title MediCloud - First Time Setup

echo.
echo  ==========================================
echo   MediCloud Local Backend - Setup
echo  ==========================================
echo.

REM Step 1: Check Python
echo  [1/4] Checking Python...
python --version
if errorlevel 1 (
    echo  Python not found. Please install Python 3.10+ from https://python.org
    echo  Make sure to check "Add Python to PATH" during installation!
    pause
    exit /b 1
)

REM Step 2: Create virtual environment
echo.
echo  [2/4] Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

REM Step 3: Install packages
echo.
echo  [3/4] Installing packages...
pip install -r requirements.txt

REM Step 4: Setup .env
echo.
echo  [4/4] Setting up .env file...
if not exist .env (
    copy .env.example .env
    echo  .env file created from template.
    echo.
    echo  ============================================================
    echo   IMPORTANT: Open .env file and check the DATABASE_URL
    echo   It should already be set to the MediCloud cloud database.
    echo  ============================================================
) else (
    echo  .env already exists, skipping.
)

echo.
echo  ==========================================
echo   Setup complete!
echo   Run start.bat to launch the backend.
echo  ==========================================
echo.
pause
