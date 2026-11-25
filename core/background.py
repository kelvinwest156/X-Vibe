"""
Autonomous Background Workers for X-VibeBot.
Runs the continuous feed scraping loop with:
- Global Super Admin pause & per-tenant suspension guardrails
- Daily AI token budget enforcement
- Queue cap pausing (skipping scans when pending queue is full)
- Browser Auto-Sleep (closing Chromium outside active hours or after 15m idle to reclaim RAM)
- Zero-token Python spam pre-filter
- Single batched DeepSeek evaluation (1 API call for up to 8 clean tweets, prefix-cached)
- Autonomous original post cap (6/day) & single-draft mode
"""

import os
import asyncio
import logging
import random
import time
import uuid
import json
from datetime import datetime, timedelta

from database import (
    SessionLocal,
    get_due_scheduled_tweets,
    get_agent_config,
    get_platform_settings,
    is_within_active_hours,
    get_daily_actions_count,
    get_hourly_actions_count,
    get_daily_original_posts_count,
    get_pending_approval_count,
    update_tweet_status,
    get_learning_memory,
    get_recent_tweets,
    is_tweet_already_processed,
    record_processed_tweet,
    is_reply_too_similar,
    compute_random_schedule_time,
    expire_stale_drafts,
)
from services.plans import is_subscription_valid
from ai_engine import (
    evaluate_tweets_batch,
    generate_original_content,
    generate_smart_search_query,
    should_prefilter_skip,
    check_tenant_token_budget,
)
from models import AgentConfig, ProcessedTweet
from core.web_scout import scout_and_rank_topics, generate_draft_from_web_topic
import core.state as state

logger = logging.getLogger("x_vibebot.background")


# ==============================================================================
# Browser Auto-Sleep Reaper (RAM Optimization)
# ==============================================================================

async def _sleep_idle_or_inactive_browsers():
    """
    Reclaims ~150-300 MB RAM per Chromium process by stopping running browser workers
    when:
    - PlatformSettings.auto_sleep_browsers_enabled is True AND tenant auto_sleep_browser is True
    - AND any of:
        * PlatformSettings.global_pause_bots is True
        * Tenant is suspended or inactive (paused) and idle >= 60s
        * Tenant is outside configured active_hours_start..active_hours_end
        * Worker has been idle >= browser_idle_sleep_minutes (default 15m)
    Session cookies remain safely backed up in DB and cookies_backup.json.
    """
    if state.is_manual_login_active:
        return

    db = SessionLocal()
    try:
        ps = get_platform_settings(db)
        if not bool(getattr(ps, "auto_sleep_browsers_enabled", True)):
            return
        idle_limit_secs = max(60, int(getattr(ps, "browser_idle_sleep_minutes", 15) or 15) * 60)
        global_paused = bool(getattr(ps, "global_pause_bots", False))

        now_ts = time.time()
        for tid, worker in list(state.tenant_workers.items()):
            if not getattr(worker, "is_running", False):
                continue
            try:
                cfg = get_agent_config(db, tenant_id=tid)
                if not bool(getattr(cfg, "auto_sleep_browser", True)):
                    continue

                last_used = float(getattr(worker, "last_used_at", 0.0) or 0.0)
                idle_secs = (now_ts - last_used) if last_used > 0 else idle_limit_secs
                start_hr = cfg.active_hours_start if cfg.active_hours_start is not None else 8
                end_hr = cfg.active_hours_end if cfg.active_hours_end is not None else 23
                outside_hours = not is_within_active_hours(start_hr, end_hr)
                is_suspended = bool(getattr(cfg, "is_suspended", False))
                is_paused = not bool(cfg.is_active)

                reason = None
                if global_paused and idle_secs >= 30:
                    reason = "global bots paused"
                elif is_suspended and idle_secs >= 30:
                    reason = "tenant suspended"
                elif outside_hours and idle_secs >= 60:
                    reason = f"outside active hours ({start_hr:02d}:00-{end_hr:02d}:00)"
                elif idle_secs >= idle_limit_secs:
                    reason = f"idle {int(idle_secs // 60)}m (limit {int(idle_limit_secs // 60)}m)"
                elif is_paused and idle_secs >= 180:
                    reason = "agent paused"

                if reason:
                    logger.info(f"Browser Auto-Sleep: Stopping Chromium for tenant '{tid}' ({reason}) to reclaim RAM.")
                    await worker.stop()
            except Exception as we:
                logger.debug(f"Browser auto-sleep check notice for '{tid}': {we}")
    except Exception as e:
        logger.debug(f"Browser auto-sleep pass notice: {e}")
    finally:
        db.close()


