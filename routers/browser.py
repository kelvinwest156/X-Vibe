"""
Browser Worker & Account Linkage Router for X-VibeBot.
Controls Playwright browser instance, cookie synchronization, session verification, and login flows.
"""

import os
import re
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from models import ConnectSessionPayload, CookiesImportPayload, AgentConfig
from database import (
    get_db,
    get_agent_config,
    update_agent_config,
    get_decrypted_cookies_json,
    get_decrypted_api_key,
)
from core.dependencies import get_current_tenant, require_active_tenant_config
from core.security import sanitize_x_cookies, encrypt_secret, scrub_secrets
import core.state as state

logger = logging.getLogger("x_vibebot.browser")
router = APIRouter(tags=["browser"])

_PATH_LEAK_RE = re.compile(
    r'(?:[A-Za-z]:\\[^\s"\':,;]+|/(?:Users|home|app|data|var|tmp|etc|opt|usr)[^\s"\':,;]*)'
)


def _sanitize_error_message(exc: Exception, fallback: str = "Operation failed.") -> str:
    """Scrubs secrets and internal filesystem paths before returning error details to clients."""
    raw = scrub_secrets(str(exc or ""))
    clean = _PATH_LEAK_RE.sub("[path]", raw).strip()
    return clean or fallback


def parse_cookie_payload(payload: ConnectSessionPayload) -> List[Dict[str, Any]]:
    """
    Normalizes auth_token strings, header strings, or JSON cookie arrays into
    strictly sanitized X/Twitter Playwright cookies via `sanitize_x_cookies`.
    """
    # 1. Direct list of cookie objects
    if payload.cookies and isinstance(payload.cookies, list):
        sanitized = sanitize_x_cookies(payload.cookies)
        if not sanitized or not any(c.get("name") == "auth_token" and c.get("value") for c in sanitized):
            raise ValueError("Cookies payload must include a valid X auth_token cookie.")
        return sanitized

    cookie_str = (payload.raw_cookies or "").strip()
    auth_token_val = (payload.auth_token or "").strip()
    ct0_val = (payload.ct0 or "").strip()

    # Auto-detect if user pasted JSON or cookie header directly into auth_token field
    if not cookie_str and (
        auth_token_val.startswith("[")
        or auth_token_val.startswith("{")
        or "auth_token=" in auth_token_val
        or ";" in auth_token_val
    ):
        cookie_str = auth_token_val
        auth_token_val = ""

    # Check if raw_cookies is JSON
    if cookie_str.startswith("[") or cookie_str.startswith("{"):
        try:
            parsed = json.loads(cookie_str)
            if isinstance(parsed, list):
                sanitized = sanitize_x_cookies(parsed)
                if not sanitized or not any(c.get("name") == "auth_token" and c.get("value") for c in sanitized):
                    raise ValueError("JSON cookies array must include a valid X auth_token cookie.")
                return sanitized
            elif isinstance(parsed, dict):
                auth_token_val = str(parsed.get("auth_token") or auth_token_val).strip()
                ct0_val = str(parsed.get("ct0") or ct0_val).strip()
        except ValueError:
            raise
        except Exception:
            pass

    # Extract auth_token/ct0 if present in header-style cookie string: 'auth_token=xxxx; ct0=yyyy'
    if "auth_token=" in cookie_str:
        m = re.search(r"auth_token=([a-zA-Z0-9%_-]+)", cookie_str)
        if m:
            auth_token_val = m.group(1)
    if "ct0=" in cookie_str:
        m = re.search(r"ct0=([a-zA-Z0-9%_-]+)", cookie_str)
        if m:
            ct0_val = m.group(1)

    # Raw token directly into input
    if not auth_token_val and cookie_str and len(cookie_str) >= 20 and ";" not in cookie_str and " " not in cookie_str:
        auth_token_val = cookie_str

    if not auth_token_val:
        raise ValueError("Enter a valid X session token (auth_token) to connect.")

    clean_auth = auth_token_val.strip().strip('"').strip("'")
    raw_list: List[Dict[str, Any]] = [
        {
            "name": "auth_token",
            "value": clean_auth,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax",
        }
    ]
    if ct0_val:
        clean_ct0 = ct0_val.strip().strip('"').strip("'")
        raw_list.append({
            "name": "ct0",
            "value": clean_ct0,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "sameSite": "Lax",
        })

    sanitized = sanitize_x_cookies(raw_list)
    if not sanitized or not any(c.get("name") == "auth_token" and c.get("value") for c in sanitized):
        raise ValueError("Enter a valid X session token (auth_token) to connect.")
    return sanitized


