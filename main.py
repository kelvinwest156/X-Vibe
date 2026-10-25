"""
X-VibeBot Monolith FastAPI Controller.
Coordinates the SQLite database, DeepSeek AI engine, Playwright browser worker,
and real-time web dashboard.
"""

import os
import sys
import time
import asyncio
import logging
from collections import deque
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from models import (
    Base,
    ProcessedTweet,
    AgentConfig,
    ProcessedTweetResponse,
    AgentConfigUpdate,
    AgentConfigResponse,
    AgentStatusResponse,
    ApproveDraftRequest,
    SystemLogEntry
)
from database import (
    init_db,
    get_db,
    is_tweet_already_processed,
    record_processed_tweet,
    update_tweet_status,
    get_daily_actions_count,
    get_pending_tweets,
    get_recent_tweets,
    get_agent_config,
    update_agent_config,
    SessionLocal
)
from ai_engine import evaluate_tweet, test_ai_api, KNOWN_GEMINI_MODELS
from browser_worker import XBrowserWorker
from pydantic import BaseModel

load_dotenv()

# ==============================================================================
# In-Memory Log Buffer for Live Dashboard Stream
# ==============================================================================

MAX_LOGS = 100
log_buffer = deque(maxlen=MAX_LOGS)

class DashboardLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            log_buffer.append({
                "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg
            })
        except Exception:
            pass

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s"))
dashboard_handler = DashboardLogHandler()
dashboard_handler.setFormatter(logging.Formatter("%(message)s"))
root_logger.addHandler(stream_handler)
root_logger.addHandler(dashboard_handler)

logger = logging.getLogger("x_vibebot.main")

# ==============================================================================
# Global Worker State & Locks
# ==============================================================================

HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
browser_worker = XBrowserWorker(headless=HEADLESS)

last_interaction_timestamp: float = 0.0  # Unix timestamp of last reply/post
is_session_logged_in: bool = False
is_manual_login_active: bool = False
bg_worker_task: Optional[asyncio.Task] = None
scrape_now_flag = asyncio.Event()


def get_cooldown_remaining(min_cooldown_minutes: int) -> int:
    """Returns seconds remaining before next action is permitted."""
    cooldown_seconds = min_cooldown_minutes * 60
    elapsed = time.time() - last_interaction_timestamp
    remaining = int(cooldown_seconds - elapsed)
    return max(0, remaining)


# ==============================================================================
# Autonomous Scraper & Execution Background Loop
# ==============================================================================

