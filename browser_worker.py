"""
Playwright Automation Worker for X (Twitter).
Features:
- Persistent Chromium Context (saves session & cookies in ./x_browser_profile)
- Stealth masking (evades bot detection)
- Humanized keystrokes & randomized delay intervals
- Safe selector targeting with fallback handling
- Single-instance lock to prevent concurrent sessions
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


class XBrowserWorker:
    def __init__(self, profile_dir: str = DEFAULT_PROFILE_DIR, headless: bool = False):
        self.profile_dir = profile_dir
        self.headless = headless
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
            logger.debug(f"playwright_stealth helper: {e}, applying direct script masking")

        # Direct script masking as a guaranteed layer
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

    async def start(self, force_headful: bool = False) -> BrowserContext:
        """Launches the persistent browser context if not already active."""
        async with self._lock:
            if self._context:
                return self._context

            os.makedirs(self.profile_dir, exist_ok=True)
            use_headless = False if force_headful else self.headless

            logger.info(f"Launching persistent Playwright browser (headless={use_headless}, profile={self.profile_dir})")
            self._playwright = await async_playwright().start()

            # Anti-detection launch flags
            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-features=IsolateOrigins,site-per-process",
            ]

            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=use_headless,
                args=args,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            )

            # Hook stealth onto every newly opened page
            self._context.on("page", lambda p: asyncio.create_task(self._apply_stealth(p)))

            self.is_running = True
            return self._context

    async def stop(self):
        """Safely closes the browser context."""
        async with self._lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception as e:
                    logger.warning(f"Error closing context: {e}")
                self._context = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"Error stopping playwright: {e}")
                self._playwright = None

            self.is_running = False
            logger.info("Browser context closed.")

    async def get_active_page(self) -> Page:
        """Retrieves or creates a valid page."""
        context = await self.start()
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()
        await self._apply_stealth(page)
        return page

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
            # Randomized keystroke timing (50ms - 150ms)
            delay = random.uniform(0.05, 0.15)
            # Micro-pause occasionally after spaces or punctuation
            if char in " ,.!?":
                delay += random.uniform(0.1, 0.3)
            await asyncio.sleep(delay)

    async def check_login_status(self) -> bool:
        """
        Navigates to X and checks if user session is active.
        Looks for primary navigation elements (Home timeline, user profile).
        """
        async with self._lock:
            page = await self.get_active_page()
            try:
                logger.info("Checking X login status...")
                await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                await self.human_delay(2.0, 4.0)

                # If redirected to login page or sign in modal is visible
                current_url = page.url
                if "login" in current_url or "i/flow/login" in current_url:
                    logger.info("Not logged in (redirected to login page).")
                    return False

                # Check for standard logged-in markers (like timeline or primary navigation)
                logged_in_selectors = [
                    '[data-testid="AppTabBar_Home_Link"]',
                    '[data-testid="SideNav_AccountSwitcher_Button"]',
                    '[data-testid="primaryColumn"]',
                    'a[href="/home"]'
                ]
                for selector in logged_in_selectors:
                    elem = await page.query_selector(selector)
                    if elem:
                        logger.info("Confirmed logged-in session on X.")
                        return True

                # If none found, double check if login button exists
                login_btn = await page.query_selector('a[href="/login"], [data-testid="loginButton"]')
                if login_btn:
                    logger.info("Login buttons detected; user is logged out.")
                    return False

                # Fallback check
                return "home" in current_url

            except Exception as e:
                logger.warning(f"Error checking login status: {e}")
                return False

    async def scrape_feed(self, search_query: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Scrapes tweets from either the Home timeline or a search query.
        Returns a list of dicts with tweet_id, author, text, url.
        """
        async with self._lock:
            page = await self.get_active_page()
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
                await self.human_delay(3.5, 6.0)

                # Scroll gently to trigger tweet loading
                for _ in range(2):
                    await page.mouse.wheel(0, random.randint(300, 600))
                    await self.human_delay(1.5, 3.0)

                # Find all tweet articles on page
                articles = await page.query_selector_all('article[data-testid="tweet"]')
                logger.info(f"Found {len(articles)} tweet elements on page.")

                for article in articles:
                    if len(tweets_data) >= limit:
                        break

                    try:
                        # Extract Tweet URL & Tweet ID
                        # Look for link matching /status/<id>
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

                        # Extract Tweet Text
                        text_elem = await article.query_selector('[data-testid="tweetText"]')
                        tweet_text = await text_elem.inner_text() if text_elem else ""

                        # Extract Author Handle
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
            page = await self.get_active_page()
            target_url = tweet_url or f"https://x.com/i/status/{tweet_id}"

            try:
                logger.info(f"Navigating to tweet for reply: {target_url}")
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                await self.human_delay(3.0, 5.5)

                # Locate reply input area
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

                # If direct textbox is not yet active, click the reply button first
                if not input_box:
                    reply_btn = await page.query_selector('[data-testid="reply"]')
                    if reply_btn:
                        await reply_btn.click()
                        await self.human_delay(1.5, 3.0)
                        input_box = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=10000)

                if not input_box:
                    logger.error("Could not find reply input box on the page.")
                    return False

                # Type character-by-character with realistic cadence
                await self.human_type(page, '[data-testid="tweetTextarea_0"]', reply_text)
                await self.human_delay(2.0, 4.0)

                # Locate tweet submit button
                submit_selectors = [
                    '[data-testid="tweetButtonInline"]',
                    '[data-testid="tweetButton"]',
                    'button[data-testid="tweetButtonInline"]'
                ]

                submit_btn = None
                for s in submit_selectors:
                    submit_btn = await page.query_selector(s)
                    if submit_btn:
                        # Ensure button is not disabled
                        is_disabled = await submit_btn.get_attribute("disabled")
                        aria_disabled = await submit_btn.get_attribute("aria-disabled")
                        if not is_disabled and aria_disabled != "true":
                            break

                if not submit_btn:
                    logger.error("Could not find active submit button.")
                    return False

                # Slight hover pause before click
                await submit_btn.hover()
                await self.human_delay(0.8, 1.8)
                await submit_btn.click()

                # Wait for post action to complete
                await self.human_delay(3.5, 6.0)
                logger.info(f"Successfully posted reply to tweet {tweet_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to post reply to {tweet_id}: {e}", exc_info=True)
                return False

    async def open_headful_for_login(self):
        """
        Helper method to launch headful browser so the user can easily log into X manually.
        Keeps running until manually stopped or closed.
        """
        await self.stop()  # Stop any headless background instance first
        context = await self.start(force_headful=True)
        page = await self.get_active_page()
        await page.goto("https://x.com/login", wait_until="domcontentloaded")
        logger.info("Headful browser opened for manual login. Please log into your X account.")
