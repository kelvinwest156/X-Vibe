@echo off
title X-VibeBot - Login to X (Twitter)
cd /d "%~dp0"
echo ======================================================================
echo    X-VIBEBOT: MANUAL X (TWITTER) LOGIN LAUNCHER
echo ======================================================================
echo.
echo Launching Chromium browser with your persistent bot profile...
echo.
echo  1. Enter your X (Twitter) username and password.
echo  2. Once signed in, your session is saved permanently in ./x_browser_profile.
echo  3. Return to the dashboard at http://localhost:8000 and click 'Refresh'.
echo.
echo ======================================================================
echo.

set "CHROMIUM_PATH=%LOCALAPPDATA%\ms-playwright\chromium-1248\chrome-win64\chrome.exe"

if not exist "%CHROMIUM_PATH%" (
    if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
        set "CHROMIUM_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
)

start "" "%CHROMIUM_PATH%" --user-data-dir="%~dp0x_browser_profile" --no-first-run --no-default-browser-check https://x.com/login

echo Browser launched on your desktop! Sign in and return to the dashboard.
pause