# ==============================================================================
# High-Speed Async Action Dispatcher Loop
# ==============================================================================

async def async_action_dispatcher_loop():
    """
    Dedicated high-speed Async Action Dispatcher.
    Continuously listens on `state.action_dispatch_queue` for immediate user approvals
    ('Post Now') and scheduled dispatches.
    Executes actions via the Playwright browser worker asynchronously without blocking
    HTTP endpoints or client UI requests.
    """
    logger.info("High-speed Async Action Dispatcher initialized.")
    while True:
        try:
            job = await state.action_dispatch_queue.get()
            tenant_id = job.get("tenant_id") or "default"
            tweet_id = job["tweet_id"]
            act_type = job.get("action_type") or "reply"
            text_to_post = job["text"]
            tweet_url = job.get("tweet_url")
            should_like = job.get("should_like", False)
            was_user_edited = job.get("was_user_edited", False)
            min_cd = job.get("min_cooldown", 10)
            max_cd = job.get("max_cooldown", 45)

            logger.info(f"Async Action Dispatcher: Processing {act_type} ({tweet_id}) [tenant={tenant_id}]...")
            worker = state.get_tenant_browser_worker(tenant_id)

            success = await worker.execute_tweet_action(
                act_type,
                tweet_id,
                text_to_post,
                tweet_url,
                should_like=should_like
            )

            def _update_db_after_action():
                db = SessionLocal()
                try:
                    state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
                    if success:
                        state.set_new_random_cooldown(min_cd, max_cd)
                        update_tweet_status(
                            db,
                            tweet_id,
                            status="posted",
                            generated_text=text_to_post,
                            user_edited=was_user_edited,
                            should_like=should_like,
                            tenant_id=tenant_id
                        )
                        logger.info(f"Async Action Dispatcher: Successfully published {act_type} ({tweet_id})!")
                    else:
                        err_msg = getattr(worker, "last_error", None) or f"Browser failed during {act_type} submission"
                        update_tweet_status(
                            db,
                            tweet_id,
                            status="failed",
                            generated_text=text_to_post,
                            error_message=err_msg,
                            tenant_id=tenant_id
                        )
                        logger.error(f"Async Action Dispatcher: Failed {act_type} ({tweet_id}): {err_msg}")
                finally:
                    db.close()

            await asyncio.to_thread(_update_db_after_action)
            state.action_dispatch_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in async action dispatcher: {e}", exc_info=True)
            await asyncio.sleep(1)


# ==============================================================================
# Randomized Scheduled Queue Dispatcher Loop
# ==============================================================================

