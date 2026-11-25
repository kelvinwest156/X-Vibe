"""
X (Twitter) Browser Actions Service for X-VibeBot.
Handles DOM parsing, metric extraction, tweet scraping, and publishing replies,
original posts, and threads.
"""

import re
import random
import asyncio
import logging
import urllib.parse
from typing import List, Dict, Optional, Any, Tuple, Sequence
from playwright.async_api import Page

from core.security import (
    validate_external_url,
    ALLOWED_X_HOSTS,
    ALLOWED_MEDIA_HOSTS,
)
import services.browser.stealth as stealth

logger = logging.getLogger("x_vibebot.services.browser.actions")

_RESERVED_X_PATHS = frozenset({
    "home", "explore", "notifications", "messages", "i", "login",
    "compose", "search", "settings", "hashtag", "tos", "privacy",
})

_TOAST_SUCCESS_TOKENS = (
    "was sent",
    "post sent",
    "reply sent",
    "added to your",
)

_TOAST_ERROR_TOKENS = (
    "something went wrong",
    "error",
    "failed",
    "try again",
    "already said",
    "duplicate",
    "limit",
    "rate",
    "suspended",
    "locked",
    "couldn't",
    "could not",
    "unable",
    "whoops",
    "spam",
    "automated",
    "blocked",
    "restricted",
    "not allowed",
    "longer",
    "exceeds",
)


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
    """
    Extracts the @username of the currently logged-in X user strictly from
    authenticated sidebar/nav DOM elements (never from timeline HTML scripts).
    """
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
            if href and href.startswith("/"):
                parts = [p for p in href.strip("/").split("/") if p]
                if len(parts) == 1:
                    clean_handle = parts[0]
                    if (
                        re.fullmatch(r'[A-Za-z0-9_]{1,30}', clean_handle)
                        and clean_handle.lower() not in _RESERVED_X_PATHS
                    ):
                        return f"@{clean_handle}"
    except Exception as e:
        logger.debug(f"Could not extract handle: {e}")
    return None


async def _is_promoted_article(article, full_text: str, tweet_text: str = "") -> bool:
    """Detects promoted/sponsored tweets using Ad badge elements and header/footer boundary tokens."""
    try:
        ad_badge = await article.query_selector(
            '[data-testid="promotedIndicator"], [aria-label="Ad"], [aria-label="Promoted"]'
        )
        if ad_badge:
            return True
    except Exception:
        pass

    # Strip the primary tweet body once so legitimate tweet prose containing "Ad" is not misclassified
    non_body_text = full_text or ""
    if tweet_text and tweet_text in non_body_text:
        non_body_text = non_body_text.replace(tweet_text, "", 1)

    for raw_line in non_body_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in ("Ad", "Promoted") or line.startswith("Promoted by "):
            return True
        if re.search(r'(?:^|\s·\s)(?:Ad|Promoted)(?:\s|$)', line):
            return True
    return False


async def _extract_main_and_quoted_text(article) -> Tuple[str, str]:
    """
    Separates the primary tweet text from any nested quoted-tweet card text
    so a quoted tweet is never mistaken for the main tweet.
    """
    text_elems = await article.query_selector_all('[data-testid="tweetText"]')
    if not text_elems:
        return "", ""

    main_texts: List[str] = []
    quoted_texts: List[str] = []

    for el in text_elems:
        in_quote = False
        try:
            eval_res = await el.evaluate('el => Boolean(el.closest(\'div[role="link"]\'))')
            if isinstance(eval_res, bool):
                in_quote = eval_res
        except Exception:
            in_quote = False

        txt = (await el.inner_text() or "").strip()
        if not txt:
            continue
        if in_quote:
            quoted_texts.append(txt)
        else:
            main_texts.append(txt)

    if not main_texts:
        return "", ""

    tweet_text = main_texts[0]
    if quoted_texts:
        quoted_text = quoted_texts[0]
    elif len(main_texts) > 1:
        quoted_text = main_texts[1]
    else:
        quoted_text = ""

    return tweet_text, quoted_text


