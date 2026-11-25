"""
Browser Process Management & Binary Detection Service for X-VibeBot.
Detects user's default Chromium-based browser on Windows (Brave, Chrome, Edge)
and safely cleans up isolated browser profile processes via psutil.
"""

import os
import re
import shlex
import asyncio
import logging
from typing import Optional, List, Sequence, Any

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

_CHROMIUM_BIN_PREFIXES = (
    "chrome",
    "chromium",
    "brave",
    "msedge",
    "microsoft-edge",
    "google-chrome",
    "headless_shell",
)
_POSIX_SINGLETON_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def normalize_profile_path(profile_dir: str) -> str:
    """Normalizes a browser profile directory path for exact cross-platform comparison."""
    if not profile_dir or not str(profile_dir).strip():
        return ""
    return os.path.normcase(os.path.realpath(str(profile_dir).strip()))


def extract_user_data_dirs_from_cmdline(cmdline: Any) -> List[str]:
    """Extracts all --user-data-dir path arguments from a process argv sequence."""
    if not cmdline:
        return []
    if isinstance(cmdline, str):
        try:
            tokens: Sequence[str] = shlex.split(cmdline, posix=(os.name != "nt"))
        except Exception:
            tokens = cmdline.split()
    else:
        tokens = list(cmdline)

    dirs: List[str] = []
    idx = 0
    total = len(tokens)
    while idx < total:
        token = str(tokens[idx] or "")
        if token.startswith("--user-data-dir="):
            raw_val = token.split("=", 1)[1].strip().strip('"').strip("'")
            if raw_val:
                dirs.append(raw_val)
        elif token == "--user-data-dir" and idx + 1 < total:
            raw_val = str(tokens[idx + 1] or "").strip().strip('"').strip("'")
            if raw_val:
                dirs.append(raw_val)
            idx += 1
        idx += 1
    return dirs


def _is_chromium_executable_name(proc_name: Optional[str], cmdline: Any) -> bool:
    """Checks whether a process name / argv[0] belongs to a Chromium-family browser."""
    candidate = (proc_name or "").strip().lower()
    if not candidate and isinstance(cmdline, (list, tuple)) and cmdline:
        candidate = os.path.basename(str(cmdline[0] or "")).strip().lower()
    if not candidate:
        return False
    if "chromedriver" in candidate:
        return False
    return candidate.startswith(_CHROMIUM_BIN_PREFIXES)


def is_profile_browser_process(
    proc_name: Optional[str],
    cmdline: Any,
    target_norm_path: str,
) -> bool:
    """
    Returns True ONLY if `proc_name`/`cmdline` is a Chromium-family process
    whose `--user-data-dir` argv token resolves to `target_norm_path` exactly.
    """
    if not target_norm_path or not cmdline:
        return False
    if not _is_chromium_executable_name(proc_name, cmdline):
        return False
    for raw_dir in extract_user_data_dirs_from_cmdline(cmdline):
        if normalize_profile_path(raw_dir) == target_norm_path:
            return True
    return False


def _find_profile_browser_processes(target_norm_path: str) -> tuple[bool, List[Any]]:
    """
    Scans running processes via psutil for Chromium instances matching `target_norm_path`.
    Returns (psutil_available, matching_processes).
    """
    if not target_norm_path:
        return True, []
    try:
        import psutil
    except ImportError:
        logger.warning("psutil is not installed; cannot inspect browser processes.")
        return False, []

    matched: List[Any] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = proc.info or {}
            cmdline = info.get("cmdline")
            if not cmdline:
                continue
            if is_profile_browser_process(info.get("name"), cmdline, target_norm_path):
                matched.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return True, matched


def _cleanup_posix_singleton_locks(profile_dir: str) -> None:
    """Removes stale Chromium Singleton* lock files/symlinks on POSIX systems."""
    if os.name == "nt" or not profile_dir or not os.path.isdir(profile_dir):
        return
    for name in _POSIX_SINGLETON_FILES:
        lock_path = os.path.join(profile_dir, name)
        try:
            if os.path.lexists(lock_path) and (os.path.islink(lock_path) or not os.path.isdir(lock_path)):
                os.unlink(lock_path)
                logger.debug(f"Removed stale Chromium lock {lock_path}")
        except Exception as exc:
            logger.debug(f"Notice removing stale Chromium lock {lock_path}: {exc}")


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


def kill_profile_browser_processes(profile_dir: str) -> None:
    """
    Safely terminates ONLY Chromium processes whose `--user-data-dir` argv token
    matches `profile_dir` exactly, leaving other tenants and personal browsers untouched.
    On POSIX/Linux, removes stale Singleton* locks only after confirming no owner remains.
    """
    target_norm = normalize_profile_path(profile_dir)
    if not target_norm:
        return

    psutil_ok, matched = _find_profile_browser_processes(target_norm)
    if not psutil_ok:
        return

    try:
        import psutil
    except ImportError:
        return

    if matched:
        for proc in matched:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as exc:
                logger.debug(f"Notice terminating profile browser process: {exc}")

        alive: List[Any] = []
        try:
            _, alive = psutil.wait_procs(matched, timeout=3.0)
        except Exception:
            alive = [p for p in matched if getattr(p, "is_running", lambda: False)()]

        if alive:
            for proc in alive:
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception as exc:
                    logger.debug(f"Notice killing straggler browser process: {exc}")
            try:
                psutil.wait_procs(alive, timeout=2.0)
            except Exception:
                pass

    if os.name != "nt":
        _, remaining = _find_profile_browser_processes(target_norm)
        live_remaining = []
        for proc in remaining:
            try:
                zombie_status = getattr(psutil, "STATUS_ZOMBIE", "zombie")
                if proc.is_running() and proc.status() != zombie_status:
                    live_remaining.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                live_remaining.append(proc)

        if not live_remaining:
            _cleanup_posix_singleton_locks(target_norm)


async def kill_profile_browser_processes_async(profile_dir: str) -> None:
    """Non-blocking async wrapper for kill_profile_browser_processes."""
    await asyncio.to_thread(kill_profile_browser_processes, profile_dir)