async def background_automation_loop():
    """
    Continuous background loop that monitors feeds, feeds tweets to DeepSeek,
    and submits replies safely based on auto-pilot or manual approval rules.
    """
    global last_interaction_timestamp, is_session_logged_in
    logger.info("Background automation worker loop initialized.")

    # Give the app a couple of seconds to boot
    await asyncio.sleep(3)

    while True:
        try:
            db = SessionLocal()
            try:
                config = get_agent_config(db)
                is_active = config.is_active
                auto_pilot = config.auto_pilot_mode
                interval_secs = max(1, config.polling_interval_minutes) * 60
                daily_cap = config.daily_action_cap
                min_cooldown = config.min_cooldown_minutes
                query = config.search_query
                selected_model = config.selected_model or "gemini-2.5-flash"
                daily_used = get_daily_actions_count(db)
            finally:
                db.close()

            # Wait condition: If bot is inactive, sleep until manually triggered or checked
            if not is_active:
                # Check for manual trigger or wait 5 seconds before re-reading config
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=5.0)
                    scrape_now_flag.clear()
                    logger.info("Manual scrape trigger activated while bot was paused.")
                except asyncio.TimeoutError:
                    continue
            else:
                # If active, check if manual trigger or wait for interval
                pass

            # Check if user is currently logging in via the headful Chromium window
            if is_manual_login_active:
                logger.info("Manual login session open. Background scanner waiting for user sign-in...")
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=15.0)
                    scrape_now_flag.clear()
                except asyncio.TimeoutError:
                    pass
                continue

            # Safety Rule 1: Daily Volume Cap
            if daily_used >= daily_cap:
                logger.warning(f"Daily action cap reached ({daily_used}/{daily_cap}). Pausing until tomorrow.")
                await asyncio.sleep(300)
                continue

            # Check X Login
            try:
                is_session_logged_in = await browser_worker.check_login_status()
            except Exception as e:
                logger.error(f"Failed to check login status: {e}")
                is_session_logged_in = False

            if not is_session_logged_in:
                logger.warning("Agent is not logged into X. Please click 'Browser Login' above to sign in manually.")
                # Wait 30 seconds before re-checking or wake immediately if user clicks Scrape Now
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=30.0)
                    scrape_now_flag.clear()
                except asyncio.TimeoutError:
                    pass
                continue

            logger.info(f"Starting feed scan with query: '{query}'...")
            tweets = await browser_worker.scrape_feed(search_query=query, limit=8)
            logger.info(f"Scraped {len(tweets)} tweets for evaluation.")

            for t in tweets:
                db = SessionLocal()
                try:
                    tweet_id = t["tweet_id"]
                    if is_tweet_already_processed(db, tweet_id):
                        continue

                    logger.info(f"Evaluating tweet {tweet_id} by @{t['author']} using {selected_model}: '{t['text'][:60]}...'")

                    # DeepSeek AI Evaluation
                    ai_result = await evaluate_tweet(t["text"], t["author"], model_name=selected_model)

                    if not ai_result["should_reply"]:
                        logger.info(f"DeepSeek skipped tweet {tweet_id}: {ai_result['reasoning']}")
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            generated_text=None,
                            status="skipped",
                            error_message=ai_result["reasoning"]
                        )
                        continue

                    # DeepSeek suggested a reply!
                    reply_text = ai_result["reply_text"]
                    logger.info(f"DeepSeek drafted reply: '{reply_text}'")

                    if not auto_pilot:
                        # Human-in-the-loop: Save as pending_approval
                        logger.info(f"Saving tweet {tweet_id} to manual approval queue.")
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            generated_text=reply_text,
                            status="pending_approval"
                        )
                    else:
                        # Full Autopilot Mode: Check cooldown before firing
                        cooldown_left = get_cooldown_remaining(min_cooldown)
                        if cooldown_left > 0:
                            logger.info(f"Auto-pilot waiting for cooldown ({cooldown_left}s remaining)...")
                            # Save as pending temporarily so it isn't lost
                            record_processed_tweet(
                                db=db,
                                tweet_id=tweet_id,
                                action_type="reply",
                                tweet_text=t["text"],
                                tweet_author=t["author"],
                                tweet_url=t["url"],
                                generated_text=reply_text,
                                status="pending_approval"
                            )
                            continue

                        # Execute posting immediately
                        logger.info(f"Auto-pilot posting reply to {tweet_id}...")
                        success = await browser_worker.post_reply(tweet_id, reply_text, t["url"])
                        if success:
                            last_interaction_timestamp = time.time()
                            record_processed_tweet(
                                db=db,
                                tweet_id=tweet_id,
                                action_type="reply",
                                tweet_text=t["text"],
                                tweet_author=t["author"],
                                tweet_url=t["url"],
                                generated_text=reply_text,
                                status="posted"
                            )
                            logger.info(f"Successfully auto-posted reply to tweet {tweet_id}!")
                        else:
                            record_processed_tweet(
                                db=db,
                                tweet_id=tweet_id,
                                action_type="reply",
                                tweet_text=t["text"],
                                tweet_author=t["author"],
                                tweet_url=t["url"],
                                generated_text=reply_text,
                                status="failed",
                                error_message="Playwright failed to post reply."
                            )

                finally:
                    db.close()

                # Stagger evaluations slightly
                await asyncio.sleep(2)

            # Wait for next interval or manual trigger
            try:
                await asyncio.wait_for(scrape_now_flag.wait(), timeout=interval_secs)
                scrape_now_flag.clear()
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            logger.error(f"Unexpected error in background worker loop: {e}", exc_info=True)
            await asyncio.sleep(15)


# ==============================================================================
# FastAPI Lifespan (Startup & Shutdown)
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite tables
    init_db()
    logger.info("SQLite database tables verified.")

    # Start background automation worker
    global bg_worker_task
    bg_worker_task = asyncio.create_task(background_automation_loop())

    yield

    # Teardown
    if bg_worker_task:
        bg_worker_task.cancel()
    await browser_worker.stop()
    logger.info("X-VibeBot shutdown complete.")


app = FastAPI(
    title="X-VibeBot Monolith Controller",
    description="Browser-Agent for X Automation with DeepSeek AI & Playwright",
    lifespan=lifespan
)

# Ensure static directory exists
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ==============================================================================
# Web Routes
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the single-page Tailwind control dashboard."""
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Static dashboard not found. Please verify static/index.html</h1>", status_code=404)


def update_env_variable(key: str, value: str):
    """Updates a key in the local .env file and environment."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    os.environ[key] = value


