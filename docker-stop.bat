@echo off
title MediCloud — Docker Stop

echo.
echo  Stopping MediCloud backend...
docker-compose down
echo.
echo  Backend stopped.
echo  Run docker-start.bat to start again.
echo.
pause
