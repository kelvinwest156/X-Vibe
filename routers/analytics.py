"""
Analytics & Historical Performance Router for X-VibeBot.
Aggregates engagement metrics, status KPIs, AI strategy briefs, and post audit history.
"""

import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models import (
    ProcessedTweet,
    ProcessedTweetResponse,
    AgentStatusResponse,
    SystemLogEntry
)
from database import (
    get_db,
    get_agent_config,
    get_daily_actions_count,
    get_hourly_actions_count,
    get_learning_memory,
    get_pending_tweets,
    get_scheduled_count,
    is_within_active_hours,
    get_recent_tweets
)
from core.dependencies import get_current_tenant
import core.state as state
from ai_engine import generate_strategy_brief

router = APIRouter(tags=["analytics"])


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


@router.get("/api/status", response_model=AgentStatusResponse)
async def get_status(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Retrieves real-time bot state, cooldown counters, and recent log messages."""
    config = get_agent_config(db, tenant_id=tenant_id)
    worker = state.get_tenant_browser_worker(tenant_id)
    if worker.logged_in_username and config.linked_username != worker.logged_in_username:
        config.linked_username = worker.logged_in_username
        db.commit()

    warmup = bool(getattr(config, "warmup_mode", False))
    daily_used = get_daily_actions_count(db, tenant_id=tenant_id)
    effective_daily_cap = min(8, config.daily_action_cap or 15) if warmup else (config.daily_action_cap or 15)
    hourly_used = get_hourly_actions_count(db, tenant_id=tenant_id)
    effective_hourly_cap = 3 if warmup else (getattr(config, "hourly_action_cap", 6) or 6)
    learning_mem = get_learning_memory(db, limit_approved=1, limit_skipped=1, tenant_id=tenant_id)

    cooldown_rem = state.get_cooldown_remaining()
    pending_items = get_pending_tweets(db, tenant_id=tenant_id)
    sched_count = get_scheduled_count(db, tenant_id=tenant_id)
    total_processed = db.query(ProcessedTweet).filter(ProcessedTweet.tenant_id == tenant_id).count()
    within_hours = is_within_active_hours(
        config.active_hours_start if config.active_hours_start is not None else 8,
        config.active_hours_end if config.active_hours_end is not None else 23
    )

    has_saved_session = (
        os.path.isfile(worker.cookies_backup_path)
        and not os.path.isfile(os.path.join(worker.profile_dir, ".disconnected"))
    )
    tenant_logged_in = (
        state.tenant_login_states.get(tenant_id, False)
        or bool(worker.logged_in_username)
        or bool(config.linked_username)
    ) and has_saved_session

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
        active_search_query=state.active_search_query_state or config.search_query or "Home Timeline",
        learned_examples_count=int(learning_mem.get("total_learned", 0)),
        cooldown_active=cooldown_rem > 0,
        cooldown_seconds_remaining=cooldown_rem,
        within_active_hours=within_hours,
        scheduled_count=sched_count,
        browser_connected=worker.is_running,
        is_logged_in=tenant_logged_in,
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
            for entry in list(state.log_buffer)[-25:]
        ]
    )


@router.get("/api/history", response_model=List[ProcessedTweetResponse])
async def get_history_endpoint(
    limit: int = 50,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Retrieves recent post audit history (posted, scheduled, skipped, failed)."""
    return get_recent_tweets(db, limit=limit, tenant_id=tenant_id)


@router.get("/api/analytics")
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
        niche=state.active_search_query_state or cfg.search_query or "AI & Tech",
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
            "active_search_query": state.active_search_query_state or cfg.search_query or "Home Timeline",
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


@router.get("/api/stats")
async def get_stats_summary(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Lightweight endpoint returning high-level KPIs and velocity numbers."""
    cfg = get_agent_config(db, tenant_id=tenant_id)
    daily_used = get_daily_actions_count(db, tenant_id=tenant_id)
    hourly_used = get_hourly_actions_count(db, tenant_id=tenant_id)
    pending_count = len(get_pending_tweets(db, tenant_id=tenant_id))
    scheduled_count = get_scheduled_count(db, tenant_id=tenant_id)

    return {
        "tenant_id": tenant_id,
        "is_active": cfg.is_active,
        "daily_actions_used": daily_used,
        "daily_action_cap": cfg.daily_action_cap,
        "hourly_actions_used": hourly_used,
        "hourly_action_cap": getattr(cfg, "hourly_action_cap", 6),
        "pending_count": pending_count,
        "scheduled_count": scheduled_count,
        "selected_model": cfg.selected_model or "gemini-3.8-flash"
    }
