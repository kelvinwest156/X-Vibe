"""
Queue & Interaction Approval Router for X-VibeBot.
Handles pending draft reviews, state-machine-enforced approvals, randomized scheduling,
rejections, angle variants, and original post generation with strict tenant isolation.
"""

import re
import uuid
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from models import (
    ProcessedTweet,
    AgentConfig,
    ProcessedTweetResponse,
    ApproveDraftRequest,
    GenerateOriginalPayload,
)
from database import (
    get_db,
    get_pending_tweets,
    get_agent_config,
    get_decrypted_api_key,
    get_daily_actions_count,
    get_hourly_actions_count,
    get_daily_original_posts_count,
    get_pending_approval_count,
    compute_random_schedule_time,
    update_tweet_status,
    claim_tweet_for_dispatch,
    clear_all_pending_tweets,
    get_recent_tweets,
    get_learning_memory,
    record_processed_tweet,
    expire_stale_drafts,
)
from core.dependencies import get_current_tenant, require_active_tenant_config
import core.state as state
from ai_engine import (
    generate_original_content,
    evaluate_tweet,
    generate_reply_variants,
    async_check_tenant_token_budget,
)

logger = logging.getLogger("x_vibebot.queue")
router = APIRouter(tags=["queue"])

_APPROVABLE_STATUSES = ("pending_approval", "scheduled", "failed")


def _validate_x_character_limits(act_type: str, text_to_post: str) -> None:
    """Enforces X's 280-character limit per post/reply or per '---'-separated thread part."""
    if act_type == "thread":
        parts = [p.strip() for p in re.split(r"\n?---\n?", text_to_post) if p.strip()]
        if not parts:
            raise HTTPException(status_code=400, detail="Cannot post an empty thread.")
        for idx, part in enumerate(parts, 1):
            if len(part) > 280:
                raise HTTPException(
                    status_code=400,
                    detail=f"Thread part {idx} exceeds X's 280-character limit ({len(part)}/280 characters).",
                )
    elif len(text_to_post) > 280:
        raise HTTPException(
            status_code=400,
            detail=f"Draft exceeds X's 280-character limit ({len(text_to_post)}/280 characters).",
        )


