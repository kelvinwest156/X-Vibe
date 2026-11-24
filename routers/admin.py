"""
Super Admin Router for X-VibeBot Standalone Admin Portal.
Provides isolated owner authentication, live AI token spend & cache telemetry,
platform guardrails management, multi-tenant user configuration, and Chromium RAM controls.
"""

import os
import re
import hmac
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import core.state as state
from core.dependencies import require_super_admin
from models import User, AgentConfig, ProcessedTweet, TokenUsageLog, PlatformSettings
from database import (
    get_db,
    create_super_admin_token,
    verify_super_admin_token,
    get_platform_settings,
    update_platform_settings,
    get_admin_platform_metrics,
    get_tenant_daily_tokens,
    get_tenant_daily_cost_usd,
    get_daily_actions_count,
    get_pending_approval_count,
    update_agent_config,
    is_within_active_hours,
)

logger = logging.getLogger("x_vibebot.admin")

router = APIRouter(prefix="/api/admin", tags=["Super Admin"])

# Default Super Admin credentials (override in production via environment variables)
DEFAULT_SUPER_ADMIN_EMAIL = "admin@xbot.org"
DEFAULT_SUPER_ADMIN_PASSWORD = "Password123"

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


def _build_user_summary(
    db: Session,
    tenant_id: str,
    user: Optional[User],
    cfg: Optional[AgentConfig],
    default_token_cap: int = 50000,
) -> Dict[str, Any]:
    worker = _get_worker_for_tenant(tenant_id)
    w_stats = _get_worker_memory_stats(worker)

    daily_actions_used = 0
    try:
        daily_actions_used = int(get_daily_actions_count(db, tenant_id=tenant_id) or 0)
    except Exception:
        pass

    daily_tokens_used = 0
    try:
        daily_tokens_used = int(get_tenant_daily_tokens(db, tenant_id=tenant_id) or 0)
    except Exception:
        pass

    daily_cost_usd = 0.0
    try:
        daily_cost_usd = round(float(get_tenant_daily_cost_usd(db, tenant_id=tenant_id) or 0.0), 6)
    except Exception:
        pass

    pending_count = 0
    try:
        pending_count = int(get_pending_approval_count(db, tenant_id=tenant_id) or 0)
    except Exception:
        pass

    linked_username = (getattr(cfg, "linked_username", None) if cfg else None) or w_stats.get("logged_in_username")
    created_at = getattr(user, "created_at", None) if user else getattr(cfg, "updated_at", None)

    from services.plans import is_subscription_valid
    sub_ok, eff_status, days_left = is_subscription_valid(cfg) if cfg else (False, "trialing", 7)

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


