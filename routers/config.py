"""
Configuration & AI Settings Router for X-VibeBot.
Manages agent execution switches, active hours, persona prompt, and Gemini/DeepSeek API key validation.
"""

import os
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel

from models import AgentConfigResponse, AgentConfigUpdate, TestKeyPayload
from database import get_db, get_agent_config, update_agent_config
from core.dependencies import get_current_tenant
import core.state as state
from ai_engine import test_ai_api

logger = logging.getLogger("x_vibebot.config")
router = APIRouter(tags=["config"])


@router.get("/api/config", response_model=AgentConfigResponse)
async def get_config(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Retrieves runtime configuration toggles for the requesting tenant."""
    cfg = get_agent_config(db, tenant_id=tenant_id)
    worker = state.get_tenant_browser_worker(tenant_id)
    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or getattr(cfg, "api_key", None) or ""
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
        selected_model=cfg.selected_model or "gemini-2.0-flash",
        linked_username=worker.logged_in_username or cfg.linked_username,
        masked_api_key=masked_key,
        updated_at=cfg.updated_at
    )


@router.post("/api/config", response_model=AgentConfigResponse)
async def update_config_endpoint(
    payload: AgentConfigUpdate,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Updates runtime agent settings and updates local .env API keys when provided."""
    updates = payload.model_dump(exclude_unset=True, exclude={"api_key"})
    if payload.api_key is not None and payload.api_key.strip():
        clean_key = payload.api_key.strip()
        updates["api_key"] = clean_key
        if clean_key.startswith("sk-"):
            state.update_env_variable("DEEPSEEK_API_KEY", clean_key)
        else:
            state.update_env_variable("GEMINI_API_KEY", clean_key)

    updated = update_agent_config(db, updates, tenant_id=tenant_id)
    worker = state.get_tenant_browser_worker(tenant_id)
    logger.info(f"Settings updated for tenant '{tenant_id}'.")

    current_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or getattr(updated, "api_key", None) or ""
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
        selected_model=updated.selected_model or "gemini-2.0-flash",
        linked_username=worker.logged_in_username or updated.linked_username,
        masked_api_key=masked_key,
        updated_at=updated.updated_at
    )


@router.get("/api/ai/models")
async def get_models_endpoint():
    """Returns accessible Google Gemini / DeepSeek models."""
    return await test_ai_api()


@router.post("/api/ai/test-key")
async def test_key_endpoint(payload: TestKeyPayload, db: Session = Depends(get_db)):
    """Tests an AI API key against Google Gemini / DeepSeek and saves it if valid."""
    key = payload.api_key.strip() if payload.api_key else None
    result = await test_ai_api(custom_key=key)
    if result.get("success") and key:
        if key.startswith("sk-"):
            state.update_env_variable("DEEPSEEK_API_KEY", key)
        else:
            state.update_env_variable("GEMINI_API_KEY", key)
            models = result.get("models") or []
            if models:
                update_agent_config(db, {"selected_model": models[0]["id"]})
    return result


@router.post("/api/verify-gemini")
async def verify_gemini_endpoint(
    payload: Optional[TestKeyPayload] = None,
    db: Session = Depends(get_db)
):
    """
    Validates a Google Gemini API key and returns available models and verification status.
    Alias for /api/ai/test-key.
    """
    key = payload.api_key.strip() if (payload and payload.api_key) else None
    return await test_key_endpoint(payload=TestKeyPayload(api_key=key), db=db)
