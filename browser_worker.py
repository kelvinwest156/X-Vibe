"""
Browser Worker Facade for X-VibeBot.
Re-exports modular browser automation services from `services.browser`.
Preserves 100% backward compatibility for all scripts, routers, and core state registries.
"""

from services.browser.process import (
    DEFAULT_PROFILE_DIR,
    get_default_chromium_path,
    kill_profile_browser_processes,
)
from services.browser.worker import XBrowserWorker

__all__ = [
    "DEFAULT_PROFILE_DIR",
    "get_default_chromium_path",
    "kill_profile_browser_processes",
    "XBrowserWorker",
]