def _build_normalized_overview(db: Session, raw_metrics: Dict[str, Any], days: int) -> Dict[str, Any]:
    """
    Combines database.get_admin_platform_metrics(db, days=days) with direct ORM
    aggregation so the portal receives consistent, exact ledger figures.
    """
    now_utc = datetime.utcnow()
    since_24h = now_utc - timedelta(hours=24)
    start_day = (now_utc - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    logs_period = (
        db.query(TokenUsageLog)
        .filter(TokenUsageLog.timestamp >= start_day)
        .all()
    )

    spend_24h = 0.0
    spend_period = 0.0
    prompt_24h = 0
    completion_24h = 0
    cache_hit_24h = 0
    cache_miss_24h = 0
    calls_24h = 0
    active_users_24h = set()

    tokens_period = 0
    calls_period = 0
    cache_hit_period = 0
    cache_miss_period = 0

    daily_map: Dict[str, Dict[str, Any]] = {}
    for offset in range(days):
        d = (start_day + timedelta(days=offset)).date()
        key = d.isoformat()
        daily_map[key] = {
            "date": key,
            "label": d.strftime("%b %d"),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "calls": 0,
        }

    task_map: Dict[str, Dict[str, Any]] = {}

    for row in logs_period:
        p_tok = int(getattr(row, "prompt_tokens", 0) or 0)
        c_tok = int(getattr(row, "completion_tokens", 0) or 0)
        ch_tok = int(getattr(row, "cache_hit_tokens", 0) or 0)
        cm_tok = int(getattr(row, "cache_miss_tokens", 0) or 0)
        if ch_tok == 0 and cm_tok == 0 and p_tok > 0:
            cm_tok = p_tok
        cost = float(getattr(row, "estimated_cost_usd", 0.0) or 0.0)
        ts = getattr(row, "timestamp", None)
        task_type = str(getattr(row, "task_type", None) or "other")
        tid = str(getattr(row, "tenant_id", None) or "default")

        tot_tok = p_tok + c_tok
        spend_period += cost
        tokens_period += tot_tok
        calls_period += 1
        cache_hit_period += ch_tok
        cache_miss_period += cm_tok

        if ts and ts >= since_24h:
            spend_24h += cost
            prompt_24h += p_tok
            completion_24h += c_tok
            cache_hit_24h += ch_tok
            cache_miss_24h += cm_tok
            calls_24h += 1
            active_users_24h.add(tid)

        if ts:
            day_key = ts.date().isoformat()
            if day_key in daily_map:
                bucket = daily_map[day_key]
                bucket["prompt_tokens"] += p_tok
                bucket["completion_tokens"] += c_tok
                bucket["cache_hit_tokens"] += ch_tok
                bucket["cache_miss_tokens"] += cm_tok
                bucket["total_tokens"] += tot_tok
                bucket["cost_usd"] += cost
                bucket["calls"] += 1

        if task_type not in task_map:
            task_map[task_type] = {
                "task_type": task_type,
                "calls": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            }
        task_map[task_type]["calls"] += 1
        task_map[task_type]["total_tokens"] += tot_tok
        task_map[task_type]["cost_usd"] += cost

    savings_rate = (DEEPSEEK_CACHE_MISS_RATE_PER_1M - DEEPSEEK_CACHE_HIT_RATE_PER_1M) / 1_000_000.0
    cache_savings_24h = cache_hit_24h * savings_rate
    cache_savings_period = cache_hit_period * savings_rate

    denom_24h = cache_hit_24h + cache_miss_24h
    denom_period = cache_hit_period + cache_miss_period
    if denom_24h > 0:
        cache_hit_rate_pct = round((cache_hit_24h / denom_24h) * 100.0, 1)
    elif denom_period > 0:
        cache_hit_rate_pct = round((cache_hit_period / denom_period) * 100.0, 1)
    else:
        cache_hit_rate_pct = 0.0

    # User & queue stats
    users = db.query(User).all()
    configs = db.query(AgentConfig).all()
    tenant_ids = {u.tenant_id for u in users} | {c.tenant_id for c in configs}
    active_bots = sum(1 for c in configs if getattr(c, "is_active", False) and not getattr(c, "is_suspended", False))
    suspended_users = sum(1 for c in configs if getattr(c, "is_suspended", False))

    published_24h = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status == "posted", ProcessedTweet.timestamp >= since_24h)
        .count()
    )
    pending_queue_total = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status == "pending_approval")
        .count()
    )

    daily_series = []
    for key in sorted(daily_map.keys()):
        item = daily_map[key]
        item["cost_usd"] = round(item["cost_usd"], 6)
        daily_series.append(item)

    task_breakdown = []
    for item in sorted(task_map.values(), key=lambda x: (x["cost_usd"], x["total_tokens"]), reverse=True):
        share = (item["total_tokens"] / tokens_period * 100.0) if tokens_period > 0 else 0.0
        task_breakdown.append({
            "task_type": item["task_type"],
            "calls": item["calls"],
            "total_tokens": item["total_tokens"],
            "cost_usd": round(item["cost_usd"], 6),
            "share_pct": round(share, 1),
        })

    return {
        "summary": {
            "spend_24h_usd": round(spend_24h, 6),
            "spend_period_usd": round(spend_period, 6),
            "tokens_24h": prompt_24h + completion_24h,
            "prompt_tokens_24h": prompt_24h,
            "completion_tokens_24h": completion_24h,
            "tokens_period": tokens_period,
            "calls_24h": calls_24h,
            "calls_period": calls_period,
            "active_users_24h": len(active_users_24h),
            "cache_hit_rate_pct": cache_hit_rate_pct,
            "cache_savings_24h_usd": round(cache_savings_24h, 6),
            "cache_savings_period_usd": round(cache_savings_period, 6),
            "total_users": len(tenant_ids),
            "active_bots": active_bots,
            "suspended_users": suspended_users,
            "published_24h": published_24h,
            "pending_queue_total": pending_queue_total,
        },
        "daily_series": daily_series,
        "task_breakdown": task_breakdown,
        "raw_metrics": raw_metrics if isinstance(raw_metrics, dict) else {},
    }


