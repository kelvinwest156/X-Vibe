"""
Playwright Automation Worker for X (Twitter).
Features:
- Persistent Chromium Context (saves session & cookies in ./x_browser_profile)
- Auto-detects user's default browser on Windows (Brave, Chrome, Edge)
- Detects linked X @username handle automatically
- Cookie Export/Import for headless cloud deployment (Render)
- Context-aware scraping (extracts engagement metrics, quoted tweets, image alt text)
- Natural human browsing flow (read pause, organic likes, variable typing cadence)
"""

import os
import sys
import re
import json
import random
import asyncio
import logging

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

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
        self._lock = asyncio.Lock()
        self.is_running = False
        self.logged_in_username: Optional[str] = None

    @property
    def cookies_backup_path(self) -> str:
        return os.path.join(self.profile_dir, "cookies_backup.json")

    async def _apply_stealth(self, page: Page):
        """Applies stealth overrides to mask automation signatures."""
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception:
            pass

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
        """Internal: Launches persistent context WITHOUT acquiring self._lock."""
        if self._context:
            return self._context

        os.makedirs(self.profile_dir, exist_ok=True)
        # On Linux/Docker without DISPLAY, always use headless
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

        # Restore cookies from backup if present (e.g. imported on Render cloud)
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

    async def human_delay(self, min_sec: float = 2.5, max_sec: float = 6.0):
        """Randomized human-like pause."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def human_type(self, page: Page, selector: str, text: str):
        """Types text character-by-character with natural bursts and pauses."""
        element = await page.wait_for_selector(selector, state="visible", timeout=15000)
        await element.click()
        await self.human_delay(0.4, 1.0)

        for i, char in enumerate(text):
            await page.keyboard.type(char)
            delay = random.uniform(0.03, 0.13)
            if char in " ,.!?":
                delay += random.uniform(0.08, 0.28)
            elif i > 0 and i % random.randint(12, 22) == 0:
                delay += random.uniform(0.15, 0.4)  # Brief thinking micro-pause
            await asyncio.sleep(delay)

    async def _extract_logged_in_handle(self, page: Page) -> Optional[str]:
        """Extracts the @username of the currently logged-in X user from the DOM."""
        try:
            # 1. Account switcher button in bottom-left sidebar
            switcher = await page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
            if switcher:
                txt = await switcher.inner_text()
                m = re.search(r'@([A-Za-z0-9_]{1,30})', txt or "")
                if m:
                    return f"@{m.group(1)}"

            # 2. Profile link in navigation bar (href="/username")
            prof_link = await page.query_selector('[data-testid="AppTabBar_Profile_Link"], a[aria-label="Profile"]')
            if prof_link:
                href = await prof_link.get_attribute("href")
                if href:
                    clean_handle = href.strip("/").split("/")[0]
                    if clean_handle and clean_handle not in ("home", "explore", "notifications", "messages", "i", "login"):
                        return f"@{clean_handle}"

            # 3. Fallback: search page scripts/state for screen_name
            html_content = await page.content()
            sn_match = re.search(r'"screen_name"\s*:\s*"([A-Za-z0-9_]{1,30})"', html_content)
            if sn_match:
                return f"@{sn_match.group(1)}"
        except Exception as e:
            logger.debug(f"Could not extract handle: {e}")
        return None

    async def _backup_cookies_internal(self):
        """Saves current context cookies to cookies_backup.json."""
        if not self._context:
            return
        try:
            cookies = await self._context.cookies()
            if cookies:
                os.makedirs(self.profile_dir, exist_ok=True)
                with open(self.cookies_backup_path, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, indent=2)
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
        """Imports X session cookies into the profile (ideal for Render cloud deployment)."""
        os.makedirs(self.profile_dir, exist_ok=True)
        with open(self.cookies_backup_path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        async with self._lock:
            if self._context:
                await self._context.add_cookies(cookies)
        return await self.check_login_status()

    async def check_login_status(self) -> bool:
        """Navigates to X, verifies if session is active, and extracts linked @username."""
        async with self._lock:
            page = await self._get_page_internal()
            try:
                logger.info("Checking X session status...")
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                await self.human_delay(2.0, 3.5)

                current_url = page.url
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
                else:
                    logger.info("Confirmed X session active.")

                await self._backup_cookies_internal()
                return True

            except Exception as e:
                logger.warning(f"Error checking login status: {e}")
                await self._close_context_internal()
                return False

    async def _extract_metric_number(self, article, testid: str) -> int:
        """Extracts numeric engagement count (likes/replies) from a tweet element."""
        try:
            el = await article.query_selector(f'[data-testid="{testid}"]')
            if not el:
                return 0
            aria = await el.get_attribute("aria-label") or ""
            m = re.search(r'(\d[\d,]*)', aria)
            if m:
                return int(m.group(1).replace(",", ""))
            txt = (await el.inner_text() or "").strip()
            if txt.isdigit():
                return int(txt)
        except Exception:
            pass
        return 0

    async def scrape_feed(self, search_query: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
        """
        Scrapes tweets from Home timeline or search query with engagement metrics and media/quote context.
        """
        async with self._lock:
            page = await self._get_page_internal()
            raw_candidates: List[Dict[str, Any]] = []

            try:
                if search_query:
                    encoded_query = search_query.replace("#", "%23")
                    # Remove f=live half the time or use top/live mix so we get high-engagement posts too
                    url = f"https://x.com/search?q={encoded_query}&f=live"
                    logger.info(f"Scanning feed: {search_query}")
                else:
                    url = "https://x.com/home"
                    logger.info("Scanning home timeline...")

                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await self.human_delay(3.0, 4.8)

                # Opportunistically refresh handle if not yet captured
                if not self.logged_in_username:
                    handle = await self._extract_logged_in_handle(page)
                    if handle:
                        self.logged_in_username = handle

                # Human-like variable scrolling
                for _ in range(random.randint(2, 4)):
                    await page.mouse.wheel(0, random.randint(350, 750))
                    await self.human_delay(1.2, 2.4)

                articles = await page.query_selector_all('article[data-testid="tweet"]')
                logger.info(f"Visible posts on screen: {len(articles)}")

                my_handle_clean = (self.logged_in_username or "").lstrip("@").lower()

                for article in articles:
                    try:
                        # Skip promoted/ad tweets
                        full_text_check = await article.inner_text()
                        if "\nPromoted" in full_text_check or "\nAd\n" in full_text_check:
                            continue

                        links = await article.query_selector_all('a[href*="/status/"]')
                        tweet_id = None
                        tweet_url = None
                        for link in links:
                            href = await link.get_attribute("href")
                            if href and "/status/" in href and not href.endswith("/analytics") and "/photo/" not in href:
                                match = re.search(r'/status/(\d+)', href)
                                if match:
                                    tweet_id = match.group(1)
                                    tweet_url = f"https://x.com{href}" if href.startswith("/") else href
                                    break

                        if not tweet_id:
                            continue

                        text_elems = await article.query_selector_all('[data-testid="tweetText"]')
                        if not text_elems:
                            continue
                        tweet_text = (await text_elems[0].inner_text() or "").strip()
                        if not tweet_text:
                            continue

                        # Extract quoted tweet text if present (second tweetText inside the same article)
                        quoted_text = ""
                        if len(text_elems) > 1:
                            quoted_text = (await text_elems[1].inner_text() or "").strip()

                        # Extract image alt text if present
                        img_elems = await article.query_selector_all('img[alt]')
                        img_alts = []
                        for img in img_elems:
                            alt = (await img.get_attribute("alt") or "").strip()
                            if alt and alt.lower() not in ("image", "embedded video", "") and len(alt) > 4:
                                img_alts.append(alt)

                        author_elem = await article.query_selector('[data-testid="User-Name"]')
                        author_raw = await author_elem.inner_text() if author_elem else ""
                        author_match = re.search(r'@([A-Za-z0-9_]+)', author_raw)
                        author = author_match.group(1) if author_match else "unknown"

                        # Never reply to our own tweets
                        if my_handle_clean and author.lower() == my_handle_clean:
                            continue

                        likes = await self._extract_metric_number(article, "like")
                        replies = await self._extract_metric_number(article, "reply")
                        metrics_str = f"{likes} likes · {replies} replies"

                        extra_parts = []
                        if quoted_text:
                            extra_parts.append(f"Quoted post: '{quoted_text[:160]}'")
                        if img_alts:
                            extra_parts.append(f"Image description: '{'; '.join(img_alts[:2])}'")
                        extra_parts.append(f"Engagement: {metrics_str}")

                        raw_candidates.append({
                            "tweet_id": tweet_id,
                            "author": author,
                            "text": tweet_text,
                            "url": tweet_url or f"https://x.com/i/status/{tweet_id}",
                            "metrics": metrics_str,
                            "engagement_score": likes + (replies * 2),
                            "extra_context": " | ".join(extra_parts)
                        })

                    except Exception as item_err:
                        logger.debug(f"Error parsing tweet element: {item_err}")
                        continue

            except Exception as e:
                logger.error(f"Error during feed scraping: {e}", exc_info=True)

            # Prioritize posts that have some engagement or substantive text (>25 chars)
            raw_candidates.sort(key=lambda x: (x["engagement_score"] > 0, len(x["text"]) > 25), reverse=True)
            return raw_candidates[:limit]

    async def post_reply(self, tweet_id: str, reply_text: str, tweet_url: Optional[str] = None) -> bool:
        """
        Navigates to the tweet, pauses to 'read', optionally likes it (~40% chance),
        types a humanized reply, and submits.
        """
        async with self._lock:
            page = await self._get_page_internal()
            target_url = tweet_url or f"https://x.com/i/status/{tweet_id}"

            try:
                logger.info(f"Opening post {tweet_id} for natural reply flow...")
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

                # Simulate human reading time + slight scroll
                await self.human_delay(2.5, 4.8)
                await page.mouse.wheel(0, random.randint(80, 220))
                await self.human_delay(0.8, 1.8)

                # 40% chance to naturally Like the post before replying
                if random.random() < 0.40:
                    try:
                        like_btn = await page.query_selector('article[data-testid="tweet"] [data-testid="like"]')
                        if like_btn:
                            await like_btn.hover()
                            await self.human_delay(0.3, 0.8)
                            await like_btn.click()
                            logger.info(f"Naturally liked post {tweet_id} before replying.")
                            await self.human_delay(1.0, 2.2)
                    except Exception:
                        pass

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
                        await self.human_delay(1.2, 2.2)
                        input_box = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=10000)

                if not input_box:
                    logger.error("Could not find reply input box on the page.")
                    return False

                await self.human_type(page, '[data-testid="tweetTextarea_0"]', reply_text)
                await self.human_delay(1.2, 2.8)

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
                await self.human_delay(0.4, 1.1)
                await submit_btn.click()

                await self.human_delay(3.0, 5.0)
                logger.info(f"Posted reply to tweet {tweet_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to post reply to {tweet_id}: {e}", exc_info=True)
                return False

    async def open_headful_for_login(self):
        """Closes any existing session and opens a visible browser window to x.com/login."""
        async with self._lock:
            await self._close_context_internal()
            logger.info("Opening browser window for manual login...")
            page = await self._get_page_internal(force_headful=True)
            try:
                await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                logger.warning(f"Initial navigation notice: {e}")
            logger.info("Browser opened for manual login. Sign into X, then close the window.")
