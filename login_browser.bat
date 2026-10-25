@echo off
title X-VibeBot - Login to X (Twitter)
cd /d "%~dp0"
echo ======================================================================
echo    Starting X-VibeBot Login Assistant...
echo ======================================================================
echo.
python login.py
if errorlevel 1 (
    echo.
    echo [ERROR] Python failed to launch login.py.
    echo Please make sure Python is installed and in your PATH.
)
echo.
pause