async def _extract_author_handle(article) -> str:
    """
    Extracts the main author handle from [data-testid="User-Name"], preferring
    the profile <a href="/handle"> link over any @mention inside the display name.
    """
    author_elem = await article.query_selector('[data-testid="User-Name"]')
    if not author_elem:
        return "unknown"

    try:
        links = await author_elem.query_selector_all("a[href]")
        fallback_handle: Optional[str] = None
        for link in links or []:
            href = (await link.get_attribute("href") or "").strip()
            if not href.startswith("/"):
                continue
            clean_path = href.split("?", 1)[0].split("#", 1)[0]
            parts = [p for p in clean_path.strip("/").split("/") if p]
            if len(parts) != 1:
                continue
            cand = parts[0]
            if not re.fullmatch(r'[A-Za-z0-9_]{1,30}', cand) or cand.lower() in _RESERVED_X_PATHS:
                continue
            try:
                link_txt = (await link.inner_text() or "").strip()
            except Exception:
                link_txt = ""
            if link_txt.startswith("@"):
                return cand
            if not fallback_handle:
                fallback_handle = cand
        if fallback_handle:
            return fallback_handle
    except Exception:
        pass

    author_raw = (await author_elem.inner_text() or "")
    for line in author_raw.splitlines():
        m_line = re.fullmatch(r'@([A-Za-z0-9_]{1,30})', line.strip())
        if m_line:
            return m_line.group(1)

    all_matches = re.findall(r'@([A-Za-z0-9_]{1,30})', author_raw)
    return all_matches[-1] if all_matches else "unknown"


def _validate_tweet_status_url(raw_url: Optional[str], tweet_id: str) -> str:
    """Validates a tweet URL against ALLOWED_X_HOSTS and `/status/{tweet_id}`."""
    fallback_url = f"https://x.com/i/status/{tweet_id}"
    if not raw_url or not isinstance(raw_url, str):
        return fallback_url
    try:
        validated = validate_external_url(
            raw_url,
            allowed_hosts=ALLOWED_X_HOSTS,
            require_https=True,
        )
        parsed = urllib.parse.urlparse(validated)
        if re.search(rf"/status/{re.escape(str(tweet_id))}(?:$|[/?#])", parsed.path or ""):
            return validated
    except ValueError:
        pass
    return fallback_url


async def _find_target_tweet_article(page: Page, tweet_id: str):
    """
    Locates the exact <article data-testid="tweet"> whose status permalink matches `tweet_id`
    so thread replies/likes never target a parent tweet by mistake.
    """
    articles = await page.query_selector_all('article[data-testid="tweet"]')
    if not articles:
        try:
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=8000)
            articles = await page.query_selector_all('article[data-testid="tweet"]')
        except Exception:
            articles = []

    if not articles:
        return None

    status_pat = re.compile(rf"/status/{re.escape(str(tweet_id))}(?:$|[/?#])")
    secondary_match = None

    for article in articles:
        try:
            links = await article.query_selector_all('a[href*="/status/"]')
            for link in links or []:
                href = (await link.get_attribute("href") or "").strip()
                if not href or not status_pat.search(href):
                    continue
                if any(s in href for s in ("/analytics", "/retweets", "/likes", "/quotes")):
                    continue

                # Skip links embedded inside a nested quoted-tweet card
                in_quote = False
                try:
                    eval_res = await link.evaluate('el => Boolean(el.closest(\'div[role="link"]\'))')
                    if isinstance(eval_res, bool):
                        in_quote = eval_res
                except Exception:
                    in_quote = False
                if in_quote:
                    continue

                try:
                    has_time = await link.query_selector("time")
                except Exception:
                    has_time = None
                if has_time:
                    return article
                if secondary_match is None:
                    secondary_match = article
        except Exception:
            continue

    if secondary_match is not None:
        return secondary_match
    if len(articles) == 1:
        return articles[0]
    return None


