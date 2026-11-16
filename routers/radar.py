"""
Web & Google Topic Radar Router for X-VibeBot.
Provides live Google News topics, on-demand scanning, and 1-click draft generation into the Review Queue.
"""

import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, get_agent_config, SessionLocal
from models import ProcessedTweet, TopicDraftPayload
from core.dependencies import get_current_tenant
import core.state as state
from core.web_scout import scout_and_rank_topics, generate_draft_from_web_topic

logger = logging.getLogger("x_vibebot.radar")
router = APIRouter(prefix="/api/radar", tags=["radar"])


@router.get("/topics")
async def get_trending_topics(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Returns ranked trending web stories matching the creator's configured niche.
    """
    cfg = get_agent_config(db, tenant_id=tenant_id)
    niche = state.active_search_query_state or cfg.search_query or "technology"
    topics = await scout_and_rank_topics(niche=niche, limit=5)
    return {
        "niche": niche,
        "scanned_at": datetime.utcnow().isoformat(),
        "topics": topics
    }


@router.post("/scan-now")
async def scan_web_radar_now(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Forces a fresh scrape of Google News for the creator's niche.
    """
    from core.web_scout import _TOPIC_CACHE
    cfg = get_agent_config(db, tenant_id=tenant_id)
    niche = state.active_search_query_state or cfg.search_query or "technology"
    niche_key = niche.strip().lower()

    # Clear cache to force fresh scan
    if niche_key in _TOPIC_CACHE:
        del _TOPIC_CACHE[niche_key]

    topics = await scout_and_rank_topics(niche=niche, limit=5)
    logger.info(f"Manual Web Radar scan completed for niche '{niche}': {len(topics)} topics discovered.")
    return {
        "status": "success",
        "niche": niche,
        "scanned_at": datetime.utcnow().isoformat(),
        "topics": topics
    }


@router.post("/draft-from-topic")
async def draft_from_topic(
    payload: TopicDraftPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Generates an original tweet or 3-tweet thread from a web topic and places it
    directly into the Review Queue with a 'Web Trend Inspo' badge.
    """
    cfg = get_agent_config(db, tenant_id=tenant_id)
    topic_data = {
        "title": payload.title,
        "source": payload.source,
        "url": payload.url,
        "hook_summary": payload.hook_summary
    }

    drafts = await generate_draft_from_web_topic(
        topic=topic_data,
        persona_prompt=cfg.persona_prompt or "Casual, sharp, short sentences",
        model_name=cfg.selected_model or "gemini-2.5-flash"
    )

    action_type = "thread" if payload.draft_type == "thread" else "post"
    primary_text = drafts.get("thread") if action_type == "thread" else drafts.get("single_tweet")

    # Generate a unique synthetic tweet_id for the original post
    synthetic_id = f"web_{uuid.uuid4().hex[:12]}"
    new_entry = ProcessedTweet(
        tweet_id=synthetic_id,
        tenant_id=tenant_id,
        action_type=action_type,
        tweet_text=f"🌐 Google News Inspo: {payload.title}\nSource: {payload.source} ({payload.url})",
        tweet_author=f"Web: {payload.source}",
        tweet_url=payload.url,
        generated_text=primary_text,
        variants_json=json.dumps({
            "witty": drafts.get("single_tweet"),
            "thread": drafts.get("thread"),
            "topic_source": payload.source,
            "topic_url": payload.url
        }),
        tweet_metrics="🌐 Web Trend Radar",
        urgency_score=8,
        status="pending_approval",
        error_message=f"Inspired by {payload.source}: '{payload.title}'"
    )

    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)

    logger.info(f"Created {action_type} draft from web topic '{payload.title[:40]}' in queue.")
    return {
        "status": "success",
        "tweet_id": synthetic_id,
        "action_type": action_type,
        "generated_text": primary_text,
        "variants": drafts
    }
