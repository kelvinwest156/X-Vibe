"""
X-VibeBot Monolith FastAPI Controller.
Coordinates the SQLite database, Google Gemini AI engine, Playwright browser worker,
randomized human-like scheduling queue, and minimal web dashboard.
"""

import sys
import asyncio

# Critical fix for Windows: Playwright subprocesses require ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        import uvicorn.loops.asyncio
        uvicorn.loops.asyncio.asyncio_setup = lambda use_subprocess=False: None
    except Exception:
        pass

import os
import re
import time
import json
import random
import logging
from collections import deque
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel

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
    get_due_scheduled_tweets,
    get_scheduled_count,
    get_recent_tweets,
    get_agent_config,
    update_agent_config,
    is_within_active_hours,
    compute_random_schedule_time,
    SessionLocal
)
from ai_engine import evaluate_tweet, generate_original_content, test_ai_api, KNOWN_GEMINI_MODELS
from browser_worker import XBrowserWorker

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
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg
            })
        except Exception:
            pass


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
# Global Worker State
# ==============================================================================

HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
browser_worker = XBrowserWorker(headless=HEADLESS)

last_interaction_timestamp: float = 0.0
current_random_cooldown_seconds: int = 0
is_session_logged_in: bool = False
is_manual_login_active: bool = False
bg_worker_task: Optional[asyncio.Task] = None
scheduler_worker_task: Optional[asyncio.Task] = None
scrape_now_flag = asyncio.Event()


def get_cooldown_remaining() -> int:
    """Returns seconds remaining in the current randomized cooldown window."""
    if last_interaction_timestamp <= 0 or current_random_cooldown_seconds <= 0:
        return 0
    elapsed = time.time() - last_interaction_timestamp
    return max(0, int(current_random_cooldown_seconds - elapsed))


def set_new_random_cooldown(min_mins: int, max_mins: int):
    """Sets a randomized cooldown duration after a post to avoid robotic intervals."""
    global last_interaction_timestamp, current_random_cooldown_seconds
    last_interaction_timestamp = time.time()
    low = max(1, min_mins) * 60
    high = max(low + 60, max_mins * 60)
    current_random_cooldown_seconds = random.randint(low, high)


def sync_detected_username(db: Session):
    """Saves browser_worker.logged_in_username to AgentConfig if newly detected."""
    if browser_worker.logged_in_username:
        cfg = get_agent_config(db)
        if cfg.linked_username != browser_worker.logged_in_username:
            cfg.linked_username = browser_worker.logged_in_username
            db.commit()


# ==============================================================================
# Randomized Scheduled Queue Dispatcher Loop
# ==============================================================================

async def scheduled_queue_dispatcher_loop():
    """
    Continuously checks for scheduled replies whose randomized `scheduled_for`
    timestamp has arrived and dispatches them organically.
    """
    logger.info("Random schedule dispatcher initialized.")
    await asyncio.sleep(5)

    while True:
        try:
            if is_manual_login_active:
                await asyncio.sleep(10)
                continue

            db = SessionLocal()
            try:
                config = get_agent_config(db)
                within_hours = is_within_active_hours(
                    config.active_hours_start or 8,
                    config.active_hours_end or 23
                )
                daily_used = get_daily_actions_count(db)
                daily_cap = config.daily_action_cap or 15
                min_cd = config.min_cooldown_minutes or 10
                max_cd = config.max_cooldown_minutes or 45
                due_items = get_due_scheduled_tweets(db) if within_hours else []
            finally:
                db.close()

            if due_items and daily_used < daily_cap:
                target = due_items[0]
                act_type = target.action_type or "reply"
                logger.info(f"Scheduled time reached for {act_type} ({target.tweet_id}). Publishing now...")
                success = await browser_worker.execute_tweet_action(
                    act_type,
                    target.tweet_id,
                    target.generated_text,
                    target.tweet_url
                )
                db = SessionLocal()
                try:
                    sync_detected_username(db)
                    if success:
                        set_new_random_cooldown(min_cd, max_cd)
                        update_tweet_status(db, target.tweet_id, status="posted")
                        logger.info(f"Successfully published scheduled {act_type} ({target.tweet_id})!")
                    else:
                        update_tweet_status(
                            db,
                            target.tweet_id,
                            status="failed",
                            error_message=f"Browser failed while publishing scheduled {act_type}"
                        )
                finally:
                    db.close()

            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error in scheduled dispatcher loop: {e}")
            await asyncio.sleep(15)


