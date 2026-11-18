"""
Queue & Interaction Approval Router for X-VibeBot.
Handles pending draft reviews, approvals, randomized scheduling, rejections, and original post generation.
"""

import time
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from models import (
    ProcessedTweet,
    ProcessedTweetResponse,
    ApproveDraftRequest,
    GenerateOriginalPayload
)
from database import (
    get_db,
    get_pending_tweets,
    get_agent_config,
    get_daily_actions_count,
    get_hourly_actions_count,
    compute_random_schedule_time,
    update_tweet_status,
    get_recent_tweets,
    get_learning_memory,
    record_processed_tweet
)
from core.dependencies import get_current_tenant
import core.state as state
from ai_engine import generate_original_content, evaluate_tweet

logger = logging.getLogger("x_vibebot.queue")
router = APIRouter(tags=["queue"])


@router.get("/api/pending", response_model=List[ProcessedTweetResponse])
@router.get("/api/queue", response_model=List[ProcessedTweetResponse])
async def get_pending_approvals_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Retrieves all pending tweets waiting for approval or currently scheduled in the queue."""
    return get_pending_tweets(db, tenant_id=tenant_id)


@router.post("/api/approve/{tweet_id}")
@router.post("/api/approve-draft/{tweet_id}")
async def approve_tweet(
    tweet_id: str,
    payload: Optional[ApproveDraftRequest] = None,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Approves a draft reply or original post.
    - Tracks whether the user edited the draft so Self-Learning Voice Memory prioritizes it.
    - Enforces rolling 60-minute and daily anti-detection velocity caps.
    - Schedules randomized future dispatch if schedule_random is True.
    """
    tweet = db.query(ProcessedTweet).filter(
        ProcessedTweet.tweet_id == tweet_id,
        ProcessedTweet.tenant_id.in_([tenant_id, "default"])
    ).first()
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
            should_like=effective_like,
            tenant_id=tenant_id
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
    worker = state.get_tenant_browser_worker(tenant_id)
    success = await worker.execute_tweet_action(
        act_type,
        tweet_id,
        text_to_post,
        tweet.tweet_url,
        should_like=effective_like
    )
    state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)

    if success:
        state.set_new_random_cooldown(config.min_cooldown_minutes or 10, config.max_cooldown_minutes or 45)
        update_tweet_status(
            db,
            tweet_id,
            status="posted",
            generated_text=text_to_post,
            user_edited=was_user_edited,
            should_like=effective_like,
            tenant_id=tenant_id
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
            error_message=err_msg,
            tenant_id=tenant_id
        )
        raise HTTPException(status_code=500, detail=f"Failed to publish {act_type}: {err_msg}")


@router.post("/api/reject/{tweet_id}")
@router.post("/api/reject-draft/{tweet_id}")
async def reject_tweet(
    tweet_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Rejects a draft post or reply, marking it as skipped in audit history."""
    tweet = db.query(ProcessedTweet).filter(
        ProcessedTweet.tweet_id == tweet_id,
        ProcessedTweet.tenant_id.in_([tenant_id, "default"])
    ).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    update_tweet_status(db, tweet_id, status="skipped", error_message="Skipped by user", tenant_id=tenant_id)
    return {"status": "skipped", "tweet_id": tweet_id}


@router.post("/api/regenerate/{tweet_id}")
async def regenerate_tweet_draft(
    tweet_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Regenerates 3 fresh context-specific variants for a reply, original post, or thread."""
    tweet = db.query(ProcessedTweet).filter(
        ProcessedTweet.tweet_id == tweet_id,
        ProcessedTweet.tenant_id.in_([tenant_id, "default"])
    ).first()
    if not tweet:
        raise HTTPException(status_code=404, detail="Tweet not found")

    cfg = get_agent_config(db, tenant_id=tenant_id)
    learning_memory = get_learning_memory(db, tenant_id=tenant_id)
    if tweet.action_type in ("post", "thread"):
        recent_db_tweets = get_recent_tweets(db, limit=8, tenant_id=tenant_id)
        live_context = [
            {"author": r.tweet_author, "text": r.tweet_text, "metrics": r.tweet_metrics}
            for r in recent_db_tweets if r.action_type == "reply" and r.tweet_text
        ]
        gen = await generate_original_content(
            mode=tweet.action_type,
            search_query=cfg.search_query,
            persona_prompt=(cfg.persona_prompt or "") + " | Take a completely fresh, different angle.",
            live_tweets=live_context,
            model_name=cfg.selected_model or "auto",
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
            error_message=gen.get("topic_summary"),
            tenant_id=tenant_id
        )
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update tweet record")
        return {
            "tweet_id": tweet_id,
            "generated_text": updated.generated_text,
            "variants_json": updated.variants_json
        }

    ai_result = await evaluate_tweet(
        tweet_text=tweet.tweet_text or "",
        tweet_author=tweet.tweet_author,
        model_name=cfg.selected_model or "auto",
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
        error_message=ai_result.get("reasoning"),
        tenant_id=tenant_id
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update tweet record")
    logger.info(f"Regenerated fresh variants for @{tweet.tweet_author}")
    return {
        "tweet_id": tweet_id,
        "generated_text": updated.generated_text,
        "variants_json": updated.variants_json
    }


@router.post("/api/generate-original")
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
    topic = (payload.custom_topic or state.active_search_query_state or cfg.search_query or "tech & culture").strip()

    recent_db_tweets = get_recent_tweets(db, limit=10, tenant_id=tenant_id)
    live_context = [
        {
            "author": r.tweet_author,
            "text": r.tweet_text,
            "metrics": r.tweet_metrics
        }
        for r in recent_db_tweets
        if r.action_type == "reply" and r.tweet_text
    ]
    learning_memory = get_learning_memory(db, tenant_id=tenant_id)

    gen = await generate_original_content(
        mode=req_mode,
        search_query=topic,
        persona_prompt=cfg.persona_prompt,
        live_tweets=live_context,
        model_name=cfg.selected_model or "auto",
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
    worker = state.get_tenant_browser_worker(tenant_id)
    author_label = (worker.logged_in_username or cfg.linked_username or "you").lstrip("@")
    item = record_processed_tweet(
        db=db,
        tweet_id=orig_id,
        tenant_id=tenant_id,
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
    logger.info(f"Generated new {final_mode} on '{topic}' for tenant '{tenant_id}'")
    return {"status": "created", "tweet_id": item.tweet_id, "action_type": final_mode}
