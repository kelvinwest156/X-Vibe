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
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel

from models import (
    Base,
    ProcessedTweet,
    AgentConfig,
    User,
    ProcessedTweetResponse,
    AgentConfigUpdate,
    AgentConfigResponse,
    AgentStatusResponse,
    ApproveDraftRequest,
    SystemLogEntry,
    SignUpRequest,
    SignInRequest,
    UserResponse,
    AuthResponse
)
from database import (
    init_db,
    get_db,
    is_tweet_already_processed,
    record_processed_tweet,
    update_tweet_status,
    get_daily_actions_count,
    get_hourly_actions_count,
    get_learning_memory,
    is_reply_too_similar,
    get_pending_tweets,
    get_due_scheduled_tweets,
    get_scheduled_count,
    get_recent_tweets,
    get_agent_config,
    update_agent_config,
    is_within_active_hours,
    compute_random_schedule_time,
    SessionLocal,
    create_user,
    get_user_by_email,
    get_user_by_id,
    verify_password,
    create_auth_token,
    verify_auth_token
)
from ai_engine import (
    evaluate_tweet,
    generate_original_content,
    generate_smart_search_query,
    generate_strategy_brief,
    test_ai_api,
    KNOWN_GEMINI_MODELS
)
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

# Multi-Tenancy Browser Profile & Tenant Isolation Registry
DEFAULT_PROFILE_DIR = os.path.abspath(os.getenv("BROWSER_PROFILE_DIR", "./x_browser_profile"))
tenant_workers: Dict[str, XBrowserWorker] = {"default": browser_worker}


def get_tenant_browser_worker(tenant_id: str = "default") -> XBrowserWorker:
    """Returns an isolated XBrowserWorker instance with an isolated profile directory per tenant."""
    clean_tenant = re.sub(r"[^a-zA-Z0-9_\-]", "_", tenant_id or "default")
    if clean_tenant not in tenant_workers:
        profile_dir = (
            DEFAULT_PROFILE_DIR
            if clean_tenant == "default"
            else os.path.abspath(f"./x_browser_profile_{clean_tenant}")
        )
        tenant_workers[clean_tenant] = XBrowserWorker(profile_dir=profile_dir, headless=HEADLESS)
    return tenant_workers[clean_tenant]


