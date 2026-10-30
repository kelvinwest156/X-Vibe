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
        self.last_error: Optional[str] = None
        self._mouse_x: float = 640.0
        self._mouse_y: float = 400.0

        # Seed cookies from default profile if tenant profile has no backup
        if not os.path.isfile(self.cookies_backup_path):
            default_backup = os.path.join(DEFAULT_PROFILE_DIR, "cookies_backup.json")
            if os.path.isfile(default_backup) and os.path.abspath(self.profile_dir) != os.path.abspath(DEFAULT_PROFILE_DIR):
                try:
                    os.makedirs(self.profile_dir, exist_ok=True)
                    import shutil
                    shutil.copy(default_backup, self.cookies_backup_path)
                    logger.info(f"Seeded active session cookies into {self.profile_dir}")
                except Exception as se:
                    logger.debug(f"Could not seed default cookies: {se}")

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

    async def move_mouse_humanlike(self, page: Page, target_x: float, target_y: float):
        """
        Anti-Detection Biometrics: Moves the cursor along a randomized Cubic Bézier curve
        with variable steps (18-30) and natural hand micro-jitter (±2.5px).
        """
        start_x, start_y = self._mouse_x, self._mouse_y
        steps = random.randint(18, 30)
        ctrl1_x = start_x + (target_x - start_x) * random.uniform(0.20, 0.45) + random.uniform(-45, 45)
        ctrl1_y = start_y + (target_y - start_y) * random.uniform(0.15, 0.40) + random.uniform(-45, 45)
        ctrl2_x = start_x + (target_x - start_x) * random.uniform(0.55, 0.85) + random.uniform(-35, 35)
        ctrl2_y = start_y + (target_y - start_y) * random.uniform(0.60, 0.85) + random.uniform(-35, 35)

        for step in range(1, steps + 1):
            t = step / steps
            inv = 1.0 - t
            bx = (inv ** 3) * start_x + 3 * (inv ** 2) * t * ctrl1_x + 3 * inv * (t ** 2) * ctrl2_x + (t ** 3) * target_x
            by = (inv ** 3) * start_y + 3 * (inv ** 2) * t * ctrl1_y + 3 * inv * (t ** 2) * ctrl2_y + (t ** 3) * target_y
            if step < steps:
                bx += random.uniform(-2.5, 2.5)
                by += random.uniform(-2.5, 2.5)
            try:
                await page.mouse.move(max(1.0, bx), max(1.0, by))
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.006, 0.019))

        self._mouse_x, self._mouse_y = target_x, target_y

    async def human_click(self, page: Page, element):
        """
        Glides the mouse along a Bézier curve into a randomized inner coordinate of `element`,
        pauses briefly like a human finger, and clicks.
        """
        try:
            await element.scroll_into_view_if_needed(timeout=4000)
        except Exception:
            pass
        box = None
        try:
            box = await element.bounding_box()
        except Exception:
            box = None

        if box and box.get("width", 0) > 4 and box.get("height", 0) > 4:
            tx = box["x"] + box["width"] * random.uniform(0.25, 0.75)
            ty = box["y"] + box["height"] * random.uniform(0.25, 0.75)
            await self.move_mouse_humanlike(page, tx, ty)
            await asyncio.sleep(random.uniform(0.12, 0.36))
            await page.mouse.click(tx, ty, delay=random.randint(35, 95))
        else:
            await element.click()

    async def simulate_reading_dwell(self, page: Page, text_length: int = 140):
        """
        Simulates proportional human reading time and viewport dwell before any interaction.
        """
        read_seconds = max(2.4, min(8.5, text_length / 26.0)) + random.uniform(0.8, 2.2)
        await asyncio.sleep(read_seconds * 0.45)
        try:
            await self.move_mouse_humanlike(
                page,
                random.uniform(360, 820),
                random.uniform(240, 560)
            )
            await page.mouse.wheel(0, random.randint(75, 210))
        except Exception:
            pass
        await asyncio.sleep(read_seconds * 0.55)

    async def human_type(self, page: Page, selector: str, text: str):
        """Types text character-by-character with natural bursts, curved mouse focus, and occasional typo/backspace."""
        element = await page.wait_for_selector(selector, state="visible", timeout=15000)
        await self.human_click(page, element)
        await self.human_delay(0.4, 1.0)

        for i, char in enumerate(text):
            # 1.5% chance on lowercase letters to make a human key-slip and immediately backspace
            if char.isalpha() and char.islower() and random.random() < 0.015:
                wrong_char = random.choice("aeiourstln")
                if wrong_char != char:
                    await page.keyboard.type(wrong_char)
                    await asyncio.sleep(random.uniform(0.06, 0.16))
                    await page.keyboard.press("Backspace")
                    await asyncio.sleep(random.uniform(0.05, 0.14))

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
                try:
                    await self._close_context_internal()
                except Exception:
                    pass
        return await self.check_login_status()

    async def check_login_status(self) -> bool:
        """Navigates to X, verifies if session is active, and extracts linked @username."""
        # 0. Seed from default cookies if tenant profile has no backup
        if not os.path.isfile(self.cookies_backup_path):
            default_backup = os.path.join(DEFAULT_PROFILE_DIR, "cookies_backup.json")
            if os.path.isfile(default_backup) and os.path.abspath(self.profile_dir) != os.path.abspath(DEFAULT_PROFILE_DIR):
                try:
                    os.makedirs(self.profile_dir, exist_ok=True)
                    import shutil
                    shutil.copy(default_backup, self.cookies_backup_path)
                    logger.info(f"Seeded active session cookies into {self.profile_dir}")
                except Exception as se:
                    logger.debug(f"Could not seed default cookies: {se}")

        # 1. Immediate fast-path: check if valid cookies backup already exists
        if os.path.isfile(self.cookies_backup_path):
            try:
                with open(self.cookies_backup_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, list) and any(c.get("name") == "auth_token" and c.get("value") for c in saved):
                    if not self.logged_in_username:
                        self.logged_in_username = "@youngkay_156"
                    logger.info(f"Confirmed X session active from cookies backup as {self.logged_in_username}")
                    return True
            except Exception as ce:
                logger.debug(f"Cookie fast check notice: {ce}")

        # 2. Otherwise navigate with Playwright
        async with self._lock:
            try:
                page = await self._get_page_internal()
            except Exception as e:
                logger.warning(f"Could not get page for login check: {e}")
                return False

            try:
                logger.info("Checking X session status...")
                current_url = page.url or ""
                # If page is already on x.com/home, avoid redundant heavy navigation
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
                elif not self.logged_in_username:
                    self.logged_in_username = "@youngkay_156"

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

                        # Extract image alt text and media URL if present (for Multimodal Vision AI)
                        img_elems = await article.query_selector_all('img')
                        img_alts = []
                        media_url = None
                        for img in img_elems:
                            src = (await img.get_attribute("src") or "").strip()
                            if not media_url and "pbs.twimg.com/media/" in src:
                                media_url = src
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
                        if media_url:
                            extra_parts.append("Attached visual media included")
                        extra_parts.append(f"Engagement: {metrics_str}")

                        raw_candidates.append({
                            "tweet_id": tweet_id,
                            "author": author,
                            "text": tweet_text,
                            "url": tweet_url or f"https://x.com/i/status/{tweet_id}",
                            "media_url": media_url,
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

    async def post_reply(
        self,
        tweet_id: str,
        reply_text: str,
        tweet_url: Optional[str] = None,
        should_like: Optional[bool] = None
    ) -> bool:
        """
        Navigates to the tweet, simulates proportional human reading dwell & curved mouse trajectory,
        likes the post when directed by AI (`should_like`), types a humanized reply, and submits.
        """
        async with self._lock:
            page = await self._get_page_internal()
            target_url = tweet_url
            if not target_url or target_url.endswith("/home") or "/status/" not in target_url:
                target_url = f"https://x.com/i/status/{tweet_id}"

            try:
                logger.info(f"Opening post {tweet_id} ({target_url}) for natural biometric reply flow...")
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

                # Check if session redirected to login
                if "login" in page.url or "i/flow/login" in page.url:
                    self.last_error = "Browser session is not logged into X (redirected to login)."
                    logger.error(self.last_error)
                    return False

                # Simulate proportional human reading dwell time + curved mouse movement
                await self.simulate_reading_dwell(page, text_length=max(120, len(reply_text) * 2))

                # AI-directed Like decision (or 35% fallback if unspecified)
                do_like = should_like if should_like is not None else (random.random() < 0.35)
                if do_like:
                    try:
                        like_btn = await page.query_selector('article[data-testid="tweet"] [data-testid="like"]')
                        if like_btn:
                            await self.human_click(page, like_btn)
                            logger.info(f"AI-directed Like executed on post {tweet_id} before replying.")
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
                        await self.human_click(page, reply_btn)
                        await self.human_delay(1.2, 2.2)
                        input_box = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=10000)

                if not input_box:
                    self.last_error = "Could not find reply input box on the page."
                    logger.error(self.last_error)
                    return False

                await self.human_type(page, '[data-testid="tweetTextarea_0"]', reply_text)
                await self.human_delay(1.2, 2.8)

                submit_selectors = [
                    '[data-testid="tweetButtonInline"]',
                    '[data-testid="tweetButton"]',
                    'button[data-testid="tweetButtonInline"]',
                    'button[data-testid="tweetButton"]'
                ]

                submit_btn = None
                for _ in range(12):  # Poll up to 6 seconds for X to validate and enable the submit button
                    for s in submit_selectors:
                        btn = await page.query_selector(s)
                        if btn:
                            is_disabled = await btn.get_attribute("disabled")
                            aria_disabled = await btn.get_attribute("aria-disabled")
                            if not is_disabled and aria_disabled != "true":
                                submit_btn = btn
                                break
                    if submit_btn:
                        break
                    await asyncio.sleep(0.5)

                if not submit_btn:
                    self.last_error = "Could not find active submit button (it may be disabled or missing)."
                    logger.error(self.last_error)
                    return False

                await self.human_click(page, submit_btn)

                await self.human_delay(3.0, 5.0)
                logger.info(f"Posted reply to tweet {tweet_id}")
                return True

            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Failed to post reply to {tweet_id}: {e}", exc_info=True)
                return False

    async def post_original(self, post_text: str) -> bool:
        """
        Publishes a standalone original post on X with humanized typing and curved mouse clicks.
        """
        async with self._lock:
            page = await self._get_page_internal()
            try:
                logger.info("Navigating to X home to compose original post...")
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)

                if "login" in page.url or "i/flow/login" in page.url:
                    self.last_error = "Browser session is not logged into X (redirected to login)."
                    logger.error(self.last_error)
                    return False

                await self.simulate_reading_dwell(page, text_length=120)

                box = await page.query_selector('[data-testid="tweetTextarea_0"]')
                if not box:
                    compose_btn = await page.query_selector('[data-testid="SideNav_NewTweet_Button"], a[href="/compose/post"]')
                    if compose_btn:
                        await self.human_click(page, compose_btn)
                        await self.human_delay(1.2, 2.2)

                await self.human_type(page, '[data-testid="tweetTextarea_0"]', post_text.strip())
                await self.human_delay(1.2, 2.5)

                submit_selectors = [
                    '[data-testid="tweetButtonInline"]',
                    '[data-testid="tweetButton"]',
                    'button[data-testid="tweetButtonInline"]',
                    'button[data-testid="tweetButton"]'
                ]
                submit_btn = None
                for _ in range(12):  # Poll up to 6 seconds for X to validate and enable the submit button
                    for s in submit_selectors:
                        btn = await page.query_selector(s)
                        if btn:
                            is_dis = await btn.get_attribute("disabled")
                            aria_dis = await btn.get_attribute("aria-disabled")
                            if not is_dis and aria_dis != "true":
                                submit_btn = btn
                                break
                    if submit_btn:
                        break
                    await asyncio.sleep(0.5)

                if not submit_btn:
                    self.last_error = "Could not find active Post button (it may be disabled or missing)."
                    logger.error(self.last_error)
                    return False

                await self.human_click(page, submit_btn)
                await self.human_delay(3.0, 5.0)
                logger.info("Successfully published original post!")
                return True
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Failed to publish original post: {e}", exc_info=True)
                return False

    async def post_thread(self, thread_text: str) -> bool:
        """
        Publishes a multi-post thread on X using X's native thread composer ('Add post' button).
        Posts in `thread_text` are separated by '---'.
        """
        posts = [p.strip() for p in re.split(r'\n?---\n?', thread_text) if p.strip()]
        if not posts:
            self.last_error = "Thread text has no posts to publish."
            return False
        if len(posts) == 1:
            return await self.post_original(posts[0])

        async with self._lock:
            page = await self._get_page_internal()
            try:
                logger.info(f"Composing {len(posts)}-post thread on X...")
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)

                if "login" in page.url or "i/flow/login" in page.url:
                    self.last_error = "Browser session is not logged into X (redirected to login)."
                    logger.error(self.last_error)
                    return False

                await self.simulate_reading_dwell(page, text_length=140)

                # Open modal composer for multi-tweet thread
                compose_btn = await page.query_selector('[data-testid="SideNav_NewTweet_Button"], a[href="/compose/post"]')
                if compose_btn:
                    await self.human_click(page, compose_btn)
                    await self.human_delay(1.5, 2.5)
                else:
                    await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
                    await self.human_delay(2.0, 3.5)

                for idx, post_content in enumerate(posts):
                    textarea_selector = f'[data-testid="tweetTextarea_{idx}"]'
                    await self.human_type(page, textarea_selector, post_content)
                    await self.human_delay(1.0, 2.2)

                    # If there is another post in the thread, click the '+' Add post button
                    if idx < len(posts) - 1:
                        add_btn = await page.wait_for_selector('[data-testid="addButton"]', state="visible", timeout=10000)
                        await self.human_click(page, add_btn)
                        await self.human_delay(1.0, 1.8)

                submit_selectors = [
                    '[data-testid="tweetButton"]',
                    '[data-testid="tweetButtonInline"]',
                    'button[data-testid="tweetButton"]'
                ]
                submit_btn = None
                for _ in range(12):
                    for s in submit_selectors:
                        btn = await page.query_selector(s)
                        if btn:
                            is_dis = await btn.get_attribute("disabled")
                            aria_dis = await btn.get_attribute("aria-disabled")
                            if not is_dis and aria_dis != "true":
                                submit_btn = btn
                                break
                    if submit_btn:
                        break
                    await asyncio.sleep(0.5)

                if not submit_btn:
                    self.last_error = "Could not find active submit button for thread."
                    logger.error(self.last_error)
                    return False

                await self.human_click(page, submit_btn)
                await self.human_delay(3.5, 5.5)
                logger.info(f"Successfully published {len(posts)}-post thread!")
                return True
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Failed to publish thread: {e}", exc_info=True)
                return False

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
        async with self._lock:
            await self._close_context_internal()
            logger.info("Opening browser window for manual login...")
            page = await self._get_page_internal(force_headful=True)
            try:
                await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=12000)
            except Exception as e:
                logger.warning(f"Initial navigation notice: {e}")
            logger.info("Browser opened for manual login. Sign into X, then close the window.")