async def _check_error_toast(page: Page) -> Optional[str]:
    """
    Inspects active `[data-testid="toast"]` elements.
    Returns an error string if an error toast is visible, or None if absent / success confirmation.
    """
    try:
        toasts = await page.query_selector_all('[data-testid="toast"]')
    except Exception:
        return None

    for toast in toasts or []:
        try:
            txt = (await toast.inner_text() or "").strip()
        except Exception:
            continue
        if not txt:
            continue
        lower = txt.lower()
        if any(tok in lower for tok in _TOAST_SUCCESS_TOKENS) and not any(tok in lower for tok in _TOAST_ERROR_TOKENS):
            continue
        if any(tok in lower for tok in _TOAST_ERROR_TOKENS) or not any(tok in lower for tok in _TOAST_SUCCESS_TOKENS):
            return f"X rejected post: {txt}"
    return None


async def _is_submit_button_inactive(page: Page, submit_selectors: Sequence[str]) -> bool:
    """Returns True if no enabled submit button remains in the active composer."""
    for sel in submit_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                is_dis = await btn.get_attribute("disabled")
                aria_dis = await btn.get_attribute("aria-disabled")
                disabled_flag = is_dis is not None and is_dis is not False
                if not disabled_flag and aria_dis != "true":
                    return False
        except Exception:
            continue
    return True