async def scheduled_queue_dispatcher_loop():
    """
    Continuously checks for scheduled replies whose randomized `scheduled_for`
    timestamp has arrived and dispatches them organically while respecting
    global pause, suspension, active hours, and rolling 60-minute velocity caps.
    """
    logger.info("Random schedule dispatcher initialized.")
    await asyncio.sleep(3)

    while True:
        try:
            if state.is_manual_login_active:
                await asyncio.sleep(10)
                continue

            def _get_due():
                db = SessionLocal()
                try:
                    ps = get_platform_settings(db)
                    if bool(getattr(ps, "global_pause_bots", False)):
                        return []
                    return get_due_scheduled_tweets(db)
                finally:
                    db.close()

            due_items = await asyncio.to_thread(_get_due)

            if due_items:
                for target in due_items:
                    target_tenant = getattr(target, "tenant_id", None) or "default"
                    
                    def _check_and_prep():
                        db = SessionLocal()
                        try:
                            config = get_agent_config(db, tenant_id=target_tenant)
                            if bool(getattr(config, "is_suspended", False)):
                                return False, None
                            within_hours = is_within_active_hours(
                                config.active_hours_start if config.active_hours_start is not None else 8,
                                config.active_hours_end if config.active_hours_end is not None else 23,
                            )
                            if not within_hours:
                                resched = datetime.utcnow() + timedelta(minutes=30)
                                update_tweet_status(db, target.tweet_id, status="scheduled", scheduled_for=resched, tenant_id=target_tenant)
                                return False, None

                            warmup = bool(getattr(config, "warmup_mode", False))
                            daily_used = get_daily_actions_count(db, tenant_id=target_tenant)
                            daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
                            hourly_used = get_hourly_actions_count(db, tenant_id=target_tenant)
                            hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
                            min_cd = config.min_cooldown_minutes or 10
                            max_cd = config.max_cooldown_minutes or 45

                            if daily_used >= daily_cap or hourly_used >= hourly_cap:
                                postpone_mins = 240 if daily_used >= daily_cap else 25
                                resched = datetime.utcnow() + timedelta(minutes=postpone_mins)
                                update_tweet_status(db, target.tweet_id, status="scheduled", scheduled_for=resched, tenant_id=target_tenant)
                                return False, None

                            # Mark as dispatching
                            update_tweet_status(db, target.tweet_id, status="dispatching", tenant_id=target_tenant)
                            return True, (min_cd, max_cd)
                        finally:
                            db.close()

                    should_dispatch, cd_tuple = await asyncio.to_thread(_check_and_prep)
                    if not should_dispatch or not cd_tuple:
                        continue

                    min_cd, max_cd = cd_tuple
                    act_type = target.action_type or "reply"
                    logger.info(f"Scheduled time reached for {act_type} ({target.tweet_id}) [tenant={target_tenant}]. Enqueueing to async dispatcher...")

                    worker = state.get_tenant_browser_worker(target_tenant)
                    state.action_dispatch_queue.put_nowait({
                        "tenant_id": target_tenant,
                        "tweet_id": target.tweet_id,
                        "action_type": act_type,
                        "text": target.generated_text,
                        "tweet_url": target.tweet_url,
                        "should_like": bool(getattr(target, "should_like", False)),
                        "was_user_edited": bool(getattr(target, "user_edited", False)),
                        "min_cooldown": min_cd,
                        "max_cooldown": max_cd,
                    })

            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in scheduled dispatcher loop: {e}")
            await asyncio.sleep(10)


# ==============================================================================
# Autonomous Scraper & Batched Evaluation Background Loop
# ==============================================================================

