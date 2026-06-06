@echo off
title MediCloud — Live Logs
echo  Showing live logs... (Press Ctrl+C to stop watching)
echo.
docker-compose logs -f