async def _submit_and_verify_tweet(
    page: Page,
    submit_btn,
    curr_mouse: tuple[float, float],
    composer_selector: str,
    submit_selectors: Sequence[str],
    confirm_timeout: float = 10.0,
) -> tuple[bool, Optional[str], tuple[float, float]]:
    """
    Clicks the enabled submit button and verifies delivery via GraphQL `CreateTweet`
    response or composer disappearance/reset, while guarding against `[data-testid="toast"]` errors.
    """
    create_tweet_state: Dict[str, Any] = {
        "seen": False,
        "ok": None,
        "status": None,
        "error": None,
    }
    create_tweet_event = asyncio.Event()

    async def _on_response(resp) -> None:
        try:
            url = str(getattr(resp, "url", "") or "")
            if "CreateTweet" not in url:
                return
            status = int(getattr(resp, "status", 0) or 0)
            ok = 200 <= status < 300
            err_msg: Optional[str] = None
            try:
                body = await resp.json()
                if isinstance(body, dict) and body.get("errors"):
                    ok = False
                    first_err = body["errors"][0]
                    if isinstance(first_err, dict):
                        err_msg = first_err.get("message") or str(first_err)
                    else:
                        err_msg = str(first_err)
            except Exception:
                pass
            create_tweet_state["seen"] = True
            create_tweet_state["ok"] = ok
            create_tweet_state["status"] = status
            create_tweet_state["error"] = err_msg
            create_tweet_event.set()
        except Exception:
            pass

    listener_attached = False
    if hasattr(page, "on"):
        try:
            page.on("response", _on_response)
            listener_attached = True
        except Exception:
            listener_attached = False

    try:
        curr_mouse = await stealth.human_click(page, submit_btn, curr_mouse)

        deadline = asyncio.get_running_loop().time() + confirm_timeout
        while True:
            toast_err = await _check_error_toast(page)
            if toast_err:
                return False, toast_err, curr_mouse

            if create_tweet_state["seen"]:
                if not create_tweet_state["ok"]:
                    err = create_tweet_state["error"] or f"CreateTweet failed (HTTP {create_tweet_state['status']})"
                    return False, err, curr_mouse
                await asyncio.sleep(0.35)
                toast_err = await _check_error_toast(page)
                if toast_err:
                    return False, toast_err, curr_mouse
                return True, None, curr_mouse

            # Fallback DOM confirmation: modal composer disappeared or inline composer cleared & button disabled
            try:
                composer_el = await page.query_selector(composer_selector)
            except Exception:
                composer_el = None

            if composer_el is None:
                await asyncio.sleep(0.35)
                toast_err = await _check_error_toast(page)
                if toast_err:
                    return False, toast_err, curr_mouse
                return True, None, curr_mouse

            try:
                raw_remaining = await composer_el.inner_text()
                remaining_txt = raw_remaining.strip() if isinstance(raw_remaining, str) else ""
            except Exception:
                remaining_txt = ""

            if not remaining_txt and await _is_submit_button_inactive(page, submit_selectors):
                await asyncio.sleep(0.35)
                toast_err = await _check_error_toast(page)
                if toast_err:
                    return False, toast_err, curr_mouse
                return True, None, curr_mouse

            now = asyncio.get_running_loop().time()
            if now >= deadline:
                break

            wait_slice = min(0.35, max(0.05, deadline - now))
            try:
                await asyncio.wait_for(create_tweet_event.wait(), timeout=wait_slice)
            except asyncio.TimeoutError:
                pass

        toast_err = await _check_error_toast(page)
        if toast_err:
            return False, toast_err, curr_mouse
        return False, "Timed out waiting for X post confirmation (CreateTweet / composer close).", curr_mouse
    finally:
        if listener_attached and hasattr(page, "remove_listener"):
            try:
                page.remove_listener("response", _on_response)
            except Exception:
                pass


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
        if search_query and search_query.strip():
            encoded_query = urllib.parse.quote_plus(search_query.strip())
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
                full_text_check = await article.inner_text() or ""
                tweet_text, quoted_text = await _extract_main_and_quoted_text(article)
                if not tweet_text:
                    continue

                if await _is_promoted_article(article, full_text_check, tweet_text=tweet_text):
                    continue

                links = await article.query_selector_all('a[href*="/status/"]')
                tweet_id: Optional[str] = None
                tweet_url: Optional[str] = None
                for link in links:
                    href = (await link.get_attribute("href") or "").strip()
                    if href and "/status/" in href and not href.endswith("/analytics") and "/photo/" not in href:
                        match = re.search(r'/status/(\d+)', href)
                        if match:
                            cand_id = match.group(1)
                            if not cand_id.isdigit():
                                continue
                            cand_url = f"https://x.com{href}" if href.startswith("/") else href
                            try:
                                cand_url = validate_external_url(
                                    cand_url,
                                    allowed_hosts=ALLOWED_X_HOSTS,
                                    require_https=True,
                                )
                            except ValueError:
                                continue
                            tweet_id = cand_id
                            tweet_url = cand_url
                            break

                if not tweet_id or not tweet_id.isdigit():
                    continue

                # Extract image alt text and validated media URL (for Multimodal Vision AI)
                img_elems = await article.query_selector_all("img")
                img_alts: List[str] = []
                media_url: Optional[str] = None
                for img in img_elems:
                    src = (await img.get_attribute("src") or "").strip()
                    if not media_url and src:
                        try:
                            validated_media = validate_external_url(
                                src,
                                allowed_hosts=ALLOWED_MEDIA_HOSTS,
                                require_https=True,
                            )
                            parsed_media = urllib.parse.urlparse(validated_media)
                            if (parsed_media.path or "").startswith("/media/"):
                                media_url = validated_media
                        except ValueError:
                            pass
                    alt = (await img.get_attribute("alt") or "").strip()
                    if alt and alt.lower() not in ("image", "embedded video", "") and len(alt) > 4:
                        img_alts.append(alt)

                author = await _extract_author_handle(article)

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

                final_tweet_url = _validate_tweet_status_url(tweet_url, tweet_id)

                raw_candidates.append({
                    "tweet_id": tweet_id,
                    "author": author,
                    "text": tweet_text,
                    "url": final_tweet_url,
                    "media_url": media_url,
                    "metrics": metrics_str,
                    "engagement_score": int(likes + (replies * 2)),
                    "extra_context": " | ".join(extra_parts)
                })

            except Exception as item_err:
                logger.debug(f"Error parsing tweet element: {item_err}")
                continue

    except Exception as e:
        logger.error(f"Error during feed scraping: {e}", exc_info=True)

    raw_candidates.sort(
        key=lambda x: (int(x.get("engagement_score", 0)), len(x.get("text", "")) > 25, len(x.get("text", ""))),
        reverse=True,
    )
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
    Navigates to the tweet, locates the exact target tweet article in thread view,
    likes if directed, types reply with human variation, and confirms post delivery.
    Returns (success, error_message, updated_mouse_pos).
    """
    target_url = _validate_tweet_status_url(tweet_url, str(tweet_id))

    curr_mouse = mouse_pos
    try:
        logger.info(f"Opening post {tweet_id} ({target_url}) for natural biometric reply flow...")
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

        if "login" in (page.url or "") or "i/flow/login" in (page.url or ""):
            err = "Browser session is not logged into X (redirected to login)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.simulate_reading_dwell(
            page,
            text_length=max(100, len(reply_text)),
            current_mouse_pos=curr_mouse
        )

        target_article = await _find_target_tweet_article(page, str(tweet_id))

        do_like = should_like if should_like is not None else (random.random() < 0.35)
        if do_like and target_article:
            try:
                like_btn = await target_article.query_selector('[data-testid="like"]')
                if like_btn:
                    curr_mouse = await stealth.human_click(page, like_btn, curr_mouse)
                    logger.info(f"AI-directed Like executed on post {tweet_id} before replying.")
                    await stealth.human_delay(0.3, 0.6)
            except Exception:
                pass

        reply_input_selectors = [
            '[data-testid="tweetTextarea_0"]',
            'div[role="textbox"][data-testid="tweetTextarea_0"]',
            'div[role="textbox"][contenteditable="true"]',
            'div[contenteditable="true"]'
        ]

        input_box = None
        matched_selector: Optional[str] = None
        for selector in reply_input_selectors:
            input_box = await page.query_selector(selector)
            if input_box:
                matched_selector = selector
                break

        if not input_box and target_article:
            reply_btn = await target_article.query_selector('[data-testid="reply"]')
            if reply_btn:
                curr_mouse = await stealth.human_click(page, reply_btn, curr_mouse)
                await stealth.human_delay(0.3, 0.7)
                for selector in reply_input_selectors:
                    try:
                        input_box = await page.wait_for_selector(selector, state="visible", timeout=5000)
                    except Exception:
                        input_box = None
                    if input_box:
                        matched_selector = selector
                        break

        if not input_box or not matched_selector:
            err = "Could not find reply input box on the page."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.human_type(page, matched_selector, reply_text, curr_mouse)
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
                    disabled_flag = is_disabled is not None and is_disabled is not False
                    if not disabled_flag and aria_disabled != "true":
                        submit_btn = btn
                        break
            if submit_btn:
                break
            await asyncio.sleep(0.3)

        if not submit_btn:
            err = "Could not find active submit button (it may be disabled or missing)."
            logger.error(err)
            return False, err, curr_mouse

        ok, err, curr_mouse = await _submit_and_verify_tweet(
            page=page,
            submit_btn=submit_btn,
            curr_mouse=curr_mouse,
            composer_selector=matched_selector,
            submit_selectors=submit_selectors,
        )
        if ok:
            logger.info(f"Posted reply to tweet {tweet_id}")
        else:
            logger.error(f"Reply confirmation failed for tweet {tweet_id}: {err}")
        return ok, err, curr_mouse

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
    clean_post = (post_text or "").strip()
    if not clean_post:
        return False, "Post text cannot be empty.", mouse_pos

    curr_mouse = mouse_pos
    try:
        logger.info("Navigating to X home to compose original post...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)

        if "login" in (page.url or "") or "i/flow/login" in (page.url or ""):
            err = "Browser session is not logged into X (redirected to login)."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.simulate_reading_dwell(page, text_length=80, current_mouse_pos=curr_mouse)

        composer_selector = '[data-testid="tweetTextarea_0"]'
        try:
            box = await page.wait_for_selector(composer_selector, state="visible", timeout=5000)
        except Exception:
            box = None

        if not box:
            compose_btn = await page.query_selector('[data-testid="SideNav_NewTweet_Button"], a[href="/compose/post"]')
            if compose_btn:
                curr_mouse = await stealth.human_click(page, compose_btn, curr_mouse)
                await stealth.human_delay(0.3, 0.7)
            else:
                await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
                await stealth.human_delay(0.4, 0.8)

            try:
                box = await page.wait_for_selector(composer_selector, state="visible", timeout=15000)
            except Exception:
                box = None

        if not box:
            err = "Could not find post composer input box."
            logger.error(err)
            return False, err, curr_mouse

        curr_mouse = await stealth.human_type(page, composer_selector, clean_post, curr_mouse)
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
                    disabled_flag = is_dis is not None and is_dis is not False
                    if not disabled_flag and aria_dis != "true":
                        submit_btn = btn
                        break
            if submit_btn:
                break
            await asyncio.sleep(0.3)

        if not submit_btn:
            err = "Could not find active Post button (it may be disabled or missing)."
            logger.error(err)
            return False, err, curr_mouse

        ok, err, curr_mouse = await _submit_and_verify_tweet(
            page=page,
            submit_btn=submit_btn,
            curr_mouse=curr_mouse,
            composer_selector=composer_selector,
            submit_selectors=submit_selectors,
        )
        if ok:
            logger.info("Successfully published original post!")
        else:
            logger.error(f"Original post confirmation failed: {err}")
        return ok, err, curr_mouse

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
    posts = [p.strip() for p in re.split(r'\r?\n\s*---\s*\r?\n', thread_text or "") if p.strip()]
    if not posts:
        return False, "Thread text has no posts to publish.", mouse_pos
    if len(posts) == 1:
        return await post_original_action(page, posts[0], mouse_pos=mouse_pos)

    curr_mouse = mouse_pos
    try:
        logger.info(f"Composing {len(posts)}-post thread on X...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)

        if "login" in (page.url or "") or "i/flow/login" in (page.url or ""):
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

        first_box = await page.wait_for_selector('[data-testid="tweetTextarea_0"]', state="visible", timeout=15000)
        if not first_box:
            return False, "Could not find thread composer input box.", curr_mouse

        for idx, post_content in enumerate(posts):
            textarea_selector = f'[data-testid="tweetTextarea_{idx}"]'
            if idx > 0:
                slot = await page.wait_for_selector(textarea_selector, state="visible", timeout=10000)
                if not slot:
                    return False, f"Could not find thread input box #{idx + 1}.", curr_mouse

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
                    disabled_flag = is_dis is not None and is_dis is not False
                    if not disabled_flag and aria_dis != "true":
                        submit_btn = btn
                        break
            if submit_btn:
                break
            await asyncio.sleep(0.3)

        if not submit_btn:
            err = "Could not find active submit button for thread."
            logger.error(err)
            return False, err, curr_mouse

        ok, err, curr_mouse = await _submit_and_verify_tweet(
            page=page,
            submit_btn=submit_btn,
            curr_mouse=curr_mouse,
            composer_selector='[data-testid="tweetTextarea_0"]',
            submit_selectors=submit_selectors,
        )
        if ok:
            logger.info(f"Successfully published {len(posts)}-post thread!")
        else:
            logger.error(f"Thread confirmation failed: {err}")
        return ok, err, curr_mouse

    except Exception as e:
        err = str(e)
        logger.error(f"Failed to publish thread: {e}", exc_info=True)
        return False, err, curr_mouse