async def background_automation_loop():
    """
    Continuous background loop with Multi-Tenant isolation, Global Pause / Suspension,
    Daily Token Cap enforcement, Queue Cap pausing, Browser Auto-Sleep,
    Zero-Token Python Spam Pre-Filter, and Single Batched DeepSeek Evaluation.
    """
    logger.info("Background automation worker loop initialized.")
    await asyncio.sleep(3)

    while True:
        try:
            # 0. Reap any idle/sleeping Chromium instances to keep RAM low
            await _sleep_idle_or_inactive_browsers()

            # 1. Drain manual scrape triggers (queued per tenant)
            manual_tenants = []
            while not state.tenant_scrape_queue.empty():
                try:
                    tid = state.tenant_scrape_queue.get_nowait()
                    if tid and tid not in manual_tenants:
                        manual_tenants.append(tid)
                except asyncio.QueueEmpty:
                    break

            if state.scrape_now_flag.is_set() and not manual_tenants:
                manual_tenants.append("default")
            state.scrape_now_flag.clear()

            # 2. Read PlatformSettings & active tenants from database
            db = SessionLocal()
            try:
                ps = get_platform_settings(db)
                global_pause = bool(getattr(ps, "global_pause_bots", False))
                if global_pause:
                    active_tenant_ids = []
                else:
                    active_configs = (
                        db.query(AgentConfig)
                        .filter(AgentConfig.is_active == True, AgentConfig.is_suspended == False)
                        .all()
                    )
                    active_tenant_ids = [c.tenant_id for c in active_configs if c.tenant_id]
            finally:
                db.close()

            if global_pause:
                if manual_tenants:
                    logger.warning("Global Bot Pause is active (Super Admin). Skipping scan triggers.")
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    pass
                continue

            # Build prioritized list of (tenant_id, is_manual)
            tenants_to_scan = []
            for tid in manual_tenants:
                tenants_to_scan.append((tid, True))
            for tid in active_tenant_ids:
                if not any(t[0] == tid for t in tenants_to_scan):
                    tenants_to_scan.append((tid, False))

            if not tenants_to_scan:
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    pass
                continue

            if state.is_manual_login_active and not any(t[1] for t in tenants_to_scan):
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    pass
                continue

            min_interval_secs = 20 * 60

            for curr_tenant_id, is_manual in tenants_to_scan:
                try:
                    db = SessionLocal()
                    try:
                        config = get_agent_config(db, tenant_id=curr_tenant_id)
                        if bool(getattr(config, "is_suspended", False)):
                            logger.warning(f"Tenant '{curr_tenant_id}' is suspended by Super Admin. Skipping.")
                            continue

                        # Subscription & Free Trial validity check
                        sub_ok, sub_status, trial_days_left = is_subscription_valid(config)
                        if not sub_ok:
                            logger.info(f"Tenant '{curr_tenant_id}': Subscription is {sub_status}. Skipping automated bot scan.")
                            worker_sub = state.tenant_workers.get(curr_tenant_id)
                            if worker_sub and worker_sub.is_running and bool(getattr(config, "auto_sleep_browser", True)):
                                await worker_sub.stop()
                            continue

                        if not is_manual and not config.is_active:
                            continue

                        auto_pilot = config.auto_pilot_mode
                        base_interval_secs = max(1, config.polling_interval_minutes) * 60
                        if base_interval_secs < min_interval_secs:
                            min_interval_secs = base_interval_secs
                        warmup = bool(getattr(config, "warmup_mode", False))
                        daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
                        hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
                        daily_orig_cap = int(getattr(config, "daily_original_post_cap", 3) or 3)
                        max_pending_queue = int(getattr(config, "max_pending_queue", 8) or 8)
                        smart_query_on = bool(getattr(config, "smart_query_enabled", True))
                        base_query = config.search_query
                        persona = config.persona_prompt
                        selected_model = config.selected_model or "auto"
                        start_hr = config.active_hours_start if config.active_hours_start is not None else 8
                        end_hr = config.active_hours_end if config.active_hours_end is not None else 23
                        daily_used = get_daily_actions_count(db, tenant_id=curr_tenant_id)
                        hourly_used = get_hourly_actions_count(db, tenant_id=curr_tenant_id)

                        # Auto-expire unreviewed drafts older than 24h before checking queue saturation
                        expire_stale_drafts(db, tenant_id=curr_tenant_id, max_age_hours=24)
                        pending_approval_count = get_pending_approval_count(db, tenant_id=curr_tenant_id)

                        learning_memory = get_learning_memory(db, limit_approved=4, limit_skipped=3, tenant_id=curr_tenant_id)
                        recent_rows = get_recent_tweets(db, limit=6, tenant_id=curr_tenant_id)
                        recent_sample_dicts = [{"text": r.tweet_text} for r in recent_rows if r.tweet_text]
                        cookies_json_val = getattr(config, "cookies_json", None)
                        tenant_api_key_val = getattr(config, "api_key", None)
                    finally:
                        db.close()

                    # Daily Token Budget Guardrail (enforced on both manual and scheduled runs)
                    budget_ok, tokens_used_today, token_cap_today = check_tenant_token_budget(curr_tenant_id)
                    if not budget_ok:
                        logger.info(
                            f"Tenant '{curr_tenant_id}': Daily AI token cap reached "
                            f"({tokens_used_today:,}/{token_cap_today:,} tokens). Skipping AI scan until UTC reset."
                        )
                        continue

                    # Check Active Hours, Action Caps & Queue Cap for scheduled automated runs
                    if not is_manual:
                        if not is_within_active_hours(start_hr, end_hr):
                            logger.info(f"Tenant '{curr_tenant_id}': Outside active hours ({start_hr:02d}:00-{end_hr:02d}:00). Sleeping...")
                            worker_sleep = state.tenant_workers.get(curr_tenant_id)
                            if worker_sleep and worker_sleep.is_running and bool(getattr(config, "auto_sleep_browser", True)):
                                await worker_sleep.stop()
                            continue
                        if daily_used >= daily_cap:
                            logger.warning(f"Tenant '{curr_tenant_id}': Daily cap reached ({daily_used}/{daily_cap}). Pausing until tomorrow.")
                            continue
                        if hourly_used >= hourly_cap:
                            logger.info(f"Tenant '{curr_tenant_id}': Hourly cap reached ({hourly_used}/{hourly_cap}). Cooling down...")
                            continue
                        if not auto_pilot and pending_approval_count >= max_pending_queue:
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Review Queue full ({pending_approval_count}/{max_pending_queue} pending). "
                                f"Skipping scan to save AI tokens until drafts are reviewed."
                            )
                            continue

                    worker = state.get_tenant_browser_worker(curr_tenant_id)

                    # Ensure cookies and API key persist across cloud container restarts
                    if not os.path.isfile(worker.cookies_backup_path) and cookies_json_val:
                        try:
                            saved_cookies = json.loads(cookies_json_val)
                            if isinstance(saved_cookies, list) and saved_cookies:
                                os.makedirs(worker.profile_dir, exist_ok=True)
                                with open(worker.cookies_backup_path, "w", encoding="utf-8") as f:
                                    json.dump(saved_cookies, f, indent=2)
                                logger.info(f"Tenant '{curr_tenant_id}': Restored session cookies from database.")
                        except Exception as ce:
                            logger.debug(f"Cookie restore note: {ce}")

                    if tenant_api_key_val and not os.getenv("DEEPSEEK_API_KEY") and not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
                        if tenant_api_key_val.startswith("sk-"):
                            os.environ["DEEPSEEK_API_KEY"] = tenant_api_key_val
                        else:
                            os.environ["GEMINI_API_KEY"] = tenant_api_key_val
                    try:
                        tenant_is_logged = await worker.check_login_status()
                        state.tenant_login_states[curr_tenant_id] = tenant_is_logged
                        if curr_tenant_id == "default":
                            state.is_session_logged_in = tenant_is_logged
                        if tenant_is_logged:
                            db = SessionLocal()
                            try:
                                state.sync_detected_username(db, tenant_id=curr_tenant_id, worker=worker)
                            finally:
                                db.close()
                    except Exception as e:
                        logger.error(f"Failed to check login status for tenant '{curr_tenant_id}': {e}")
                        tenant_is_logged = False

                    if not tenant_is_logged:
                        logger.warning(f"Tenant '{curr_tenant_id}' is not logged into X. Connect your account in the top bar.")
                        continue

                    # ==========================================================
                    # Dual-Engine Radar: Internet & Google Trend Scouting (2h Cache)
                    # ==========================================================
                    effective_query = base_query
                    web_topics = []
                    try:
                        web_topics = await scout_and_rank_topics(
                            niche=base_query or "technology",
                            limit=3,
                            tenant_id=curr_tenant_id,
                        )
                    except Exception as e:
                        logger.debug(f"Web scout pass note: {e}")

                    # If web topics found, bridge into live X search query & gate auto web draft (max 1/day)
                    if web_topics:
                        top_topic = web_topics[0]
                        s_query = top_topic.get("suggested_query")
                        if s_query and len(s_query) >= 3:
                            effective_query = s_query
                            logger.info(f"Tenant '{curr_tenant_id}': Web Radar selected breaking query '{effective_query}' from {top_topic.get('source')} ('{top_topic.get('title')[:45]}...')")

                        # Gate auto-staging: max 1 web trend draft per day & only when queue isn't full
                        if pending_approval_count < max_pending_queue:
                            db_web = SessionLocal()
                            try:
                                today_utc_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                                web_drafts_today = (
                                    db_web.query(ProcessedTweet)
                                    .filter(
                                        ProcessedTweet.tenant_id == curr_tenant_id,
                                        ProcessedTweet.tweet_id.like("web_%"),
                                        ProcessedTweet.timestamp >= today_utc_start,
                                    )
                                    .count()
                                )
                                topic_url = top_topic.get("url", "")
                                already_drafted = (
                                    db_web.query(ProcessedTweet)
                                    .filter(
                                        ProcessedTweet.tenant_id == curr_tenant_id,
                                        ProcessedTweet.tweet_url == topic_url,
                                    )
                                    .first()
                                )

                                if web_drafts_today < 1 and not already_drafted:
                                    drafts = await generate_draft_from_web_topic(
                                        topic=top_topic,
                                        persona_prompt=persona or "Casual, sharp, short sentences",
                                        model_name=selected_model,
                                        draft_type="tweet",
                                        tenant_id=curr_tenant_id,
                                    )
                                    single_text = drafts.get("single_tweet")
                                    if single_text:
                                        synth_id = f"web_{uuid.uuid4().hex[:12]}"
                                        new_post = ProcessedTweet(
                                            tweet_id=synth_id,
                                            tenant_id=curr_tenant_id,
                                            action_type="post",
                                            tweet_text=f"🌐 Google News Inspo: {top_topic.get('title')}\nSource: {top_topic.get('source')} ({topic_url})",
                                            tweet_author=f"Web: {top_topic.get('source')}",
                                            tweet_url=topic_url,
                                            generated_text=single_text,
                                            variants_json=None,
                                            tweet_metrics="🌐 Web Trend Radar",
                                            urgency_score=8,
                                            status="pending_approval",
                                            error_message=f"Autonomous Inspo from {top_topic.get('source')}",
                                        )
                                        db_web.add(new_post)
                                        db_web.commit()
                                        pending_approval_count += 1
                                        logger.info(f"Tenant '{curr_tenant_id}': Auto-staged web trend draft '{top_topic.get('title')[:40]}' in Review Queue.")
                            except Exception as ex:
                                logger.debug(f"Web draft staging note: {ex}")
                            finally:
                                db_web.close()

                    elif smart_query_on and base_query and base_query.strip():
                        effective_query = await generate_smart_search_query(
                            niche_topic=base_query,
                            recent_tweets=recent_sample_dicts,
                            model_name=selected_model,
                            tenant_id=curr_tenant_id,
                        )
                    state.active_search_query_state = effective_query or "Home Timeline"

                    logger.info(f"Tenant '{curr_tenant_id}': Scanning X feed for '{effective_query}' (learned: {learning_memory.get('total_learned', 0)})...")
                    tweets = await worker.scrape_feed(search_query=effective_query, limit=8)
                    logger.info(f"Tenant '{curr_tenant_id}': Collected {len(tweets)} candidate posts.")

                    db = SessionLocal()
                    try:
                        state.sync_detected_username(db, tenant_id=curr_tenant_id, worker=worker)
                    finally:
                        db.close()

                    # ==========================================================
                    # Zero-Token Python Spam Pre-Filter + Deduplication
                    # ==========================================================
                    clean_candidates = []
                    prefiltered_count = 0
                    new_count = 0

                    db = SessionLocal()
                    try:
                        for t in tweets:
                            tweet_id = t["tweet_id"]
                            if is_tweet_already_processed(db, tweet_id, tenant_id=curr_tenant_id):
                                continue

                            new_count += 1
                            skip_now, skip_reason = should_prefilter_skip(t)
                            if skip_now:
                                prefiltered_count += 1
                                logger.info(f"$0 Pre-filter skipped @{t['author']}: {skip_reason}")
                                record_processed_tweet(
                                    db=db,
                                    tweet_id=tweet_id,
                                    tenant_id=curr_tenant_id,
                                    action_type="reply",
                                    tweet_text=t["text"],
                                    tweet_author=t["author"],
                                    tweet_url=t["url"],
                                    media_url=t.get("media_url"),
                                    generated_text=None,
                                    variants_json=None,
                                    tweet_metrics=t.get("metrics"),
                                    status="skipped",
                                    error_message=skip_reason,
                                )
                                continue

                            clean_candidates.append(t)
                    finally:
                        db.close()

                    if prefiltered_count > 0:
                        logger.info(
                            f"Tenant '{curr_tenant_id}': $0 Pre-filter dropped {prefiltered_count}/{new_count} noisy posts; "
                            f"sending {len(clean_candidates)} clean post(s) in 1 batched AI call."
                        )

                    # ==========================================================
                    # Single Batched DeepSeek Evaluation (1 call instead of 8!)
                    # ==========================================================
                    if clean_candidates:
                        batch_results = await evaluate_tweets_batch(
                            tweets=clean_candidates,
                            model_name=selected_model,
                            search_query=base_query or effective_query,
                            persona_prompt=persona,
                            learning_memory=learning_memory,
                            include_variants=False,
                            tenant_id=curr_tenant_id,
                        )

                        for t in clean_candidates:
                            tweet_id = t["tweet_id"]
                            ai_result = batch_results.get(str(tweet_id))
                            if not ai_result:
                                continue

                            if ai_result.get("raw_response") == "NO_API_KEY":
                                logger.warning("Paused: AI API key not configured. Check environment variables.")
                                break

                            db = SessionLocal()
                            try:
                                if not ai_result["should_reply"]:
                                    logger.info(f"Skipped @{t['author']}: {ai_result['reasoning']}")
                                    record_processed_tweet(
                                        db=db,
                                        tweet_id=tweet_id,
                                        tenant_id=curr_tenant_id,
                                        action_type="reply",
                                        tweet_text=t["text"],
                                        tweet_author=t["author"],
                                        tweet_url=t["url"],
                                        media_url=t.get("media_url"),
                                        generated_text=None,
                                        variants_json=None,
                                        tweet_metrics=t.get("metrics"),
                                        status="skipped",
                                        error_message=ai_result["reasoning"],
                                    )
                                    continue

                                reply_text = ai_result["reply_text"]
                                variants_dict = ai_result.get("variants") or {}
                                variants_json = ai_result.get("variants_json")
                                should_like = bool(ai_result.get("should_like", False))
                                urgency_score = int(ai_result.get("urgency_score", 5))

                                # Anti-Detection Duplicate & Template Similarity Filter
                                if is_reply_too_similar(db, reply_text, tenant_id=curr_tenant_id):
                                    alt_chosen = None
                                    for alt_text in variants_dict.values():
                                        if alt_text and not is_reply_too_similar(db, alt_text, tenant_id=curr_tenant_id):
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
                                            tenant_id=curr_tenant_id,
                                            action_type="reply",
                                            tweet_text=t["text"],
                                            tweet_author=t["author"],
                                            tweet_url=t["url"],
                                            media_url=t.get("media_url"),
                                            generated_text=None,
                                            status="skipped",
                                            error_message="Filtered by Anti-Detection Similarity Shield",
                                        )
                                        continue

                                logger.info(f"Drafted for @{t['author']} [urgency {urgency_score}/10, like={should_like}]: '{reply_text}'")

                                if not auto_pilot:
                                    record_processed_tweet(
                                        db=db,
                                        tweet_id=tweet_id,
                                        tenant_id=curr_tenant_id,
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
                                        error_message=ai_result["reasoning"],
                                    )
                                else:
                                    cfg = get_agent_config(db, tenant_id=curr_tenant_id)
                                    sched_utc = compute_random_schedule_time(db, cfg, urgency_score=urgency_score)
                                    mins_away = max(1, int((sched_utc - datetime.utcnow()).total_seconds() // 60))
                                    logger.info(f"Autopilot scheduled reply to @{t['author']} in ~{mins_away}m (urgency {urgency_score}/10).")
                                    record_processed_tweet(
                                        db=db,
                                        tweet_id=tweet_id,
                                        tenant_id=curr_tenant_id,
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
                                        error_message=ai_result["reasoning"],
                                    )
                            finally:
                                db.close()

                    if new_count == 0 and len(tweets) > 0:
                        logger.info(f"All {len(tweets)} visible posts for '{effective_query}' were already evaluated.")

                    # ==========================================================
                    # Autonomous Original Post / Thread (Capped at 6/day)
                    # ==========================================================
                    if new_count >= 2:
                        db = SessionLocal()
                        try:
                            orig_today = get_daily_original_posts_count(db, tenant_id=curr_tenant_id)
                        finally:
                            db.close()

                        still_in_budget, _, _ = check_tenant_token_budget(curr_tenant_id)
                        if orig_today < daily_orig_cap and still_in_budget:
                            logger.info(
                                f"AI autonomously synthesizing original content from live '{effective_query}' pulse "
                                f"({orig_today + 1}/{daily_orig_cap} daily autonomous originals)..."
                            )
                            gen = await generate_original_content(
                                mode="auto",
                                search_query=base_query or effective_query,
                                persona_prompt=persona,
                                live_tweets=tweets,
                                model_name=selected_model,
                                learning_memory=learning_memory,
                                include_variants=False,
                                tenant_id=curr_tenant_id,
                            )
                            if gen.get("success") and gen.get("text"):
                                chosen_mode = gen.get("action_type") or "post"
                                orig_urgency = int(gen.get("urgency_score", 6))
                                db = SessionLocal()
                                try:
                                    cfg = get_agent_config(db, tenant_id=curr_tenant_id)
                                    orig_id = f"{chosen_mode}_{int(time.time() * 1000)}"
                                    author_label = (worker.logged_in_username or cfg.linked_username or "you").lstrip("@")
                                    if auto_pilot:
                                        sched_utc = compute_random_schedule_time(db, cfg, urgency_score=orig_urgency)
                                        record_processed_tweet(
                                            db=db,
                                            tweet_id=orig_id,
                                            tenant_id=curr_tenant_id,
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
                                            error_message=gen["topic_summary"],
                                        )
                                    else:
                                        record_processed_tweet(
                                            db=db,
                                            tweet_id=orig_id,
                                            tenant_id=curr_tenant_id,
                                            action_type=chosen_mode,
                                            tweet_text=gen["topic_summary"],
                                            tweet_author=author_label,
                                            tweet_url="https://x.com/home",
                                            generated_text=gen["text"],
                                            variants_json=gen.get("variants_json"),
                                            tweet_metrics="Live Pulse · Thread" if chosen_mode == "thread" else "Live Pulse · Original Post",
                                            urgency_score=orig_urgency,
                                            status="pending_approval",
                                            error_message=gen["topic_summary"],
                                        )
                                    logger.info(f"AI chose and drafted original {chosen_mode} (urgency {orig_urgency}/10) from live pulse for tenant '{curr_tenant_id}'.")
                                finally:
                                    db.close()
                        elif orig_today >= 6:
                            logger.info(f"Tenant '{curr_tenant_id}': Daily autonomous original post limit reached ({orig_today}/6).")

                except Exception as te:
                    logger.error(f"Error during feed scan for tenant '{curr_tenant_id}': {te}", exc_info=True)

            jittered_wait = int(min_interval_secs * random.uniform(0.65, 1.45)) + random.randint(3, 58)
            # Wake periodically (at most every 120s) so idle browser auto-sleep runs promptly even during long waits
            wait_deadline = time.time() + jittered_wait
            while time.time() < wait_deadline:
                remaining = wait_deadline - time.time()
                slice_sec = min(120.0, max(1.0, remaining))
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=slice_sec)
                    break
                except asyncio.TimeoutError:
                    await _sleep_idle_or_inactive_browsers()

        except Exception as e:
            logger.error(f"Unexpected error in background worker loop: {e}", exc_info=True)
            await asyncio.sleep(15)
