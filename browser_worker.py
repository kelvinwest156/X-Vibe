"""
Playwright Automation Worker for X (Twitter).
Features:
- Persistent Chromium Context (saves session & cookies in ./x_browser_profile)
- Stealth masking (evades bot detection)
- Humanized keystrokes & randomized delay intervals
- Safe selector targeting with fallback handling
- Single-instance lock to prevent concurrent sessions (deadlock-free architecture)
"""

import os
import re
import random
import asyncio
import logging
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

logger = logging.getLogger("x_vibebot.browser")

DEFAULT_PROFILE_DIR = os.path.abspath(os.getenv("BROWSER_PROFILE_DIR", "./x_browser_profile"))


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
        import re
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


class XBrowserWorker:
    def __init__(self, profile_dir: str = DEFAULT_PROFILE_DIR, headless: bool = False, executable_path: Optional[str] = None):
        self.profile_dir = profile_dir
        self.headless = headless
        self.executable_path = executable_path or get_default_chromium_path()
        self.browser_name = (
            "Brave" if "brave" in (self.executable_path or "").lower()
            else ("Chrome" if "chrome" in (self.executable_path or "").lower()
            else ("Edge" if "edge" in (self.executable_path or "").lower()
            else "Chromium"))
        )
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()  # Ensure strictly no parallel browser contexts
        self.is_running = False

    async def _apply_stealth(self, page: Page):
        """Applies stealth overrides to mask automation signatures."""
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception as e:
            logger.debug(f"playwright_stealth helper notice: {e}")

        # Direct script masking as a guaranteed layer
        try:
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {}
                };
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
            """)
        except Exception:
            pass

    async def _ensure_context(self, force_headful: bool = False) -> BrowserContext:
        """
        Internal: Launches persistent context WITHOUT acquiring self._lock.
        Assumes caller manages lock or concurrency.
        """
        if self._context:
            return self._context

        os.makedirs(self.profile_dir, exist_ok=True)
        use_headless = False if force_headful else self.headless

        logger.info(f"Launching {self.browser_name} (headless={use_headless}, exe={self.executable_path or 'bundled'}, profile={self.profile_dir})")
        if not self._playwright:
            self._playwright = await async_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
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
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        }
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path

        self._context = await self._playwright.chromium.launch_persistent_context(**launch_kwargs)

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
                logger.info("Existing browser session closed or expired; initializing fresh context...")
                await self._close_context_internal()

        context = await self._ensure_context(force_headful=force_headful)
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()
        await self._apply_stealth(page)
        return page

    async def _close_context_internal(self):
        """Internal helper to close context and playwright without re-locking."""
        if self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.warning(f"Notice closing context: {e}")
            self._context = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"Notice stopping playwright: {e}")
            self._playwright = None

        self.is_running = False
        logger.info("Browser context closed.")

    async def start(self, force_headful: bool = False) -> BrowserContext:
        """Public method to start browser."""
        async with self._lock:
            return await self._ensure_context(force_headful=force_headful)

    async def stop(self):
        """Public method to stop browser."""
        async with self._lock:
            await self._close_context_internal()

    async def get_active_page(self) -> Page:
        """Public method to get active page."""
        async with self._lock:
            return await self._get_page_internal()

    async def human_delay(self, min_sec: float = 3.0, max_sec: float = 7.0):
        """Randomized human-like pause. Never uses flat timeouts."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def human_type(self, page: Page, selector: str, text: str):
        """Types text character-by-character with randomized keystroke intervals."""
        element = await page.wait_for_selector(selector, state="visible", timeout=15000)
        await element.click()
        await self.human_delay(0.5, 1.2)

        for char in text:
            await page.keyboard.type(char)
            delay = random.uniform(0.05, 0.15)
            if char in " ,.!?":
                delay += random.uniform(0.1, 0.3)
            await asyncio.sleep(delay)

    async def check_login_status(self) -> bool:
        """
        Navigates to X and checks if user session is active.
        """
        async with self._lock:
            page = await self._get_page_internal()
            try:
                logger.info("Checking X login status on x.com/home...")
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                await self.human_delay(2.0, 3.5)

                current_url = page.url
                if "login" in current_url or "i/flow/login" in current_url:
                    logger.info("Session status: Redirected to login page (Logged Out).")
                    return False

                logged_in_selectors = [
                    '[data-testid="AppTabBar_Home_Link"]',
                    '[data-testid="SideNav_AccountSwitcher_Button"]',
                    '[data-testid="primaryColumn"]',
                    'a[href="/home"]'
                ]
                for selector in logged_in_selectors:
                    elem = await page.query_selector(selector)
                    if elem:
                        logger.info("Session status: Confirmed logged-in session on X.")
                        return True

                login_btn = await page.query_selector('a[href="/login"], [data-testid="loginButton"]')
                if login_btn:
                    logger.info("Session status: Login button detected (Logged Out).")
                    return False

                return "home" in current_url

            except Exception as e:
                logger.warning(f"Error checking login status: {e}")
                return False

    async def scrape_feed(self, search_query: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Scrapes tweets from either the Home timeline or a search query.
        """
        async with self._lock:
            page = await self._get_page_internal()
            tweets_data: List[Dict[str, Any]] = []

            try:
                if search_query:
                    encoded_query = search_query.replace("#", "%23")
                    url = f"https://x.com/search?q={encoded_query}&f=live"
                    logger.info(f"Navigating to search feed: {url}")
                else:
                    url = "https://x.com/home"
                    logger.info("Navigating to home timeline...")

                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await self.human_delay(3.5, 5.0)

                # Scroll gently to trigger tweet loading
                for _ in range(2):
                    await page.mouse.wheel(0, random.randint(300, 600))
                    await self.human_delay(1.5, 2.5)

                articles = await page.query_selector_all('article[data-testid="tweet"]')
                logger.info(f"Found {len(articles)} tweet elements on page.")

                for article in articles:
                    if len(tweets_data) >= limit:
                        break

                    try:
                        links = await article.query_selector_all('a[href*="/status/"]')
                        tweet_id = None
                        tweet_url = None
                        for link in links:
                            href = await link.get_attribute("href")
                            if href and "/status/" in href and not href.endswith("/analytics"):
                                match = re.search(r'/status/(\d+)', href)
                                if match:
                                    tweet_id = match.group(1)
                                    tweet_url = f"https://x.com{href}" if href.startswith("/") else href
                                    break

                        if not tweet_id:
                            continue

                        text_elem = await article.query_selector('[data-testid="tweetText"]')
                        tweet_text = await text_elem.inner_text() if text_elem else ""

                        author_elem = await article.query_selector('[data-testid="User-Name"]')
                        author_raw = await author_elem.inner_text() if author_elem else ""
                        author_match = re.search(r'@([A-Za-z0-9_]+)', author_raw)
                        author = author_match.group(1) if author_match else "unknown"

                        if tweet_id and tweet_text:
                            tweets_data.append({
                                "tweet_id": tweet_id,
                                "author": author,
                                "text": tweet_text.strip(),
                                "url": tweet_url or f"https://x.com/i/status/{tweet_id}"
                            })

                    except Exception as item_err:
                        logger.debug(f"Error parsing tweet element: {item_err}")
                        continue

            except Exception as e:
                logger.error(f"Error during feed scraping: {e}", exc_info=True)

            return tweets_data

    async def post_reply(self, tweet_id: str, reply_text: str, tweet_url: Optional[str] = None) -> bool:
        """
        Navigates to the specific tweet, enters humanized reply, and submits.
        """
        async with self._lock:
            page = await self._get_page_internal()
            target_url = tweet_url or f"https://x.com/i/status/{tweet_id}"

            try:
                logger.info(f"Navigating to tweet for reply: {target_url}")
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                await self.human_delay(3.0, 5.0)

                reply_input_selectors = [
                    '[data-testid="tweetTextarea_0"]',
                    'div[role="textbox"][data-testid="tweetTextarea_0"]',
                    'div[contenteditable="true"]'
                ]

                input_box = None
                for selector in reply_input_selectors:
                    input_box = await page.query_selector(selector)
                    if input_box:
                        break

                if not input_box:
                    reply_btn = await page.query_selector('[data-testid="reply"]')
                    if reply_btn:
                        await reply_btn.click()
                        await self.human_delay(1.5, 2.5)
                        input_box = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=10000)

                if not input_box:
                    logger.error("Could not find reply input box on the page.")
                    return False

                await self.human_type(page, '[data-testid="tweetTextarea_0"]', reply_text)
                await self.human_delay(1.5, 3.0)

                submit_selectors = [
                    '[data-testid="tweetButtonInline"]',
                    '[data-testid="tweetButton"]',
                    'button[data-testid="tweetButtonInline"]'
                ]

                submit_btn = None
                for s in submit_selectors:
                    submit_btn = await page.query_selector(s)
                    if submit_btn:
                        is_disabled = await submit_btn.get_attribute("disabled")
                        aria_disabled = await submit_btn.get_attribute("aria-disabled")
                        if not is_disabled and aria_disabled != "true":
                            break

                if not submit_btn:
                    logger.error("Could not find active submit button.")
                    return False

                await submit_btn.hover()
                await self.human_delay(0.5, 1.2)
                await submit_btn.click()

                await self.human_delay(3.0, 5.0)
                logger.info(f"Successfully posted reply to tweet {tweet_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to post reply to {tweet_id}: {e}", exc_info=True)
                return False

    async def open_headful_for_login(self):
        """
        Helper method to launch headful browser so the user can easily log into X manually.
        Closes any existing headless session and opens headful window pointing to x.com/login.
        """
        async with self._lock:
            await self._close_context_internal()
            logger.info("Opening Chromium window for manual login...")
            page = await self._get_page_internal(force_headful=True)
            try:
                await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                logger.warning(f"Initial navigation notice: {e}")
            logger.info("Headful browser opened for manual login. Please sign into X in the browser window.")
