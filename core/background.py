"""
Autonomous Background Workers for X-VibeBot.
Runs the continuous feed scraping loop, async action dispatcher, and scheduled dispatcher with:
- Per-tenant log context & SSE notifications
- Encrypted personal API key & cookie handling (zero global os.environ mutation)
- Atomic dispatch claims, startup stale-dispatch recovery, and batch velocity tracking
- Per-tenant next_scan_at scheduling, timeout guards, and worker memory eviction
- Batch SQL deduplication, in-memory similarity filtering, and single-transaction commits
"""

import os
import asyncio
import logging
import random
import time
import uuid
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from database import (
    SessionLocal,
    get_due_scheduled_tweets,
    get_agent_config,
    get_decrypted_api_key,
    get_decrypted_cookies_json,
    get_platform_settings,
    is_within_active_hours,
    get_daily_actions_count,
    get_hourly_actions_count,
    get_daily_original_posts_count,
    get_pending_approval_count,
    update_tweet_status,
    claim_tweet_for_dispatch,
    recover_stale_dispatching_tweets,
    get_learning_memory,
    get_recent_tweets,
    get_processed_tweet_ids_batch,
    get_recent_reply_texts,
    is_text_too_similar_to_list,
    record_processed_tweet,
    compute_random_schedule_time,
    expire_stale_drafts,
)
from services.plans import is_subscription_valid
from ai_engine import (
    evaluate_tweets_batch,
    generate_original_content,
    generate_smart_search_query,
    should_prefilter_skip,
    async_check_tenant_token_budget,
)
from models import AgentConfig, ProcessedTweet
from core.web_scout import scout_and_rank_topics, generate_draft_from_web_topic
import core.state as state

logger = logging.getLogger("x_vibebot.background")


def _restore_worker_cookies(worker, cookies_json_val: Optional[str], tenant_id: str) -> None:
    """Writes decrypted cookies to the worker's profile backup with strict 0o600 permissions."""
    if not os.path.isfile(worker.cookies_backup_path) and cookies_json_val:
        try:
            saved_cookies = json.loads(cookies_json_val)
            if isinstance(saved_cookies, list) and saved_cookies:
                os.makedirs(worker.profile_dir, exist_ok=True)
                with open(worker.cookies_backup_path, "w", encoding="utf-8") as f:
                    json.dump(saved_cookies, f, indent=2)
                try:
                    os.chmod(worker.cookies_backup_path, 0o600)
                except Exception:
                    pass
                logger.info(f"Tenant '{tenant_id}': Restored session cookies from database.")
        except Exception as ce:
            logger.debug(f"Cookie restore note: {ce}")


# ==============================================================================
# Browser Auto-Sleep Reaper (RAM Optimization)
# ==============================================================================

async def _sleep_idle_or_inactive_browsers():
    """
    Reclaims ~150-300 MB RAM per Chromium process by stopping idle/inactive browser workers
    and evicting stopped non-default workers from memory.
    """
    running_items = [
        (tid, w)
        for tid, w in list(state.tenant_workers.items())
        if getattr(w, "is_running", False) and not state.is_manual_login(tid)
    ]
    if not running_items:
        return

    def _find_workers_to_sleep():
        db = SessionLocal()
        try:
            ps = get_platform_settings(db)
            if not bool(getattr(ps, "auto_sleep_browsers_enabled", True)):
                return []
            idle_limit_secs = max(60, int(getattr(ps, "browser_idle_sleep_minutes", 15) or 15) * 60)
            global_paused = bool(getattr(ps, "global_pause_bots", False))
            now_ts = time.time()
            targets = []

            for tid, worker in running_items:
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
                        targets.append((tid, worker, reason))
                except Exception as we:
                    logger.debug(f"Browser auto-sleep check notice for '{tid}': {we}")
            return targets
        finally:
            db.close()

    try:
        to_sleep = await asyncio.to_thread(_find_workers_to_sleep)
        for tid, worker, reason in to_sleep:
            try:
                logger.info(
                    f"Browser Auto-Sleep: Stopping Chromium for tenant '{tid}' ({reason}) to reclaim RAM."
                )
                await worker.stop()
                state.evict_stopped_worker(tid)
            except Exception as se:
                logger.debug(f"Browser auto-sleep stop notice for '{tid}': {se}")
    except Exception as e:
        logger.debug(f"Browser auto-sleep pass notice: {e}")


# ==============================================================================
# High-Speed Async Action Dispatcher Loop
# ==============================================================================