@app.get("/api/status", response_model=AgentStatusResponse)
async def get_status(db: Session = Depends(get_db)):
    """Returns the comprehensive run state for the UI."""
    config = get_agent_config(db)
    daily_used = get_daily_actions_count(db)
    cooldown_rem = get_cooldown_remaining(config.min_cooldown_minutes)
    pending_items = get_pending_tweets(db)
    total_processed = db.query(ProcessedTweet).count()

    return AgentStatusResponse(
        is_active=config.is_active,
        auto_pilot_mode=config.auto_pilot_mode,
        polling_interval_minutes=config.polling_interval_minutes,
        daily_action_cap=config.daily_action_cap,
        daily_actions_used=daily_used,
        cooldown_active=cooldown_rem > 0,
        cooldown_seconds_remaining=cooldown_rem,
        browser_connected=browser_worker.is_running,
        is_logged_in=is_session_logged_in,
        pending_approvals_count=len(pending_items),
        total_processed_count=total_processed,
        selected_model=config.selected_model or "gemini-2.5-flash",
        recent_logs=[
            SystemLogEntry(
                timestamp=entry["timestamp"],
                level=entry["level"],
                message=entry["message"]
            )
            for entry in list(log_buffer)[-25:]
        ]
    )


@app.get("/api/config", response_model=AgentConfigResponse)
async def get_config(db: Session = Depends(get_db)):
    """Returns current runtime agent configuration."""
    cfg = get_agent_config(db)
    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
    masked_key = (current_key[:4] + "..." + current_key[-4:]) if len(current_key) > 8 else ("***" if current_key else "")
    return AgentConfigResponse(
        id=cfg.id,
        is_active=cfg.is_active,
        auto_pilot_mode=cfg.auto_pilot_mode,
        polling_interval_minutes=cfg.polling_interval_minutes,
        daily_action_cap=cfg.daily_action_cap,
        min_cooldown_minutes=cfg.min_cooldown_minutes,
        search_query=cfg.search_query,
        selected_model=cfg.selected_model or "gemini-2.5-flash",
        masked_api_key=masked_key,
        updated_at=cfg.updated_at
    )


@app.post("/api/config", response_model=AgentConfigResponse)
async def update_config_endpoint(payload: AgentConfigUpdate, db: Session = Depends(get_db)):
    """Updates runtime agent toggles and AI settings."""
    if payload.api_key is not None and payload.api_key.strip():
        clean_key = payload.api_key.strip()
        if clean_key.startswith("sk-"):
            update_env_variable("DEEPSEEK_API_KEY", clean_key)
            logger.info("Updated DEEPSEEK_API_KEY in environment and .env")
        else:
            update_env_variable("GEMINI_API_KEY", clean_key)
            logger.info("Updated GEMINI_API_KEY in environment and .env")

    updates = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    updated = update_agent_config(db, updates)
    logger.info(f"Updated agent configuration: {updates}")

    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
    masked_key = (current_key[:4] + "..." + current_key[-4:]) if len(current_key) > 8 else ("***" if current_key else "")
    return AgentConfigResponse(
        id=updated.id,
        is_active=updated.is_active,
        auto_pilot_mode=updated.auto_pilot_mode,
        polling_interval_minutes=updated.polling_interval_minutes,
        daily_action_cap=updated.daily_action_cap,
        min_cooldown_minutes=updated.min_cooldown_minutes,
        search_query=updated.search_query,
        selected_model=updated.selected_model or "gemini-2.5-flash",
        masked_api_key=masked_key,
        updated_at=updated.updated_at
    )


class TestKeyPayload(BaseModel):
    api_key: Optional[str] = None


@app.get("/api/ai/models")
async def get_models_endpoint():
    """Returns available AI models and live connectivity status."""
    return await test_ai_api()


@app.post("/api/ai/test-key")
async def test_key_endpoint(payload: TestKeyPayload):
    """Tests a provided API key against the AI provider."""
    key = payload.api_key.strip() if payload.api_key else None
    return await test_ai_api(custom_key=key)


@app.get("/api/pending", response_model=List[ProcessedTweetResponse])
async def get_pending_approvals_endpoint(db: Session = Depends(get_db)):
    """Returns all tweets waiting for human approval."""
    return get_pending_tweets(db)


@app.get("/api/history", response_model=List[ProcessedTweetResponse])
async def get_history_endpoint(limit: int = 50, db: Session = Depends(get_db)):
    """Returns recent tweet interactions and audit log."""
    return get_recent_tweets(db, limit=limit)


