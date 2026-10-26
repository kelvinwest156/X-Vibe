@echo off
title X-VibeBot Controller Server
cd /d "%~dp0"
echo ======================================================================
echo    X-VIBEBOT: LAUNCHING AUTONOMOUS AGENT SERVER
echo ======================================================================
echo.
echo Control Dashboard: http://localhost:8000
echo.
echo Press CTRL+C at any time to pause the server.
echo.
echo ======================================================================
echo.
python main.py
pause