async def _cancel_worker_login_watcher(worker) -> None:
    """Cancels any lingering headful login watcher task on a worker cleanly."""
    cancel_fn = getattr(worker, "_cancel_login_watcher_if_any", None)
    if callable(cancel_fn):
        try:
            await cancel_fn()
            return
        except Exception:
            pass
    watcher_task = getattr(worker, "_login_watcher_task", None)
    if watcher_task and not watcher_task.done():
        watcher_task.cancel()
        try:
            await watcher_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            worker._login_watcher_task = None
        except Exception:
            pass


@router.post("/api/trigger-scrape")
async def trigger_scrape_now(
    tenant_ctx: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """Manually queues an immediate feed scan and AI evaluation for an active, subscribed tenant."""
    tenant_id, cfg = tenant_ctx
    state.set_manual_login(tenant_id, False)

    tenant_api_key = get_decrypted_api_key(cfg)
    has_key = bool(
        tenant_api_key
        or (os.getenv("DEEPSEEK_API_KEY") or "").strip()
        or (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    )
    if not has_key:
        return {
            "status": "missing_api_key",
            "message": "AI API key is missing. Please configure your API key in Settings or server environment variables.",
        }

    # Release open DB transaction before potentially slow browser checks
    db.rollback()

    worker = state.get_tenant_browser_worker(tenant_id)
    worker._tenant_id = tenant_id
    logged_in = state.tenant_login_states.get(tenant_id, False)
    if not logged_in:
        logged_in = await worker.check_login_status()
        state.tenant_login_states[tenant_id] = logged_in
        if tenant_id == "default":
            state.is_session_logged_in = logged_in
        if logged_in:
            state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)

    if not logged_in:
        return {
            "status": "not_logged_in",
            "message": "Connect your X account before scanning your feed.",
        }

    state.tenant_scrape_queue.put_nowait(tenant_id)
    state.scrape_now_flag.set()
    state.emit_tenant_event(tenant_id, "scrape_queued", {"tenant_id": tenant_id})
    logger.info(f"Manual feed scan queued for tenant '{tenant_id}'.")
    return {
        "status": "triggered",
        "message": "Scanning feed and generating drafts...",
    }


@router.post("/api/browser/launch-login")
@router.post("/api/login-browser")
async def launch_headful_login(tenant_id: str = Depends(get_current_tenant)):
    """Launches an interactive browser window for manual X login."""
    try:
        worker = state.get_tenant_browser_worker(tenant_id)
        worker._tenant_id = tenant_id

        await _cancel_worker_login_watcher(worker)
        state.set_manual_login(tenant_id, True)

        marker_path = os.path.join(worker.profile_dir, ".disconnected")
        if await asyncio.to_thread(os.path.isfile, marker_path):
            try:
                await asyncio.to_thread(os.remove, marker_path)
            except Exception:
                pass

        await worker.open_headful_for_login()

        return {
            "status": "browser_opened",
            "open_url": "https://x.com/login",
            "message": "X login window opened. Sign into X, then return here and click 'Verify Connection'.",
        }
    except Exception as e:
        state.set_manual_login(tenant_id, False)
        logger.warning(f"Failed to launch login browser for tenant '{tenant_id}': {_sanitize_error_message(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to open browser window. Please verify browser availability and try again.",
        )


@router.post("/api/browser/release")
async def release_browser_profile(tenant_id: str = Depends(get_current_tenant)):
    """Releases locks on the browser profile folder."""
    state.set_manual_login(tenant_id, True)
    worker = state.get_tenant_browser_worker(tenant_id)
    worker._tenant_id = tenant_id
    await _cancel_worker_login_watcher(worker)
    await worker.stop()
    return {"status": "released"}


@router.post("/api/browser/check-session")
async def check_session(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Checks whether the browser session for the requesting tenant is currently logged into X."""
    state.set_manual_login(tenant_id, False)
    worker = state.get_tenant_browser_worker(tenant_id)
    worker._tenant_id = tenant_id

    cfg = get_agent_config(db, tenant_id=tenant_id)
    decrypted_cookies_raw = get_decrypted_cookies_json(cfg)
    cached_username = cfg.linked_username
    # Release DB transaction before running Playwright network checks
    db.rollback()

    logged_in = False
    has_local_backup = await asyncio.to_thread(os.path.isfile, worker.cookies_backup_path)

    # Cloud persistence: restore decrypted cookies from database if container wiped the local profile
    restored_and_verified = False
    if not has_local_backup and decrypted_cookies_raw:
        try:
            db_cookies = json.loads(decrypted_cookies_raw)
            sanitized_db = sanitize_x_cookies(db_cookies) if isinstance(db_cookies, list) else []
            if sanitized_db:
                logged_in = await asyncio.wait_for(
                    worker.import_cookies(sanitized_db, verify_live=True),
                    timeout=25.0,
                )
                restored_and_verified = True
                logger.info(f"Restored and verified X session cookies for tenant '{tenant_id}' from database.")
        except Exception as ce:
            logger.debug(f"DB cookie restore notice for tenant '{tenant_id}': {_sanitize_error_message(ce)}")

    if not restored_and_verified:
        try:
            logged_in = await asyncio.wait_for(
                worker.check_login_status(verify_live=True),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Session check timed out for tenant {tenant_id}")
            logged_in = False
        except Exception as e:
            logger.warning(f"Session check error for tenant {tenant_id}: {_sanitize_error_message(e)}")
            logged_in = False

    state.tenant_login_states[tenant_id] = logged_in
    if tenant_id == "default":
        state.is_session_logged_in = logged_in

    if logged_in:
        state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
        cfg = get_agent_config(db, tenant_id=tenant_id)
        linked_username = worker.logged_in_username or cfg.linked_username or None
        db.rollback()
        state.emit_tenant_event(tenant_id, "session_verified", {"linked_username": linked_username})
    else:
        linked_username = worker.logged_in_username or cached_username or None

    return {
        "is_logged_in": logged_in,
        "linked_username": linked_username,
    }


@router.post("/api/browser/connect-session")
async def connect_session_endpoint(
    payload: ConnectSessionPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    SaaS & Cloud Account Connection Endpoint:
    Sanitizes cookies, imports into the tenant's isolated browser profile,
    validates the session live with X, encrypts at rest, and links the detected handle.
    """
    state.set_manual_login(tenant_id, False)
    try:
        cookies = parse_cookie_payload(payload)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=_sanitize_error_message(ve, "Invalid cookie payload."))

    try:
        worker = state.get_tenant_browser_worker(tenant_id)
        worker._tenant_id = tenant_id
        await _cancel_worker_login_watcher(worker)

        is_logged = await worker.import_cookies(cookies, verify_live=True)
        state.tenant_login_states[tenant_id] = is_logged
        if tenant_id == "default":
            state.is_session_logged_in = is_logged

        if is_logged:
            cfg = get_agent_config(db, tenant_id=tenant_id)
            cfg.cookies_json = encrypt_secret(json.dumps(cookies))
            db.commit()
            state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
            handle = worker.logged_in_username or cfg.linked_username or "Connected Account"
            state.emit_tenant_event(tenant_id, "session_connected", {"linked_username": handle})
            return {
                "success": True,
                "is_logged_in": True,
                "linked_username": handle,
                "message": f"Connected {handle} to your workspace.",
            }
        else:
            return {
                "success": False,
                "is_logged_in": False,
                "message": "X rejected or expired this session token. Copy a fresh auth_token from x.com and try again.",
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Connect session error for tenant '{tenant_id}': {_sanitize_error_message(e)}")
        raise HTTPException(
            status_code=400,
            detail="Could not validate X session cookies. Please verify your token and try again.",
        )


@router.post("/api/browser/disconnect")
async def disconnect_account_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Disconnects the X account from the tenant's isolated sandbox."""
    state.set_manual_login(tenant_id, False)
    worker = state.get_tenant_browser_worker(tenant_id)
    worker._tenant_id = tenant_id
    await worker.disconnect()

    state.tenant_login_states[tenant_id] = False
    if tenant_id == "default":
        state.is_session_logged_in = False

    cfg = get_agent_config(db, tenant_id=tenant_id)
    cfg.linked_username = None
    cfg.cookies_json = None
    db.commit()
    state.emit_tenant_event(tenant_id, "session_disconnected", {"tenant_id": tenant_id})
    return {"success": True, "message": "X account disconnected."}


@router.get("/api/browser/cookies")
@router.get("/api/cookies")
@router.get("/api/cookies/export")
async def export_cookies_endpoint(tenant_id: str = Depends(get_current_tenant)):
    """Exports sanitized session cookies as JSON for the active tenant."""
    worker = state.get_tenant_browser_worker(tenant_id)
    worker._tenant_id = tenant_id
    cookies = await worker.export_cookies()
    return JSONResponse(content={"cookies": cookies, "count": len(cookies)})


@router.post("/api/browser/cookies")
@router.post("/api/cookies")
@router.post("/api/cookies/import")
async def import_cookies_endpoint(
    payload: CookiesImportPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Sanitizes and imports session cookies into the active tenant's isolated profile and verifies login."""
    state.set_manual_login(tenant_id, False)
    try:
        sanitized = sanitize_x_cookies(payload.cookies)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=_sanitize_error_message(ve, "Invalid cookies payload."))

    if not sanitized or not any(c.get("name") == "auth_token" and c.get("value") for c in sanitized):
        raise HTTPException(status_code=400, detail="Cookies payload must include a valid X auth_token cookie.")

    try:
        worker = state.get_tenant_browser_worker(tenant_id)
        worker._tenant_id = tenant_id
        await _cancel_worker_login_watcher(worker)

        logged_in = await worker.import_cookies(sanitized, verify_live=True)
        state.tenant_login_states[tenant_id] = logged_in
        if tenant_id == "default":
            state.is_session_logged_in = logged_in

        if logged_in:
            cfg = get_agent_config(db, tenant_id=tenant_id)
            cfg.cookies_json = encrypt_secret(json.dumps(sanitized))
            db.commit()
            state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)

        cfg = get_agent_config(db, tenant_id=tenant_id)
        linked = worker.logged_in_username or cfg.linked_username
        db.rollback()
        return {
            "is_logged_in": logged_in,
            "linked_username": linked,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Import cookies error for tenant '{tenant_id}': {_sanitize_error_message(e)}")
        raise HTTPException(
            status_code=400,
            detail="Failed to import and verify X cookies.",
        )


@router.post("/api/start-worker")
async def start_worker_endpoint(
    tenant_ctx: Tuple[str, AgentConfig] = Depends(require_active_tenant_config),
    db: Session = Depends(get_db),
):
    """Enables autonomous agent background activity for an active, subscribed tenant."""
    tenant_id, _ = tenant_ctx
    cfg = update_agent_config(db, {"is_active": True}, tenant_id=tenant_id)
    state.tenant_scrape_queue.put_nowait(tenant_id)
    state.scrape_now_flag.set()
    state.emit_tenant_event(tenant_id, "worker_started", {"is_active": cfg.is_active})
    logger.info(f"Worker enabled for tenant '{tenant_id}'.")
    return {"status": "started", "is_active": cfg.is_active}


@router.post("/api/stop-worker")
async def stop_worker_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Disables autonomous background activity and stops active browser execution for this tenant."""
    state.set_manual_login(tenant_id, False)
    cfg = update_agent_config(db, {"is_active": False}, tenant_id=tenant_id)
    is_active = bool(cfg.is_active)
    # Release DB transaction before stopping Playwright
    db.rollback()

    worker = state.get_tenant_browser_worker(tenant_id)
    worker._tenant_id = tenant_id
    await worker.stop()
    state.emit_tenant_event(tenant_id, "worker_stopped", {"is_active": is_active})
    logger.info(f"Worker stopped for tenant '{tenant_id}'.")
    return {"status": "stopped", "is_active": is_active}