async def get_current_tenant(
    authorization: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None)
) -> str:
    """
    Multi-tenancy isolation dependency:
    Extracts tenant ID from signed session token, Firebase JWT Bearer token, or 'X-Tenant-Id' header.
    Defaults cleanly to 'default' when running in single-user or local mode.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token and x_auth_token.strip():
        token = x_auth_token.strip()

    if token:
        # Check signed session token first
        payload = verify_auth_token(token)
        if payload and payload.get("tenant_id"):
            return payload["tenant_id"]
        # Check Firebase token fallback
        try:
            import firebase_admin.auth
            decoded = firebase_admin.auth.verify_id_token(token)
            if decoded.get("uid"):
                return decoded["uid"]
        except Exception:
            pass

    if x_tenant_id and x_tenant_id.strip():
        return x_tenant_id.strip()

    return "default"

last_interaction_timestamp: float = 0.0
current_random_cooldown_seconds: int = 0
is_session_logged_in: bool = False
is_manual_login_active: bool = False
active_search_query_state: Optional[str] = None
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


def sync_detected_username(db: Session, tenant_id: str = "default", worker: Optional[XBrowserWorker] = None):
    """Saves worker.logged_in_username to AgentConfig for the specified tenant if newly detected."""
    w = worker or get_tenant_browser_worker(tenant_id)
    if w.logged_in_username:
        cfg = get_agent_config(db, tenant_id=tenant_id)
        if cfg.linked_username != w.logged_in_username:
            cfg.linked_username = w.logged_in_username
            db.commit()


# ==============================================================================
# Randomized Scheduled Queue Dispatcher Loop
# ==============================================================================

async def scheduled_queue_dispatcher_loop():
    """
    Continuously checks for scheduled replies whose randomized `scheduled_for`
    timestamp has arrived and dispatches them organically while respecting
    the rolling 60-minute anti-detection velocity cap and warmup mode.
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
                warmup = bool(getattr(config, "warmup_mode", False))
                daily_used = get_daily_actions_count(db)
                daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
                hourly_used = get_hourly_actions_count(db)
                hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
                min_cd = config.min_cooldown_minutes or 10
                max_cd = config.max_cooldown_minutes or 45
                due_items = get_due_scheduled_tweets(db) if within_hours else []
            finally:
                db.close()

            if due_items and daily_used < daily_cap and hourly_used < hourly_cap:
                target = due_items[0]
                act_type = target.action_type or "reply"
                logger.info(f"Scheduled time reached for {act_type} ({target.tweet_id}). Publishing now (hourly {hourly_used + 1}/{hourly_cap})...")
                success = await browser_worker.execute_tweet_action(
                    act_type,
                    target.tweet_id,
                    target.generated_text,
                    target.tweet_url,
                    should_like=bool(getattr(target, "should_like", False))
                )
                db = SessionLocal()
                try:
                    sync_detected_username(db)
                    if success:
                        set_new_random_cooldown(min_cd, max_cd)
                        update_tweet_status(db, target.tweet_id, status="posted")
                        logger.info(f"Successfully published scheduled {act_type} ({target.tweet_id})!")
                    else:
                        err_msg = getattr(browser_worker, "last_error", None) or f"Browser failed while publishing scheduled {act_type}"
                        update_tweet_status(
                            db,
                            target.tweet_id,
                            status="failed",
                            error_message=err_msg
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
    Continuous background loop with Smart AI Search Discovery, Multimodal Vision,
    Self-Learning Voice Memory, Duplicate Similarity Filtering, and Urgency Scheduling.
    """
    global is_session_logged_in, active_search_query_state
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
                warmup = bool(getattr(config, "warmup_mode", False))
                daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
                hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
                smart_query_on = bool(getattr(config, "smart_query_enabled", True))
                base_query = config.search_query
                persona = config.persona_prompt
                selected_model = config.selected_model or "gemini-3.8-flash"
                start_hr = config.active_hours_start if config.active_hours_start is not None else 8
                end_hr = config.active_hours_end if config.active_hours_end is not None else 23
                daily_used = get_daily_actions_count(db)
                hourly_used = get_hourly_actions_count(db)
                learning_memory = get_learning_memory(db)
                recent_rows = get_recent_tweets(db, limit=6)
                recent_sample_dicts = [{"text": r.tweet_text} for r in recent_rows if r.tweet_text]
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

            if hourly_used >= hourly_cap and not scrape_now_flag.is_set():
                logger.info(f"Hourly anti-detection cap reached ({hourly_used}/{hourly_cap} in last 60m). Cooling down...")
                await asyncio.sleep(180)
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

            # Smart AI Search Query Discovery
            effective_query = base_query
            if smart_query_on and base_query and base_query.strip():
                effective_query = await generate_smart_search_query(
                    niche_topic=base_query,
                    recent_tweets=recent_sample_dicts,
                    model_name=selected_model
                )
            active_search_query_state = effective_query or "Home Timeline"

            logger.info(f"Scanning X feed for '{effective_query}' (learned samples: {learning_memory.get('total_learned', 0)})...")
            tweets = await browser_worker.scrape_feed(search_query=effective_query, limit=8)
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
                    search_query=base_query or effective_query,
                    persona_prompt=persona,
                    extra_context=t.get("extra_context"),
                    media_url=t.get("media_url"),
                    learning_memory=learning_memory
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
                            media_url=t.get("media_url"),
                            generated_text=None,
                            variants_json=None,
                            tweet_metrics=t.get("metrics"),
                            status="skipped",
                            error_message=ai_result["reasoning"]
                        )
                        continue

                    reply_text = ai_result["reply_text"]
                    variants_dict = ai_result.get("variants") or {}
                    variants_json = ai_result.get("variants_json")
                    should_like = bool(ai_result.get("should_like", False))
                    urgency_score = int(ai_result.get("urgency_score", 5))

                    # Anti-Detection Duplicate & Template Similarity Filter
                    if is_reply_too_similar(db, reply_text):
                        alt_chosen = None
                        for alt_text in variants_dict.values():
                            if alt_text and not is_reply_too_similar(db, alt_text):
                                alt_chosen = alt_text
                                break
                        if alt_chosen:
                            logger.info("Primary draft shared opening words with a recent reply; switched to fresh variant.")
                            reply_text = alt_chosen
                        else:
                            logger.info(f"Skipped @{t['author']}: Draft too similar to recent replies (anti-template shield).")
                            record_processed_tweet(
                                db=db,
                                tweet_id=tweet_id,
                                action_type="reply",
                                tweet_text=t["text"],
                                tweet_author=t["author"],
                                tweet_url=t["url"],
                                media_url=t.get("media_url"),
                                generated_text=None,
                                status="skipped",
                                error_message="Filtered by Anti-Detection Similarity Shield"
                            )
                            continue

                    logger.info(f"Drafted for @{t['author']} [urgency {urgency_score}/10, like={should_like}]: '{reply_text}'")

                    if not auto_pilot:
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            media_url=t.get("media_url"),
                            generated_text=reply_text,
                            variants_json=variants_json,
                            tweet_metrics=t.get("metrics"),
                            should_like=should_like,
                            urgency_score=urgency_score,
                            status="pending_approval",
                            error_message=ai_result["reasoning"]
                        )
                    else:
                        # Autopilot schedules replies using AI urgency-weighted random timestamps
                        cfg = get_agent_config(db)
                        sched_utc = compute_random_schedule_time(db, cfg, urgency_score=urgency_score)
                        mins_away = max(1, int((sched_utc - datetime.utcnow()).total_seconds() // 60))
                        logger.info(f"Autopilot scheduled reply to @{t['author']} in ~{mins_away}m (urgency {urgency_score}/10).")
                        record_processed_tweet(
                            db=db,
                            tweet_id=tweet_id,
                            action_type="reply",
                            tweet_text=t["text"],
                            tweet_author=t["author"],
                            tweet_url=t["url"],
                            media_url=t.get("media_url"),
                            generated_text=reply_text,
                            variants_json=variants_json,
                            tweet_metrics=t.get("metrics"),
                            should_like=should_like,
                            urgency_score=urgency_score,
                            status="scheduled",
                            scheduled_for=sched_utc,
                            error_message=ai_result["reasoning"]
                        )
                finally:
                    db.close()

                await asyncio.sleep(random.uniform(1.2, 2.5))

            if new_count == 0 and len(tweets) > 0:
                logger.info(f"All {len(tweets)} visible posts for '{effective_query}' were already evaluated.")

            # Autonomously synthesize 1 original Post or Thread (AI chooses best format via mode="auto")
            if len(tweets) >= 2:
                logger.info(f"AI autonomously synthesizing original content from live '{effective_query}' pulse...")
                gen = await generate_original_content(
                    mode="auto",
                    search_query=base_query or effective_query,
                    persona_prompt=persona,
                    live_tweets=tweets,
                    model_name=selected_model,
                    learning_memory=learning_memory
                )
                if gen.get("success") and gen.get("text"):
                    chosen_mode = gen.get("action_type") or "post"
                    orig_urgency = int(gen.get("urgency_score", 6))
                    db = SessionLocal()
                    try:
                        cfg = get_agent_config(db)
                        orig_id = f"{chosen_mode}_{int(time.time())}"
                        author_label = (browser_worker.logged_in_username or cfg.linked_username or "you").lstrip("@")
                        if auto_pilot:
                            sched_utc = compute_random_schedule_time(db, cfg, urgency_score=orig_urgency)
                            record_processed_tweet(
                                db=db,
                                tweet_id=orig_id,
                                action_type=chosen_mode,
                                tweet_text=gen["topic_summary"],
                                tweet_author=author_label,
                                tweet_url="https://x.com/home",
                                generated_text=gen["text"],
                                variants_json=gen.get("variants_json"),
                                tweet_metrics="Live Pulse · Original Thread" if chosen_mode == "thread" else "Live Pulse · Original Post",
                                urgency_score=orig_urgency,
                                status="scheduled",
                                scheduled_for=sched_utc,
                                error_message=gen["topic_summary"]
                            )
                        else:
                            record_processed_tweet(
                                db=db,
                                tweet_id=orig_id,
                                action_type=chosen_mode,
                                tweet_text=gen["topic_summary"],
                                tweet_author=author_label,
                                tweet_url="https://x.com/home",
                                generated_text=gen["text"],
                                variants_json=gen.get("variants_json"),
                                tweet_metrics="Live Pulse · Thread" if chosen_mode == "thread" else "Live Pulse · Original Post",
                                urgency_score=orig_urgency,
                                status="pending_approval",
                                error_message=gen["topic_summary"]
                            )
                        logger.info(f"AI chose and drafted original {chosen_mode} (urgency {orig_urgency}/10) from live pulse.")
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


# ==============================================================================
# Authentication Endpoints (Sign Up, Sign In, Profile, Sign Out)
# ==============================================================================

@app.post("/api/auth/signup", response_model=AuthResponse)
async def signup(req: SignUpRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email address.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters long.")

    existing = get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists. Please sign in.")

    user = create_user(db, email=email, password_plain=req.password, name=req.name)
    token = create_auth_token(user.user_id, user.email, user.tenant_id)
    return AuthResponse(
        success=True,
        token=token,
        user=UserResponse(
            uid=user.user_id,
            email=user.email,
            name=user.name,
            tenant_id=user.tenant_id,
            created_at=user.created_at
        ),
        tenant_id=user.tenant_id,
        message="Account created successfully."
    )


@app.post("/api/auth/signin", response_model=AuthResponse)
async def signin(req: SignInRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    user = get_user_by_email(db, email)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_auth_token(user.user_id, user.email, user.tenant_id)
    return AuthResponse(
        success=True,
        token=token,
        user=UserResponse(
            uid=user.user_id,
            email=user.email,
            name=user.name,
            tenant_id=user.tenant_id,
            created_at=user.created_at
        ),
        tenant_id=user.tenant_id,
        message="Signed in successfully."
    )


@app.get("/api/auth/me")
async def get_me(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token and x_auth_token.strip():
        token = x_auth_token.strip()

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    payload = verify_auth_token(token)
    if not payload or not payload.get("uid"):
        # Check Firebase token fallback
        try:
            import firebase_admin.auth
            decoded = firebase_admin.auth.verify_id_token(token)
            return {
                "uid": decoded.get("uid"),
                "email": decoded.get("email"),
                "name": decoded.get("name") or decoded.get("email", "").split("@")[0],
                "tenant_id": decoded.get("uid")
            }
        except Exception:
            raise HTTPException(status_code=401, detail="Session expired or invalid. Please sign in again.")

    user = get_user_by_id(db, payload["uid"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return {
        "uid": user.user_id,
        "email": user.email,
        "name": user.name,
        "tenant_id": user.tenant_id,
        "created_at": user.created_at.isoformat() if user.created_at else None
    }


@app.post("/api/auth/signout")
async def signout():
    return {"success": True, "message": "Signed out successfully."}



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
async def get_status(tenant_id: str = Depends(get_current_tenant), db: Session = Depends(get_db)):
    config = get_agent_config(db, tenant_id=tenant_id)
    worker = get_tenant_browser_worker(tenant_id)
    if worker.logged_in_username and config.linked_username != worker.logged_in_username:
        config.linked_username = worker.logged_in_username
        db.commit()

    warmup = bool(getattr(config, "warmup_mode", False))
    daily_used = get_daily_actions_count(db, tenant_id=tenant_id)
    effective_daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
    hourly_used = get_hourly_actions_count(db, tenant_id=tenant_id)
    effective_hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
    learning_mem = get_learning_memory(db, limit_approved=1, limit_skipped=1, tenant_id=tenant_id)

    cooldown_rem = get_cooldown_remaining()
    pending_items = get_pending_tweets(db, tenant_id=tenant_id)
    sched_count = get_scheduled_count(db, tenant_id=tenant_id)
    total_processed = db.query(ProcessedTweet).filter(ProcessedTweet.tenant_id == tenant_id).count()
    within_hours = is_within_active_hours(
        config.active_hours_start if config.active_hours_start is not None else 8,
        config.active_hours_end if config.active_hours_end is not None else 23
    )

    has_profile_cookies = (
        os.path.isfile(worker.cookies_backup_path)
        or os.path.isfile(os.path.join(worker.profile_dir, "Default", "Network", "Cookies"))
        or os.path.isfile(os.path.join(worker.profile_dir, "Default", "Cookies"))
    )

    return AgentStatusResponse(
        is_active=config.is_active,
        auto_pilot_mode=config.auto_pilot_mode,
        polling_interval_minutes=config.polling_interval_minutes,
        daily_action_cap=effective_daily_cap,
        daily_actions_used=daily_used,
        hourly_action_cap=effective_hourly_cap,
        hourly_actions_used=hourly_used,
        smart_query_enabled=bool(getattr(config, "smart_query_enabled", True)),
        warmup_mode=warmup,
        active_search_query=active_search_query_state or config.search_query or "Home Timeline",
        learned_examples_count=int(learning_mem.get("total_learned", 0)),
        cooldown_active=cooldown_rem > 0,
        cooldown_seconds_remaining=cooldown_rem,
        within_active_hours=within_hours,
        scheduled_count=sched_count,
        browser_connected=worker.is_running,
        is_logged_in=is_session_logged_in or bool(config.linked_username) or has_profile_cookies,
        linked_username=worker.logged_in_username or config.linked_username,
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
async def get_config(tenant_id: str = Depends(get_current_tenant), db: Session = Depends(get_db)):
    cfg = get_agent_config(db, tenant_id=tenant_id)
    worker = get_tenant_browser_worker(tenant_id)
    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    masked_key = (current_key[:4] + "..." + current_key[-4:]) if len(current_key) > 8 else ("***" if current_key else "")
    return AgentConfigResponse(
        id=cfg.id,
        is_active=cfg.is_active,
        auto_pilot_mode=cfg.auto_pilot_mode,
        polling_interval_minutes=cfg.polling_interval_minutes,
        daily_action_cap=cfg.daily_action_cap,
        hourly_action_cap=getattr(cfg, "hourly_action_cap", 6) or 6,
        min_cooldown_minutes=cfg.min_cooldown_minutes or 10,
        max_cooldown_minutes=cfg.max_cooldown_minutes or 45,
        active_hours_start=cfg.active_hours_start if cfg.active_hours_start is not None else 8,
        active_hours_end=cfg.active_hours_end if cfg.active_hours_end is not None else 23,
        search_query=cfg.search_query,
        smart_query_enabled=bool(getattr(cfg, "smart_query_enabled", True)),
        warmup_mode=bool(getattr(cfg, "warmup_mode", False)),
        persona_prompt=cfg.persona_prompt or "",
        selected_model=cfg.selected_model or "gemini-3.8-flash",
        linked_username=worker.logged_in_username or cfg.linked_username,
        masked_api_key=masked_key,
        updated_at=cfg.updated_at
    )


@app.post("/api/config", response_model=AgentConfigResponse)
async def update_config_endpoint(
    payload: AgentConfigUpdate,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    if payload.api_key is not None and payload.api_key.strip():
        clean_key = payload.api_key.strip()
        if clean_key.startswith("sk-"):
            update_env_variable("DEEPSEEK_API_KEY", clean_key)
        else:
            update_env_variable("GEMINI_API_KEY", clean_key)

    updates = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    updated = update_agent_config(db, updates, tenant_id=tenant_id)
    worker = get_tenant_browser_worker(tenant_id)
    logger.info(f"Settings updated for tenant '{tenant_id}'.")

    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    masked_key = (current_key[:4] + "..." + current_key[-4:]) if len(current_key) > 8 else ("***" if current_key else "")
    return AgentConfigResponse(
        id=updated.id,
        is_active=updated.is_active,
        auto_pilot_mode=updated.auto_pilot_mode,
        polling_interval_minutes=updated.polling_interval_minutes,
        daily_action_cap=updated.daily_action_cap,
        hourly_action_cap=getattr(updated, "hourly_action_cap", 6) or 6,
        min_cooldown_minutes=updated.min_cooldown_minutes or 10,
        max_cooldown_minutes=updated.max_cooldown_minutes or 45,
        active_hours_start=updated.active_hours_start if updated.active_hours_start is not None else 8,
        active_hours_end=updated.active_hours_end if updated.active_hours_end is not None else 23,
        search_query=updated.search_query,
        smart_query_enabled=bool(getattr(updated, "smart_query_enabled", True)),
        warmup_mode=bool(getattr(updated, "warmup_mode", False)),
        persona_prompt=updated.persona_prompt or "",
        selected_model=updated.selected_model or "gemini-3.8-flash",
        linked_username=worker.logged_in_username or updated.linked_username,
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
async def get_pending_approvals_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    return get_pending_tweets(db, tenant_id=tenant_id)


@app.get("/api/history", response_model=List[ProcessedTweetResponse])
async def get_history_endpoint(
    limit: int = 50,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    return get_recent_tweets(db, limit=limit, tenant_id=tenant_id)


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
async def get_analytics_endpoint(
    refresh_brief: bool = False,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Computes rich Power-BI style analytics on posts, replies, threads,
    target feed engagement, hourly velocity, author leaderboards, and AI Strategy Brief.
    """
    all_rows = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.tenant_id == tenant_id)
        .order_by(ProcessedTweet.timestamp.desc())
        .all()
    )
    cfg = get_agent_config(db, tenant_id=tenant_id)

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

    warmup = bool(getattr(cfg, "warmup_mode", False))
    daily_used = get_daily_actions_count(db, tenant_id=tenant_id)
    daily_cap = min(8, cfg.daily_action_cap or 15) if warmup else (cfg.daily_action_cap or 15)
    hourly_used = get_hourly_actions_count(db, tenant_id=tenant_id)
    hourly_cap = 3 if warmup else (getattr(cfg, "hourly_action_cap", 6) or 6)
    learning_memory = get_learning_memory(db, tenant_id=tenant_id)

    kpis_dict = {
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
        "daily_used": daily_used,
        "daily_cap": daily_cap,
        "hourly_used": hourly_used,
        "hourly_cap": hourly_cap,
        "learned_examples_count": int(learning_memory.get("total_learned", 0))
    }

    strategy_brief = await generate_strategy_brief(
        kpis=kpis_dict,
        top_authors=top_authors,
        learning_memory=learning_memory,
        niche=active_search_query_state or cfg.search_query or "AI & Tech",
        model_name=cfg.selected_model or "gemini-3.8-flash",
        force_refresh=refresh_brief
    )

    return {
        "kpis": kpis_dict,
        "strategy_brief": strategy_brief,
        "learning_memory": learning_memory,
        "velocity_shield": {
            "hourly_used": hourly_used,
            "hourly_cap": hourly_cap,
            "daily_used": daily_used,
            "daily_cap": daily_cap,
            "warmup_mode": warmup,
            "smart_query_enabled": bool(getattr(cfg, "smart_query_enabled", True)),
            "active_search_query": active_search_query_state or cfg.search_query or "Home Timeline",
            "learned_examples_count": int(learning_memory.get("total_learned", 0)),
        },
        "content_mix": [
            {"label": "Smart Replies", "key": "reply", "count": replies_cnt, "color": "#01B8AA"},
            {"label": "Original Posts", "key": "post", "count": posts_cnt, "color": "#F2C811"},
            {"label": "Multi-Post Threads", "key": "thread", "count": threads_cnt, "color": "#374649"}
        ],
        "status_funnel": [
            {"label": "Published", "count": posted, "color": "#01B8AA"},
            {"label": "Scheduled (Random)", "count": scheduled, "color": "#374649"},
            {"label": "In Review Queue", "count": pending, "color": "#F2C811"},
            {"label": "AI Filtered / Skipped", "count": skipped, "color": "#FD625E"}
        ],
        "length_distribution": [
            {"label": "Punchy (<95c)", "count": short_cnt, "color": "#01B8AA"},
            {"label": "Conversational (95-185c)", "count": med_cnt, "color": "#374649"},
            {"label": "Deep Thread (>185c)", "count": long_cnt, "color": "#F2C811"}
        ],
        "timeline": timeline,
        "top_authors": top_authors
    }