@app.post("/api/approve/{tweet_id}")
async def approve_tweet(
    tweet_id: str,
    payload: Optional[ApproveDraftRequest] = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Approves a draft reply, triggers Playwright to type and submit it,
    and updates the database status.
    """
    global last_interaction_timestamp

    tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    config = get_agent_config(db)
    daily_used = get_daily_actions_count(db)
    if daily_used >= config.daily_action_cap:
        raise HTTPException(
            status_code=429,
            detail=f"Daily action cap ({config.daily_action_cap}) reached! Wait until tomorrow or increase cap."
        )

    # Use edited text if provided by user in UI
    text_to_post = payload.custom_text if (payload and payload.custom_text) else tweet.generated_text
    if not text_to_post:
        raise HTTPException(status_code=400, detail="Cannot post an empty reply.")

    logger.info(f"Manual approval received for tweet {tweet_id}. Dispatching browser worker...")

    # Execute posting via browser worker
    success = await browser_worker.post_reply(tweet_id, text_to_post, tweet.tweet_url)

    if success:
        last_interaction_timestamp = time.time()
        update_tweet_status(db, tweet_id, status="posted", generated_text=text_to_post)
        logger.info(f"Draft approved and successfully posted to tweet {tweet_id}!")
        return {"status": "posted", "tweet_id": tweet_id, "text": text_to_post}
    else:
        update_tweet_status(
            db,
            tweet_id,
            status="failed",
            generated_text=text_to_post,
            error_message="Playwright failed during post interaction"
        )
        raise HTTPException(status_code=500, detail="Failed to post reply via browser automation.")


@app.post("/api/reject/{tweet_id}")
async def reject_tweet(tweet_id: str, db: Session = Depends(get_db)):
    """Rejects/skips a pending draft."""
    tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    update_tweet_status(db, tweet_id, status="skipped", error_message="Rejected by user review")
    logger.info(f"User rejected draft for tweet {tweet_id}.")
    return {"status": "skipped", "tweet_id": tweet_id}


@app.post("/api/trigger-scrape")
async def trigger_scrape_now():
    """Wakes up the scraper immediately without waiting for interval."""
    global is_session_logged_in, is_manual_login_active
    is_manual_login_active = False

    if not is_session_logged_in:
        # Check login status directly
        is_session_logged_in = await browser_worker.check_login_status()

    if not is_session_logged_in:
        logger.warning("Scrape requested, but agent is not logged into X. Please use 'Browser Login' first.")
        return {
            "status": "not_logged_in",
            "message": "Cannot scan feed: Not logged into X! Please click 'Browser Login' to log in first."
        }

    scrape_now_flag.set()
    logger.info("Manual scrape cycle triggered. Scanning feed...")
    return {
        "status": "triggered",
        "message": "Scrape cycle started! Scanning target feed for tweets..."
    }


def is_on_default_desktop() -> bool:
    """Checks whether the process is attached to the interactive user desktop."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        tid = kernel32.GetCurrentThreadId()
        hDesk = user32.GetThreadDesktop(tid)
        buf = ctypes.create_string_buffer(256)
        needed = wintypes.DWORD()
        user32.GetUserObjectInformationA(hDesk, 2, buf, 256, ctypes.byref(needed))
        desk_name = buf.value.decode("ascii", errors="ignore")
        return desk_name.lower() == "default"
    except Exception:
        return True


@app.post("/api/browser/launch-login")
async def launch_headful_login():
    """
    Opens a headful Chromium window to x.com/login so the user can log in manually.
    Stores the cookies/session into ./x_browser_profile.
    """
    global is_manual_login_active
    try:
        is_manual_login_active = True
        logger.info("Opening Chromium window in headful mode for manual bootstrap login...")
        await browser_worker.open_headful_for_login()

        on_default = is_on_default_desktop()
        if not on_default:
            msg = (
                "Notice: Server is running in background sandbox. "
                "To see the browser window directly on your monitor, double-click 'login_browser.bat' in the project folder!"
            )
        else:
            msg = "Chromium window launched! Please log in to your X account on your desktop."

        return {
            "status": "browser_opened",
            "is_default_desktop": on_default,
            "message": msg
        }
    except Exception as e:
        is_manual_login_active = False
        logger.error(f"Failed to open Chromium browser: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to open browser: {str(e)}")


@app.post("/api/browser/check-session")
async def check_session():
    """Forces an active verification of the X login session."""
    global is_session_logged_in, is_manual_login_active
    is_manual_login_active = False
    is_session_logged_in = await browser_worker.check_login_status()
    return {"is_logged_in": is_session_logged_in}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