# ==============================================================================
# Authentication Endpoints
# ==============================================================================

@router.post("/auth/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest):
    """Authenticates the platform owner using constant-time credential verification."""
    expected_email = os.getenv("SUPER_ADMIN_EMAIL", DEFAULT_SUPER_ADMIN_EMAIL).strip().lower()
    expected_password = os.getenv("SUPER_ADMIN_PASSWORD", DEFAULT_SUPER_ADMIN_PASSWORD)

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
    return AdminMeResponse(
        authenticated=True,
        email=str(admin.get("email") or os.getenv("SUPER_ADMIN_EMAIL", DEFAULT_SUPER_ADMIN_EMAIL)),
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
    raw_metrics = get_admin_platform_metrics(db, days=days)
    normalized = _build_normalized_overview(db, raw_metrics, days=days)
    settings_row = get_platform_settings(db)
    ram_stats = _collect_server_ram_stats()

    return {
        "days": days,
        "summary": normalized["summary"],
        "daily_series": normalized["daily_series"],
        "task_breakdown": normalized["task_breakdown"],
        "ram": ram_stats,
        "settings": _serialize_platform_settings(settings_row),
        "raw_metrics": normalized["raw_metrics"],
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
    db: Session = Depends(get_db),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Lists all creator tenants with usage metrics, caps, and live browser status."""
    settings_row = get_platform_settings(db)
    default_token_cap = int(getattr(settings_row, "default_daily_token_cap", 50000) or 50000)

    users = db.query(User).all()
    configs = db.query(AgentConfig).all()

    user_by_tenant: Dict[str, User] = {u.tenant_id: u for u in users}
    cfg_by_tenant: Dict[str, AgentConfig] = {c.tenant_id: c for c in configs}
    all_tenants = sorted(set(user_by_tenant.keys()) | set(cfg_by_tenant.keys()))

    q = (search or "").strip().lower()
    summaries: List[Dict[str, Any]] = []

    for tid in all_tenants:
        summary = _build_user_summary(
            db,
            tenant_id=tid,
            user=user_by_tenant.get(tid),
            cfg=cfg_by_tenant.get(tid),
            default_token_cap=default_token_cap,
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

    return {"total": len(summaries), "users": summaries}


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

    # Apply plan preset if plan_tier was changed
    if payload.plan_tier:
        from services.plans import apply_plan_to_config
        cfg_pre = get_agent_config(db, tenant_id=tenant_id)
        apply_plan_to_config(cfg_pre, payload.plan_tier, status=payload.subscription_status or "active")
        db.commit()

    if payload.extend_trial_days:
        cfg_pre = get_agent_config(db, tenant_id=tenant_id)
        current_end = getattr(cfg_pre, "trial_ends_at", None) or datetime.utcnow()
        cfg_pre.trial_ends_at = max(current_end, datetime.utcnow()) + timedelta(days=payload.extend_trial_days)
        cfg_pre.subscription_status = "trialing"
        db.commit()

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
                    logger.warning(f"Failed stopping browser for suspended tenant '{tenant_id}': {exc}")

    settings_row = get_platform_settings(db)
    default_token_cap = int(getattr(settings_row, "default_daily_token_cap", 50000) or 50000)
    user = db.query(User).filter(User.tenant_id == tenant_id).first()

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
    users = db.query(User).all()
    configs = db.query(AgentConfig).all()
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

    return {
        "workers": workers_payload,
        "ram": _collect_server_ram_stats(),
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

    configs = db.query(AgentConfig).all()
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
                logger.warning(f"Error sleeping browser worker '{worker_key}': {exc}")

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
        raise HTTPException(status_code=500, detail=f"Failed to stop browser worker: {exc}")

    freed = round(float(w_stats["estimated_ram_mb"]), 1)
    logger.info(f"Super Admin stopped browser worker for tenant '{tenant_id}' (~{freed} MB freed).")
    return {
        "success": True,
        "tenant_id": tenant_id,
        "already_asleep": False,
        "estimated_ram_freed_mb": freed,
    }
