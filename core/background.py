"""
Autonomous Background Workers for X-VibeBot.
Runs the continuous feed scraping loop, AI tweet evaluation, multimodal analysis,
self-learning memory ingestion, and human-like randomized queue dispatcher.
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
    is_within_active_hours,
    get_daily_actions_count,
    get_hourly_actions_count,
    update_tweet_status,
    get_learning_memory,
    get_recent_tweets,
    is_tweet_already_processed,
    record_processed_tweet,
    is_reply_too_similar,
    compute_random_schedule_time
)
from ai_engine import (
    evaluate_tweet,
    generate_original_content,
    generate_smart_search_query
)
from models import AgentConfig, ProcessedTweet
from core.web_scout import scout_and_rank_topics, generate_draft_from_web_topic
import core.state as state

logger = logging.getLogger("x_vibebot.background")


# ==============================================================================
# Randomized Scheduled Queue Dispatcher Loop
# ==============================================================================

async def scheduled_queue_dispatcher_loop():
    """
    Continuously checks for scheduled replies whose randomized `scheduled_for`
    timestamp has arrived and dispatches them organically while respecting
    the rolling 60-minute anti-detection velocity cap and warmup mode.
    Dispatches using the target post's tenant browser worker.
    """
    logger.info("Random schedule dispatcher initialized.")
    await asyncio.sleep(5)

    while True:
        try:
            if state.is_manual_login_active:
                await asyncio.sleep(10)
                continue

            db = SessionLocal()
            try:
                due_items = get_due_scheduled_tweets(db)
            finally:
                db.close()

            if due_items:
                for target in due_items:
                    target_tenant = getattr(target, "tenant_id", None) or "default"
                    db = SessionLocal()
                    try:
                        config = get_agent_config(db, tenant_id=target_tenant)
                        within_hours = is_within_active_hours(
                            config.active_hours_start or 8,
                            config.active_hours_end or 23
                        )
                        if not within_hours:
                            resched = datetime.utcnow() + timedelta(minutes=30)
                            update_tweet_status(db, target.tweet_id, status="scheduled", scheduled_for=resched, tenant_id=target_tenant)
                            continue

                        warmup = bool(getattr(config, "warmup_mode", False))
                        daily_used = get_daily_actions_count(db, tenant_id=target_tenant)
                        daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
                        hourly_used = get_hourly_actions_count(db, tenant_id=target_tenant)
                        hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
                        min_cd = config.min_cooldown_minutes or 10
                        max_cd = config.max_cooldown_minutes or 45

                        if daily_used >= daily_cap or hourly_used >= hourly_cap:
                            logger.info(f"Target tenant '{target_tenant}' cap reached ({daily_used}/{daily_cap} daily, {hourly_used}/{hourly_cap} hourly). Postponing scheduled item.")
                            postpone_mins = 240 if daily_used >= daily_cap else 25
                            resched = datetime.utcnow() + timedelta(minutes=postpone_mins)
                            update_tweet_status(db, target.tweet_id, status="scheduled", scheduled_for=resched, tenant_id=target_tenant)
                            continue
                    finally:
                        db.close()

                    act_type = target.action_type or "reply"
                    logger.info(f"Scheduled time reached for {act_type} ({target.tweet_id}) [tenant={target_tenant}]. Publishing now (hourly {hourly_used + 1}/{hourly_cap})...")
                    worker = state.get_tenant_browser_worker(target_tenant)
                    if not os.path.isfile(worker.cookies_backup_path) and getattr(config, "cookies_json", None):
                        try:
                            saved_cookies = json.loads(config.cookies_json)
                            if isinstance(saved_cookies, list) and saved_cookies:
                                os.makedirs(worker.profile_dir, exist_ok=True)
                                with open(worker.cookies_backup_path, "w", encoding="utf-8") as f:
                                    json.dump(saved_cookies, f, indent=2)
                        except Exception:
                            pass
                    success = await worker.execute_tweet_action(
                        act_type,
                        target.tweet_id,
                        target.generated_text,
                        target.tweet_url,
                        should_like=bool(getattr(target, "should_like", False))
                    )
                    db = SessionLocal()
                    try:
                        state.sync_detected_username(db, tenant_id=target_tenant, worker=worker)
                        if success:
                            state.set_new_random_cooldown(min_cd, max_cd)
                            update_tweet_status(db, target.tweet_id, status="posted", tenant_id=target_tenant)
                            logger.info(f"Successfully published scheduled {act_type} ({target.tweet_id}) for tenant '{target_tenant}'!")
                        else:
                            err_msg = getattr(worker, "last_error", None) or f"Browser failed while publishing scheduled {act_type}"
                            update_tweet_status(
                                db,
                                target.tweet_id,
                                status="failed",
                                error_message=err_msg,
                                tenant_id=target_tenant
                            )
                    finally:
                        db.close()
                    break

            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Error in scheduled dispatcher loop: {e}")
            await asyncio.sleep(15)


# ==============================================================================
# Autonomous Scraper & Evaluation Background Loop
# ==============================================================================

async def background_automation_loop():
    """
    Continuous background loop with Multi-Tenant isolation, Smart AI Search Discovery,
    Multimodal Vision, Self-Learning Voice Memory, Duplicate Similarity Filtering, and Urgency Scheduling.
    """
    logger.info("Background automation worker loop initialized.")
    await asyncio.sleep(3)

    while True:
        try:
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

            # 2. Check active tenants from database
            db = SessionLocal()
            try:
                active_configs = db.query(AgentConfig).filter(AgentConfig.is_active == True).all()
                active_tenant_ids = [c.tenant_id for c in active_configs if c.tenant_id]
            finally:
                db.close()

            # Build prioritized list of (tenant_id, is_manual)
            tenants_to_scan = []
            for tid in manual_tenants:
                tenants_to_scan.append((tid, True))
            for tid in active_tenant_ids:
                if not any(t[0] == tid for t in tenants_to_scan):
                    tenants_to_scan.append((tid, False))

            if not tenants_to_scan:
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=5.0)
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
                        if not is_manual and not config.is_active:
                            continue
                        auto_pilot = config.auto_pilot_mode
                        base_interval_secs = max(1, config.polling_interval_minutes) * 60
                        if base_interval_secs < min_interval_secs:
                            min_interval_secs = base_interval_secs
                        warmup = bool(getattr(config, "warmup_mode", False))
                        daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
                        hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
                        smart_query_on = bool(getattr(config, "smart_query_enabled", True))
                        base_query = config.search_query
                        persona = config.persona_prompt
                        selected_model = config.selected_model or "auto"
                        start_hr = config.active_hours_start if config.active_hours_start is not None else 8
                        end_hr = config.active_hours_end if config.active_hours_end is not None else 23
                        daily_used = get_daily_actions_count(db, tenant_id=curr_tenant_id)
                        hourly_used = get_hourly_actions_count(db, tenant_id=curr_tenant_id)
                        learning_memory = get_learning_memory(db, tenant_id=curr_tenant_id)
                        recent_rows = get_recent_tweets(db, limit=6, tenant_id=curr_tenant_id)
                        recent_sample_dicts = [{"text": r.tweet_text} for r in recent_rows if r.tweet_text]
                    finally:
                        db.close()

                    # Check Active Hours & Caps for scheduled automated runs
                    if not is_manual:
                        if not is_within_active_hours(start_hr, end_hr):
                            logger.info(f"Tenant '{curr_tenant_id}': Outside active hours ({start_hr:02d}:00-{end_hr:02d}:00). Sleeping...")
                            continue
                        if daily_used >= daily_cap:
                            logger.warning(f"Tenant '{curr_tenant_id}': Daily cap reached ({daily_used}/{daily_cap}). Pausing until tomorrow.")
                            continue
                        if hourly_used >= hourly_cap:
                            logger.info(f"Tenant '{curr_tenant_id}': Hourly cap reached ({hourly_used}/{hourly_cap}). Cooling down...")
                            continue

                    worker = state.get_tenant_browser_worker(curr_tenant_id)

                    # Ensure cookies and API key persist across cloud container restarts
                    if not os.path.isfile(worker.cookies_backup_path) and getattr(config, "cookies_json", None):
                        try:
                            saved_cookies = json.loads(config.cookies_json)
                            if isinstance(saved_cookies, list) and saved_cookies:
                                os.makedirs(worker.profile_dir, exist_ok=True)
                                with open(worker.cookies_backup_path, "w", encoding="utf-8") as f:
                                    json.dump(saved_cookies, f, indent=2)
                                logger.info(f"Tenant '{curr_tenant_id}': Restored session cookies from database.")
                        except Exception as ce:
                            logger.debug(f"Cookie restore note: {ce}")

                    if getattr(config, "api_key", None) and not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
                        if config.api_key.startswith("sk-"):
                            os.environ["DEEPSEEK_API_KEY"] = config.api_key
                        else:
                            os.environ["GEMINI_API_KEY"] = config.api_key
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
                    # Dual-Engine Radar: Internet & Google Trend Scouting
                    # ==========================================================
                    effective_query = base_query
                    web_topics = []
                    try:
                        web_topics = await scout_and_rank_topics(niche=base_query or "technology", limit=3)
                    except Exception as e:
                        logger.debug(f"Web scout pass note: {e}")

                    # If web topics found, bridge into live X search query & auto-draft
                    if web_topics:
                        top_topic = web_topics[0]
                        s_query = top_topic.get("suggested_query")
                        if s_query and len(s_query) >= 3:
                            effective_query = s_query
                            logger.info(f"Tenant '{curr_tenant_id}': Web Radar selected breaking query '{effective_query}' from {top_topic.get('source')} ('{top_topic.get('title')[:45]}...')")

                        # Auto-stage top web story into Review Queue as an original post draft if not already drafted
                        db_web = SessionLocal()
                        try:
                            topic_url = top_topic.get("url", "")
                            already_drafted = db_web.query(ProcessedTweet).filter(
                                ProcessedTweet.tenant_id == curr_tenant_id,
                                ProcessedTweet.tweet_url == topic_url
                            ).first()

                            if not already_drafted:
                                drafts = await generate_draft_from_web_topic(
                                    topic=top_topic,
                                    persona_prompt=persona or "Casual, sharp, short sentences",
                                    model_name=selected_model
                                )
                                synth_id = f"web_{uuid.uuid4().hex[:12]}"
                                new_post = ProcessedTweet(
                                    tweet_id=synth_id,
                                    tenant_id=curr_tenant_id,
                                    action_type="post",
                                    tweet_text=f"🌐 Google News Inspo: {top_topic.get('title')}\nSource: {top_topic.get('source')} ({topic_url})",
                                    tweet_author=f"Web: {top_topic.get('source')}",
                                    tweet_url=topic_url,
                                    generated_text=drafts.get("single_tweet"),
                                    variants_json=json.dumps({
                                        "witty": drafts.get("single_tweet"),
                                        "thread": drafts.get("thread"),
                                        "topic_source": top_topic.get("source"),
                                        "topic_url": topic_url
                                    }),
                                    tweet_metrics="🌐 Web Trend Radar",
                                    urgency_score=8,
                                    status="pending_approval",
                                    error_message=f"Autonomous Inspo from {top_topic.get('source')}"
                                )
                                db_web.add(new_post)
                                db_web.commit()
                                logger.info(f"Tenant '{curr_tenant_id}': Auto-staged web trend draft '{top_topic.get('title')[:40]}' in Review Queue.")
                        except Exception as ex:
                            logger.debug(f"Web draft staging note: {ex}")
                        finally:
                            db_web.close()

                    elif smart_query_on and base_query and base_query.strip():
                        effective_query = await generate_smart_search_query(
                            niche_topic=base_query,
                            recent_tweets=recent_sample_dicts,
                            model_name=selected_model
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

                    new_count = 0
                    for t in tweets:
                        tweet_id = t["tweet_id"]
                        db = SessionLocal()
                        try:
                            already_done = is_tweet_already_processed(db, tweet_id, tenant_id=curr_tenant_id)
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
                            logger.warning("Paused: Paste your Google Gemini API key in Settings first.")
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
                                    error_message=ai_result["reasoning"]
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
                                        error_message="Filtered by Anti-Detection Similarity Shield"
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
                                    error_message=ai_result["reasoning"]
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
                                    error_message=ai_result["reasoning"]
                                )
                        finally:
                            db.close()

                        await asyncio.sleep(random.uniform(1.2, 2.5))

                    if new_count == 0 and len(tweets) > 0:
                        logger.info(f"All {len(tweets)} visible posts for '{effective_query}' were already evaluated.")

                    # Autonomously synthesize 1 original Post or Thread
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
                                        error_message=gen["topic_summary"]
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
                                        error_message=gen["topic_summary"]
                                    )
                                logger.info(f"AI chose and drafted original {chosen_mode} (urgency {orig_urgency}/10) from live pulse for tenant '{curr_tenant_id}'.")
                            finally:
                                db.close()

                except Exception as te:
                    logger.error(f"Error during feed scan for tenant '{curr_tenant_id}': {te}", exc_info=True)

            jittered_wait = int(min_interval_secs * random.uniform(0.65, 1.45)) + random.randint(3, 58)
            try:
                await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=jittered_wait)
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            logger.error(f"Unexpected error in background worker loop: {e}", exc_info=True)
            await asyncio.sleep(15)
