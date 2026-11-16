"""
Browser Automation Services for X-VibeBot.
Re-exports the core XBrowserWorker and platform utilities.
"""

from services.browser.process import (
    DEFAULT_PROFILE_DIR,
    get_default_chromium_path,
    kill_profile_browser_processes,
)
from services.browser.worker import XBrowserWorker

__all__ = [
    "XBrowserWorker",
    "DEFAULT_PROFILE_DIR",
    "get_default_chromium_path",
    "kill_profile_browser_processes",
]
