"""
X (Twitter) Browser Actions Service for X-VibeBot.
Handles DOM parsing, metric extraction, tweet scraping, and publishing replies,
original posts, and threads.
"""

import re
import random
import asyncio
import logging
from typing import List, Dict, Optional, Any, Tuple
from playwright.async_api import Page

import services.browser.stealth as stealth

logger = logging.getLogger("x_vibebot.services.browser.actions")


async def extract_metric_number(article, testid: str) -> int:
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


async def extract_logged_in_handle(page: Page) -> Optional[str]:
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


async def scrape_feed_action(
    page: Page,
    search_query: Optional[str] = None,
    limit: int = 8,
    logged_in_username: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Scrapes tweets from Home timeline or search query with engagement metrics and media/quote context.
    Returns (scraped_candidates, detected_handle).
    """
    raw_candidates: List[Dict[str, Any]] = []
    detected_handle = logged_in_username

    try:
        if search_query:
            encoded_query = search_query.replace("#", "%23")
            url = f"https://x.com/search?q={encoded_query}&f=live"
            logger.info(f"Scanning feed: {search_query}")
        else:
            url = "https://x.com/home"
            logger.info("Scanning home timeline...")

        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await stealth.human_delay(0.8, 1.6)

        if not detected_handle:
            detected_handle = await extract_logged_in_handle(page)

        # Human-like variable scrolling
        for _ in range(random.randint(1, 2)):
            await page.mouse.wheel(0, random.randint(350, 750))
            await stealth.human_delay(0.4, 0.9)

        articles = await page.query_selector_all('article[data-testid="tweet"]')
        logger.info(f"Visible posts on screen: {len(articles)}")

        my_handle_clean = (detected_handle or "").lstrip("@").lower()

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

                likes = await extract_metric_number(article, "like")
                replies = await extract_metric_number(article, "reply")
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

    raw_candidates.sort(key=lambda x: (x["engagement_score"] > 0, len(x["text"]) > 25), reverse=True)
    return raw_candidates[:limit], detected_handle


async def post_reply_action(
    page: Page,
    tweet_id: str,
    reply_text: str,
    tweet_url: Optional[str] = None,
    should_like: Optional[bool] = None,
    mouse_pos: tuple[float, float] = (640.0, 400.0)
) -> tuple[bool, Optional[str], tuple[float, float]]:
    """
    Navigates to the tweet, simulates reading dwell & mouse trajectory,
    likes if directed, types reply with human variation, and submits.
    Returns (success, error_message, updated_mouse_pos).
    """
    target_url = tweet_url
    if not target_url or target_url.endswith("/home") or "/status/" not in target_url:
        target_url = f"https://x.com/i/status/{tweet_id}"

    curr_mouse = mouse_pos
    try:
        logger.info(f"Opening post {tweet_id} ({target_url}) for natural biometric reply flow...")
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

        if "login" in page.url or "i/flow/login" in page.url:
            err = "Browser session is not logged into X (redirected to login)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.simulate_reading_dwell(
            page,
            text_length=max(100, len(reply_text)),
            current_mouse_pos=curr_mouse
        )

        do_like = should_like if should_like is not None else (random.random() < 0.35)
        if do_like:
            try:
                like_btn = await page.query_selector('article[data-testid="tweet"] [data-testid="like"]')
                if like_btn:
                    curr_mouse = await stealth.human_click(page, like_btn, curr_mouse)
                    logger.info(f"AI-directed Like executed on post {tweet_id} before replying.")
                    await stealth.human_delay(0.3, 0.6)
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
                curr_mouse = await stealth.human_click(page, reply_btn, curr_mouse)
                await stealth.human_delay(0.3, 0.7)
                input_box = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=10000)

        if not input_box:
            err = "Could not find reply input box on the page."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.human_type(page, '[data-testid="tweetTextarea_0"]', reply_text, curr_mouse)
        await stealth.human_delay(0.3, 0.7)

        submit_selectors = [
            '[data-testid="tweetButtonInline"]',
            '[data-testid="tweetButton"]',
            'button[data-testid="tweetButtonInline"]',
            'button[data-testid="tweetButton"]'
        ]

        submit_btn = None
        for _ in range(12):
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
            await asyncio.sleep(0.3)

        if not submit_btn:
            err = "Could not find active submit button (it may be disabled or missing)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.human_click(page, submit_btn, curr_mouse)
        await stealth.human_delay(0.8, 1.5)
        logger.info(f"Posted reply to tweet {tweet_id}")
        return True, None, curr_mouse

    except Exception as e:
        err = str(e)
        logger.error(f"Failed to post reply to {tweet_id}: {e}", exc_info=True)
        return False, err, curr_mouse


async def post_original_action(
    page: Page,
    post_text: str,
    mouse_pos: tuple[float, float] = (640.0, 400.0)
) -> tuple[bool, Optional[str], tuple[float, float]]:
    """
    Publishes a standalone original post on X.
    Returns (success, error_message, updated_mouse_pos).
    """
    curr_mouse = mouse_pos
    try:
        logger.info("Navigating to X home to compose original post...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)

        if "login" in page.url or "i/flow/login" in page.url:
            err = "Browser session is not logged into X (redirected to login)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.simulate_reading_dwell(page, text_length=80, current_mouse_pos=curr_mouse)

        box = await page.query_selector('[data-testid="tweetTextarea_0"]')
        if not box:
            compose_btn = await page.query_selector('[data-testid="SideNav_NewTweet_Button"], a[href="/compose/post"]')
            if compose_btn:
                curr_mouse = await stealth.human_click(page, compose_btn, curr_mouse)
                await stealth.human_delay(0.3, 0.7)

        curr_mouse = await stealth.human_type(page, '[data-testid="tweetTextarea_0"]', post_text.strip(), curr_mouse)
        await stealth.human_delay(0.3, 0.7)

        submit_selectors = [
            '[data-testid="tweetButtonInline"]',
            '[data-testid="tweetButton"]',
            'button[data-testid="tweetButtonInline"]',
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
            await asyncio.sleep(0.3)

        if not submit_btn:
            err = "Could not find active Post button (it may be disabled or missing)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.human_click(page, submit_btn, curr_mouse)
        await stealth.human_delay(0.8, 1.5)
        logger.info("Successfully published original post!")
        return True, None, curr_mouse

    except Exception as e:
        err = str(e)
        logger.error(f"Failed to publish original post: {e}", exc_info=True)
        return False, err, curr_mouse


async def post_thread_action(
    page: Page,
    thread_text: str,
    mouse_pos: tuple[float, float] = (640.0, 400.0)
) -> tuple[bool, Optional[str], tuple[float, float]]:
    """
    Publishes a multi-post thread on X.
    Returns (success, error_message, updated_mouse_pos).
    """
    posts = [p.strip() for p in re.split(r'\n?---\n?', thread_text) if p.strip()]
    if not posts:
        return False, "Thread text has no posts to publish.", mouse_pos
    if len(posts) == 1:
        return await post_original_action(page, posts[0], mouse_pos=mouse_pos)

    curr_mouse = mouse_pos
    try:
        logger.info(f"Composing {len(posts)}-post thread on X...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)

        if "login" in page.url or "i/flow/login" in page.url:
            err = "Browser session is not logged into X (redirected to login)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.simulate_reading_dwell(page, text_length=90, current_mouse_pos=curr_mouse)

        compose_btn = await page.query_selector('[data-testid="SideNav_NewTweet_Button"], a[href="/compose/post"]')
        if compose_btn:
            curr_mouse = await stealth.human_click(page, compose_btn, curr_mouse)
            await stealth.human_delay(0.4, 0.8)
        else:
            await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
            await stealth.human_delay(0.6, 1.2)

        for idx, post_content in enumerate(posts):
            textarea_selector = f'[data-testid="tweetTextarea_{idx}"]'
            curr_mouse = await stealth.human_type(page, textarea_selector, post_content, curr_mouse)
            await stealth.human_delay(0.3, 0.7)

            if idx < len(posts) - 1:
                add_btn = await page.wait_for_selector('[data-testid="addButton"]', state="visible", timeout=10000)
                curr_mouse = await stealth.human_click(page, add_btn, curr_mouse)
                await stealth.human_delay(0.3, 0.6)

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
            await asyncio.sleep(0.3)

        if not submit_btn:
            err = "Could not find active submit button for thread."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.human_click(page, submit_btn, curr_mouse)
        await stealth.human_delay(1.0, 1.8)
        logger.info(f"Successfully published {len(posts)}-post thread!")
        return True, None, curr_mouse

    except Exception as e:
        err = str(e)
        logger.error(f"Failed to publish thread: {e}", exc_info=True)
        return False, err, curr_mouse