# ==============================================================================
# Autonomous Scraper & Evaluation Background Loop
# ==============================================================================

async def background_automation_loop():
    """
    Continuous background loop with randomized jitter, active hours sleep window,
    and automatic random scheduling when Autopilot is enabled.
    """
    global is_session_logged_in
    logger.info("Background automation worker loop initialized.")
    await asyncio.sleep(3)

    while True:
        try:
            db = SessionLocal()
            try:
                config = get_agent_config(db)
                is_active = config.is_active
                auto_pilot = config.auto_pilot_mode
                base_interval_secs = max(1, config.polling_interval_minutes) * 60
                daily_cap = config.daily_action_cap
                query = config.search_query
                persona = config.persona_prompt
                selected_model = config.selected_model or "gemini-3.8-flash"
                start_hr = config.active_hours_start if config.active_hours_start is not None else 8
                end_hr = config.active_hours_end if config.active_hours_end is not None else 23
                daily_used = get_daily_actions_count(db)
            finally:
                db.close()

            manual_triggered = scrape_now_flag.is_set()

            if not is_active and not manual_triggered:
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=5.0)
                    logger.info("Manual scrape triggered.")
                except asyncio.TimeoutError:
                    continue

            if is_manual_login_active and not scrape_now_flag.is_set():
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    pass
                continue

            # Respect Active Waking Hours (unless user explicitly clicked Scrape Now)
            if not scrape_now_flag.is_set() and not is_within_active_hours(start_hr, end_hr):
                logger.info(f"Outside active hours ({start_hr:02d}:00-{end_hr:02d}:00). Sleeping...")
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    pass
                continue

            if daily_used >= daily_cap and not scrape_now_flag.is_set():
                logger.warning(f"Daily action cap reached ({daily_used}/{daily_cap}). Pausing until tomorrow.")
                await asyncio.sleep(300)
                continue

            # Verify X Login
            try:
                is_session_logged_in = await browser_worker.check_login_status()
                if is_session_logged_in:
                    db = SessionLocal()
                    try:
                        sync_detected_username(db)
                    finally:
                        db.close()
            except Exception as e:
                logger.error(f"Failed to check login status: {e}")
                is_session_logged_in = False

            if not is_session_logged_in:
                scrape_now_flag.clear()
                logger.warning("Not logged into X. Use 'Login' in the top bar or run login_browser.bat.")
                try:
                    await asyncio.wait_for(scrape_now_flag.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass
                continue

            # Consume manual scrape trigger right as scan starts
            scrape_now_flag.clear()
            logger.info(f"Scanning X feed for '{query}'...")
            tweets = await browser_worker.scrape_feed(search_query=query, limit=8)
            logger.info(f"Collected {len(tweets)} candidate posts.")

            db = SessionLocal()
            try:
                sync_detected_username(db)
            finally:
                db.close()

            new_count = 0
            for t in tweets:
                tweet_id = t["tweet_id"]

                db = SessionLocal()
                try:
                    already_done = is_tweet_already_processed(db, tweet_id)
                finally:
                    db.close()

                if already_done:
                    continue

                new_count += 1
                logger.info(f"Evaluating @{t['author']} ({t.get('metrics', '')}): '{t['text'][:55]}...'")

                ai_result = await evaluate_tweet(
                    tweet_text=t["text"],
                    tweet_author=t["author"],
                    model_name=selected_model,
                    search_query=query,
                    persona_prompt=persona,
                    extra_context=t.get("extra_context")
                )

                if ai_result.get("raw_response") == "NO_API_KEY":
                    logger.warning("Paused: Paste your Google Gemini API key in the sidebar first.")
                    break

                db = SessionLocal()
                try:
                    if not ai_result["should_reply"]:
                        logger.info(f"Skipped @{t['author']}: {ai_result['reasoning']}")
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            generated_text=None,
                            variants_json=None,
                            tweet_metrics=t.get("metrics"),
                            status="skipped",
                            error_message=ai_result["reasoning"]
                        )
                        continue

                    reply_text = ai_result["reply_text"]
                    variants_json = ai_result.get("variants_json")
                    logger.info(f"Drafted for @{t['author']}: '{reply_text}'")

                    if not auto_pilot:
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            generated_text=reply_text,
                            variants_json=variants_json,
                            tweet_metrics=t.get("metrics"),
                            status="pending_approval",
                            error_message=ai_result["reasoning"]
                        )
                    else:
                        # Autopilot schedules replies at completely random future timestamps
                        cfg = get_agent_config(db)
                        sched_utc = compute_random_schedule_time(db, cfg)
                        mins_away = max(1, int((sched_utc - datetime.utcnow()).total_seconds() // 60))
                        logger.info(f"Autopilot scheduled reply to @{t['author']} in ~{mins_away}m (random time).")
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            generated_text=reply_text,
                            variants_json=variants_json,
                            tweet_metrics=t.get("metrics"),
                            status="scheduled",
                            scheduled_for=sched_utc,
                            error_message=ai_result["reasoning"]
                        )
                finally:
                    db.close()

                await asyncio.sleep(random.uniform(1.2, 2.5))

            if new_count == 0 and len(tweets) > 0:
                logger.info(f"All {len(tweets)} visible posts for '{query}' were already evaluated.")

            # Also synthesize 1 original Post or Thread from the live conversation pulse
            if len(tweets) >= 2:
                orig_mode = random.choice(["post", "thread"])
                logger.info(f"Synthesizing original {orig_mode} from live '{query}' conversation & real-time info...")
                gen = await generate_original_content(
                    mode=orig_mode,
                    search_query=query,
                    persona_prompt=persona,
                    live_tweets=tweets,
                    model_name=selected_model
                )
                if gen.get("success") and gen.get("text"):
                    db = SessionLocal()
                    try:
                        cfg = get_agent_config(db)
                        orig_id = f"{orig_mode}_{int(time.time())}"
                        author_label = (browser_worker.logged_in_username or cfg.linked_username or "you").lstrip("@")
                        if auto_pilot:
                            sched_utc = compute_random_schedule_time(db, cfg)
                            record_processed_tweet(
                                db=db,
                                tweet_id=orig_id,
                                action_type=orig_mode,
                                tweet_text=gen["topic_summary"],
                                tweet_author=author_label,
                                tweet_url="https://x.com/home",
                                generated_text=gen["text"],
                                variants_json=gen.get("variants_json"),
                                tweet_metrics="Live Pulse · OriginalThread" if orig_mode == "thread" else "Live Pulse · Original Post",
                                status="scheduled",
                                scheduled_for=sched_utc,
                                error_message=gen["topic_summary"]
                            )
                        else:
                            record_processed_tweet(
                                db=db,
                                tweet_id=orig_id,
                                action_type=orig_mode,
                                tweet_text=gen["topic_summary"],
                                tweet_author=author_label,
                                tweet_url="https://x.com/home",
                                generated_text=gen["text"],
                                variants_json=gen.get("variants_json"),
                                tweet_metrics="Live Pulse · Thread" if orig_mode == "thread" else "Live Pulse · Original Post",
                                status="pending_approval",
                                error_message=gen["topic_summary"]
                            )
                        logger.info(f"Drafted original {orig_mode} from live conversation pulse.")
                    finally:
                        db.close()

            # Randomized jitter between scans (0.65x to 1.45x of polling interval + random seconds)
            jittered_wait = int(base_interval_secs * random.uniform(0.65, 1.45)) + random.randint(3, 58)
            try:
                await asyncio.wait_for(scrape_now_flag.wait(), timeout=jittered_wait)
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            logger.error(f"Unexpected error in background worker loop: {e}", exc_info=True)
            await asyncio.sleep(15)


# ==============================================================================
# FastAPI Lifespan & App Initialization
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bg_worker_task, scheduler_worker_task
    init_db()
    logger.info("Database verified.")
    bg_worker_task = asyncio.create_task(background_automation_loop())
    scheduler_worker_task = asyncio.create_task(scheduled_queue_dispatcher_loop())
    yield
    logger.info("Shutting down X-VibeBot...")
    for task in (bg_worker_task, scheduler_worker_task):
        if task:
            task.cancel()
    await browser_worker.stop()


app = FastAPI(
    title="X-VibeBot",
    description="Minimal AI Browser-Agent for X (Twitter)",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

NEXT_OUT_DIR = os.path.join(os.path.dirname(__file__), "frontend", "out")
if os.path.isdir(os.path.join(NEXT_OUT_DIR, "_next")):
    app.mount("/_next", StaticFiles(directory=os.path.join(NEXT_OUT_DIR, "_next")), name="next_assets")
elif os.path.isdir(os.path.join("static", "_next")):
    app.mount("/_next", StaticFiles(directory=os.path.join("static", "_next")), name="next_static_assets")


# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    next_index = os.path.join(NEXT_OUT_DIR, "index.html")
    if os.path.exists(next_index):
        return FileResponse(next_index)
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Static dashboard not found.</h1>", status_code=404)


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
    config = get_agent_config(db)
    if browser_worker.logged_in_username and config.linked_username != browser_worker.logged_in_username:
        config.linked_username = browser_worker.logged_in_username
        db.commit()

    daily_used = get_daily_actions_count(db)
    cooldown_rem = get_cooldown_remaining()
    pending_items = get_pending_tweets(db)
    sched_count = get_scheduled_count(db)
    total_processed = db.query(ProcessedTweet).count()
    within_hours = is_within_active_hours(
        config.active_hours_start if config.active_hours_start is not None else 8,
        config.active_hours_end if config.active_hours_end is not None else 23
    )

    has_profile_cookies = (
        os.path.isfile(browser_worker.cookies_backup_path)
        or os.path.isfile(os.path.join(browser_worker.profile_dir, "Default", "Network", "Cookies"))
        or os.path.isfile(os.path.join(browser_worker.profile_dir, "Default", "Cookies"))
    )

    return AgentStatusResponse(
        is_active=config.is_active,
        auto_pilot_mode=config.auto_pilot_mode,
        polling_interval_minutes=config.polling_interval_minutes,
        daily_action_cap=config.daily_action_cap,
        daily_actions_used=daily_used,
        cooldown_active=cooldown_rem > 0,
        cooldown_seconds_remaining=cooldown_rem,
        within_active_hours=within_hours,
        scheduled_count=sched_count,
        browser_connected=browser_worker.is_running,
        is_logged_in=is_session_logged_in or bool(config.linked_username) or has_profile_cookies,
        linked_username=browser_worker.logged_in_username or config.linked_username,
        pending_approvals_count=len(pending_items),
        total_processed_count=total_processed,
        selected_model=config.selected_model or "gemini-3.8-flash",
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
    cfg = get_agent_config(db)
    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    masked_key = (current_key[:4] + "..." + current_key[-4:]) if len(current_key) > 8 else ("***" if current_key else "")
    return AgentConfigResponse(
        id=cfg.id,
        is_active=cfg.is_active,
        auto_pilot_mode=cfg.auto_pilot_mode,
        polling_interval_minutes=cfg.polling_interval_minutes,
        daily_action_cap=cfg.daily_action_cap,
        min_cooldown_minutes=cfg.min_cooldown_minutes or 10,
        max_cooldown_minutes=cfg.max_cooldown_minutes or 45,
        active_hours_start=cfg.active_hours_start if cfg.active_hours_start is not None else 8,
        active_hours_end=cfg.active_hours_end if cfg.active_hours_end is not None else 23,
        search_query=cfg.search_query,
        persona_prompt=cfg.persona_prompt or "",
        selected_model=cfg.selected_model or "gemini-3.8-flash",
        linked_username=browser_worker.logged_in_username or cfg.linked_username,
        masked_api_key=masked_key,
        updated_at=cfg.updated_at
    )


@app.post("/api/config", response_model=AgentConfigResponse)
async def update_config_endpoint(payload: AgentConfigUpdate, db: Session = Depends(get_db)):
    if payload.api_key is not None and payload.api_key.strip():
        clean_key = payload.api_key.strip()
        if clean_key.startswith("sk-"):
            update_env_variable("DEEPSEEK_API_KEY", clean_key)
        else:
            update_env_variable("GEMINI_API_KEY", clean_key)

    updates = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    updated = update_agent_config(db, updates)
    logger.info("Settings updated.")

    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    masked_key = (current_key[:4] + "..." + current_key[-4:]) if len(current_key) > 8 else ("***" if current_key else "")
    return AgentConfigResponse(
        id=updated.id,
        is_active=updated.is_active,
        auto_pilot_mode=updated.auto_pilot_mode,
        polling_interval_minutes=updated.polling_interval_minutes,
        daily_action_cap=updated.daily_action_cap,
        min_cooldown_minutes=updated.min_cooldown_minutes or 10,
        max_cooldown_minutes=updated.max_cooldown_minutes or 45,
        active_hours_start=updated.active_hours_start if updated.active_hours_start is not None else 8,
        active_hours_end=updated.active_hours_end if updated.active_hours_end is not None else 23,
        search_query=updated.search_query,
        persona_prompt=updated.persona_prompt or "",
        selected_model=updated.selected_model or "gemini-3.8-flash",
        linked_username=browser_worker.logged_in_username or updated.linked_username,
        masked_api_key=masked_key,
        updated_at=updated.updated_at
    )


class TestKeyPayload(BaseModel):
    api_key: Optional[str] = None


@app.get("/api/ai/models")
async def get_models_endpoint():
    return await test_ai_api()


@app.post("/api/ai/test-key")
async def test_key_endpoint(payload: TestKeyPayload, db: Session = Depends(get_db)):
    key = payload.api_key.strip() if payload.api_key else None
    result = await test_ai_api(custom_key=key)
    if result.get("success") and key:
        if key.startswith("sk-"):
            update_env_variable("DEEPSEEK_API_KEY", key)
        else:
            update_env_variable("GEMINI_API_KEY", key)
            models = result.get("models") or []
            if models:
                update_agent_config(db, {"selected_model": models[0]["id"]})
    return result


@app.get("/api/pending", response_model=List[ProcessedTweetResponse])
async def get_pending_approvals_endpoint(db: Session = Depends(get_db)):
    return get_pending_tweets(db)


@app.get("/api/history", response_model=List[ProcessedTweetResponse])
async def get_history_endpoint(limit: int = 50, db: Session = Depends(get_db)):
    return get_recent_tweets(db, limit=limit)


def _parse_metric_numbers(metrics_str: Optional[str]) -> Dict[str, int]:
    """Extracts likes and replies integer counts from strings like '24 likes · 5 replies'."""
    if not metrics_str:
        return {"likes": 0, "replies": 0}
    likes = 0
    replies = 0
    m_likes = re.search(r"([\d\.]+)([KkMm]?)\s*like", metrics_str, re.IGNORECASE)
    if m_likes:
        val = float(m_likes.group(1))
        mult = 1000 if m_likes.group(2).upper() == "K" else (1000000 if m_likes.group(2).upper() == "M" else 1)
        likes = int(val * mult)
    m_rep = re.search(r"([\d\.]+)([KkMm]?)\s*repl", metrics_str, re.IGNORECASE)
    if m_rep:
        val = float(m_rep.group(1))
        mult = 1000 if m_rep.group(2).upper() == "K" else (1000000 if m_rep.group(2).upper() == "M" else 1)
        replies = int(val * mult)
    return {"likes": likes, "replies": replies}


@app.get("/api/analytics")
async def get_analytics_endpoint(db: Session = Depends(get_db)):
    """
    Computes rich Power-BI style analytics on posts, replies, threads,
    target feed engagement, hourly velocity, and author leaderboards.
    """
    all_rows = db.query(ProcessedTweet).order_by(ProcessedTweet.timestamp.desc()).all()
    cfg = get_agent_config(db)

    total = len(all_rows)
    posted = sum(1 for r in all_rows if r.status == "posted")
    scheduled = sum(1 for r in all_rows if r.status == "scheduled")
    pending = sum(1 for r in all_rows if r.status == "pending_approval")
    skipped = sum(1 for r in all_rows if r.status == "skipped")
    failed = sum(1 for r in all_rows if r.status == "failed")

    replies_cnt = sum(1 for r in all_rows if (r.action_type or "reply") == "reply")
    posts_cnt = sum(1 for r in all_rows if r.action_type == "post")
    threads_cnt = sum(1 for r in all_rows if r.action_type == "thread")

    actionable = posted + scheduled + pending
    approval_rate = round((actionable / total) * 100, 1) if total > 0 else 0.0

    total_likes = 0
    total_replies = 0
    char_lengths = []
    short_cnt = 0
    med_cnt = 0
    long_cnt = 0

    author_map: Dict[str, Dict[str, Any]] = {}
    hour_buckets: Dict[str, Dict[str, int]] = {}

    now = datetime.utcnow()
    for i in range(11, -1, -1):
        slot_dt = now - timedelta(hours=i * 2)
        label = slot_dt.strftime("%H:00")
        hour_buckets[label] = {"evaluated": 0, "drafted": 0, "engagement": 0}

    bucket_keys = list(hour_buckets.keys())

    for idx, r in enumerate(all_rows):
        parsed = _parse_metric_numbers(r.tweet_metrics)
        # Only real scraped numbers are counted; items without metrics contribute zero.
        likes_val = parsed["likes"]
        replies_val = parsed["replies"]
        total_likes += likes_val
        total_replies += replies_val

        if r.generated_text:
            clen = len(r.generated_text.strip())
            char_lengths.append(clen)
            if clen < 95:
                short_cnt += 1
            elif clen <= 185:
                med_cnt += 1
            else:
                long_cnt += 1

        handle = (r.tweet_author or "unknown").lstrip("@")
        if handle not in author_map:
            author_map[handle] = {
                "author": f"@{handle}",
                "interactions": 0,
                "likes": 0,
                "replies": 0,
                "score": 0,
                "last_type": r.action_type or "reply",
                "status": r.status
            }
        author_map[handle]["interactions"] += 1
        author_map[handle]["likes"] += likes_val
        author_map[handle]["replies"] += replies_val
        author_map[handle]["score"] += likes_val + (replies_val * 3)

        if r.timestamp:
            b_key = r.timestamp.strftime("%H:00")
            if b_key not in hour_buckets and bucket_keys:
                b_key = bucket_keys[idx % len(bucket_keys)]
            if b_key in hour_buckets:
                hour_buckets[b_key]["evaluated"] += 1
                if r.status in ("posted", "scheduled", "pending_approval"):
                    hour_buckets[b_key]["drafted"] += 1
                hour_buckets[b_key]["engagement"] += likes_val + replies_val

    avg_len = int(sum(char_lengths) / len(char_lengths)) if char_lengths else 112
    top_authors = sorted(author_map.values(), key=lambda x: x["score"], reverse=True)[:6]

    timeline = [
        {
            "time": k,
            "evaluated": v["evaluated"],
            "drafted": v["drafted"],
            "engagement": v["engagement"]
        }
        for k, v in hour_buckets.items()
    ]

    return {
        "kpis": {
            "total_evaluated": total,
            "published_count": posted,
            "scheduled_count": scheduled,
            "pending_count": pending,
            "skipped_count": skipped,
            "failed_count": failed,
            "approval_rate": approval_rate,
            "feed_likes_captured": total_likes,
            "feed_replies_captured": total_replies,
            "avg_engagement_score": round((total_likes + total_replies * 2) / max(1, total), 1),
            "avg_draft_length": avg_len,
            "daily_used": get_daily_actions_count(db),
            "daily_cap": cfg.daily_action_cap
        },
        "content_mix": [
            {"label": "Smart Replies", "key": "reply", "count": replies_cnt, "color": "#38BDF8"},
            {"label": "Original Posts", "key": "post", "count": posts_cnt, "color": "#34D399"},
            {"label": "Multi-Post Threads", "key": "thread", "count": threads_cnt, "color": "#A78BFA"}
        ],
        "status_funnel": [
            {"label": "Published", "count": posted, "color": "#34D399"},
            {"label": "Scheduled (Random)", "count": scheduled, "color": "#38BDF8"},
            {"label": "In Review Queue", "count": pending, "color": "#FBBF24"},
            {"label": "AI Filtered / Skipped", "count": skipped, "color": "#64748B"}
        ],
        "length_distribution": [
            {"label": "Punchy (<95c)", "count": short_cnt, "color": "#38BDF8"},
            {"label": "Conversational (95-185c)", "count": med_cnt, "color": "#818CF8"},
            {"label": "Deep Thread (>185c)", "count": long_cnt, "color": "#C084FC"}
        ],
        "timeline": timeline,
        "top_authors": top_authors
    }


@app.post("/api/approve/{tweet_id}")
async def approve_tweet(
    tweet_id: str,
    payload: Optional[ApproveDraftRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Approves a draft reply.
    - If payload.schedule_random is True: schedules it for a completely random future time.
    - Otherwise: dispatches Playwright to post it immediately.
    """
    tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    config = get_agent_config(db)
    daily_used = get_daily_actions_count(db)
    if daily_used >= config.daily_action_cap:
        raise HTTPException(
            status_code=429,
            detail=f"Daily action cap ({config.daily_action_cap}) reached!"
        )

    text_to_post = payload.custom_text.strip() if (payload and payload.custom_text) else tweet.generated_text
    if not text_to_post:
        raise HTTPException(status_code=400, detail="Cannot post an empty reply.")

    if payload and payload.schedule_random:
        sched_utc = compute_random_schedule_time(db, config)
        update_tweet_status(
            db,
            tweet_id,
            status="scheduled",
            generated_text=text_to_post,
            scheduled_for=sched_utc
        )
        mins_away = max(1, int((sched_utc - datetime.utcnow()).total_seconds() // 60))
        logger.info(f"Scheduled reply to @{tweet.tweet_author} for random time (~{mins_away}m from now).")
        return {
            "status": "scheduled",
            "tweet_id": tweet_id,
            "scheduled_for": sched_utc.isoformat(),
            "minutes_from_now": mins_away
        }

    act_type = tweet.action_type or "reply"
    logger.info(f"Publishing approved {act_type} ({tweet_id})...")
    success = await browser_worker.execute_tweet_action(act_type, tweet_id, text_to_post, tweet.tweet_url)
    sync_detected_username(db)

    if success:
        set_new_random_cooldown(config.min_cooldown_minutes or 10, config.max_cooldown_minutes or 45)
        update_tweet_status(db, tweet_id, status="posted", generated_text=text_to_post)
        logger.info(f"Successfully published {act_type} ({tweet_id})!")
        return {"status": "posted", "tweet_id": tweet_id, "text": text_to_post}
    else:
        update_tweet_status(
            db,
            tweet_id,
            status="failed",
            generated_text=text_to_post,
            error_message=f"Browser failed during {act_type} submission"
        )
        raise HTTPException(status_code=500, detail=f"Failed to publish {act_type} via browser.")


class GenerateOriginalPayload(BaseModel):
    mode: str = "post"  # "post" or "thread"
    custom_topic: Optional[str] = None


@app.post("/api/generate-original")
async def generate_original_endpoint(payload: GenerateOriginalPayload, db: Session = Depends(get_db)):
    """
    Generates a fresh Original Post or Multi-Post Thread from real-time conversations
    and current Google Search information, adding it directly to the Queue.
    """
    cfg = get_agent_config(db)
    mode = "thread" if payload.mode == "thread" else "post"
    topic = (payload.custom_topic or cfg.search_query or "tech & culture").strip()

    recent_db_tweets = get_recent_tweets(db, limit=10)
    live_context = [
        {
            "author": r.tweet_author,
            "text": r.tweet_text,
            "metrics": r.tweet_metrics
        }
        for r in recent_db_tweets
        if r.action_type == "reply" and r.tweet_text
    ]

    gen = await generate_original_content(
        mode=mode,
        search_query=topic,
        persona_prompt=cfg.persona_prompt,
        live_tweets=live_context,
        model_name=cfg.selected_model or "gemini-3.8-flash"
    )
    if not gen.get("success") or not gen.get("text"):
        raise HTTPException(status_code=500, detail=gen.get("topic_summary") or "Failed to generate content")

    orig_id = f"{mode}_{int(time.time() * 1000)}"
    author_label = (browser_worker.logged_in_username or cfg.linked_username or "you").lstrip("@")
    item = record_processed_tweet(
        db=db,
        tweet_id=orig_id,
        action_type=mode,
        tweet_text=gen["topic_summary"],
        tweet_author=author_label,
        tweet_url="https://x.com/home",
        generated_text=gen["text"],
        variants_json=gen.get("variants_json"),
        tweet_metrics="Original Thread" if mode == "thread" else "Original Post",
        status="pending_approval",
        error_message=gen["topic_summary"]
    )
    logger.info(f"Generated new {mode} on '{topic}'")
    return {"status": "created", "tweet_id": item.tweet_id, "action_type": mode}


@app.post("/api/regenerate/{tweet_id}")
async def regenerate_tweet_draft(tweet_id: str, db: Session = Depends(get_db)):
    """Regenerates 3 fresh anti-robotic variants for a reply, original post, or thread."""
    tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    cfg = get_agent_config(db)
    if tweet.action_type in ("post", "thread"):
        recent_db_tweets = get_recent_tweets(db, limit=8)
        live_context = [
            {"author": r.tweet_author, "text": r.tweet_text, "metrics": r.tweet_metrics}
            for r in recent_db_tweets if r.action_type == "reply" and r.tweet_text
        ]
        gen = await generate_original_content(
            mode=tweet.action_type,
            search_query=cfg.search_query,
            persona_prompt=(cfg.persona_prompt or "") + " | Take a completely fresh, different angle.",
            live_tweets=live_context,
            model_name=cfg.selected_model or "gemini-3.8-flash"
        )
        if not gen.get("success") or not gen.get("text"):
            raise HTTPException(status_code=500, detail="Failed to regenerate")
        updated = update_tweet_status(
            db,
            tweet_id,
            status="pending_approval",
            generated_text=gen["text"],
            variants_json=gen.get("variants_json"),
            error_message=gen.get("topic_summary")
        )
        return {
            "tweet_id": tweet_id,
            "generated_text": updated.generated_text,
            "variants_json": updated.variants_json
        }

    ai_result = await evaluate_tweet(
        tweet_text=tweet.tweet_text or "",
        tweet_author=tweet.tweet_author,
        model_name=cfg.selected_model or "gemini-3.8-flash",
        search_query=cfg.search_query,
        persona_prompt=(cfg.persona_prompt or "") + " | Write a completely fresh, different angle.",
        extra_context=f"Engagement: {tweet.tweet_metrics or ''}",
        temperature=0.9
    )

    if not ai_result.get("reply_text"):
        raise HTTPException(status_code=500, detail=ai_result.get("reasoning") or "Failed to regenerate draft")

    updated = update_tweet_status(
        db,
        tweet_id,
        status="pending_approval",
        generated_text=ai_result["reply_text"],
        variants_json=ai_result.get("variants_json"),
        error_message=ai_result.get("reasoning")
    )
    logger.info(f"Regenerated fresh variants for @{tweet.tweet_author}")
    return {
        "tweet_id": tweet_id,
        "generated_text": updated.generated_text,
        "variants_json": updated.variants_json
    }


@app.post("/api/reject/{tweet_id}")
async def reject_tweet(tweet_id: str, db: Session = Depends(get_db)):
    tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    update_tweet_status(db, tweet_id, status="skipped", error_message="Skipped by user")
    return {"status": "skipped", "tweet_id": tweet_id}


@app.post("/api/trigger-scrape")
async def trigger_scrape_now(db: Session = Depends(get_db)):
    global is_session_logged_in, is_manual_login_active
    is_manual_login_active = False

    has_key = bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())
    if not has_key:
        return {
            "status": "missing_api_key",
            "message": "Paste your Google Gemini API key in the sidebar first!"
        }

    if not is_session_logged_in:
        is_session_logged_in = await browser_worker.check_login_status()
        if is_session_logged_in:
            sync_detected_username(db)

    if not is_session_logged_in:
        return {
            "status": "not_logged_in",
            "message": "Not logged into X! Click 'Login' or run login_browser.bat."
        }

    scrape_now_flag.set()
    logger.info("Manual feed scan started.")
    return {
        "status": "triggered",
        "message": "Scanning feed & generating drafts..."
    }


def is_on_default_desktop() -> bool:
    if os.name != "nt":
        return False
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
    global is_manual_login_active
    try:
        is_manual_login_active = True
        await browser_worker.open_headful_for_login()
        on_default = is_on_default_desktop()
        msg = (
            "Browser window opened! Sign into X on your desktop."
            if on_default else
            "Run 'login_browser.bat' in your project folder (or import cookies for cloud deploy)."
        )
        return {
            "status": "browser_opened",
            "is_default_desktop": on_default,
            "message": msg
        }
    except Exception as e:
        is_manual_login_active = False
        raise HTTPException(status_code=500, detail=f"Failed to open browser: {str(e)}")


@app.post("/api/browser/release")
async def release_browser_profile():
    global is_manual_login_active
    is_manual_login_active = True
    await browser_worker.stop()
    return {"status": "released"}


@app.post("/api/browser/check-session")
async def check_session(db: Session = Depends(get_db)):
    global is_session_logged_in, is_manual_login_active
    is_manual_login_active = False
    is_session_logged_in = await browser_worker.check_login_status()
    if is_session_logged_in:
        sync_detected_username(db)
    cfg = get_agent_config(db)
    return {
        "is_logged_in": is_session_logged_in,
        "linked_username": browser_worker.logged_in_username or cfg.linked_username
    }


class CookiesImportPayload(BaseModel):
    cookies: List[Dict[str, Any]]


@app.get("/api/browser/cookies")
async def export_cookies_endpoint():
    """Exports session cookies as JSON so they can be imported onto a cloud instance (Render)."""
    cookies = await browser_worker.export_cookies()
    return JSONResponse(content={"cookies": cookies, "count": len(cookies)})


@app.post("/api/browser/cookies")
async def import_cookies_endpoint(payload: CookiesImportPayload, db: Session = Depends(get_db)):
    """Imports session cookies on a headless cloud instance (Render) and verifies login."""
    global is_session_logged_in
    is_session_logged_in = await browser_worker.import_cookies(payload.cookies)
    if is_session_logged_in:
        sync_detected_username(db)
    cfg = get_agent_config(db)
    return {
        "is_logged_in": is_session_logged_in,
        "linked_username": browser_worker.logged_in_username or cfg.linked_username
    }


if __name__ == "__main__":
    import uvicorn
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            import uvicorn.loops.asyncio
            uvicorn.loops.asyncio.asyncio_setup = lambda use_subprocess=False: None
        except Exception:
            pass
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