async def async_action_dispatcher_loop():
    """
    Dedicated high-speed Async Action Dispatcher.
    Recovers stale 'dispatching' rows on startup, processes jobs with strict try/finally
    task_done() accounting, updates DB status only after Playwright confirms, and emits SSE events.
    """
    logger.info("High-speed Async Action Dispatcher initialized.")

    def _recover_stale():
        db = SessionLocal()
        try:
            return recover_stale_dispatching_tweets(db)
        finally:
            db.close()

    try:
        recovered = await asyncio.to_thread(_recover_stale)
        if recovered > 0:
            logger.info(
                f"Async Action Dispatcher: Recovered {recovered} stale dispatching tweet(s) to failed."
            )
    except Exception as rec_err:
        logger.warning(f"Stale dispatching recovery notice: {rec_err}")

    while True:
        try:
            job = await state.action_dispatch_queue.get()
        except asyncio.CancelledError:
            break

        tok = None
        tenant_id = "default"
        tweet_id = None
        act_type = "reply"
        text_to_post = ""
        was_user_edited = False
        should_like = False
        min_cd = 10
        max_cd = 45
        worker = None
        success = False
        err_msg = None

        try:
            tenant_id = job.get("tenant_id") or "default"
            tok = state.set_log_tenant_context(tenant_id)
            tweet_id = job["tweet_id"]
            act_type = job.get("action_type") or "reply"
            text_to_post = job["text"]
            tweet_url = job.get("tweet_url")
            should_like = bool(job.get("should_like", False))
            was_user_edited = bool(job.get("was_user_edited", False))
            min_cd = job.get("min_cooldown", 10)
            max_cd = job.get("max_cooldown", 45)

            logger.info(
                f"Async Action Dispatcher: Processing {act_type} ({tweet_id}) [tenant={tenant_id}]..."
            )
            worker = state.get_tenant_browser_worker(tenant_id)

            try:
                success = await asyncio.wait_for(
                    worker.execute_tweet_action(
                        act_type,
                        tweet_id,
                        text_to_post,
                        tweet_url,
                        should_like=should_like,
                    ),
                    timeout=180.0,
                )
            except asyncio.TimeoutError:
                success = False
                err_msg = f"Browser timed out while executing {act_type}"
            except Exception as exec_err:
                success = False
                err_msg = str(exec_err)

            if not success and not err_msg:
                err_msg = (
                    getattr(worker, "last_error", None)
                    or f"Browser failed during {act_type} submission"
                )

            def _update_db_after_action():
                db = SessionLocal()
                try:
                    if worker is not None:
                        state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
                    if success:
                        state.set_new_random_cooldown(min_cd, max_cd, tenant_id=tenant_id)
                        update_tweet_status(
                            db,
                            tweet_id,
                            status="posted",
                            generated_text=text_to_post,
                            user_edited=was_user_edited,
                            should_like=should_like,
                            tenant_id=tenant_id,
                        )
                        logger.info(
                            f"Async Action Dispatcher: Successfully published {act_type} ({tweet_id})!"
                        )
                    else:
                        update_tweet_status(
                            db,
                            tweet_id,
                            status="failed",
                            generated_text=text_to_post,
                            error_message=err_msg,
                            tenant_id=tenant_id,
                        )
                        logger.error(
                            f"Async Action Dispatcher: Failed {act_type} ({tweet_id}): {err_msg}"
                        )
                finally:
                    db.close()

            await asyncio.to_thread(_update_db_after_action)

            state.emit_tenant_event(
                tenant_id,
                "action_completed",
                {
                    "tweet_id": tweet_id,
                    "action_type": act_type,
                    "success": bool(success),
                    "status": "posted" if success else "failed",
                    "error": err_msg if not success else None,
                },
            )
            state.emit_tenant_event(
                tenant_id,
                "queue_changed",
                {"tweet_id": tweet_id, "status": "posted" if success else "failed"},
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in async action dispatcher: {e}", exc_info=True)
            if tweet_id:
                def _mark_failed_on_error():
                    db = SessionLocal()
                    try:
                        update_tweet_status(
                            db,
                            tweet_id,
                            status="failed",
                            error_message=str(e),
                            tenant_id=tenant_id,
                        )
                    finally:
                        db.close()

                try:
                    await asyncio.to_thread(_mark_failed_on_error)
                except Exception:
                    pass
            await asyncio.sleep(1)
        finally:
            if tok is not None:
                state.reset_log_tenant_context(tok)
            state.action_dispatch_queue.task_done()


# ==============================================================================
# Randomized Scheduled Queue Dispatcher Loop
# ==============================================================================

async def scheduled_queue_dispatcher_loop():
    """
    Continuously checks for scheduled tweets whose randomized `scheduled_for`
    timestamp has arrived and dispatches them atomically while enforcing:
    - Per-tenant manual login check
    - Per-tenant randomized cooldown window
    - Batch-wide daily & rolling 60-min velocity quota tracking
    """
    logger.info("Random schedule dispatcher initialized.")
    await asyncio.sleep(3)

    while True:
        try:
            def _get_due_snapshots() -> List[Dict[str, Any]]:
                db = SessionLocal()
                try:
                    ps = get_platform_settings(db)
                    if bool(getattr(ps, "global_pause_bots", False)):
                        return []
                    rows = get_due_scheduled_tweets(db)
                    return [
                        {
                            "tweet_id": r.tweet_id,
                            "tenant_id": getattr(r, "tenant_id", None) or "default",
                            "action_type": r.action_type or "reply",
                            "generated_text": r.generated_text,
                            "tweet_url": r.tweet_url,
                            "should_like": bool(getattr(r, "should_like", False)),
                            "user_edited": bool(getattr(r, "user_edited", False)),
                        }
                        for r in rows
                    ]
                finally:
                    db.close()

            due_items = await asyncio.to_thread(_get_due_snapshots)

            if due_items:
                tenant_quota_remaining: Dict[str, Tuple[int, int]] = {}

                for target in due_items:
                    target_tenant = target["tenant_id"]
                    tweet_id = target["tweet_id"]
                    tok = state.set_log_tenant_context(target_tenant)
                    try:
                        if state.is_manual_login(target_tenant):
                            continue

                        cooldown_rem = state.get_cooldown_remaining(target_tenant)
                        if cooldown_rem > 0:
                            def _postpone_cooldown():
                                db = SessionLocal()
                                try:
                                    resched = datetime.utcnow() + timedelta(
                                        seconds=cooldown_rem + random.randint(5, 30)
                                    )
                                    claim_tweet_for_dispatch(
                                        db,
                                        tweet_id=tweet_id,
                                        tenant_id=target_tenant,
                                        allowed_from_statuses=("scheduled",),
                                        new_status="scheduled",
                                        scheduled_for=resched,
                                    )
                                finally:
                                    db.close()

                            await asyncio.to_thread(_postpone_cooldown)
                            continue

                        if not (target["generated_text"] or "").strip():
                            def _mark_empty_failed():
                                db = SessionLocal()
                                try:
                                    update_tweet_status(
                                        db,
                                        tweet_id,
                                        status="failed",
                                        error_message="Scheduled tweet text was empty",
                                        tenant_id=target_tenant,
                                    )
                                finally:
                                    db.close()

                            await asyncio.to_thread(_mark_empty_failed)
                            continue

                        def _check_and_claim():
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
                                    claim_tweet_for_dispatch(
                                        db,
                                        tweet_id=tweet_id,
                                        tenant_id=target_tenant,
                                        allowed_from_statuses=("scheduled",),
                                        new_status="scheduled",
                                        scheduled_for=resched,
                                    )
                                    return False, None

                                if target_tenant not in tenant_quota_remaining:
                                    daily_cap = config.effective_daily_cap()
                                    hourly_cap = config.effective_hourly_cap()
                                    daily_used = get_daily_actions_count(db, tenant_id=target_tenant)
                                    hourly_used = get_hourly_actions_count(db, tenant_id=target_tenant)
                                    tenant_quota_remaining[target_tenant] = (
                                        max(0, daily_cap - daily_used),
                                        max(0, hourly_cap - hourly_used),
                                    )

                                daily_rem, hourly_rem = tenant_quota_remaining[target_tenant]
                                if daily_rem <= 0 or hourly_rem <= 0:
                                    postpone_mins = 240 if daily_rem <= 0 else 25
                                    resched = datetime.utcnow() + timedelta(minutes=postpone_mins)
                                    claim_tweet_for_dispatch(
                                        db,
                                        tweet_id=tweet_id,
                                        tenant_id=target_tenant,
                                        allowed_from_statuses=("scheduled",),
                                        new_status="scheduled",
                                        scheduled_for=resched,
                                    )
                                    return False, None

                                claimed = claim_tweet_for_dispatch(
                                    db,
                                    tweet_id=tweet_id,
                                    tenant_id=target_tenant,
                                    allowed_from_statuses=("scheduled",),
                                    new_status="dispatching",
                                )
                                if not claimed:
                                    return False, None

                                tenant_quota_remaining[target_tenant] = (
                                    daily_rem - 1,
                                    hourly_rem - 1,
                                )
                                min_cd = config.min_cooldown_minutes or 10
                                max_cd = config.max_cooldown_minutes or 45
                                return True, (min_cd, max_cd)
                            finally:
                                db.close()

                        should_dispatch, cd_tuple = await asyncio.to_thread(_check_and_claim)
                        if not should_dispatch or not cd_tuple:
                            continue

                        min_cd, max_cd = cd_tuple
                        act_type = target["action_type"]
                        logger.info(
                            f"Scheduled time reached for {act_type} ({tweet_id}) "
                            f"[tenant={target_tenant}]. Enqueueing to async dispatcher..."
                        )

                        try:
                            state.action_dispatch_queue.put_nowait({
                                "tenant_id": target_tenant,
                                "tweet_id": tweet_id,
                                "action_type": act_type,
                                "text": target["generated_text"],
                                "tweet_url": target["tweet_url"],
                                "should_like": target["should_like"],
                                "was_user_edited": target["user_edited"],
                                "min_cooldown": min_cd,
                                "max_cooldown": max_cd,
                            })
                            state.emit_tenant_event(
                                target_tenant,
                                "queue_changed",
                                {"tweet_id": tweet_id, "status": "dispatching"},
                            )
                        except asyncio.QueueFull:
                            def _revert_queue_full():
                                db = SessionLocal()
                                try:
                                    claim_tweet_for_dispatch(
                                        db,
                                        tweet_id=tweet_id,
                                        tenant_id=target_tenant,
                                        allowed_from_statuses=("dispatching",),
                                        new_status="scheduled",
                                        scheduled_for=datetime.utcnow() + timedelta(minutes=2),
                                    )
                                finally:
                                    db.close()

                            await asyncio.to_thread(_revert_queue_full)
                            logger.warning(
                                f"Action dispatch queue full while scheduling {tweet_id}; postponed 2m."
                            )
                    finally:
                        state.reset_log_tenant_context(tok)

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
    Continuous background loop with per-tenant next_scan_at scheduling,
    Global Pause / Suspension guardrails, Daily Token Cap enforcement,
    Zero-Token Spam Pre-Filter, Single Batched Evaluation, and single-commit DB writes.
    """
    logger.info("Background automation worker loop initialized.")
    await asyncio.sleep(3)

    next_scan_at: Dict[str, float] = {}

    while True:
        try:
            # 0. Reap any idle/sleeping Chromium instances to keep RAM low
            await _sleep_idle_or_inactive_browsers()

            # 1. Clear wakeup flag BEFORE draining queue so concurrent triggers aren't dropped
            was_flag_set = state.scrape_now_flag.is_set()
            state.scrape_now_flag.clear()
            manual_tenants: List[str] = []
            while not state.tenant_scrape_queue.empty():
                try:
                    tid = state.tenant_scrape_queue.get_nowait()
                    if tid and tid not in manual_tenants:
                        manual_tenants.append(tid)
                except asyncio.QueueEmpty:
                    break

            if was_flag_set and not manual_tenants:
                manual_tenants.append("default")

            # 2. Read PlatformSettings & active tenants from database
            def _load_global_and_active():
                db = SessionLocal()
                try:
                    ps = get_platform_settings(db)
                    g_pause = bool(getattr(ps, "global_pause_bots", False))
                    if g_pause:
                        return True, []
                    active_configs = (
                        db.query(AgentConfig.tenant_id, AgentConfig.polling_interval_minutes)
                        .filter(AgentConfig.is_active == True, AgentConfig.is_suspended == False)
                        .all()
                    )
                    return False, [
                        (row.tenant_id, max(1, int(row.polling_interval_minutes or 20)) * 60)
                        for row in active_configs
                        if row.tenant_id
                    ]
                finally:
                    db.close()

            global_pause, active_tenants_info = await asyncio.to_thread(_load_global_and_active)

            if global_pause:
                if manual_tenants:
                    logger.warning("Global Bot Pause is active (Super Admin). Skipping scan triggers.")
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    pass
                continue

            active_interval_map = {tid: secs for tid, secs in active_tenants_info}
            for stale_tid in list(next_scan_at.keys()):
                if stale_tid not in active_interval_map and stale_tid not in manual_tenants:
                    next_scan_at.pop(stale_tid, None)

            now_ts = time.time()
            tenants_to_scan: List[Tuple[str, bool]] = []
            for tid in manual_tenants:
                tenants_to_scan.append((tid, True))
            for tid, _ in active_tenants_info:
                if tid in manual_tenants:
                    continue
                if now_ts >= next_scan_at.get(tid, 0.0):
                    tenants_to_scan.append((tid, False))

            if not tenants_to_scan:
                next_due = min(
                    (next_scan_at.get(tid, now_ts + 10.0) for tid, _ in active_tenants_info),
                    default=now_ts + 10.0,
                )
                wait_secs = max(5.0, min(120.0, next_due - time.time()))
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=wait_secs)
                except asyncio.TimeoutError:
                    pass
                continue

            for curr_tenant_id, is_manual in tenants_to_scan:
                tok = state.set_log_tenant_context(curr_tenant_id)
                try:
                    if not is_manual and state.is_manual_login(curr_tenant_id):
                        continue

                    def _load_tenant_ctx():
                        db = SessionLocal()
                        try:
                            config = get_agent_config(db, tenant_id=curr_tenant_id)
                            is_susp = bool(getattr(config, "is_suspended", False))
                            sub_ok, sub_status, _ = is_subscription_valid(config)
                            auto_sleep = bool(getattr(config, "auto_sleep_browser", True))
                            is_active_flag = bool(config.is_active)
                            auto_pilot = bool(config.auto_pilot_mode)
                            base_int_secs = max(1, int(config.polling_interval_minutes or 20)) * 60
                            daily_cap = config.effective_daily_cap()
                            hourly_cap = config.effective_hourly_cap()
                            daily_orig_cap = int(getattr(config, "daily_original_post_cap", 3) or 3)
                            max_pending_queue = int(getattr(config, "max_pending_queue", 8) or 8)
                            smart_query_on = bool(getattr(config, "smart_query_enabled", True))
                            base_query = config.search_query
                            persona = config.persona_prompt
                            selected_model = config.selected_model or "auto"
                            start_hr = config.active_hours_start if config.active_hours_start is not None else 8
                            end_hr = config.active_hours_end if config.active_hours_end is not None else 23
                            cookies_json_val = get_decrypted_cookies_json(config)
                            tenant_api_key_val = get_decrypted_api_key(config)
                            linked_username = config.linked_username

                            if is_susp or not sub_ok or (not is_manual and not is_active_flag):
                                return {
                                    "proceed": False,
                                    "is_suspended": is_susp,
                                    "sub_ok": sub_ok,
                                    "sub_status": sub_status,
                                    "auto_sleep": auto_sleep,
                                    "is_active": is_active_flag,
                                    "base_interval_secs": base_int_secs,
                                }

                            daily_used = get_daily_actions_count(db, tenant_id=curr_tenant_id)
                            hourly_used = get_hourly_actions_count(db, tenant_id=curr_tenant_id)
                            expire_stale_drafts(db, tenant_id=curr_tenant_id, max_age_hours=24)
                            pending_approval_count = get_pending_approval_count(db, tenant_id=curr_tenant_id)
                            learning_memory = get_learning_memory(
                                db, limit_approved=4, limit_skipped=3, tenant_id=curr_tenant_id
                            )
                            recent_rows = get_recent_tweets(db, limit=6, tenant_id=curr_tenant_id)
                            recent_sample_dicts = [
                                {"text": r.tweet_text} for r in recent_rows if r.tweet_text
                            ]

                            return {
                                "proceed": True,
                                "auto_sleep": auto_sleep,
                                "auto_pilot": auto_pilot,
                                "base_interval_secs": base_int_secs,
                                "daily_cap": daily_cap,
                                "hourly_cap": hourly_cap,
                                "daily_orig_cap": daily_orig_cap,
                                "max_pending_queue": max_pending_queue,
                                "smart_query_on": smart_query_on,
                                "base_query": base_query,
                                "persona": persona,
                                "selected_model": selected_model,
                                "start_hr": start_hr,
                                "end_hr": end_hr,
                                "daily_used": daily_used,
                                "hourly_used": hourly_used,
                                "pending_approval_count": pending_approval_count,
                                "learning_memory": learning_memory,
                                "recent_sample_dicts": recent_sample_dicts,
                                "cookies_json_val": cookies_json_val,
                                "tenant_api_key_val": tenant_api_key_val,
                                "linked_username": linked_username,
                            }
                        finally:
                            db.close()

                    t_ctx = await asyncio.to_thread(_load_tenant_ctx)
                    base_interval_secs = t_ctx["base_interval_secs"]
                    next_scan_at[curr_tenant_id] = (
                        time.time()
                        + int(base_interval_secs * random.uniform(0.65, 1.45))
                        + random.randint(3, 58)
                    )

                    if not t_ctx["proceed"]:
                        if t_ctx["is_suspended"]:
                            logger.warning(
                                f"Tenant '{curr_tenant_id}' is suspended by Super Admin. Skipping."
                            )
                        elif not t_ctx["sub_ok"]:
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Subscription is {t_ctx['sub_status']}. Skipping automated bot scan."
                            )
                            worker_sub = state.tenant_workers.get(curr_tenant_id)
                            if worker_sub and worker_sub.is_running and t_ctx["auto_sleep"]:
                                await worker_sub.stop()
                                state.evict_stopped_worker(curr_tenant_id)
                        continue

                    auto_pilot = t_ctx["auto_pilot"]
                    daily_cap = t_ctx["daily_cap"]
                    hourly_cap = t_ctx["hourly_cap"]
                    daily_orig_cap = t_ctx["daily_orig_cap"]
                    max_pending_queue = t_ctx["max_pending_queue"]
                    smart_query_on = t_ctx["smart_query_on"]
                    base_query = t_ctx["base_query"]
                    persona = t_ctx["persona"]
                    selected_model = t_ctx["selected_model"]
                    start_hr = t_ctx["start_hr"]
                    end_hr = t_ctx["end_hr"]
                    daily_used = t_ctx["daily_used"]
                    hourly_used = t_ctx["hourly_used"]
                    pending_approval_count = t_ctx["pending_approval_count"]
                    learning_memory = t_ctx["learning_memory"]
                    recent_sample_dicts = t_ctx["recent_sample_dicts"]
                    cookies_json_val = t_ctx["cookies_json_val"]
                    tenant_api_key_val = t_ctx["tenant_api_key_val"]

                    # Daily Token Budget Guardrail
                    budget_ok, tokens_used_today, token_cap_today = await async_check_tenant_token_budget(
                        curr_tenant_id
                    )
                    if not budget_ok:
                        logger.info(
                            f"Tenant '{curr_tenant_id}': Daily AI token cap reached "
                            f"({tokens_used_today:,}/{token_cap_today:,} tokens). Skipping AI scan until UTC reset."
                        )
                        continue

                    # Active Hours, Action Caps & Queue Cap for scheduled automated runs
                    if not is_manual:
                        if not is_within_active_hours(start_hr, end_hr):
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Outside active hours ({start_hr:02d}:00-{end_hr:02d}:00). Sleeping..."
                            )
                            worker_sleep = state.tenant_workers.get(curr_tenant_id)
                            if worker_sleep and worker_sleep.is_running and t_ctx["auto_sleep"]:
                                await worker_sleep.stop()
                                state.evict_stopped_worker(curr_tenant_id)
                            continue
                        if daily_used >= daily_cap:
                            logger.warning(
                                f"Tenant '{curr_tenant_id}': Daily cap reached ({daily_used}/{daily_cap}). Pausing until tomorrow."
                            )
                            continue
                        if hourly_used >= hourly_cap:
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Hourly cap reached ({hourly_used}/{hourly_cap}). Cooling down..."
                            )
                            continue
                        if not auto_pilot and pending_approval_count >= max_pending_queue:
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Review Queue full ({pending_approval_count}/{max_pending_queue} pending). "
                                f"Skipping scan to save AI tokens until drafts are reviewed."
                            )
                            continue

                    worker = state.get_tenant_browser_worker(curr_tenant_id)
                    _restore_worker_cookies(worker, cookies_json_val, curr_tenant_id)

                    try:
                        tenant_is_logged = await asyncio.wait_for(
                            worker.check_login_status(), timeout=20.0
                        )
                        state.tenant_login_states[curr_tenant_id] = tenant_is_logged
                        if curr_tenant_id == "default":
                            state.is_session_logged_in = tenant_is_logged
                        if tenant_is_logged:
                            def _sync_user():
                                db = SessionLocal()
                                try:
                                    state.sync_detected_username(
                                        db, tenant_id=curr_tenant_id, worker=worker
                                    )
                                finally:
                                    db.close()

                            await asyncio.to_thread(_sync_user)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Login status check timed out for tenant '{curr_tenant_id}'."
                        )
                        tenant_is_logged = False
                    except Exception as e:
                        logger.error(
                            f"Failed to check login status for tenant '{curr_tenant_id}': {e}"
                        )
                        tenant_is_logged = False

                    if not tenant_is_logged:
                        logger.warning(
                            f"Tenant '{curr_tenant_id}' is not logged into X. Connect your account in the top bar."
                        )
                        continue

                    # ==========================================================
                    # Dual-Engine Radar: Internet & Google Trend Scouting
                    # ==========================================================
                    effective_query = base_query
                    web_topics = []
                    try:
                        web_topics = await scout_and_rank_topics(
                            niche=base_query or "technology",
                            limit=3,
                            custom_key=tenant_api_key_val,
                            tenant_id=curr_tenant_id,
                        )
                    except Exception as e:
                        logger.debug(f"Web scout pass note: {e}")

                    if web_topics:
                        top_topic = web_topics[0]
                        s_query = top_topic.get("suggested_query")
                        if s_query and len(s_query) >= 3:
                            effective_query = s_query
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Web Radar selected breaking query '{effective_query}' "
                                f"from {top_topic.get('source')} ('{(top_topic.get('title') or '')[:45]}...')"
                            )

                        if pending_approval_count < max_pending_queue:
                            topic_url = top_topic.get("url", "")

                            def _check_web_draft_eligible():
                                db_web = SessionLocal()
                                try:
                                    today_utc_start = datetime.utcnow().replace(
                                        hour=0, minute=0, second=0, microsecond=0
                                    )
                                    web_drafts_today = (
                                        db_web.query(ProcessedTweet)
                                        .filter(
                                            ProcessedTweet.tenant_id == curr_tenant_id,
                                            ProcessedTweet.tweet_id.like("web_%"),
                                            ProcessedTweet.timestamp >= today_utc_start,
                                        )
                                        .count()
                                    )
                                    already_drafted = (
                                        db_web.query(ProcessedTweet.tweet_id)
                                        .filter(
                                            ProcessedTweet.tenant_id == curr_tenant_id,
                                            ProcessedTweet.tweet_url == topic_url,
                                        )
                                        .first()
                                    )
                                    return web_drafts_today < 1 and not already_drafted
                                finally:
                                    db_web.close()

                            should_stage_web = await asyncio.to_thread(_check_web_draft_eligible)
                            if should_stage_web:
                                try:
                                    drafts = await generate_draft_from_web_topic(
                                        topic=top_topic,
                                        persona_prompt=persona or "Casual, sharp, short sentences",
                                        model_name=selected_model,
                                        custom_key=tenant_api_key_val,
                                        draft_type="tweet",
                                        tenant_id=curr_tenant_id,
                                    )
                                    single_text = drafts.get("single_tweet")
                                    if single_text:
                                        synth_id = f"web_{uuid.uuid4().hex[:12]}"

                                        def _save_web_draft():
                                            db_web = SessionLocal()
                                            try:
                                                new_post = ProcessedTweet(
                                                    tweet_id=synth_id,
                                                    tenant_id=curr_tenant_id,
                                                    action_type="post",
                                                    tweet_text=(
                                                        f"🌐 Google News Inspo: {top_topic.get('title')}\n"
                                                        f"Source: {top_topic.get('source')} ({topic_url})"
                                                    ),
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
                                            finally:
                                                db_web.close()

                                        await asyncio.to_thread(_save_web_draft)
                                        pending_approval_count += 1
                                        state.emit_tenant_event(
                                            curr_tenant_id,
                                            "queue_changed",
                                            {"tweet_id": synth_id, "status": "pending_approval"},
                                        )
                                        logger.info(
                                            f"Tenant '{curr_tenant_id}': Auto-staged web trend draft "
                                            f"'{(top_topic.get('title') or '')[:40]}' in Review Queue."
                                        )
                                except Exception as ex:
                                    logger.debug(f"Web draft staging note: {ex}")

                    elif smart_query_on and base_query and base_query.strip():
                        effective_query = await generate_smart_search_query(
                            niche_topic=base_query,
                            recent_tweets=recent_sample_dicts,
                            model_name=selected_model,
                            custom_key=tenant_api_key_val,
                            tenant_id=curr_tenant_id,
                        )

                    state.set_active_search_query(
                        curr_tenant_id, effective_query or "Home Timeline"
                    )

                    logger.info(
                        f"Tenant '{curr_tenant_id}': Scanning X feed for '{effective_query}' "
                        f"(learned: {learning_memory.get('total_learned', 0)})..."
                    )
                    try:
                        tweets = await asyncio.wait_for(
                            worker.scrape_feed(search_query=effective_query, limit=8),
                            timeout=60.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Tenant '{curr_tenant_id}': Feed scrape timed out after 60s."
                        )
                        continue

                    logger.info(
                        f"Tenant '{curr_tenant_id}': Collected {len(tweets)} candidate posts."
                    )

                    def _sync_after_scrape():
                        db = SessionLocal()
                        try:
                            state.sync_detected_username(
                                db, tenant_id=curr_tenant_id, worker=worker
                            )
                        finally:
                            db.close()

                    await asyncio.to_thread(_sync_after_scrape)

                    # ==========================================================
                    # Zero-Token Python Spam Pre-Filter + Batch SQL Deduplication
                    # ==========================================================
                    def _dedup_and_prefilter():
                        db = SessionLocal()
                        try:
                            candidate_ids = [t["tweet_id"] for t in tweets if t.get("tweet_id")]
                            processed_ids = get_processed_tweet_ids_batch(
                                db, candidate_ids, tenant_id=curr_tenant_id
                            )
                            clean_list = []
                            prefiltered_cnt = 0
                            new_cnt = 0
                            dirty = False

                            for t in tweets:
                                tid = t.get("tweet_id")
                                if not tid or str(tid) in processed_ids:
                                    continue
                                new_cnt += 1
                                skip_now, skip_reason = should_prefilter_skip(t)
                                if skip_now:
                                    prefiltered_cnt += 1
                                    logger.info(
                                        f"$0 Pre-filter skipped @{t.get('author')}: {skip_reason}"
                                    )
                                    record_processed_tweet(
                                        db=db,
                                        tweet_id=tid,
                                        tenant_id=curr_tenant_id,
                                        action_type="reply",
                                        tweet_text=t.get("text"),
                                        tweet_author=t.get("author"),
                                        tweet_url=t.get("url"),
                                        media_url=t.get("media_url"),
                                        generated_text=None,
                                        variants_json=None,
                                        tweet_metrics=t.get("metrics"),
                                        status="skipped",
                                        error_message=skip_reason,
                                        commit=False,
                                    )
                                    dirty = True
                                    continue
                                clean_list.append(t)

                            if dirty:
                                db.commit()
                            return clean_list, prefiltered_cnt, new_cnt
                        finally:
                            db.close()

                    clean_candidates, prefiltered_count, new_count = await asyncio.to_thread(
                        _dedup_and_prefilter
                    )

                    if prefiltered_count > 0:
                        logger.info(
                            f"Tenant '{curr_tenant_id}': $0 Pre-filter dropped {prefiltered_count}/{new_count} noisy posts; "
                            f"sending {len(clean_candidates)} clean post(s) in 1 batched AI call."
                        )

                    # ==========================================================
                    # Single Batched Evaluation + Batch Similarity + 1 Transaction
                    # ==========================================================
                    if clean_candidates:
                        batch_results = await evaluate_tweets_batch(
                            tweets=clean_candidates,
                            model_name=selected_model,
                            custom_key=tenant_api_key_val,
                            search_query=base_query or effective_query,
                            persona_prompt=persona,
                            learning_memory=learning_memory,
                            include_variants=False,
                            tenant_id=curr_tenant_id,
                        )

                        def _persist_batch_evaluations():
                            db = SessionLocal()
                            try:
                                recent_texts = get_recent_reply_texts(
                                    db, tenant_id=curr_tenant_id, limit=20
                                )
                                cfg = (
                                    get_agent_config(db, tenant_id=curr_tenant_id)
                                    if auto_pilot
                                    else None
                                )
                                drafts_landed = 0
                                any_writes = False

                                for t in clean_candidates:
                                    tid = t["tweet_id"]
                                    ai_result = batch_results.get(str(tid))
                                    if not ai_result:
                                        continue
                                    if ai_result.get("raw_response") == "NO_API_KEY":
                                        logger.warning(
                                            "Paused: AI API key not configured. Check settings or environment variables."
                                        )
                                        break

                                    if not ai_result["should_reply"]:
                                        logger.info(
                                            f"Skipped @{t['author']}: {ai_result['reasoning']}"
                                        )
                                        record_processed_tweet(
                                            db=db,
                                            tweet_id=tid,
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
                                            commit=False,
                                        )
                                        any_writes = True
                                        continue

                                    reply_text = ai_result["reply_text"]
                                    variants_dict = ai_result.get("variants") or {}
                                    variants_json = ai_result.get("variants_json")
                                    should_like = bool(ai_result.get("should_like", False))
                                    urgency_score = int(ai_result.get("urgency_score", 5))

                                    if is_text_too_similar_to_list(reply_text, recent_texts):
                                        alt_chosen = None
                                        for alt_text in variants_dict.values():
                                            if alt_text and not is_text_too_similar_to_list(
                                                alt_text, recent_texts
                                            ):
                                                alt_chosen = alt_text
                                                break
                                        if alt_chosen:
                                            logger.info(
                                                "Primary draft shared opening words with a recent reply; switched to fresh variant."
                                            )
                                            reply_text = alt_chosen
                                        else:
                                            logger.info(
                                                f"Skipped @{t['author']}: Draft too similar to recent replies (anti-template shield)."
                                            )
                                            record_processed_tweet(
                                                db=db,
                                                tweet_id=tid,
                                                tenant_id=curr_tenant_id,
                                                action_type="reply",
                                                tweet_text=t["text"],
                                                tweet_author=t["author"],
                                                tweet_url=t["url"],
                                                media_url=t.get("media_url"),
                                                generated_text=None,
                                                status="skipped",
                                                error_message="Filtered by Anti-Detection Similarity Shield",
                                                commit=False,
                                            )
                                            any_writes = True
                                            continue

                                    recent_texts.append(reply_text)
                                    logger.info(
                                        f"Drafted for @{t['author']} [urgency {urgency_score}/10, like={should_like}]: '{reply_text}'"
                                    )

                                    if not auto_pilot:
                                        record_processed_tweet(
                                            db=db,
                                            tweet_id=tid,
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
                                            commit=False,
                                        )
                                    else:
                                        sched_utc = compute_random_schedule_time(
                                            db, cfg, urgency_score=urgency_score
                                        )
                                        mins_away = max(
                                            1,
                                            int((sched_utc - datetime.utcnow()).total_seconds() // 60),
                                        )
                                        logger.info(
                                            f"Autopilot scheduled reply to @{t['author']} in ~{mins_away}m (urgency {urgency_score}/10)."
                                        )
                                        record_processed_tweet(
                                            db=db,
                                            tweet_id=tid,
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
                                            commit=False,
                                        )
                                        db.flush()

                                    drafts_landed += 1
                                    any_writes = True

                                if any_writes:
                                    db.commit()
                                return drafts_landed
                            finally:
                                db.close()

                        new_drafts_landed = await asyncio.to_thread(_persist_batch_evaluations)
                        if new_drafts_landed > 0:
                            state.emit_tenant_event(
                                curr_tenant_id,
                                "queue_changed",
                                {"added": new_drafts_landed},
                            )

                    if new_count == 0 and len(tweets) > 0:
                        logger.info(
                            f"All {len(tweets)} visible posts for '{effective_query}' were already evaluated."
                        )

                    # ==========================================================
                    # Autonomous Original Post / Thread (Plan-Capped)
                    # ==========================================================
                    if new_count >= 2:
                        def _get_orig_count():
                            db = SessionLocal()
                            try:
                                return get_daily_original_posts_count(
                                    db, tenant_id=curr_tenant_id
                                )
                            finally:
                                db.close()

                        orig_today = await asyncio.to_thread(_get_orig_count)
                        still_in_budget, _, _ = await async_check_tenant_token_budget(curr_tenant_id)

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
                                custom_key=tenant_api_key_val,
                                learning_memory=learning_memory,
                                include_variants=False,
                                tenant_id=curr_tenant_id,
                            )
                            if gen.get("success") and gen.get("text"):
                                chosen_mode = gen.get("action_type") or "post"
                                orig_urgency = int(gen.get("urgency_score", 6))
                                orig_id = f"{chosen_mode}_{uuid.uuid4().hex[:12]}"

                                def _save_orig_pulse():
                                    db = SessionLocal()
                                    try:
                                        cfg = get_agent_config(db, tenant_id=curr_tenant_id)
                                        author_label = (
                                            worker.logged_in_username
                                            or cfg.linked_username
                                            or "you"
                                        ).lstrip("@")
                                        if auto_pilot:
                                            sched_utc = compute_random_schedule_time(
                                                db, cfg, urgency_score=orig_urgency
                                            )
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
                                                tweet_metrics=(
                                                    "Live Pulse · Original Thread"
                                                    if chosen_mode == "thread"
                                                    else "Live Pulse · Original Post"
                                                ),
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
                                                tweet_metrics=(
                                                    "Live Pulse · Thread"
                                                    if chosen_mode == "thread"
                                                    else "Live Pulse · Original Post"
                                                ),
                                                urgency_score=orig_urgency,
                                                status="pending_approval",
                                                error_message=gen["topic_summary"],
                                            )
                                        logger.info(
                                            f"AI chose and drafted original {chosen_mode} (urgency {orig_urgency}/10) "
                                            f"from live pulse for tenant '{curr_tenant_id}'."
                                        )
                                    finally:
                                        db.close()

                                await asyncio.to_thread(_save_orig_pulse)
                                state.emit_tenant_event(
                                    curr_tenant_id,
                                    "queue_changed",
                                    {
                                        "tweet_id": orig_id,
                                        "status": "scheduled" if auto_pilot else "pending_approval",
                                    },
                                )
                        elif orig_today >= daily_orig_cap:
                            logger.info(
                                f"Tenant '{curr_tenant_id}': Daily autonomous original post limit reached ({orig_today}/{daily_orig_cap})."
                            )

                except Exception as te:
                    logger.error(
                        f"Error during feed scan for tenant '{curr_tenant_id}': {te}",
                        exc_info=True,
                    )
                finally:
                    state.reset_log_tenant_context(tok)

            # Sleep until the earliest scheduled tenant scan, waking in <=120s slices to reap idle browsers
            next_due = min(
                (next_scan_at.get(tid, time.time() + 60.0) for tid, _ in active_tenants_info),
                default=time.time() + 60.0,
            )
            wait_deadline = max(time.time() + 10.0, next_due)
            while time.time() < wait_deadline:
                remaining = wait_deadline - time.time()
                slice_sec = min(120.0, max(1.0, remaining))
                try:
                    await asyncio.wait_for(state.scrape_now_flag.wait(), timeout=slice_sec)
                    break
                except asyncio.TimeoutError:
                    await _sleep_idle_or_inactive_browsers()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Unexpected error in background worker loop: {e}", exc_info=True)
            await asyncio.sleep(15)
