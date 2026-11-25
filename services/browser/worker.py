"""
Playwright Automation Worker for X (Twitter).
Coordinates persistent browser context, anti-detection stealth,
cookie synchronization, and automated publishing actions.
"""

import os
import sys
import json
import time
import asyncio
import logging
import weakref
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from core.security import sanitize_x_cookies, ALLOWED_X_COOKIE_DOMAINS
from services.browser.process import (
    DEFAULT_PROFILE_DIR,
    get_default_chromium_path,
    kill_profile_browser_processes,
    kill_profile_browser_processes_async,
    normalize_profile_path,
    is_profile_browser_process,
)
import services.browser.stealth as stealth
import services.browser.actions as actions

logger = logging.getLogger("x_vibebot.services.browser.worker")

_LOGGED_IN_SELECTORS = (
    '[data-testid="AppTabBar_Home_Link"]',
    '[data-testid="SideNav_AccountSwitcher_Button"]',
    '[data-testid="primaryColumn"]',
    'a[href="/home"]',
)
_LOGGED_OUT_SELECTORS = (
    'a[href="/login"]',
    '[data-testid="loginButton"]',
)


def _get_os_user_agent() -> str:
    """Returns an OS-accurate modern Chromium User-Agent string matching the host OS."""
    if sys.platform.startswith("win"):
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    if sys.platform == "darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )


def _read_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_secure(path: str, payload: Any, secure_perms: bool = False) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    if secure_perms and os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _write_text_file(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _remove_file_if_exists(path: str) -> None:
    if os.path.isfile(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _filter_and_sanitize_browser_cookies(raw_cookies: Any) -> List[Dict[str, Any]]:
    """
    Filters raw browser context cookies down to X/Twitter domains and prioritizes
    essential auth cookies before running `sanitize_x_cookies(..., max_cookies=50)`.
    """
    if not isinstance(raw_cookies, list):
        return []
    priority_names = {"auth_token", "ct0", "twid", "kdt", "att", "guest_id"}
    x_only = [
        c for c in raw_cookies
        if isinstance(c, dict)
        and str(c.get("domain") or "").strip().lower() in ALLOWED_X_COOKIE_DOMAINS
    ]
    x_only.sort(key=lambda c: (0 if str(c.get("name") or "") in priority_names else 1))
    return sanitize_x_cookies(x_only[:50])


class XBrowserWorker:
    """
    Modular Playwright Browser Worker for X (Twitter).
    Maintains persistent profile directories, anti-detection stealth,
    and safe interaction dispatch.
    """

    def __init__(
        self,
        profile_dir: str = DEFAULT_PROFILE_DIR,
        headless: bool = False,
        executable_path: Optional[str] = None,
        proxy_url: Optional[str] = None,
        tenant_id: str = "default",
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.executable_path = executable_path or get_default_chromium_path()
        self.proxy_url = proxy_url
        self._tenant_id = (tenant_id or "default").strip() or "default"
        self.browser_name = (
            "Brave" if "brave" in (self.executable_path or "").lower()
            else ("Chrome" if "chrome" in (self.executable_path or "").lower()
            else ("Edge" if "edge" in (self.executable_path or "").lower()
            else "Chromium"))
        )
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()
        self._stealthed_pages: weakref.WeakSet = weakref.WeakSet()
        self._stealth_tasks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self._login_watcher_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.last_used_at: float = 0.0
        self.logged_in_username: Optional[str] = None
        self.last_error: Optional[str] = None
        self._mouse_x: float = 640.0
        self._mouse_y: float = 400.0

        os.makedirs(self.profile_dir, exist_ok=True)

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @tenant_id.setter
    def tenant_id(self, value: str) -> None:
        self._tenant_id = (value or "default").strip() or "default"

    @property
    def cookies_backup_path(self) -> str:
        return os.path.join(self.profile_dir, "cookies_backup.json")

    def get_memory_stats(self) -> Dict[str, Any]:
        """Returns runtime status, idle duration, and estimated RAM usage (MB) for this browser worker."""
        idle_seconds = int(max(0.0, time.time() - self.last_used_at)) if self.last_used_at else 0
        estimated_ram_mb = 0.0
        if self.is_running:
            measured_mb = 0.0
            try:
                import psutil
                target_norm = normalize_profile_path(self.profile_dir)
                for proc in psutil.process_iter(["name", "cmdline", "memory_info"]):
                    try:
                        info = proc.info or {}
                        cmdline = info.get("cmdline")
                        if target_norm and cmdline and is_profile_browser_process(
                            info.get("name"), cmdline, target_norm
                        ):
                            mem = info.get("memory_info")
                            if mem:
                                measured_mb += mem.rss / (1024 * 1024)
                    except Exception:
                        continue
            except Exception:
                pass
            estimated_ram_mb = round(measured_mb, 1) if measured_mb > 0 else 160.0

        return {
            "is_running": self.is_running,
            "idle_seconds": idle_seconds,
            "estimated_ram_mb": estimated_ram_mb,
            "logged_in_username": self.logged_in_username,
        }

    async def get_memory_stats_async(self) -> Dict[str, Any]:
        """Non-blocking async wrapper around get_memory_stats()."""
        return await asyncio.to_thread(self.get_memory_stats)

    async def _apply_stealth(self, page: Page):
        """Applies stealth overrides at most once per page instance."""
        if page is None:
            return
        try:
            if page in self._stealthed_pages:
                return
            self._stealthed_pages.add(page)
        except TypeError:
            pass

        try:
            await stealth.apply_stealth(page)
        except Exception as exc:
            try:
                self._stealthed_pages.discard(page)
            except TypeError:
                pass
            logger.debug(f"Apply stealth notice: {exc}")

    def _on_page_created(self, page: Page) -> None:
        """Event callback for newly opened pages in the persistent context."""
        try:
            if page in self._stealthed_pages or page in self._stealth_tasks:
                return
            task = asyncio.create_task(self._apply_stealth(page))
            self._stealth_tasks[page] = task
        except Exception:
            pass

    def _on_context_closed(self) -> None:
        self._context = None
        self.is_running = False

    async def _ensure_context(self, force_headful: bool = False) -> BrowserContext:
        """Internal: Launches persistent context WITHOUT acquiring self._lock."""
        if self._context:
            return self._context

        await asyncio.to_thread(os.makedirs, self.profile_dir, exist_ok=True)
        is_cloud_linux = (os.name != "nt" and not os.getenv("DISPLAY"))
        use_headless = True if is_cloud_linux else (False if force_headful else self.headless)

        logger.info(f"Launching {self.browser_name} (headless={use_headless}, profile={self.profile_dir})")
        if not self._playwright:
            self._playwright = await async_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
        ]

        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": self.profile_dir,
            "headless": use_headless,
            "args": args,
            "viewport": {"width": 1280, "height": 800},
            "user_agent": _get_os_user_agent(),
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path

        proxy_server = getattr(self, "proxy_url", None) or os.getenv("PROXY_SERVER")
        if proxy_server and proxy_server.strip():
            p_server = proxy_server.strip()
            proxy_dict = {"server": p_server}
            p_user = os.getenv("PROXY_USERNAME")
            p_pass = os.getenv("PROXY_PASSWORD")
            if p_user and p_pass:
                proxy_dict["username"] = p_user.strip()
                proxy_dict["password"] = p_pass.strip()
            launch_kwargs["proxy"] = proxy_dict
            clean_host = p_server.split("@")[-1]
            logger.info(f"Playwright routing through residential proxy: {clean_host}")

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            err_msg = str(e)
            if "ProcessSingleton" in err_msg or "0x20" in err_msg or "already in use" in err_msg:
                logger.warning("Profile lock detected. Releasing orphaned bot browser instance and retrying...")
                await kill_profile_browser_processes_async(self.profile_dir)
                await asyncio.sleep(1.0)
                try:
                    self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
                except Exception:
                    await self._close_context_internal()
                    raise
            else:
                await self._close_context_internal()
                raise

        try:
            # Close stray initial popup tabs before registering listeners
            initial_pages = list(self._context.pages)
            for extra_page in initial_pages[1:]:
                try:
                    await extra_page.close()
                except Exception:
                    pass

            # Restore sanitized cookies from backup if present (e.g. on cloud restart)
            if await asyncio.to_thread(os.path.isfile, self.cookies_backup_path):
                try:
                    saved_cookies = await asyncio.to_thread(_read_json_file, self.cookies_backup_path)
                    clean_cookies = _filter_and_sanitize_browser_cookies(saved_cookies)
                    if clean_cookies:
                        await self._context.add_cookies(clean_cookies)
                except Exception as ce:
                    logger.debug(f"Cookie restore notice: {ce}")

            self._context.on("page", self._on_page_created)
            self._context.on("close", lambda *_: self._on_context_closed())

            # Apply stealth once to the initial persistent page created before on("page")
            if initial_pages:
                await self._apply_stealth(initial_pages[0])

            self.is_running = True
            self.last_used_at = time.time()
            return self._context
        except Exception:
            await self._close_context_internal()
            raise

    async def _get_page_internal(self, force_headful: bool = False) -> Page:
        """Internal helper to retrieve or create the single active page without re-locking."""
        if self._context:
            try:
                pages = list(self._context.pages)
                if pages:
                    for extra_page in pages[1:]:
                        try:
                            await extra_page.close()
                        except Exception:
                            pass
                    return pages[0]
                page = await self._context.new_page()
                pending_task = self._stealth_tasks.get(page)
                if pending_task is not None:
                    await pending_task
                elif page not in self._stealthed_pages:
                    await self._apply_stealth(page)
                return page
            except Exception:
                await self._close_context_internal()

        context = await self._ensure_context(force_headful=force_headful)
        pages = list(context.pages)
        if pages:
            for extra_page in pages[1:]:
                try:
                    await extra_page.close()
                except Exception:
                    pass
            return pages[0]

        page = await context.new_page()
        pending_task = self._stealth_tasks.get(page)
        if pending_task is not None:
            await pending_task
        elif page not in self._stealthed_pages:
            await self._apply_stealth(page)
        return page

    async def get_active_page(self, force_headful: bool = False) -> Page:
        """Public helper to retrieve or create the active stealth page."""
        async with self._lock:
            return await self._get_page_internal(force_headful=force_headful)

    async def _close_context_internal(self):
        """Internal helper to close context and playwright safely with timeout + fallback kill."""
        need_force_kill = False
        if self._context:
            ctx = self._context
            self._context = None
            try:
                await asyncio.wait_for(ctx.close(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out closing Playwright context; cleaning up profile processes.")
                need_force_kill = True
            except Exception as exc:
                logger.debug(f"Context close notice: {exc}")
                need_force_kill = True

        if self._playwright:
            pw = self._playwright
            self._playwright = None
            try:
                await asyncio.wait_for(pw.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping Playwright runtime.")
                need_force_kill = True
            except Exception as exc:
                logger.debug(f"Playwright stop notice: {exc}")
                need_force_kill = True

        if need_force_kill:
            try:
                await kill_profile_browser_processes_async(self.profile_dir)
            except Exception as ke:
                logger.debug(f"Fallback profile cleanup notice: {ke}")

        self.is_running = False

    async def _cancel_login_watcher_if_any(self) -> None:
        task = self._login_watcher_task
        current = asyncio.current_task()
        if task and task is not current and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if task is not current:
            self._login_watcher_task = None

    async def start(self, force_headful: bool = False) -> BrowserContext:
        async with self._lock:
            return await self._ensure_context(force_headful=force_headful)

    async def stop(self):
        await self._cancel_login_watcher_if_any()
        async with self._lock:
            await self._close_context_internal()

    async def disconnect(self):
        """Disconnects the session, clears credentials, and sets the disconnected marker."""
        await self.stop()
        self.logged_in_username = None
        await asyncio.to_thread(_remove_file_if_exists, self.cookies_backup_path)
        meta_path = os.path.join(self.profile_dir, "session_metadata.json")
        await asyncio.to_thread(_remove_file_if_exists, meta_path)
        marker_path = os.path.join(self.profile_dir, ".disconnected")
        try:
            await asyncio.to_thread(_write_text_file, marker_path, "disconnected")
        except Exception:
            pass

    async def human_delay(self, min_sec: float = 2.5, max_sec: float = 6.0):
        """Randomized human-like pause."""
        await stealth.human_delay(min_sec, max_sec)

    async def move_mouse_humanlike(self, page: Page, target_x: float, target_y: float):
        """Moves cursor along a randomized Cubic Bézier curve."""
        self._mouse_x, self._mouse_y = await stealth.move_mouse_humanlike(
            page, self._mouse_x, self._mouse_y, target_x, target_y
        )

    async def human_click(self, page: Page, element):
        """Glides mouse along a Bézier curve into element and clicks."""
        self._mouse_x, self._mouse_y = await stealth.human_click(
            page, element, (self._mouse_x, self._mouse_y)
        )

    async def simulate_reading_dwell(self, page: Page, text_length: int = 140):
        """Simulates proportional human reading time and viewport dwell."""
        self._mouse_x, self._mouse_y = await stealth.simulate_reading_dwell(
            page, text_length, (self._mouse_x, self._mouse_y)
        )

    async def human_type(self, page: Page, selector: str, text: str):
        """Types text with natural human variance and occasional typo correction."""
        self._mouse_x, self._mouse_y = await stealth.human_type(
            page, selector, text, (self._mouse_x, self._mouse_y)
        )

    async def _extract_logged_in_handle(self, page: Page) -> Optional[str]:
        """Extracts the @username of the currently logged-in X user from the DOM."""
        return await actions.extract_logged_in_handle(page)

    async def _backup_cookies_unlocked(self):
        """Saves current sanitized X context cookies to cookies_backup.json (caller must hold self._lock)."""
        if not self._context:
            return
        try:
            raw_cookies = await self._context.cookies()
            cookies = _filter_and_sanitize_browser_cookies(raw_cookies)
            if cookies:
                await asyncio.to_thread(_write_json_secure, self.cookies_backup_path, cookies, True)
                if self.logged_in_username:
                    meta_path = os.path.join(self.profile_dir, "session_metadata.json")
                    await asyncio.to_thread(
                        _write_json_secure,
                        meta_path,
                        {"linked_username": self.logged_in_username, "updated_at": time.time()},
                        True,
                    )
        except Exception as e:
            logger.debug(f"Cookie backup notice: {e}")

    async def _backup_cookies_internal(self):
        """Saves current context cookies to cookies_backup.json and caches metadata under lock."""
        async with self._lock:
            await self._backup_cookies_unlocked()

    async def export_cookies(self) -> List[Dict[str, Any]]:
        """Exports sanitized X session cookies for cloud deployment."""
        async with self._lock:
            if await asyncio.to_thread(os.path.isfile, self.cookies_backup_path):
                try:
                    data = await asyncio.to_thread(_read_json_file, self.cookies_backup_path)
                    clean = _filter_and_sanitize_browser_cookies(data)
                    if clean:
                        return clean
                except Exception:
                    pass
            await self._ensure_context()
            await self._backup_cookies_unlocked()
            if self._context:
                raw_cookies = await self._context.cookies()
                return _filter_and_sanitize_browser_cookies(raw_cookies)
            return []

    async def _verify_live_session_unlocked(self, page: Page) -> tuple[bool, bool]:
        """
        Navigates to https://x.com/home and verifies live session acceptance with X.
        Caller must hold self._lock.
        Returns (is_logged_in, definitively_rejected_by_x).
        """
        logger.info("Checking live X session status at https://x.com/home...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)

        for _ in range(10):
            current_url = (page.url or "").lower()
            if "login" in current_url or "i/flow/login" in current_url or "account/access" in current_url:
                return False, True

            for log_sel in _LOGGED_OUT_SELECTORS:
                try:
                    if await page.query_selector(log_sel):
                        return False, True
                except Exception:
                    pass

            for ok_sel in _LOGGED_IN_SELECTORS:
                try:
                    if await page.query_selector(ok_sel):
                        if "home" in current_url or "x.com" in current_url or "twitter.com" in current_url:
                            return True, False
                except Exception:
                    pass

            await asyncio.sleep(0.3)

        current_url = (page.url or "").lower()
        if "login" in current_url or "i/flow/login" in current_url or "home" not in current_url:
            return False, True
        return False, False

    async def import_cookies(self, cookies: List[Dict[str, Any]], verify_live: bool = True) -> bool:
        """
        Sanitizes and imports X session cookies into the profile.
        When `verify_live=True`, confirms X accepts the session at `https://x.com/home`
        BEFORE persisting `cookies_backup.json`. Removes temporary/stale backups on failure.
        """
        try:
            sanitized = sanitize_x_cookies(cookies)
        except ValueError as ve:
            logger.warning(f"Rejected invalid cookies payload: {ve}")
            return False

        if not sanitized:
            logger.warning("Rejected cookie import: no valid X/Twitter cookies present.")
            return False

        has_auth_token = any(
            c.get("name") == "auth_token" and bool(str(c.get("value") or "").strip())
            for c in sanitized
        )
        if not has_auth_token:
            logger.warning("Rejected cookie import: missing required X auth_token cookie.")
            return False

        marker_path = os.path.join(self.profile_dir, ".disconnected")
        await asyncio.to_thread(_remove_file_if_exists, marker_path)
        meta_path = os.path.join(self.profile_dir, "session_metadata.json")

        if not verify_live:
            async with self._lock:
                await asyncio.to_thread(_write_json_secure, self.cookies_backup_path, sanitized, True)
                if self._context:
                    try:
                        await self._context.clear_cookies()
                    except Exception:
                        pass
                    try:
                        await self._context.add_cookies(sanitized)
                    except Exception as exc:
                        logger.debug(f"Live context cookie injection notice: {exc}")
                return True

        async with self._lock:
            self.last_used_at = time.time()
            self.logged_in_username = None
            await self._close_context_internal()
            # Ensure stale backups cannot leak into _ensure_context or survive a failed check
            await asyncio.to_thread(_remove_file_if_exists, self.cookies_backup_path)
            await asyncio.to_thread(_remove_file_if_exists, meta_path)

            try:
                page = await self._get_page_internal()
                if self._context:
                    try:
                        await self._context.clear_cookies()
                    except Exception:
                        pass
                    await self._context.add_cookies(sanitized)

                is_valid, _ = await self._verify_live_session_unlocked(page)
                if not is_valid:
                    logger.info("Imported X cookies failed live verification; cleaning up.")
                    await self._close_context_internal()
                    await asyncio.to_thread(_remove_file_if_exists, self.cookies_backup_path)
                    await asyncio.to_thread(_remove_file_if_exists, meta_path)
                    self.logged_in_username = None
                    return False

                handle = await self._extract_logged_in_handle(page)
                if handle:
                    self.logged_in_username = handle
                    logger.info(f"Confirmed imported X session live as {handle}")

                await self._backup_cookies_unlocked()
                return True
            except Exception as exc:
                logger.warning(f"Live cookie verification failed: {exc}")
                await self._close_context_internal()
                await asyncio.to_thread(_remove_file_if_exists, self.cookies_backup_path)
                await asyncio.to_thread(_remove_file_if_exists, meta_path)
                self.logged_in_username = None
                return False

    async def check_login_status(self, verify_live: bool = False) -> bool:
        """
        Verifies whether the X session is active and extracts linked @username.
        When `verify_live=True`, bypasses fast-path caches and navigates to `https://x.com/home`.
        """
        self.last_used_at = time.time()
        disconnected_marker = os.path.join(self.profile_dir, ".disconnected")
        if await asyncio.to_thread(os.path.isfile, disconnected_marker):
            return False

        async with self._lock:
            if not verify_live:
                # 1. Live Context Check (under self._lock)
                try:
                    if self._context:
                        active_cookies = await self._context.cookies()
                        if any(
                            c.get("name") == "auth_token" and c.get("value")
                            for c in active_cookies
                            if str(c.get("domain") or "").lower() in ALLOWED_X_COOKIE_DOMAINS
                            or "x.com" in str(c.get("domain") or "").lower()
                            or "twitter.com" in str(c.get("domain") or "").lower()
                        ):
                            if self._context.pages:
                                cur_url = (self._context.pages[0].url or "").lower()
                                if "login" not in cur_url and "i/flow/login" not in cur_url:
                                    handle = await self._extract_logged_in_handle(self._context.pages[0])
                                    if handle:
                                        self.logged_in_username = handle
                            await self._backup_cookies_unlocked()
                            logger.info(
                                f"Confirmed X session active from live open browser as {self.logged_in_username or 'authenticated'}"
                            )
                            return True
                except Exception as lce:
                    logger.debug(f"Live context cookie check notice: {lce}")

                # 2. Cookies backup fast-path (only when verify_live=False)
                if await asyncio.to_thread(os.path.isfile, self.cookies_backup_path):
                    try:
                        saved = await asyncio.to_thread(_read_json_file, self.cookies_backup_path)
                        clean_saved = _filter_and_sanitize_browser_cookies(saved)
                        if any(c.get("name") == "auth_token" and c.get("value") for c in clean_saved):
                            if not self.logged_in_username:
                                meta_file = os.path.join(self.profile_dir, "session_metadata.json")
                                if await asyncio.to_thread(os.path.isfile, meta_file):
                                    try:
                                        meta = await asyncio.to_thread(_read_json_file, meta_file)
                                        if isinstance(meta, dict):
                                            self.logged_in_username = meta.get("linked_username")
                                    except Exception:
                                        pass
                            logger.info(
                                f"Confirmed X session active from cookies backup as {self.logged_in_username or 'authenticated'}"
                            )
                            return True
                    except Exception as ce:
                        logger.debug(f"Cookie fast check notice: {ce}")

            # 3. Live Playwright navigation check
            try:
                page = await self._get_page_internal()
            except Exception as e:
                logger.warning(f"Could not get page for login check: {e}")
                return False

            try:
                is_logged, rejected = await self._verify_live_session_unlocked(page)
                if not is_logged:
                    logger.info("Session status: Logged Out. Releasing profile lock.")
                    await self._close_context_internal()
                    if rejected:
                        await asyncio.to_thread(_remove_file_if_exists, self.cookies_backup_path)
                        meta_file = os.path.join(self.profile_dir, "session_metadata.json")
                        await asyncio.to_thread(_remove_file_if_exists, meta_file)
                        self.logged_in_username = None
                    return False

                handle = await self._extract_logged_in_handle(page)
                if handle:
                    self.logged_in_username = handle
                    logger.info(f"Confirmed X session active as {handle}")

                await self._backup_cookies_unlocked()
                return True
            except Exception as e:
                logger.warning(f"Error checking login status: {e}")
                await self._close_context_internal()
                return False

    async def _extract_metric_number(self, article, testid: str) -> int:
        """Extracts numeric engagement count (likes/replies) from a tweet element."""
        return await actions.extract_metric_number(article, testid)

    async def scrape_feed(self, search_query: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
        """Scrapes tweets from Home timeline or search query with engagement metrics and media/quote context."""
        async with self._lock:
            self.last_used_at = time.time()
            page = await self._get_page_internal()
            items, handle = await actions.scrape_feed_action(
                page, search_query=search_query, limit=limit, logged_in_username=self.logged_in_username
            )
            self.last_used_at = time.time()
            if handle:
                self.logged_in_username = handle
            return items

    async def post_reply(
        self,
        tweet_id: str,
        reply_text: str,
        tweet_url: Optional[str] = None,
        should_like: Optional[bool] = None
    ) -> bool:
        """Publishes a reply with humanized biometric reading dwell and typing."""
        async with self._lock:
            self.last_used_at = time.time()
            page = await self._get_page_internal()
            ok, err, new_mouse = await actions.post_reply_action(
                page=page,
                tweet_id=tweet_id,
                reply_text=reply_text,
                tweet_url=tweet_url,
                should_like=should_like,
                mouse_pos=(self._mouse_x, self._mouse_y)
            )
            self.last_used_at = time.time()
            self._mouse_x, self._mouse_y = new_mouse
            self.last_error = err
            return ok

    async def post_original(self, post_text: str) -> bool:
        """Publishes a standalone original post on X with humanized typing and mouse clicks."""
        async with self._lock:
            self.last_used_at = time.time()
            page = await self._get_page_internal()
            ok, err, new_mouse = await actions.post_original_action(
                page=page,
                post_text=post_text,
                mouse_pos=(self._mouse_x, self._mouse_y)
            )
            self.last_used_at = time.time()
            self._mouse_x, self._mouse_y = new_mouse
            self.last_error = err
            return ok

    async def post_thread(self, thread_text: str) -> bool:
        """Publishes a multi-post thread on X."""
        async with self._lock:
            self.last_used_at = time.time()
            page = await self._get_page_internal()
            ok, err, new_mouse = await actions.post_thread_action(
                page=page,
                thread_text=thread_text,
                mouse_pos=(self._mouse_x, self._mouse_y)
            )
            self.last_used_at = time.time()
            self._mouse_x, self._mouse_y = new_mouse
            self.last_error = err
            return ok

    async def execute_tweet_action(
        self,
        action_type: str,
        tweet_id: str,
        text: str,
        tweet_url: Optional[str] = None,
        should_like: Optional[bool] = None
    ) -> bool:
        """Unified dispatcher for replies, original posts, and multi-post threads."""
        self.last_error = None
        if action_type == "thread":
            return await self.post_thread(text)
        elif action_type == "post":
            return await self.post_original(text)
        else:
            return await self.post_reply(tweet_id, text, tweet_url, should_like=should_like)

    async def open_headful_for_login(self):
        """
        Closes any existing session, opens a visible browser window to x.com/login,
        and launches a single tracked background watcher that verifies sign-in and closes the window.
        """
        await self._cancel_login_watcher_if_any()

        marker_path = os.path.join(self.profile_dir, ".disconnected")
        await asyncio.to_thread(_remove_file_if_exists, marker_path)

        try:
            async with self._lock:
                await self._close_context_internal()
                logger.info("Opening browser window for manual login...")
                page = await self._get_page_internal(force_headful=True)
                try:
                    await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=12000)
                except Exception as e:
                    logger.warning(f"Initial navigation notice: {e}")
                logger.info("Browser opened for manual login. Auto-monitoring for sign-in completion...")

            try:
                import core.state as app_state
                app_state.set_manual_login(self._tenant_id, True)
            except Exception:
                pass

            self._login_watcher_task = asyncio.create_task(self._watch_login_and_autoclose(page))
        except Exception:
            try:
                import core.state as app_state
                app_state.set_manual_login(self._tenant_id, False)
            except Exception:
                pass
            raise

    async def _watch_login_and_autoclose(self, page: Page):
        """
        Actively monitors the opened login window under `self._lock`.
        As soon as the user logs in:
        1. Verifies the session by detecting auth cookies and feed/UI elements.
        2. Extracts the authenticated @username.
        3. Saves cookies and session metadata to disk.
        4. Automatically closes the opened browser window and resets manual-login state.
        """
        logger.info("Session auto-verification watcher running. Waiting for X sign-in...")
        poll_interval = 1.5
        max_duration = 300  # 5 minutes timeout
        start_time = time.time()

        try:
            while time.time() - start_time < max_duration:
                await asyncio.sleep(poll_interval)
                try:
                    ready_for_finalize = False
                    async with self._lock:
                        if not self._context or page.is_closed():
                            logger.info("Login browser window was closed by user.")
                            return

                        cookies = await self._context.cookies()
                        has_auth = any(
                            c.get("name") == "auth_token" and len(c.get("value", "")) >= 15
                            for c in cookies
                            if "x.com" in str(c.get("domain", "")).lower()
                            or "twitter.com" in str(c.get("domain", "")).lower()
                        )

                        url = (page.url or "").lower()
                        is_on_feed = "x.com/home" in url or (
                            "x.com" in url and "login" not in url and "i/flow" not in url
                        )

                        has_app_ui = False
                        if has_auth or is_on_feed:
                            try:
                                switcher = await page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
                                home_link = await page.query_selector('[data-testid="AppTabBar_Home_Link"]')
                                primary_col = await page.query_selector('[data-testid="primaryColumn"]')
                                if switcher or home_link or primary_col:
                                    has_app_ui = True
                            except Exception:
                                pass

                        if has_auth and (is_on_feed or has_app_ui):
                            ready_for_finalize = True

                    if ready_for_finalize:
                        logger.info("Detected successful X sign-in. Waiting 1.2s for token finalization...")
                        await asyncio.sleep(1.2)
                        async with self._lock:
                            if not self._context or page.is_closed():
                                return

                            try:
                                handle = await self._extract_logged_in_handle(page)
                                if handle:
                                    self.logged_in_username = handle
                            except Exception as he:
                                logger.debug(f"Handle extraction note: {he}")

                            await self._backup_cookies_unlocked()

                            logger.info(
                                f"Successfully verified X session for {self.logged_in_username or 'account'}! "
                                f"Automatically closing browser window now."
                            )
                            await self._close_context_internal()
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"Login watcher tick notice: {e}")
                    continue

            logger.info("Login watcher reached maximum wait duration (5m).")
            try:
                async with self._lock:
                    await self._close_context_internal()
            except Exception:
                pass
        finally:
            if self._login_watcher_task is asyncio.current_task():
                self._login_watcher_task = None
            try:
                import core.state as app_state
                app_state.set_manual_login(self._tenant_id, False)
            except Exception:
                pass
