"""
Browser Process Management & Binary Detection Service for X-VibeBot.
Detects user's default Chromium-based browser on Windows (Brave, Chrome, Edge)
and safely cleans up isolated browser profile processes.
"""

import os
import re
import logging
from typing import Optional

logger = logging.getLogger("x_vibebot.services.browser.process")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_env_profile = os.getenv("BROWSER_PROFILE_DIR")
if _env_profile:
    DEFAULT_PROFILE_DIR = os.path.abspath(_env_profile)
elif os.path.exists(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile")):
    DEFAULT_PROFILE_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile"))
elif os.path.exists(os.path.join(BASE_DIR, "x_browser_profile")):
    DEFAULT_PROFILE_DIR = os.path.abspath(os.path.join(BASE_DIR, "x_browser_profile"))
else:
    DEFAULT_PROFILE_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile"))


def get_default_chromium_path() -> Optional[str]:
    """
    Detects the user's default Chromium-based browser on Windows (e.g. Brave, Chrome, Edge).
    Returns the executable path, or None to fall back to Playwright's bundled Chromium.
    """
    env_browser = os.getenv("BROWSER_EXECUTABLE_PATH")
    if env_browser and os.path.isfile(env_browser):
        return env_browser

    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
            ) as key:
                prog_id, _ = winreg.QueryValueEx(key, "ProgId")

            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                rf"{prog_id}\shell\open\command"
            ) as cmd_key:
                raw_cmd, _ = winreg.QueryValueEx(cmd_key, "")

            match = re.search(r'"([^"]+)"', raw_cmd)
            exe_path = match.group(1) if match else raw_cmd.split()[0]
            if os.path.isfile(exe_path) and any(b in exe_path.lower() for b in ["brave", "chrome", "msedge", "edge"]):
                return exe_path
        except Exception:
            pass

        candidates = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

    return None


def kill_profile_browser_processes(profile_dir: str):
    """
    Safely terminates ONLY browser processes whose command line explicitly targets `profile_dir`
    (e.g. x_browser_profile), leaving the user's personal browser windows completely untouched.
    """
    profile_folder_name = os.path.basename(os.path.normpath(profile_dir))
    if not profile_folder_name:
        return

    if os.name == "nt":
        import subprocess
        ps_cmd = (
            f"Get-CimInstance Win32_Process -Filter \"Name='brave.exe' OR Name='chrome.exe' OR Name='msedge.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{profile_folder_name}*' }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                timeout=20
            )
        except Exception as e:
            logger.debug(f"Notice cleaning up profile processes: {e}")