@app.post("/api/approve/{tweet_id}")
async def approve_tweet(
    tweet_id: str,
    payload: Optional[ApproveDraftRequest] = None,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Approves a draft reply.
    - Tracks whether the user edited the draft so Self-Learning Voice Memory can prioritize it.
    - Enforces rolling 60-minute and daily anti-detection caps.
    """
    tweet = db.query(ProcessedTweet).filter(
        ProcessedTweet.tweet_id == tweet_id,
        ProcessedTweet.tenant_id == tenant_id
    ).first()
    if not tweet:
        tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    config = get_agent_config(db, tenant_id=tenant_id)
    warmup = bool(getattr(config, "warmup_mode", False))
    daily_used = get_daily_actions_count(db, tenant_id=tenant_id)
    daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
    hourly_used = get_hourly_actions_count(db, tenant_id=tenant_id)
    hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)

    text_to_post = payload.custom_text.strip() if (payload and payload.custom_text) else tweet.generated_text
    if not text_to_post:
        raise HTTPException(status_code=400, detail="Cannot post an empty reply.")

    was_user_edited = bool(
        payload and payload.custom_text and payload.custom_text.strip() != (tweet.generated_text or "").strip()
    )
    effective_like = (
        bool(payload.should_like)
        if (payload and payload.should_like is not None)
        else bool(getattr(tweet, "should_like", False))
    )
    urgency_val = int(getattr(tweet, "urgency_score", 5) or 5)

    if payload and payload.schedule_random:
        sched_utc = compute_random_schedule_time(db, config, urgency_score=urgency_val)
        update_tweet_status(
            db,
            tweet_id,
            status="scheduled",
            generated_text=text_to_post,
            scheduled_for=sched_utc,
            user_edited=was_user_edited,
            should_like=effective_like
        )
        mins_away = max(1, int((sched_utc - datetime.utcnow()).total_seconds() // 60))
        logger.info(f"Scheduled reply to @{tweet.tweet_author} for random time (~{mins_away}m from now, edited={was_user_edited}).")
        return {
            "status": "scheduled",
            "tweet_id": tweet_id,
            "scheduled_for": sched_utc.isoformat(),
            "minutes_from_now": mins_away
        }

    if daily_used >= daily_cap:
        raise HTTPException(
            status_code=429,
            detail=f"Daily anti-detection cap ({daily_cap}) reached!"
        )
    if hourly_used >= hourly_cap:
        raise HTTPException(
            status_code=429,
            detail=f"Hourly anti-detection velocity cap ({hourly_cap}/hr) reached! Use 'Schedule' to queue safely."
        )

    act_type = tweet.action_type or "reply"
    logger.info(f"Publishing approved {act_type} ({tweet_id}) [edited={was_user_edited}, like={effective_like}, tenant={tenant_id}]...")
    worker = get_tenant_browser_worker(tenant_id)
    success = await worker.execute_tweet_action(
        act_type,
        tweet_id,
        text_to_post,
        tweet.tweet_url,
        should_like=effective_like
    )
    sync_detected_username(db)

    if success:
        set_new_random_cooldown(config.min_cooldown_minutes or 10, config.max_cooldown_minutes or 45)
        update_tweet_status(
            db,
            tweet_id,
            status="posted",
            generated_text=text_to_post,
            user_edited=was_user_edited,
            should_like=effective_like
        )
        logger.info(f"Successfully published {act_type} ({tweet_id})!")
        return {"status": "posted", "tweet_id": tweet_id, "text": text_to_post}
    else:
        err_msg = getattr(worker, "last_error", None) or f"Browser failed during {act_type} submission"
        update_tweet_status(
            db,
            tweet_id,
            status="failed",
            generated_text=text_to_post,
            error_message=err_msg
        )
        raise HTTPException(status_code=500, detail=f"Failed to publish {act_type}: {err_msg}")


class GenerateOriginalPayload(BaseModel):
    mode: str = "auto"  # "auto", "post", or "thread"
    custom_topic: Optional[str] = None


@app.post("/api/generate-original")
async def generate_original_endpoint(
    payload: GenerateOriginalPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Generates a fresh Original Post or Multi-Post Thread from real-time conversations,
    user voice memory, and current Google Search information, adding it directly to the Queue.
    """
    cfg = get_agent_config(db, tenant_id=tenant_id)
    req_mode = payload.mode if payload.mode in ("auto", "post", "thread") else "auto"
    topic = (payload.custom_topic or active_search_query_state or cfg.search_query or "tech & culture").strip()

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
    learning_memory = get_learning_memory(db)

    gen = await generate_original_content(
        mode=req_mode,
        search_query=topic,
        persona_prompt=cfg.persona_prompt,
        live_tweets=live_context,
        model_name=cfg.selected_model or "gemini-3.8-flash",
        learning_memory=learning_memory
    )
    if not gen.get("success") or not gen.get("text"):
        err_msg = gen.get("error") or gen.get("topic_summary") or "Failed to generate content"
        err_code = gen.get("error_code")
        if not err_code:
            err_code = 429 if ("quota" in err_msg.lower() or "429" in err_msg or "resource_exhausted" in err_msg.lower()) else 500
        raise HTTPException(status_code=err_code, detail=err_msg)

    final_mode = gen.get("action_type") or ("thread" if req_mode == "thread" else "post")
    orig_id = f"{final_mode}_{int(time.time() * 1000)}"
    author_label = (browser_worker.logged_in_username or cfg.linked_username or "you").lstrip("@")
    item = record_processed_tweet(
        db=db,
        tweet_id=orig_id,
        action_type=final_mode,
        tweet_text=gen["topic_summary"],
        tweet_author=author_label,
        tweet_url="https://x.com/home",
        generated_text=gen["text"],
        variants_json=gen.get("variants_json"),
        tweet_metrics="Original Thread" if final_mode == "thread" else "Original Post",
        urgency_score=int(gen.get("urgency_score", 6)),
        status="pending_approval",
        error_message=gen["topic_summary"]
    )
    logger.info(f"Generated new {final_mode} on '{topic}'")
    return {"status": "created", "tweet_id": item.tweet_id, "action_type": final_mode}


@app.post("/api/regenerate/{tweet_id}")
async def regenerate_tweet_draft(tweet_id: str, db: Session = Depends(get_db)):
    """Regenerates 3 fresh context-specific variants for a reply, original post, or thread."""
    tweet = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    cfg = get_agent_config(db)
    learning_memory = get_learning_memory(db)
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
            model_name=cfg.selected_model or "gemini-3.8-flash",
            learning_memory=learning_memory
        )
        if not gen.get("success") or not gen.get("text"):
            err_msg = gen.get("error") or gen.get("topic_summary") or "Failed to regenerate"
            err_code = gen.get("error_code")
            if not err_code:
                err_code = 429 if ("quota" in err_msg.lower() or "429" in err_msg or "resource_exhausted" in err_msg.lower()) else 500
            raise HTTPException(status_code=err_code, detail=err_msg)
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
        temperature=0.9,
        media_url=getattr(tweet, "media_url", None),
        learning_memory=learning_memory
    )

    if not ai_result.get("reply_text"):
        reason = ai_result.get("reasoning") or "Failed to regenerate draft"
        status_code = 429 if ("quota" in reason.lower() or "429" in reason or "resource_exhausted" in reason.lower()) else 500
        raise HTTPException(status_code=status_code, detail=reason)

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
async def launch_headful_login(tenant_id: str = Depends(get_current_tenant)):
    global is_manual_login_active
    try:
        is_manual_login_active = True
        worker = get_tenant_browser_worker(tenant_id)
        
        # On Windows desktop, try launching the system browser via OS shell so it appears interactively
        if sys.platform == "win32":
            try:
                import webbrowser
                webbrowser.open("https://x.com/login")
            except Exception:
                pass

        try:
            await worker.open_headful_for_login()
        except Exception as we:
            logger.warning(f"Worker headful launch note: {we}")

        return {
            "status": "browser_opened",
            "open_url": "https://x.com/login",
            "message": "X login window opened. Sign into X, then return here and click 'Verify Connection'."
        }
    except Exception as e:
        is_manual_login_active = False
        raise HTTPException(status_code=500, detail=f"Failed to open browser: {str(e)}")


