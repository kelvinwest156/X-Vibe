@echo off
title X-VibeBot - Login to X (Twitter)
cd /d "%~dp0"
echo ======================================================================
echo    Starting X-VibeBot Login Assistant (Default Browser)...
echo ======================================================================
echo.
python login.py
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to launch login.py.
    echo Please make sure Python is installed and in your PATH.
)
echo.
pause
