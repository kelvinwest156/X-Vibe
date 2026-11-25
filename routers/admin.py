"""
Super Admin Router for X-VibeBot Standalone Admin Portal.
Provides isolated owner authentication, live AI token spend & cache telemetry,
platform guardrails management, multi-tenant user configuration, and Chromium RAM controls.
"""

import os
import re
import hmac
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import core.state as state
from core.dependencies import require_super_admin
from core.security import is_production_env, scrub_secrets, rate_limiter, get_client_ip
from models import User, AgentConfig, PlatformSettings
from services.plans import PLAN_CATALOG, is_subscription_valid, apply_plan_to_config
from database import (
    get_db,
    create_super_admin_token,
    get_platform_settings,
    update_platform_settings,
    get_admin_platform_metrics,
    get_admin_user_aggregates,
    get_agent_config,
    get_tenant_daily_tokens,
    get_tenant_daily_cost_usd,
    get_daily_actions_count,
    get_pending_approval_count,
    update_agent_config,
    is_within_active_hours,
)

logger = logging.getLogger("x_vibebot.admin")

router = APIRouter(prefix="/api/admin", tags=["Super Admin"])

# Development-only Super Admin credentials (never accepted in production)
DEFAULT_SUPER_ADMIN_EMAIL = "admin@xbot.org"
DEFAULT_SUPER_ADMIN_PASSWORD = "Password123"
ALLOWED_SUBSCRIPTION_STATUSES = frozenset({"trialing", "active", "expired", "canceled", "suspended"})

# DeepSeek V3 reference pricing (USD per 1M tokens) for cache savings calculation
DEEPSEEK_CACHE_HIT_RATE_PER_1M = 0.07
DEEPSEEK_CACHE_MISS_RATE_PER_1M = 0.27


# ==============================================================================
# Admin Pydantic Schemas (Scoped to routers/admin.py)
# ==============================================================================

class AdminLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=255)


class AdminLoginResponse(BaseModel):
    token: str
    email: str
    role: str = "super_admin"


class AdminMeResponse(BaseModel):
    authenticated: bool = True
    email: str
    role: str = "super_admin"


class PlatformSettingsUpdatePayload(BaseModel):
    default_daily_token_cap: Optional[int] = Field(None, ge=1000, le=5000000)
    web_radar_cache_seconds: Optional[int] = Field(None, ge=300, le=86400)
    browser_idle_sleep_minutes: Optional[int] = Field(None, ge=1, le=1440)
    auto_sleep_browsers_enabled: Optional[bool] = None
    global_pause_bots: Optional[bool] = None


class AdminUserUpdatePayload(BaseModel):
    is_active: Optional[bool] = None
    is_suspended: Optional[bool] = None
    auto_pilot_mode: Optional[bool] = None
    warmup_mode: Optional[bool] = None
    daily_action_cap: Optional[int] = Field(None, ge=1, le=200)
    hourly_action_cap: Optional[int] = Field(None, ge=1, le=60)
    daily_token_cap: Optional[int] = Field(None, ge=1000, le=5000000)
    max_pending_queue: Optional[int] = Field(None, ge=1, le=100)
    polling_interval_minutes: Optional[int] = Field(None, ge=5, le=240)
    active_hours_start: Optional[int] = Field(None, ge=0, le=23)
    active_hours_end: Optional[int] = Field(None, ge=0, le=23)
    auto_sleep_browser: Optional[bool] = None
    plan_tier: Optional[str] = None
    subscription_status: Optional[str] = None
    daily_original_post_cap: Optional[int] = Field(None, ge=1, le=20)
    extend_trial_days: Optional[int] = Field(None, ge=1, le=90)


# ==============================================================================
# Internal Serialization & Telemetry Helpers
# ==============================================================================

