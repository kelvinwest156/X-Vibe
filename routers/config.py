"""
Configuration & AI Settings Router for X-VibeBot.
Manages per-tenant runtime toggles, active hours, persona prompt, encrypted personal AI keys,
and Gemini/DeepSeek key verification without mutating global environment state.
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import AgentConfig, AgentConfigResponse, AgentConfigUpdate, TestKeyPayload
from database import get_db, get_agent_config, update_agent_config, get_decrypted_api_key
from core.dependencies import get_current_tenant
import core.state as state
from ai_engine import test_ai_api

logger = logging.getLogger("x_vibebot.config")
router = APIRouter(tags=["config"])


def _mask_tenant_or_env_key(cfg: AgentConfig) -> str:
    """Masks the tenant's decrypted personal key, falling back to server env only if unset."""
    current_key = (
        get_decrypted_api_key(cfg)
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    )
    if not current_key:
        return ""
    if len(current_key) > 8:
        return current_key[:4] + "..." + current_key[-4:]
    return "***"


def _serialize_config(cfg: AgentConfig, tenant_id: str) -> AgentConfigResponse:
    """Builds a complete AgentConfigResponse including all subscription/plan fields."""
    worker = state.tenant_workers.get(tenant_id)
    linked_user = (worker.logged_in_username if worker else None) or cfg.linked_username
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
        selected_model=cfg.selected_model or "auto",
        linked_username=linked_user,
        masked_api_key=_mask_tenant_or_env_key(cfg),
        plan_tier=getattr(cfg, "plan_tier", "trial") or "trial",
        subscription_status=getattr(cfg, "subscription_status", "trialing") or "trialing",
        trial_ends_at=getattr(cfg, "trial_ends_at", None),
        daily_original_post_cap=int(getattr(cfg, "daily_original_post_cap", 3) or 3),
        updated_at=cfg.updated_at,
    )


@router.get("/api/config", response_model=AgentConfigResponse)
def get_config(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Retrieves runtime configuration toggles for the requesting tenant."""
    cfg = get_agent_config(db, tenant_id=tenant_id)
    return _serialize_config(cfg, tenant_id)


@router.post("/api/config", response_model=AgentConfigResponse)
async def update_config_endpoint(
    payload: AgentConfigUpdate,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Updates runtime agent settings and stores any custom API key encrypted per-tenant in DB."""
    updates = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    if payload.api_key is not None and payload.api_key.strip():
        updates["api_key"] = payload.api_key.strip()

    def _save_config():
        existing = get_agent_config(db, tenant_id=tenant_id)
        eff_min = (
            updates["min_cooldown_minutes"]
            if "min_cooldown_minutes" in updates and updates["min_cooldown_minutes"] is not None
            else (existing.min_cooldown_minutes or 10)
        )
        eff_max = (
            updates["max_cooldown_minutes"]
            if "max_cooldown_minutes" in updates and updates["max_cooldown_minutes"] is not None
            else (existing.max_cooldown_minutes or 45)
        )
        if eff_min > eff_max:
            raise HTTPException(
                status_code=400,
                detail="min_cooldown_minutes cannot exceed max_cooldown_minutes.",
            )
        updated = update_agent_config(db, updates, tenant_id=tenant_id)
        return _serialize_config(updated, tenant_id)

    resp = await asyncio.to_thread(_save_config)
    logger.info(f"Settings updated for tenant '{tenant_id}'.")
    state.emit_tenant_event(tenant_id, "config_changed", {})
    return resp


@router.get("/api/ai/models")
async def get_models_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Returns accessible Google Gemini / DeepSeek models for the authenticated tenant."""
    def _get_key_and_release():
        cfg = get_agent_config(db, tenant_id=tenant_id)
        key = get_decrypted_api_key(cfg)
        db.close()
        return key

    custom_key = await asyncio.to_thread(_get_key_and_release)
    return await test_ai_api(custom_key=custom_key, tenant_id=tenant_id)


@router.post("/api/ai/test-key")
async def test_key_endpoint(
    payload: TestKeyPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Tests an AI API key against Google Gemini / DeepSeek and saves it encrypted for the tenant if valid."""
    provided_key = payload.api_key.strip() if payload.api_key else None

    def _get_effective_key_and_release():
        cfg = get_agent_config(db, tenant_id=tenant_id)
        eff = provided_key or get_decrypted_api_key(cfg)
        db.close()
        return eff

    effective_key = await asyncio.to_thread(_get_effective_key_and_release)
    result = await test_ai_api(custom_key=effective_key, tenant_id=tenant_id)

    if result.get("success") and provided_key:
        db_updates: Dict[str, Any] = {"api_key": provided_key}
        if not provided_key.startswith("sk-"):
            models = result.get("models") or []
            if models:
                db_updates["selected_model"] = models[0]["id"]
        await asyncio.to_thread(update_agent_config, db, db_updates, tenant_id)

    return result


@router.post("/api/verify-gemini")
async def verify_gemini_endpoint(
    payload: Optional[TestKeyPayload] = None,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Validates a Google Gemini API key and returns available models and verification status.
    Alias for /api/ai/test-key.
    """
    key = payload.api_key.strip() if (payload and payload.api_key) else None
    return await test_key_endpoint(
        payload=TestKeyPayload(api_key=key),
        tenant_id=tenant_id,
        db=db,
    )
