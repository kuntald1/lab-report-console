@echo off
REM ============================================================
REM  MediCloud Local Backend - Portproxy Setup Script
REM  Run this once as Administrator to create a Scheduled Task
REM  that re-applies portproxy rules on every reboot.
REM ============================================================

echo Removing any existing portproxy rules on these ports...
netsh interface portproxy delete v4tov4 listenport=8080 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=2001 listenaddress=0.0.0.0 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=5002 listenaddress=0.0.0.0 >nul 2>&1

echo Adding portproxy rules...

REM GH-900 (HbA1c) : 8080 -> 7777
netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=7777 connectaddress=127.0.0.1

REM Snibe Maglumi X3 : 2001 -> 6003
netsh interface portproxy add v4tov4 listenport=2001 listenaddress=0.0.0.0 connectport=6003 connectaddress=127.0.0.1

REM Sysmex XN330 : 5002 -> 6002
netsh interface portproxy add v4tov4 listenport=5002 listenaddress=0.0.0.0 connectport=6002 connectaddress=127.0.0.1

echo.
echo Done! Current portproxy rules:
netsh interface portproxy show all

echo.
echo ============================================================
echo Now creating a Scheduled Task to run this automatically
echo at every system startup (runs as SYSTEM, no login needed)...
echo ============================================================

REM Get the full path of this batch file
set SCRIPT_PATH=%~dp0setup_portproxy.bat

schtasks /Create /TN "MediCloud_Portproxy_Setup" /TR "\"%SCRIPT_PATH%\"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F

echo.
echo ============================================================
echo Setup complete! Portproxy rules will now be re-applied
echo automatically every time this PC reboots.
echo ============================================================
pause