@router.get("/api/pending", response_model=List[ProcessedTweetResponse])
@router.get("/api/queue", response_model=List[ProcessedTweetResponse])
def get_pending_approvals_endpoint(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Retrieves pending tweets waiting for approval or scheduled in the queue (strictly read-only)."""
    return get_pending_tweets(db, tenant_id=tenant_id, limit=limit, offset=offset)


@router.post("/api/queue/clear-stale")
async def clear_stale_queue(
    max_age_hours: int = Query(24, ge=1, le=720),
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Expires all pending drafts older than specified hours (default 24h)."""
    expired_count = await asyncio.to_thread(
        expire_stale_drafts, db, tenant_id=tenant_id, max_age_hours=max_age_hours
    )
    if expired_count > 0:
        state.emit_tenant_event(tenant_id, "queue_changed", {"expired_count": expired_count})
    return {
        "success": True,
        "expired_count": expired_count,
        "message": f"Expired {expired_count} stale draft(s).",
    }


@router.post("/api/queue/clear-all")
async def clear_all_pending(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Dismisses all current pending drafts for the tenant to unblock scans."""
    count = await asyncio.to_thread(clear_all_pending_tweets, db, tenant_id)
    if count > 0:
        state.emit_tenant_event(tenant_id, "queue_changed", {"dismissed_count": count})
    return {
        "success": True,
        "dismissed_count": count,
        "message": f"Dismissed {count} pending draft(s).",
    }


@router.post("/api/approve/{tweet_id}")
@router.post("/api/approve-draft/{tweet_id}")
async def approve_tweet(
    tweet_id: str,
    payload: Optional[ApproveDraftRequest] = None,
    tenant_cfg: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """
    Approves a draft reply or original post using an atomic state machine:
    - Only transitions from ('pending_approval', 'scheduled', 'failed').
    - Enforces X 280-char limits and rolling 60-min / daily velocity caps BEFORE claiming.
    - Marks 'dispatching' (never 'posted' prematurely) until browser execution confirms.
    """
    tenant_id, config = tenant_cfg

    def _prepare_and_claim():
        tweet = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
            )
            .first()
        )
        if not tweet:
            raise HTTPException(status_code=404, detail="Tweet not found")

        if tweet.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Tweet cannot be approved from '{tweet.status}' state.",
            )

        text_to_post = (
            payload.custom_text.strip()
            if (payload and payload.custom_text)
            else (tweet.generated_text or "").strip()
        )
        if not text_to_post:
            raise HTTPException(status_code=400, detail="Cannot post an empty reply.")

        act_type = tweet.action_type or "reply"
        _validate_x_character_limits(act_type, text_to_post)

        was_user_edited = bool(
            payload
            and payload.custom_text
            and payload.custom_text.strip() != (tweet.generated_text or "").strip()
        )
        effective_like = (
            bool(payload.should_like)
            if (payload and payload.should_like is not None)
            else bool(getattr(tweet, "should_like", False))
        )
        urgency_val = int(getattr(tweet, "urgency_score", 5) or 5)
        prev_status = tweet.status
        prev_sched = tweet.scheduled_for
        tweet_url = tweet.tweet_url
        tweet_author = tweet.tweet_author
        min_cd = config.min_cooldown_minutes or 10
        max_cd = config.max_cooldown_minutes or 45

        if payload and payload.schedule_random:
            sched_utc = compute_random_schedule_time(db, config, urgency_score=urgency_val)
            claimed = claim_tweet_for_dispatch(
                db,
                tweet_id=tweet_id,
                tenant_id=tenant_id,
                allowed_from_statuses=_APPROVABLE_STATUSES,
                new_status="scheduled",
                generated_text=text_to_post,
                user_edited=was_user_edited,
                should_like=effective_like,
                scheduled_for=sched_utc,
            )
            if not claimed:
                raise HTTPException(
                    status_code=409,
                    detail="Tweet state changed concurrently; please refresh your queue.",
                )
            mins_away = max(1, int((sched_utc - datetime.utcnow()).total_seconds() // 60))
            return {
                "mode": "scheduled",
                "tweet_author": tweet_author,
                "was_user_edited": was_user_edited,
                "sched_utc": sched_utc,
                "mins_away": mins_away,
            }

        daily_cap = config.effective_daily_cap()
        hourly_cap = config.effective_hourly_cap()
        daily_used = get_daily_actions_count(db, tenant_id=tenant_id)
        hourly_used = get_hourly_actions_count(db, tenant_id=tenant_id)

        if daily_used >= daily_cap:
            raise HTTPException(
                status_code=429,
                detail=f"Daily anti-detection cap ({daily_cap}) reached!",
            )
        if hourly_used >= hourly_cap:
            raise HTTPException(
                status_code=429,
                detail=f"Hourly anti-detection velocity cap ({hourly_cap}/hr) reached! Use 'Schedule' to queue safely.",
            )

        claimed = claim_tweet_for_dispatch(
            db,
            tweet_id=tweet_id,
            tenant_id=tenant_id,
            allowed_from_statuses=_APPROVABLE_STATUSES,
            new_status="dispatching",
            generated_text=text_to_post,
            user_edited=was_user_edited,
            should_like=effective_like,
        )
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail="Tweet is already dispatching or has already been processed.",
            )

        return {
            "mode": "dispatching",
            "act_type": act_type,
            "text_to_post": text_to_post,
            "tweet_url": tweet_url,
            "effective_like": effective_like,
            "was_user_edited": was_user_edited,
            "min_cd": min_cd,
            "max_cd": max_cd,
            "prev_status": prev_status,
            "prev_sched": prev_sched,
        }

    prep = await asyncio.to_thread(_prepare_and_claim)

    if prep["mode"] == "scheduled":
        sched_utc = prep["sched_utc"]
        mins_away = prep["mins_away"]
        logger.info(
            f"Scheduled reply to @{prep['tweet_author']} for random time (~{mins_away}m from now, edited={prep['was_user_edited']})."
        )
        state.emit_tenant_event(tenant_id, "queue_changed", {"tweet_id": tweet_id, "status": "scheduled"})
        return {
            "status": "scheduled",
            "tweet_id": tweet_id,
            "scheduled_for": sched_utc.isoformat(),
            "minutes_from_now": mins_away,
        }

    act_type = prep["act_type"]
    text_to_post = prep["text_to_post"]
    logger.info(
        f"Enqueueing approved {act_type} ({tweet_id}) to Async Action Dispatcher "
        f"[edited={prep['was_user_edited']}, like={prep['effective_like']}, tenant={tenant_id}]..."
    )

    try:
        state.action_dispatch_queue.put_nowait({
            "tenant_id": tenant_id,
            "tweet_id": tweet_id,
            "action_type": act_type,
            "text": text_to_post,
            "tweet_url": prep["tweet_url"],
            "should_like": prep["effective_like"],
            "was_user_edited": prep["was_user_edited"],
            "min_cooldown": prep["min_cd"],
            "max_cooldown": prep["max_cd"],
        })
    except asyncio.QueueFull:
        revert_status = prep["prev_status"] if prep["prev_status"] in _APPROVABLE_STATUSES else "pending_approval"
        revert_sched = prep["prev_sched"] if revert_status == "scheduled" else None
        await asyncio.to_thread(
            update_tweet_status,
            db,
            tweet_id,
            status=revert_status,
            scheduled_for=revert_sched,
            error_message="Dispatch queue temporarily full; please retry.",
            tenant_id=tenant_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Action dispatch queue is temporarily full. Please try again in a few seconds.",
        )

    state.emit_tenant_event(tenant_id, "queue_changed", {"tweet_id": tweet_id, "status": "dispatching"})
    return {"status": "dispatching", "tweet_id": tweet_id, "text": text_to_post}


@router.post("/api/reject/{tweet_id}")
@router.post("/api/reject-draft/{tweet_id}")
async def reject_tweet(
    tweet_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Rejects a draft post or reply, marking it as skipped in audit history."""
    def _reject():
        tweet = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
            )
            .first()
        )
        if not tweet:
            raise HTTPException(status_code=404, detail="Tweet not found")
        if tweet.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot reject tweet in '{tweet.status}' state.",
            )
        rows = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
                ProcessedTweet.status.in_(list(_APPROVABLE_STATUSES)),
            )
            .update(
                {
                    ProcessedTweet.status: "skipped",
                    ProcessedTweet.scheduled_for: None,
                    ProcessedTweet.error_message: "Skipped by user",
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if rows != 1:
            raise HTTPException(status_code=409, detail="Tweet state changed concurrently.")

    await asyncio.to_thread(_reject)
    state.emit_tenant_event(tenant_id, "queue_changed", {"tweet_id": tweet_id, "status": "skipped"})
    return {"status": "skipped", "tweet_id": tweet_id}


@router.post("/api/queue/{tweet_id}/variants")
async def generate_queue_variants_endpoint(
    tweet_id: str,
    tenant_cfg: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """
    On-demand generation of 3 alternative reply angles for a queued draft.
    Checks tenant daily token budget, releases DB across LLM await, saves variants_json, and returns them.
    """
    tenant_id, cfg = tenant_cfg

    allowed, used_today, daily_cap = await async_check_tenant_token_budget(tenant_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI token cap reached ({used_today:,}/{daily_cap:,} tokens). Resets at UTC midnight.",
        )

    def _load_tweet_and_release():
        tweet = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
            )
            .first()
        )
        if not tweet:
            raise HTTPException(status_code=404, detail="Tweet not found")
        if tweet.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot generate variants for tweet in '{tweet.status}' state.",
            )
        data = {
            "tweet_text": tweet.tweet_text or "",
            "tweet_author": tweet.tweet_author or "creator",
            "generated_text": tweet.generated_text or "",
            "persona_prompt": cfg.persona_prompt,
            "selected_model": cfg.selected_model or "auto",
            "custom_key": get_decrypted_api_key(cfg),
        }
        db.close()
        return data

    ctx = await asyncio.to_thread(_load_tweet_and_release)

    res = await generate_reply_variants(
        tweet_text=ctx["tweet_text"],
        tweet_author=ctx["tweet_author"],
        current_reply=ctx["generated_text"],
        persona_prompt=ctx["persona_prompt"],
        model_name=ctx["selected_model"],
        custom_key=ctx["custom_key"],
        tenant_id=tenant_id,
    )
    if not res.get("success") or not res.get("variants"):
        err_msg = res.get("error") or "Failed to generate angle variants"
        status_code = 429 if ("quota" in err_msg.lower() or "429" in err_msg) else 500
        raise HTTPException(status_code=status_code, detail=err_msg)

    def _save_variants():
        tweet_row = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
            )
            .first()
        )
        if not tweet_row:
            raise HTTPException(status_code=404, detail="Tweet not found")
        if tweet_row.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot update variants; tweet moved to '{tweet_row.status}'.",
            )
        tweet_row.variants_json = res["variants_json"]
        db.commit()

    await asyncio.to_thread(_save_variants)
    state.emit_tenant_event(tenant_id, "queue_changed", {"tweet_id": tweet_id})
    logger.info(f"Generated 3 on-demand angle variants for @{ctx['tweet_author']} (tenant={tenant_id})")
    return {
        "tweet_id": tweet_id,
        "variants": res["variants"],
        "variants_json": res["variants_json"],
    }


