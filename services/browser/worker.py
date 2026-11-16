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
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from services.browser.process import (
    DEFAULT_PROFILE_DIR,
    get_default_chromium_path,
    kill_profile_browser_processes,
)
import services.browser.stealth as stealth
import services.browser.actions as actions

logger = logging.getLogger("x_vibebot.services.browser.worker")


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
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.executable_path = executable_path or get_default_chromium_path()
        self.proxy_url = proxy_url
        self.browser_name = (
            "Brave" if "brave" in (self.executable_path or "").lower()
            else ("Chrome" if "chrome" in (self.executable_path or "").lower()
            else ("Edge" if "edge" in (self.executable_path or "").lower()
            else "Chromium"))
        )
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()
        self.is_running = False
        self.logged_in_username: Optional[str] = None
        self.last_error: Optional[str] = None
        self._mouse_x: float = 640.0
        self._mouse_y: float = 400.0

        os.makedirs(self.profile_dir, exist_ok=True)

    @property
    def cookies_backup_path(self) -> str:
        return os.path.join(self.profile_dir, "cookies_backup.json")

    async def _apply_stealth(self, page: Page):
        """Applies stealth overrides to mask automation signatures."""
        await stealth.apply_stealth(page)

    async def _ensure_context(self, force_headful: bool = False) -> BrowserContext:
        """Internal: Launches persistent context WITHOUT acquiring self._lock."""
        if self._context:
            return self._context

        os.makedirs(self.profile_dir, exist_ok=True)
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
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        launch_kwargs = {
            "user_data_dir": self.profile_dir,
            "headless": use_headless,
            "args": args,
            "viewport": {"width": 1280, "height": 800},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
            if "ProcessSingleton" in str(e) or "0x20" in str(e) or "already in use" in str(e):
                logger.warning("Profile lock detected. Releasing orphaned bot browser instance and retrying...")
                kill_profile_browser_processes(self.profile_dir)
                await asyncio.sleep(1.0)
                self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)
            else:
                raise

        # Restore cookies from backup if present (e.g. on Render cloud)
        if os.path.isfile(self.cookies_backup_path):
            try:
                with open(self.cookies_backup_path, "r", encoding="utf-8") as f:
                    saved_cookies = json.load(f)
                if isinstance(saved_cookies, list) and saved_cookies:
                    await self._context.add_cookies(saved_cookies)
            except Exception as ce:
                logger.debug(f"Cookie restore notice: {ce}")

        self._context.on("page", lambda p: asyncio.create_task(self._apply_stealth(p)))
        self._context.on("close", lambda: setattr(self, "_context", None))
        self.is_running = True
        return self._context

    async def _get_page_internal(self, force_headful: bool = False) -> Page:
        """Internal helper to retrieve or create a page without re-locking."""
        if self._context:
            try:
                if self._context.pages:
                    page = self._context.pages[0]
                    await self._apply_stealth(page)
                    return page
                else:
                    page = await self._context.new_page()
                    await self._apply_stealth(page)
                    return page
            except Exception:
                await self._close_context_internal()

        context = await self._ensure_context(force_headful=force_headful)
        page = context.pages[0] if context.pages else await context.new_page()
        await self._apply_stealth(page)
        return page

    async def get_active_page(self, force_headful: bool = False) -> Page:
        """Public helper to retrieve or create the active stealth page."""
        return await self._get_page_internal(force_headful=force_headful)

    async def _close_context_internal(self):
        """Internal helper to close context and playwright without re-locking."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self.is_running = False

    async def start(self, force_headful: bool = False) -> BrowserContext:
        async with self._lock:
            return await self._ensure_context(force_headful=force_headful)

    async def stop(self):
        async with self._lock:
            await self._close_context_internal()

    async def disconnect(self):
        """Disconnects the session, clears credentials, and sets the disconnected marker."""
        await self.stop()
        self.logged_in_username = None
        if os.path.isfile(self.cookies_backup_path):
            try:
                os.remove(self.cookies_backup_path)
            except Exception:
                pass
        meta_path = os.path.join(self.profile_dir, "session_metadata.json")
        if os.path.isfile(meta_path):
            try:
                os.remove(meta_path)
            except Exception:
                pass
        marker_path = os.path.join(self.profile_dir, ".disconnected")
        try:
            os.makedirs(self.profile_dir, exist_ok=True)
            with open(marker_path, "w", encoding="utf-8") as f:
                f.write("disconnected")
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

    async def _backup_cookies_internal(self):
        """Saves current context cookies to cookies_backup.json and caches metadata."""
        if not self._context:
            return
        try:
            cookies = await self._context.cookies()
            if cookies:
                os.makedirs(self.profile_dir, exist_ok=True)
                with open(self.cookies_backup_path, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, indent=2)
                if self.logged_in_username:
                    meta_path = os.path.join(self.profile_dir, "session_metadata.json")
                    with open(meta_path, "w", encoding="utf-8") as mf:
                        json.dump({"linked_username": self.logged_in_username, "updated_at": time.time()}, mf, indent=2)
        except Exception as e:
            logger.debug(f"Cookie backup notice: {e}")

    async def export_cookies(self) -> List[Dict[str, Any]]:
        """Exports X session cookies for cloud deployment."""
        if os.path.isfile(self.cookies_backup_path):
            try:
                with open(self.cookies_backup_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
            except Exception:
                pass
        async with self._lock:
            await self._ensure_context()
            await self._backup_cookies_internal()
            if self._context:
                return await self._context.cookies()
            return []

    async def import_cookies(self, cookies: List[Dict[str, Any]]) -> bool:
        """Imports X session cookies into the profile."""
        marker_path = os.path.join(self.profile_dir, ".disconnected")
        if os.path.isfile(marker_path):
            try:
                os.remove(marker_path)
            except Exception:
                pass
        os.makedirs(self.profile_dir, exist_ok=True)
        with open(self.cookies_backup_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        async with self._lock:
            if self._context:
                try:
                    await self._close_context_internal()
                except Exception:
                    pass
        return await self.check_login_status()

    async def check_login_status(self) -> bool:
        """Navigates to X, verifies if session is active, and extracts linked @username."""
        disconnected_marker = os.path.join(self.profile_dir, ".disconnected")
        if os.path.isfile(disconnected_marker):
            return False

        # 1. Live Context Check
        try:
            if self._context:
                active_cookies = await self._context.cookies()
                if any(c.get("name") == "auth_token" and c.get("value") for c in active_cookies if "x.com" in c.get("domain", "") or "twitter.com" in c.get("domain", "")):
                    if self._context.pages:
                        handle = await self._extract_logged_in_handle(self._context.pages[0])
                        if handle:
                            self.logged_in_username = handle
                    await self._backup_cookies_internal()
                    logger.info(f"Confirmed X session active from live open browser as {self.logged_in_username or 'authenticated'}")
                    return True
        except Exception as lce:
            logger.debug(f"Live context cookie check notice: {lce}")

        # 2. Cookies backup fast-path
        if os.path.isfile(self.cookies_backup_path):
            try:
                with open(self.cookies_backup_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, list) and any(c.get("name") == "auth_token" and c.get("value") for c in saved):
                    if not self.logged_in_username:
                        meta_file = os.path.join(self.profile_dir, "session_metadata.json")
                        if os.path.isfile(meta_file):
                            try:
                                with open(meta_file, "r", encoding="utf-8") as mf:
                                    meta = json.load(mf)
                                    self.logged_in_username = meta.get("linked_username")
                            except Exception:
                                pass
                    logger.info(f"Confirmed X session active from cookies backup as {self.logged_in_username or 'authenticated'}")
                    return True
            except Exception as ce:
                logger.debug(f"Cookie fast check notice: {ce}")

        # 3. Navigate with Playwright
        async with self._lock:
            try:
                page = await self._get_page_internal()
            except Exception as e:
                logger.warning(f"Could not get page for login check: {e}")
                return False

            try:
                if self._context:
                    try:
                        ctx_cookies = await self._context.cookies()
                        if any(c.get("name") == "auth_token" and c.get("value") for c in ctx_cookies if "x.com" in c.get("domain", "") or "twitter.com" in c.get("domain", "")):
                            handle = await self._extract_logged_in_handle(page)
                            if handle:
                                self.logged_in_username = handle
                            await self._backup_cookies_internal()
                            logger.info(f"Confirmed X session active from browser cookies as {self.logged_in_username or 'authenticated'}")
                            return True
                    except Exception:
                        pass

                logger.info("Checking X session status...")
                current_url = page.url or ""
                if "x.com/home" in current_url:
                    await asyncio.sleep(0.5)
                else:
                    await page.goto("https://x.com/home", wait_until="commit", timeout=8000)
                    await asyncio.sleep(0.5)

                current_url = page.url or ""
                if "login" in current_url or "i/flow/login" in current_url:
                    logger.info("Session status: Logged Out. Releasing profile lock.")
                    await self._close_context_internal()
                    return False

                logged_in_selectors = [
                    '[data-testid="AppTabBar_Home_Link"]',
                    '[data-testid="SideNav_AccountSwitcher_Button"]',
                    '[data-testid="primaryColumn"]',
                    'a[href="/home"]'
                ]
                is_logged = False
                for selector in logged_in_selectors:
                    if await page.query_selector(selector):
                        is_logged = True
                        break

                if not is_logged:
                    login_btn = await page.query_selector('a[href="/login"], [data-testid="loginButton"]')
                    if login_btn or "home" not in current_url:
                        await self._close_context_internal()
                        return False
                    is_logged = True

                handle = await self._extract_logged_in_handle(page)
                if handle:
                    self.logged_in_username = handle
                    logger.info(f"Confirmed X session active as {handle}")

                await self._backup_cookies_internal()
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
            page = await self._get_page_internal()
            items, handle = await actions.scrape_feed_action(
                page, search_query=search_query, limit=limit, logged_in_username=self.logged_in_username
            )
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
            page = await self._get_page_internal()
            ok, err, new_mouse = await actions.post_reply_action(
                page=page,
                tweet_id=tweet_id,
                reply_text=reply_text,
                tweet_url=tweet_url,
                should_like=should_like,
                mouse_pos=(self._mouse_x, self._mouse_y)
            )
            self._mouse_x, self._mouse_y = new_mouse
            self.last_error = err
            return ok

    async def post_original(self, post_text: str) -> bool:
        """Publishes a standalone original post on X with humanized typing and mouse clicks."""
        async with self._lock:
            page = await self._get_page_internal()
            ok, err, new_mouse = await actions.post_original_action(
                page=page,
                post_text=post_text,
                mouse_pos=(self._mouse_x, self._mouse_y)
            )
            self._mouse_x, self._mouse_y = new_mouse
            self.last_error = err
            return ok

    async def post_thread(self, thread_text: str) -> bool:
        """Publishes a multi-post thread on X."""
        async with self._lock:
            page = await self._get_page_internal()
            ok, err, new_mouse = await actions.post_thread_action(
                page=page,
                thread_text=thread_text,
                mouse_pos=(self._mouse_x, self._mouse_y)
            )
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
        """Closes any existing session and opens a visible browser window to x.com/login."""
        marker_path = os.path.join(self.profile_dir, ".disconnected")
        if os.path.isfile(marker_path):
            try:
                os.remove(marker_path)
            except Exception:
                pass
        async with self._lock:
            await self._close_context_internal()
            logger.info("Opening browser window for manual login...")
            page = await self._get_page_internal(force_headful=True)
            try:
                await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=12000)
            except Exception as e:
                logger.warning(f"Initial navigation notice: {e}")
            logger.info("Browser opened for manual login. Sign into X, then close the window.")
