"""
Web & Google Topic Radar Router for X-VibeBot.
Provides live Google News topics, on-demand scanning, SSRF-validated draft generation,
and strict per-tenant isolation and quota enforcement.
"""

import uuid
import json
import asyncio
import logging
from datetime import datetime
from typing import Tuple
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import (
    get_db,
    get_agent_config,
    get_decrypted_api_key,
    get_daily_original_posts_count,
    get_pending_approval_count,
)
from models import AgentConfig, ProcessedTweet, TopicDraftPayload
from core.dependencies import get_current_tenant, require_active_tenant_config
from core.security import async_validate_external_url
import core.state as state
from ai_engine import async_check_tenant_token_budget
from core.web_scout import scout_and_rank_topics, generate_draft_from_web_topic

logger = logging.getLogger("x_vibebot.radar")
router = APIRouter(prefix="/api/radar", tags=["radar"])


@router.get("/topics")
async def get_trending_topics(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Returns ranked trending web stories matching the creator's configured niche."""
    def _load_ctx():
        cfg = get_agent_config(db, tenant_id=tenant_id)
        niche_val = state.get_active_search_query(tenant_id) or cfg.search_query or "technology"
        key_val = get_decrypted_api_key(cfg)
        db.close()
        return niche_val, key_val

    niche, custom_key = await asyncio.to_thread(_load_ctx)
    topics = await scout_and_rank_topics(
        niche=niche,
        limit=5,
        custom_key=custom_key,
        tenant_id=tenant_id,
    )
    return {
        "niche": niche,
        "scanned_at": datetime.utcnow().isoformat(),
        "topics": topics,
    }


@router.post("/scan-now")
async def scan_web_radar_now(
    tenant_cfg: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """Forces a fresh scrape of Google News for the creator's niche."""
    from core.web_scout import _TOPIC_CACHE

    tenant_id, cfg = tenant_cfg

    def _load_ctx():
        niche_val = state.get_active_search_query(tenant_id) or cfg.search_query or "technology"
        key_val = get_decrypted_api_key(cfg)
        db.close()
        return niche_val, key_val

    niche, custom_key = await asyncio.to_thread(_load_ctx)
    niche_key = niche.strip().lower()
    _TOPIC_CACHE.pop(niche_key, None)

    topics = await scout_and_rank_topics(
        niche=niche,
        limit=5,
        custom_key=custom_key,
        tenant_id=tenant_id,
    )
    logger.info(
        f"Manual Web Radar scan completed for tenant '{tenant_id}' niche '{niche}': {len(topics)} topics discovered."
    )
    return {
        "status": "success",
        "niche": niche,
        "scanned_at": datetime.utcnow().isoformat(),
        "topics": topics,
    }


@router.post("/draft-from-topic")
async def draft_from_topic(
    payload: TopicDraftPayload,
    tenant_cfg: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """
    Validates external URL against SSRF, enforces token/queue/original-post budgets,
    generates an original tweet or 3-tweet thread, and places it into the Review Queue.
    """
    tenant_id, cfg = tenant_cfg

    try:
        safe_url = await async_validate_external_url(
            payload.url, require_https=False, resolve_dns=True
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Invalid topic URL: {ve}")

    allowed, used_today, daily_cap = await async_check_tenant_token_budget(tenant_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI token cap reached ({used_today:,}/{daily_cap:,} tokens). Resets at UTC midnight.",
        )

    def _load_ctx_and_check_caps():
        max_pending = int(getattr(cfg, "max_pending_queue", 8) or 8)
        pending_cnt = get_pending_approval_count(db, tenant_id=tenant_id)
        if pending_cnt >= max_pending:
            raise HTTPException(
                status_code=429,
                detail=f"Review queue is full ({pending_cnt}/{max_pending} pending). Review or clear drafts first.",
            )

        daily_orig_cap = int(getattr(cfg, "daily_original_post_cap", 3) or 3)
        orig_today = get_daily_original_posts_count(db, tenant_id=tenant_id)
        if orig_today >= daily_orig_cap:
            raise HTTPException(
                status_code=429,
                detail=f"Daily original post cap ({daily_orig_cap}) reached for your plan.",
            )

        ctx = {
            "persona_prompt": cfg.persona_prompt or "Casual, sharp, short sentences",
            "selected_model": cfg.selected_model or "auto",
            "custom_key": get_decrypted_api_key(cfg),
        }
        db.close()
        return ctx

    ctx = await asyncio.to_thread(_load_ctx_and_check_caps)

    topic_data = {
        "title": payload.title,
        "source": payload.source,
        "url": safe_url,
        "hook_summary": payload.hook_summary,
    }

    drafts = await generate_draft_from_web_topic(
        topic=topic_data,
        persona_prompt=ctx["persona_prompt"],
        model_name=ctx["selected_model"],
        custom_key=ctx["custom_key"],
        draft_type=payload.draft_type,
        tenant_id=tenant_id,
    )

    action_type = "thread" if payload.draft_type == "thread" else "post"
    primary_text = drafts.get("thread") if action_type == "thread" else drafts.get("single_tweet")
    if not primary_text:
        primary_text = drafts.get("single_tweet") or drafts.get("thread") or ""
    if not primary_text.strip():
        raise HTTPException(status_code=500, detail="Failed to generate draft from web topic.")

    synthetic_id = f"web_{uuid.uuid4().hex[:12]}"

    def _save_entry():
        new_entry = ProcessedTweet(
            tweet_id=synthetic_id,
            tenant_id=tenant_id,
            action_type=action_type,
            tweet_text=f"🌐 Google News Inspo: {payload.title}\nSource: {payload.source} ({safe_url})",
            tweet_author=f"Web: {payload.source}",
            tweet_url=safe_url,
            generated_text=primary_text,
            variants_json=json.dumps({
                "witty": drafts.get("single_tweet"),
                "thread": drafts.get("thread"),
                "topic_source": payload.source,
                "topic_url": safe_url,
            }),
            tweet_metrics="🌐 Web Trend Radar",
            urgency_score=8,
            status="pending_approval",
            error_message=f"Inspired by {payload.source}: '{payload.title}'",
        )
        db.add(new_entry)
        db.commit()
        db.refresh(new_entry)

    await asyncio.to_thread(_save_entry)
    state.emit_tenant_event(
        tenant_id, "queue_changed", {"tweet_id": synthetic_id, "status": "pending_approval"}
    )
    logger.info(
        f"Created {action_type} draft from web topic '{payload.title[:40]}' in queue (tenant={tenant_id})."
    )
    return {
        "status": "success",
        "tweet_id": synthetic_id,
        "action_type": action_type,
        "generated_text": primary_text,
        "variants": drafts,
    }