@router.post("/api/regenerate/{tweet_id}")
async def regenerate_tweet_draft(
    tweet_id: str,
    tenant_cfg: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """Regenerates a fresh draft for a reply, original post, or thread."""
    tenant_id, cfg = tenant_cfg

    allowed, used_today, daily_cap = await async_check_tenant_token_budget(tenant_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI token cap reached ({used_today:,}/{daily_cap:,} tokens). Resets at UTC midnight.",
        )

    def _load_context_and_release():
        tweet = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
            )
            .first()
        )
        if not tweet:
            raise HTTPException(status_code=404, detail="Tweet not found")
        if tweet.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot regenerate tweet in '{tweet.status}' state.",
            )

        learning_memory = get_learning_memory(db, limit_approved=4, limit_skipped=3, tenant_id=tenant_id)
        live_context = []
        if tweet.action_type in ("post", "thread"):
            recent_db_tweets = get_recent_tweets(db, limit=8, tenant_id=tenant_id)
            live_context = [
                {"author": r.tweet_author, "text": r.tweet_text, "metrics": r.tweet_metrics}
                for r in recent_db_tweets
                if r.action_type == "reply" and r.tweet_text
            ]

        ctx = {
            "action_type": tweet.action_type or "reply",
            "tweet_text": tweet.tweet_text or "",
            "tweet_author": tweet.tweet_author,
            "tweet_metrics": tweet.tweet_metrics or "",
            "media_url": getattr(tweet, "media_url", None),
            "persona_prompt": cfg.persona_prompt or "",
            "selected_model": cfg.selected_model or "auto",
            "search_query": state.get_active_search_query(tenant_id) or cfg.search_query,
            "custom_key": get_decrypted_api_key(cfg),
            "learning_memory": learning_memory,
            "live_context": live_context,
        }
        db.close()
        return ctx

    ctx = await asyncio.to_thread(_load_context_and_release)

    if ctx["action_type"] in ("post", "thread"):
        gen = await generate_original_content(
            mode=ctx["action_type"],
            search_query=ctx["search_query"],
            persona_prompt=ctx["persona_prompt"] + " | Take a completely fresh, different angle.",
            live_tweets=ctx["live_context"],
            model_name=ctx["selected_model"],
            custom_key=ctx["custom_key"],
            learning_memory=ctx["learning_memory"],
            include_variants=False,
            tenant_id=tenant_id,
        )
        if not gen.get("success") or not gen.get("text"):
            err_msg = gen.get("error") or gen.get("topic_summary") or "Failed to regenerate"
            err_code = gen.get("error_code")
            if not err_code:
                err_code = (
                    429
                    if ("quota" in err_msg.lower() or "429" in err_msg or "resource_exhausted" in err_msg.lower())
                    else 500
                )
            raise HTTPException(status_code=err_code, detail=err_msg)
        new_text = gen["text"]
        new_variants = gen.get("variants_json")
        new_reason = gen.get("topic_summary")
    else:
        ai_result = await evaluate_tweet(
            tweet_text=ctx["tweet_text"],
            tweet_author=ctx["tweet_author"],
            model_name=ctx["selected_model"],
            custom_key=ctx["custom_key"],
            search_query=ctx["search_query"],
            persona_prompt=ctx["persona_prompt"] + " | Write a completely fresh, different angle.",
            extra_context=f"Engagement: {ctx['tweet_metrics']}",
            temperature=0.9,
            media_url=ctx["media_url"],
            learning_memory=ctx["learning_memory"],
            include_variants=False,
            tenant_id=tenant_id,
        )
        if not ai_result.get("reply_text"):
            reason = ai_result.get("reasoning") or "Failed to regenerate draft"
            status_code = (
                429
                if ("quota" in reason.lower() or "429" in reason or "resource_exhausted" in reason.lower())
                else 500
            )
            raise HTTPException(status_code=status_code, detail=reason)
        new_text = ai_result["reply_text"]
        new_variants = ai_result.get("variants_json")
        new_reason = ai_result.get("reasoning")

    def _persist_regeneration():
        row = (
            db.query(ProcessedTweet)
            .filter(
                ProcessedTweet.tweet_id == tweet_id,
                ProcessedTweet.tenant_id == tenant_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Tweet not found")
        if row.status not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot regenerate tweet; status moved to '{row.status}'.",
            )
        updated = update_tweet_status(
            db,
            tweet_id,
            status="pending_approval",
            generated_text=new_text,
            variants_json=new_variants,
            error_message=new_reason,
            tenant_id=tenant_id,
        )
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update tweet record")
        return {
            "tweet_id": tweet_id,
            "generated_text": updated.generated_text,
            "variants_json": updated.variants_json,
        }

    result = await asyncio.to_thread(_persist_regeneration)
    state.emit_tenant_event(tenant_id, "queue_changed", {"tweet_id": tweet_id, "status": "pending_approval"})
    logger.info(f"Regenerated fresh draft for @{ctx['tweet_author']} (tenant={tenant_id})")
    return result


@router.post("/api/generate-original")
async def generate_original_endpoint(
    payload: GenerateOriginalPayload,
    tenant_cfg: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """
    Generates a fresh Original Post or Multi-Post Thread from real-time conversations,
    user voice memory, and current topic pulse, enforcing queue & plan caps.
    """
    tenant_id, cfg = tenant_cfg

    allowed, used_today, daily_cap = await async_check_tenant_token_budget(tenant_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily AI token cap reached ({used_today:,}/{daily_cap:,} tokens). Resets at UTC midnight.",
        )

    def _load_context_and_release():
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

        topic = (
            payload.custom_topic
            or state.get_active_search_query(tenant_id)
            or cfg.search_query
            or "tech & culture"
        ).strip()

        recent_db_tweets = get_recent_tweets(db, limit=10, tenant_id=tenant_id)
        live_context = [
            {
                "author": r.tweet_author,
                "text": r.tweet_text,
                "metrics": r.tweet_metrics,
            }
            for r in recent_db_tweets
            if r.action_type == "reply" and r.tweet_text
        ]
        learning_memory = get_learning_memory(db, limit_approved=4, limit_skipped=3, tenant_id=tenant_id)
        ctx = {
            "topic": topic,
            "persona_prompt": cfg.persona_prompt,
            "selected_model": cfg.selected_model or "auto",
            "linked_username": cfg.linked_username,
            "custom_key": get_decrypted_api_key(cfg),
            "live_context": live_context,
            "learning_memory": learning_memory,
        }
        db.close()
        return ctx

    ctx = await asyncio.to_thread(_load_context_and_release)
    req_mode = payload.mode if payload.mode in ("auto", "post", "thread") else "auto"

    gen = await generate_original_content(
        mode=req_mode,
        search_query=ctx["topic"],
        persona_prompt=ctx["persona_prompt"],
        live_tweets=ctx["live_context"],
        model_name=ctx["selected_model"],
        custom_key=ctx["custom_key"],
        learning_memory=ctx["learning_memory"],
        include_variants=False,
        tenant_id=tenant_id,
    )
    if not gen.get("success") or not gen.get("text"):
        err_msg = gen.get("error") or gen.get("topic_summary") or "Failed to generate content"
        err_code = gen.get("error_code")
        if not err_code:
            err_code = (
                429
                if ("quota" in err_msg.lower() or "429" in err_msg or "resource_exhausted" in err_msg.lower())
                else 500
            )
        raise HTTPException(status_code=err_code, detail=err_msg)

    final_mode = gen.get("action_type") or ("thread" if req_mode == "thread" else "post")
    orig_id = f"{final_mode}_{uuid.uuid4().hex[:12]}"
    worker = state.tenant_workers.get(tenant_id)
    author_label = ((worker.logged_in_username if worker else None) or ctx["linked_username"] or "you").lstrip("@")

    def _save_original():
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
            error_message=gen["topic_summary"],
        )
        return item.tweet_id

    saved_id = await asyncio.to_thread(_save_original)
    state.emit_tenant_event(tenant_id, "queue_changed", {"tweet_id": saved_id, "status": "pending_approval"})
    logger.info(f"Generated new {final_mode} on '{ctx['topic']}' for tenant '{tenant_id}'")
    return {"status": "created", "tweet_id": saved_id, "action_type": final_mode}