def _sanitize_tenant_key(tenant_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", tenant_id or "default")


def _get_worker_for_tenant(tenant_id: str):
    if tenant_id in state.tenant_workers:
        return state.tenant_workers[tenant_id]
    clean = _sanitize_tenant_key(tenant_id)
    return state.tenant_workers.get(clean)


def _get_worker_memory_stats(worker) -> Dict[str, Any]:
    """Safely queries worker.get_memory_stats() with attribute fallback."""
    if worker is None:
        return {
            "is_running": False,
            "idle_seconds": 0,
            "estimated_ram_mb": 0.0,
            "logged_in_username": None,
        }

    stats_fn = getattr(worker, "get_memory_stats", None)
    if callable(stats_fn):
        try:
            raw = stats_fn()
            if isinstance(raw, dict):
                return {
                    "is_running": bool(raw.get("is_running", False)),
                    "idle_seconds": int(raw.get("idle_seconds", 0) or 0),
                    "estimated_ram_mb": round(float(raw.get("estimated_ram_mb", 0.0) or 0.0), 1),
                    "logged_in_username": raw.get("logged_in_username") or getattr(worker, "logged_in_username", None),
                }
        except Exception as exc:
            logger.debug(f"Worker get_memory_stats fallback: {exc}")

    is_running = bool(
        getattr(worker, "is_running", False)
        or getattr(worker, "_browser_context", None) is not None
        or getattr(worker, "context", None) is not None
    )
    last_used = float(getattr(worker, "last_used_at", 0.0) or 0.0)
    idle_seconds = int(max(0.0, time.time() - last_used)) if (is_running and last_used > 0) else 0
    estimated_ram = 140.0 if is_running else 0.0
    return {
        "is_running": is_running,
        "idle_seconds": idle_seconds,
        "estimated_ram_mb": estimated_ram,
        "logged_in_username": getattr(worker, "logged_in_username", None),
    }


def _detect_system_ram_limit_mb(psutil_mod=None) -> float:
    """Determines container or host RAM ceiling in MB (Render/cgroup aware)."""
    for env_key in ("RENDER_RAM_LIMIT_MB", "SERVER_RAM_LIMIT_MB"):
        raw = os.getenv(env_key)
        if raw:
            try:
                val = float(raw)
                if val > 0:
                    return round(val, 1)
            except ValueError:
                pass

    # Linux cgroup v2 / v1 container memory limits (e.g., Render 512MB container)
    for cg_path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            if os.path.isfile(cg_path):
                with open(cg_path, "r", encoding="utf-8") as fh:
                    text = fh.read().strip()
                if text.isdigit():
                    limit_bytes = int(text)
                    # Ignore unbounded sentinel values (> 64 GB)
                    if 64 * 1024 * 1024 <= limit_bytes <= 64 * 1024 * 1024 * 1024:
                        return round(limit_bytes / (1024 * 1024), 1)
        except Exception:
            pass

    if os.getenv("RENDER"):
        return 512.0

    if psutil_mod is not None:
        try:
            return round(psutil_mod.virtual_memory().total / (1024 * 1024), 1)
        except Exception:
            pass

    return 512.0


def _collect_server_ram_stats() -> Dict[str, Any]:
    """Measures live Python RSS + Chromium child process RSS using psutil with safe fallback."""
    psutil_mod = None
    try:
        import psutil as _psutil
        psutil_mod = _psutil
    except ImportError:
        psutil_mod = None

    awake_count = 0
    worker_est_ram_mb = 0.0
    for w in list(state.tenant_workers.values()):
        ws = _get_worker_memory_stats(w)
        if ws["is_running"]:
            awake_count += 1
            worker_est_ram_mb += float(ws["estimated_ram_mb"])

    total_browsers = len(state.tenant_workers)
    process_rss_mb = 0.0
    chromium_rss_mb = 0.0

    if psutil_mod is not None:
        try:
            proc = psutil_mod.Process(os.getpid())
            process_rss_mb = proc.memory_info().rss / (1024 * 1024)
            child_browser_mb = 0.0
            for child in proc.children(recursive=True):
                try:
                    name = (child.name() or "").lower()
                    if any(tok in name for tok in ("chrom", "playwright", "headless", "firefox", "webkit")):
                        child_browser_mb += child.memory_info().rss / (1024 * 1024)
                except Exception:
                    continue
            chromium_rss_mb = child_browser_mb if child_browser_mb > 0 else worker_est_ram_mb
        except Exception as exc:
            logger.debug(f"psutil RSS read fallback: {exc}")
            chromium_rss_mb = worker_est_ram_mb
    else:
        chromium_rss_mb = worker_est_ram_mb

    total_rss_mb = round(process_rss_mb + chromium_rss_mb, 1)
    limit_mb = _detect_system_ram_limit_mb(psutil_mod)
    utilization_pct = round(min(100.0, (total_rss_mb / limit_mb) * 100.0), 1) if limit_mb > 0 else 0.0

    return {
        "process_rss_mb": round(process_rss_mb, 1),
        "chromium_rss_mb": round(chromium_rss_mb, 1),
        "total_rss_mb": total_rss_mb,
        "system_ram_limit_mb": limit_mb,
        "utilization_pct": utilization_pct,
        "awake_browsers_count": awake_count,
        "total_browsers_count": total_browsers,
        "psutil_available": psutil_mod is not None,
    }


def _serialize_platform_settings(settings_row: PlatformSettings) -> Dict[str, Any]:
    updated_at = getattr(settings_row, "updated_at", None)
    return {
        "default_daily_token_cap": int(getattr(settings_row, "default_daily_token_cap", 50000) or 50000),
        "web_radar_cache_seconds": int(getattr(settings_row, "web_radar_cache_seconds", 7200) or 7200),
        "browser_idle_sleep_minutes": int(getattr(settings_row, "browser_idle_sleep_minutes", 15) or 15),
        "auto_sleep_browsers_enabled": bool(getattr(settings_row, "auto_sleep_browsers_enabled", True)),
        "global_pause_bots": bool(getattr(settings_row, "global_pause_bots", False)),
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
    }


def _get_super_admin_credentials() -> Tuple[str, str]:
    """Resolves Super Admin credentials, failing closed in production if unset."""
    env_email = (os.getenv("SUPER_ADMIN_EMAIL") or "").strip().lower()
    env_password = os.getenv("SUPER_ADMIN_PASSWORD") or ""
    if is_production_env():
        if not env_email or not env_password:
            raise HTTPException(
                status_code=503,
                detail="Super Admin credentials are not configured on this server.",
            )
        return env_email, env_password
    return (
        env_email or DEFAULT_SUPER_ADMIN_EMAIL,
        env_password or DEFAULT_SUPER_ADMIN_PASSWORD,
    )


def _build_user_summary(
    db: Optional[Session],
    tenant_id: str,
    user: Optional[Any],
    cfg: Optional[Any],
    default_token_cap: int = 50000,
    daily_actions_used: Optional[int] = None,
    pending_count: Optional[int] = None,
    daily_tokens_used: Optional[int] = None,
    daily_cost_usd: Optional[float] = None,
) -> Dict[str, Any]:
    worker = _get_worker_for_tenant(tenant_id)
    w_stats = _get_worker_memory_stats(worker)

    if daily_actions_used is None and db is not None:
        try:
            daily_actions_used = int(get_daily_actions_count(db, tenant_id=tenant_id) or 0)
        except Exception:
            daily_actions_used = 0
    else:
        daily_actions_used = int(daily_actions_used or 0)

    if daily_tokens_used is None and db is not None:
        try:
            daily_tokens_used = int(get_tenant_daily_tokens(db, tenant_id=tenant_id) or 0)
        except Exception:
            daily_tokens_used = 0
    else:
        daily_tokens_used = int(daily_tokens_used or 0)

    if daily_cost_usd is None and db is not None:
        try:
            daily_cost_usd = round(float(get_tenant_daily_cost_usd(db, tenant_id=tenant_id) or 0.0), 6)
        except Exception:
            daily_cost_usd = 0.0
    else:
        daily_cost_usd = round(float(daily_cost_usd or 0.0), 6)

    if pending_count is None and db is not None:
        try:
            pending_count = int(get_pending_approval_count(db, tenant_id=tenant_id) or 0)
        except Exception:
            pending_count = 0
    else:
        pending_count = int(pending_count or 0)

    linked_username = (getattr(cfg, "linked_username", None) if cfg else None) or w_stats.get("logged_in_username")
    created_at = getattr(user, "created_at", None) if user else getattr(cfg, "updated_at", None)

    _sub_ok, eff_status, days_left = is_subscription_valid(cfg) if cfg else (False, "trialing", 7)

    return {
        "tenant_id": tenant_id,
        "email": user.email if user else f"{tenant_id}@local.workspace",
        "name": (user.name if user and user.name else (tenant_id if tenant_id != "default" else "Local Default")),
        "linked_username": linked_username,
        "plan_tier": getattr(cfg, "plan_tier", "trial") if cfg else "trial",
        "subscription_status": eff_status,
        "trial_days_remaining": days_left,
        "daily_original_post_cap": int(getattr(cfg, "daily_original_post_cap", 3) or 3) if cfg else 3,
        "is_active": bool(getattr(cfg, "is_active", False)) if cfg else False,
        "is_suspended": bool(getattr(cfg, "is_suspended", False)) if cfg else False,
        "auto_pilot_mode": bool(getattr(cfg, "auto_pilot_mode", False)) if cfg else False,
        "warmup_mode": bool(getattr(cfg, "warmup_mode", False)) if cfg else False,
        "daily_action_cap": int(getattr(cfg, "daily_action_cap", 15) or 15) if cfg else 15,
        "hourly_action_cap": int(getattr(cfg, "hourly_action_cap", 6) or 6) if cfg else 6,
        "daily_actions_used": daily_actions_used,
        "daily_token_cap": int(getattr(cfg, "daily_token_cap", default_token_cap) or default_token_cap) if cfg else default_token_cap,
        "daily_tokens_used": daily_tokens_used,
        "daily_cost_usd": daily_cost_usd,
        "max_pending_queue": int(getattr(cfg, "max_pending_queue", 8) or 8) if cfg else 8,
        "pending_count": pending_count,
        "polling_interval_minutes": int(getattr(cfg, "polling_interval_minutes", 20) or 20) if cfg else 20,
        "active_hours_start": int(getattr(cfg, "active_hours_start", 8) if getattr(cfg, "active_hours_start", None) is not None else 8) if cfg else 8,
        "active_hours_end": int(getattr(cfg, "active_hours_end", 23) if getattr(cfg, "active_hours_end", None) is not None else 23) if cfg else 23,
        "auto_sleep_browser": bool(getattr(cfg, "auto_sleep_browser", True)) if cfg else True,
        "browser_running": bool(w_stats["is_running"]),
        "browser_ram_mb": float(w_stats["estimated_ram_mb"]),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
    }


# ==============================================================================
# Authentication Endpoints
# ==============================================================================

@router.post("/auth/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest, request: Request):
    """Authenticates the platform owner using constant-time credential verification."""
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.check_and_hit(
        "admin_login", client_ip, limit=5, window_seconds=300
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    expected_email, expected_password = _get_super_admin_credentials()

    provided_email = payload.email.strip().lower()
    provided_password = payload.password

    email_ok = hmac.compare_digest(provided_email.encode("utf-8"), expected_email.encode("utf-8"))
    password_ok = hmac.compare_digest(provided_password.encode("utf-8"), expected_password.encode("utf-8"))

    if not (email_ok and password_ok):
        raise HTTPException(status_code=401, detail="Invalid Super Admin email or password.")

    token = create_super_admin_token(expected_email, expires_hours=12)
    return AdminLoginResponse(token=token, email=expected_email, role="super_admin")


@router.get("/auth/me", response_model=AdminMeResponse)
async def admin_me(admin: Dict[str, Any] = Depends(require_super_admin)):
    """Verifies the active Super Admin session."""
    fallback_email = "" if is_production_env() else DEFAULT_SUPER_ADMIN_EMAIL
    resolved_email = str(admin.get("email") or os.getenv("SUPER_ADMIN_EMAIL") or fallback_email).strip().lower()
    if is_production_env() and not resolved_email:
        raise HTTPException(
            status_code=503,
            detail="Super Admin credentials are not configured on this server.",
        )
    return AdminMeResponse(
        authenticated=True,
        email=resolved_email,
        role="super_admin",
    )


# ==============================================================================
# Platform Overview & Global Guardrails
# ==============================================================================

@router.get("/overview")
async def get_admin_overview(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Returns platform-wide AI spend, token usage, cache savings, live RAM, and global settings."""
    metrics = get_admin_platform_metrics(db, days=days)
    settings_row = get_platform_settings(db)
    ram_stats = await asyncio.to_thread(_collect_server_ram_stats)

    return {
        "days": metrics.get("days", days),
        "summary": metrics.get("summary", {}),
        "daily_series": metrics.get("daily_series", []),
        "task_breakdown": metrics.get("task_breakdown", []),
        "ram": ram_stats,
        "settings": _serialize_platform_settings(settings_row),
    }


@router.patch("/settings")
async def patch_admin_settings(
    payload: PlatformSettingsUpdatePayload,
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Updates global PlatformSettings guardrails."""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        settings_row = get_platform_settings(db)
        return {"success": True, "settings": _serialize_platform_settings(settings_row)}

    updated = update_platform_settings(db, updates)
    logger.info(f"Super Admin updated platform settings: {list(updates.keys())}")
    return {"success": True, "settings": _serialize_platform_settings(updated)}


# ==============================================================================
# Multi-Tenant User Management
# ==============================================================================

@router.get("/users")
async def list_admin_users(
    search: Optional[str] = Query(None, max_length=128),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Lists creator tenants with SQL-aggregated usage metrics, caps, and live browser status."""
    settings_row = get_platform_settings(db)
    default_token_cap = int(getattr(settings_row, "default_daily_token_cap", 50000) or 50000)

    tweet_stats, token_stats = get_admin_user_aggregates(db)

    users = db.query(
        User.tenant_id,
        User.email,
        User.name,
        User.created_at,
    ).all()
    configs = db.query(
        AgentConfig.tenant_id,
        AgentConfig.linked_username,
        AgentConfig.plan_tier,
        AgentConfig.subscription_status,
        AgentConfig.trial_ends_at,
        AgentConfig.daily_original_post_cap,
        AgentConfig.is_active,
        AgentConfig.is_suspended,
        AgentConfig.auto_pilot_mode,
        AgentConfig.warmup_mode,
        AgentConfig.daily_action_cap,
        AgentConfig.hourly_action_cap,
        AgentConfig.daily_token_cap,
        AgentConfig.max_pending_queue,
        AgentConfig.polling_interval_minutes,
        AgentConfig.active_hours_start,
        AgentConfig.active_hours_end,
        AgentConfig.auto_sleep_browser,
        AgentConfig.updated_at,
    ).all()

    user_by_tenant: Dict[str, Any] = {u.tenant_id: u for u in users}
    cfg_by_tenant: Dict[str, Any] = {c.tenant_id: c for c in configs}
    all_tenants = sorted(set(user_by_tenant.keys()) | set(cfg_by_tenant.keys()))

    q = (search or "").strip().lower()
    summaries: List[Dict[str, Any]] = []

    for tid in all_tenants:
        d_actions, pend = tweet_stats.get(tid, (0, 0))
        d_tokens, d_cost = token_stats.get(tid, (0, 0.0))
        summary = _build_user_summary(
            None,
            tenant_id=tid,
            user=user_by_tenant.get(tid),
            cfg=cfg_by_tenant.get(tid),
            default_token_cap=default_token_cap,
            daily_actions_used=d_actions,
            pending_count=pend,
            daily_tokens_used=d_tokens,
            daily_cost_usd=d_cost,
        )
        if q:
            haystack = " ".join(
                str(v or "").lower()
                for v in (
                    summary["tenant_id"],
                    summary["email"],
                    summary["name"],
                    summary["linked_username"],
                )
            )
            if q not in haystack:
                continue
        summaries.append(summary)

    summaries.sort(
        key=lambda item: (
            1 if item["is_suspended"] else 0,
            0 if item["is_active"] else 1,
            -item["daily_tokens_used"],
            item["email"],
        )
    )

    total = len(summaries)
    paginated = summaries[offset : offset + limit]
    return {"total": total, "users": paginated}


@router.patch("/users/{tenant_id}")
async def update_admin_user(
    tenant_id: str,
    payload: AdminUserUpdatePayload,
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Updates per-tenant caps, active hours, automation toggles, or suspension status."""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates.get("is_suspended") is True:
        updates["is_active"] = False

    normalized_plan: Optional[str] = None
    if payload.plan_tier is not None:
        normalized_plan = payload.plan_tier.strip().lower()
        if normalized_plan not in PLAN_CATALOG:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid plan_tier '{payload.plan_tier}'. Must be one of: {', '.join(PLAN_CATALOG.keys())}.",
            )

    normalized_status: Optional[str] = None
    if payload.subscription_status is not None:
        normalized_status = payload.subscription_status.strip().lower()
        if normalized_status not in ALLOWED_SUBSCRIPTION_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid subscription_status '{payload.subscription_status}'.",
            )

    cfg_pre = get_agent_config(db, tenant_id=tenant_id)

    # Apply plan preset before explicit cap overrides so custom limits in the same PATCH are preserved
    if normalized_plan is not None:
        current_plan = (getattr(cfg_pre, "plan_tier", None) or "").strip().lower()
        if normalized_plan != current_plan:
            target_status = normalized_status or ("trialing" if normalized_plan == "trial" else "active")
            apply_plan_to_config(cfg_pre, normalized_plan, status=target_status)
        elif normalized_status is not None:
            cfg_pre.subscription_status = normalized_status
            if normalized_status == "trialing" and not getattr(cfg_pre, "trial_ends_at", None):
                cfg_pre.trial_ends_at = datetime.utcnow() + timedelta(days=7)
        updates.pop("plan_tier", None)
        updates.pop("subscription_status", None)
    elif normalized_status is not None:
        cfg_pre.subscription_status = normalized_status
        if normalized_status == "trialing" and not getattr(cfg_pre, "trial_ends_at", None):
            cfg_pre.trial_ends_at = datetime.utcnow() + timedelta(days=7)
        updates.pop("subscription_status", None)

    if payload.extend_trial_days:
        current_end = getattr(cfg_pre, "trial_ends_at", None) or datetime.utcnow()
        cfg_pre.trial_ends_at = max(current_end, datetime.utcnow()) + timedelta(days=payload.extend_trial_days)
        cfg_pre.subscription_status = "trialing"

    # Remove non-column helper keys from updates dictionary before direct ORM update
    updates.pop("extend_trial_days", None)

    updated_cfg = update_agent_config(db, updates, tenant_id=tenant_id)

    # Immediately stop running Chromium worker if user was suspended
    if updates.get("is_suspended") is True:
        worker = _get_worker_for_tenant(tenant_id)
        if worker is not None:
            w_stats = _get_worker_memory_stats(worker)
            if w_stats["is_running"]:
                try:
                    await worker.stop()
                except Exception as exc:
                    logger.warning(f"Failed stopping browser for suspended tenant '{tenant_id}': {scrub_secrets(exc)}")

    settings_row = get_platform_settings(db)
    default_token_cap = int(getattr(settings_row, "default_daily_token_cap", 50000) or 50000)
    user = (
        db.query(User.tenant_id, User.email, User.name, User.created_at)
        .filter(User.tenant_id == tenant_id)
        .first()
    )

    logger.info(f"Super Admin updated tenant '{tenant_id}': {list(updates.keys())}")
    return {
        "success": True,
        "user": _build_user_summary(
            db,
            tenant_id=tenant_id,
            user=user,
            cfg=updated_cfg,
            default_token_cap=default_token_cap,
        ),
    }


# ==============================================================================
# Infrastructure & Browser Worker RAM Controls
# ==============================================================================

@router.get("/browsers")
async def list_browser_workers(
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Lists all registered Playwright browser workers, idle duration, and live RAM."""
    users = db.query(User.tenant_id, User.email).all()
    configs = db.query(
        AgentConfig.tenant_id,
        AgentConfig.linked_username,
        AgentConfig.is_active,
        AgentConfig.is_suspended,
        AgentConfig.auto_sleep_browser,
        AgentConfig.active_hours_start,
        AgentConfig.active_hours_end,
    ).all()
    user_by_key = {_sanitize_tenant_key(u.tenant_id): u for u in users}
    cfg_by_key = {_sanitize_tenant_key(c.tenant_id): c for c in configs}

    workers_payload: List[Dict[str, Any]] = []
    for worker_key, worker in list(state.tenant_workers.items()):
        w_stats = _get_worker_memory_stats(worker)
        user = user_by_key.get(worker_key)
        cfg = cfg_by_key.get(worker_key)

        start_hr = int(getattr(cfg, "active_hours_start", 8) if (cfg and getattr(cfg, "active_hours_start", None) is not None) else 8)
        end_hr = int(getattr(cfg, "active_hours_end", 23) if (cfg and getattr(cfg, "active_hours_end", None) is not None) else 23)
        cookies_path = getattr(worker, "cookies_backup_path", None)

        workers_payload.append({
            "tenant_id": user.tenant_id if user else (cfg.tenant_id if cfg else worker_key),
            "worker_key": worker_key,
            "email": user.email if user else f"{worker_key}@local.workspace",
            "linked_username": (getattr(cfg, "linked_username", None) if cfg else None) or w_stats.get("logged_in_username"),
            "is_running": bool(w_stats["is_running"]),
            "idle_seconds": int(w_stats["idle_seconds"]),
            "estimated_ram_mb": float(w_stats["estimated_ram_mb"]),
            "is_active": bool(getattr(cfg, "is_active", False)) if cfg else False,
            "is_suspended": bool(getattr(cfg, "is_suspended", False)) if cfg else False,
            "auto_sleep_browser": bool(getattr(cfg, "auto_sleep_browser", True)) if cfg else True,
            "active_hours_start": start_hr,
            "active_hours_end": end_hr,
            "within_active_hours": bool(is_within_active_hours(start_hr, end_hr)),
            "has_cookies_backup": bool(cookies_path and os.path.isfile(cookies_path)),
        })

    workers_payload.sort(key=lambda item: (0 if item["is_running"] else 1, -item["estimated_ram_mb"], item["tenant_id"]))
    settings_row = get_platform_settings(db)
    ram_stats = await asyncio.to_thread(_collect_server_ram_stats)

    return {
        "workers": workers_payload,
        "ram": ram_stats,
        "settings": _serialize_platform_settings(settings_row),
    }


@router.post("/browsers/sleep-idle")
async def sleep_idle_browsers(
    force: bool = Query(False),
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Stops idle, paused, or sleeping-hours browser workers (or all running workers when force=true)."""
    settings_row = get_platform_settings(db)
    idle_limit_sec = int(getattr(settings_row, "browser_idle_sleep_minutes", 15) or 15) * 60

    configs = db.query(
        AgentConfig.tenant_id,
        AgentConfig.is_active,
        AgentConfig.is_suspended,
        AgentConfig.active_hours_start,
        AgentConfig.active_hours_end,
    ).all()
    cfg_by_key = {_sanitize_tenant_key(c.tenant_id): c for c in configs}

    stopped_tenants: List[str] = []
    freed_mb = 0.0

    for worker_key, worker in list(state.tenant_workers.items()):
        w_stats = _get_worker_memory_stats(worker)
        if not w_stats["is_running"]:
            continue

        cfg = cfg_by_key.get(worker_key)
        is_paused_or_suspended = (cfg is not None) and (
            not getattr(cfg, "is_active", False) or getattr(cfg, "is_suspended", False)
        )
        start_hr = int(getattr(cfg, "active_hours_start", 8) if (cfg and getattr(cfg, "active_hours_start", None) is not None) else 8)
        end_hr = int(getattr(cfg, "active_hours_end", 23) if (cfg and getattr(cfg, "active_hours_end", None) is not None) else 23)
        outside_hours = not is_within_active_hours(start_hr, end_hr)
        is_idle = (w_stats["idle_seconds"] >= idle_limit_sec) or (float(getattr(worker, "last_used_at", 0.0) or 0.0) == 0.0)

        if force or is_idle or is_paused_or_suspended or outside_hours:
            try:
                await worker.stop()
                stopped_tenants.append(cfg.tenant_id if cfg else worker_key)
                freed_mb += float(w_stats["estimated_ram_mb"])
            except Exception as exc:
                logger.warning(f"Error sleeping browser worker '{worker_key}': {scrub_secrets(exc)}")

    logger.info(f"Super Admin sleep-idle (force={force}): stopped {len(stopped_tenants)} worker(s), ~{round(freed_mb, 1)} MB freed.")
    return {
        "success": True,
        "stopped_count": len(stopped_tenants),
        "stopped_tenants": stopped_tenants,
        "estimated_ram_freed_mb": round(freed_mb, 1),
    }


@router.post("/browsers/{tenant_id}/stop")
async def stop_tenant_browser(
    tenant_id: str,
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Gracefully stops a single tenant's Chromium process while preserving session cookies."""
    worker = _get_worker_for_tenant(tenant_id)
    if worker is None:
        return {
            "success": True,
            "tenant_id": tenant_id,
            "already_asleep": True,
            "estimated_ram_freed_mb": 0.0,
        }

    w_stats = _get_worker_memory_stats(worker)
    if not w_stats["is_running"]:
        return {
            "success": True,
            "tenant_id": tenant_id,
            "already_asleep": True,
            "estimated_ram_freed_mb": 0.0,
        }

    try:
        await worker.stop()
    except Exception as exc:
        logger.error(f"Failed to stop browser worker for tenant '{tenant_id}': {scrub_secrets(exc)}")
        raise HTTPException(status_code=500, detail="Failed to stop browser worker.")

    freed = round(float(w_stats["estimated_ram_mb"]), 1)
    logger.info(f"Super Admin stopped browser worker for tenant '{tenant_id}' (~{freed} MB freed).")
    return {
        "success": True,
        "tenant_id": tenant_id,
        "already_asleep": False,
        "estimated_ram_freed_mb": freed,
    }