@app.post("/api/browser/release")
async def release_browser_profile(tenant_id: str = Depends(get_current_tenant)):
    global is_manual_login_active
    is_manual_login_active = True
    worker = get_tenant_browser_worker(tenant_id)
    await worker.stop()
    return {"status": "released"}


@app.post("/api/browser/check-session")
async def check_session(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    global is_session_logged_in, is_manual_login_active
    is_manual_login_active = False
    worker = get_tenant_browser_worker(tenant_id)
    is_session_logged_in = await worker.check_login_status()
    if is_session_logged_in:
        sync_detected_username(db, tenant_id=tenant_id, worker=worker)
    cfg = get_agent_config(db, tenant_id=tenant_id)
    return {
        "is_logged_in": is_session_logged_in,
        "linked_username": worker.logged_in_username or cfg.linked_username
    }


class ConnectSessionPayload(BaseModel):
    auth_token: Optional[str] = None
    ct0: Optional[str] = None
    raw_cookies: Optional[str] = None
    cookies: Optional[List[Dict[str, Any]]] = None


def parse_cookie_payload(payload: ConnectSessionPayload) -> List[Dict[str, Any]]:
    # 1. Direct list of cookie objects
    if payload.cookies and isinstance(payload.cookies, list):
        parsed_list = []
        for c in payload.cookies:
            if isinstance(c, dict) and c.get("name") and c.get("value"):
                parsed_list.append({
                    "name": str(c["name"]).strip(),
                    "value": str(c["value"]).strip(),
                    "domain": str(c.get("domain", ".x.com")).strip(),
                    "path": str(c.get("path", "/")).strip(),
                    "secure": bool(c.get("secure", True)),
                    "httpOnly": bool(c.get("httpOnly", c.get("name") == "auth_token")),
                    "sameSite": str(c.get("sameSite", "Lax")).strip()
                })
        if parsed_list:
            return parsed_list

    cookie_str = (payload.raw_cookies or "").strip()
    auth_token_val = (payload.auth_token or "").strip()
    ct0_val = (payload.ct0 or "").strip()

    # Check if raw_cookies is JSON
    if cookie_str.startswith("[") or cookie_str.startswith("{"):
        try:
            parsed = json.loads(cookie_str)
            if isinstance(parsed, list):
                return parse_cookie_payload(ConnectSessionPayload(cookies=parsed))
            elif isinstance(parsed, dict):
                auth_token_val = parsed.get("auth_token", auth_token_val)
                ct0_val = parsed.get("ct0", ct0_val)
        except Exception:
            pass

    # Extract auth_token if present in header-style cookie string: 'auth_token=xxxx; ct0=yyyy'
    if "auth_token=" in cookie_str:
        m = re.search(r"auth_token=([a-zA-Z0-9%_-]+)", cookie_str)
        if m:
            auth_token_val = m.group(1)
    if "ct0=" in cookie_str:
        m = re.search(r"ct0=([a-zA-Z0-9%_-]+)", cookie_str)
        if m:
            ct0_val = m.group(1)

    # If user pasted raw 40-char token directly into raw_cookies input
    if not auth_token_val and cookie_str and len(cookie_str) >= 20 and ";" not in cookie_str and " " not in cookie_str:
        auth_token_val = cookie_str

    if not auth_token_val:
        raise ValueError("Valid X 'auth_token' cookie is required to connect.")

    clean_auth = auth_token_val.strip().strip('"').strip("'")
    cookies = [
        {
            "name": "auth_token",
            "value": clean_auth,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax"
        }
    ]
    if ct0_val:
        clean_ct0 = ct0_val.strip().strip('"').strip("'")
        cookies.append({
            "name": "ct0",
            "value": clean_ct0,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "sameSite": "Lax"
        })
    return cookies


@app.post("/api/browser/connect-session")
async def connect_session_endpoint(
    payload: ConnectSessionPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    SaaS & Cloud Account Connection Endpoint:
    Imports auth_token or full cookie session into the tenant's isolated browser profile,
    validates the session live with X, and links the detected handle.
    """
    global is_session_logged_in, is_manual_login_active
    is_manual_login_active = False
    try:
        cookies = parse_cookie_payload(payload)
        worker = get_tenant_browser_worker(tenant_id)
        is_logged = await worker.import_cookies(cookies)
        if is_logged:
            is_session_logged_in = True
            sync_detected_username(db, tenant_id=tenant_id, worker=worker)
            cfg = get_agent_config(db, tenant_id=tenant_id)
            handle = worker.logged_in_username or cfg.linked_username or "Connected Account"
            return {
                "success": True,
                "is_logged_in": True,
                "linked_username": handle,
                "message": f"Successfully connected {handle} to your studio sandbox!"
            }
        else:
            return {
                "success": False,
                "is_logged_in": False,
                "message": "The session token was not recognized or has expired on X. Please verify your auth_token and retry."
            }
    except Exception as e:
        logger.warning(f"Connect session error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/browser/disconnect")
async def disconnect_account_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Disconnects the X account from the tenant's isolated sandbox."""
    worker = get_tenant_browser_worker(tenant_id)
    await worker.stop()
    if os.path.isfile(worker.cookies_backup_path):
        try:
            os.remove(worker.cookies_backup_path)
        except Exception:
            pass
    cfg = get_agent_config(db, tenant_id=tenant_id)
    cfg.linked_username = None
    db.commit()
    return {"success": True, "message": "X account disconnected successfully."}


class CookiesImportPayload(BaseModel):
    cookies: List[Dict[str, Any]]


@app.get("/api/browser/cookies")
async def export_cookies_endpoint(tenant_id: str = Depends(get_current_tenant)):
    """Exports session cookies as JSON for the active tenant."""
    worker = get_tenant_browser_worker(tenant_id)
    cookies = await worker.export_cookies()
    return JSONResponse(content={"cookies": cookies, "count": len(cookies)})


@app.post("/api/browser/cookies")
async def import_cookies_endpoint(
    payload: CookiesImportPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Imports session cookies into the active tenant's isolated profile and verifies login."""
    global is_session_logged_in
    worker = get_tenant_browser_worker(tenant_id)
    is_session_logged_in = await worker.import_cookies(payload.cookies)
    if is_session_logged_in:
        sync_detected_username(db, tenant_id=tenant_id, worker=worker)
    cfg = get_agent_config(db, tenant_id=tenant_id)
    return {
        "is_logged_in": is_session_logged_in,
        "linked_username": worker.logged_in_username or cfg.linked_username
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
