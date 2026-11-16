"""
Browser Worker & Account Linkage Router for X-VibeBot.
Controls Playwright browser instance, cookie synchronization, session verification, and login flows.
"""

import os
import re
import json
import asyncio
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from models import ConnectSessionPayload, CookiesImportPayload
from database import get_db, get_agent_config, update_agent_config
from core.dependencies import get_current_tenant
import core.state as state

logger = logging.getLogger("x_vibebot.browser")
router = APIRouter(tags=["browser"])


def parse_cookie_payload(payload: ConnectSessionPayload) -> List[Dict[str, Any]]:
    """Normalizes auth_token strings, header strings, or JSON cookie arrays into Playwright cookies."""
    # 1. Direct list of cookie objects
    if payload.cookies and isinstance(payload.cookies, list):
        parsed_list = []
        for c in payload.cookies:
            if isinstance(c, dict) and c.get("name") and c.get("value"):
                parsed_list.append({
                    "name": str(c["name"]).strip(),
                    "value": str(c["value"]).strip(),
                    "domain": str(c.get("domain", ".x.com")).strip(),
                    "path": str(c.get("path", "/")).strip(),
                    "secure": bool(c.get("secure", True)),
                    "httpOnly": bool(c.get("httpOnly", c.get("name") == "auth_token")),
                    "sameSite": str(c.get("sameSite", "Lax")).strip()
                })
        if parsed_list:
            return parsed_list

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
                return parse_cookie_payload(ConnectSessionPayload(cookies=parsed))
            elif isinstance(parsed, dict):
                auth_token_val = parsed.get("auth_token", auth_token_val)
                ct0_val = parsed.get("ct0", ct0_val)
        except Exception:
            pass

    # Extract auth_token if present in header-style cookie string: 'auth_token=xxxx; ct0=yyyy'
    if "auth_token=" in cookie_str:
        m = re.search(r"auth_token=([a-zA-Z0-9%_-]+)", cookie_str)
        if m:
            auth_token_val = m.group(1)
    if "ct0=" in cookie_str:
        m = re.search(r"ct0=([a-zA-Z0-9%_-]+)", cookie_str)
        if m:
            ct0_val = m.group(1)

    # Raw 40-char token directly into input
    if not auth_token_val and cookie_str and len(cookie_str) >= 20 and ";" not in cookie_str and " " not in cookie_str:
        auth_token_val = cookie_str

    if not auth_token_val:
        raise ValueError("Enter a valid X session token (auth_token) to connect.")

    clean_auth = auth_token_val.strip().strip('"').strip("'")
    cookies = [
        {
            "name": "auth_token",
            "value": clean_auth,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Lax"
        }
    ]
    if ct0_val:
        clean_ct0 = ct0_val.strip().strip('"').strip("'")
        cookies.append({
            "name": "ct0",
            "value": clean_ct0,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
            "sameSite": "Lax"
        })
    return cookies


@router.post("/api/trigger-scrape")
async def trigger_scrape_now(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Manually queues an immediate feed scan and AI evaluation for the active tenant."""
    state.is_manual_login_active = False

    has_key = bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())
    if not has_key:
        return {
            "status": "missing_api_key",
            "message": "Add your Gemini API key in Settings before scanning."
        }

    worker = state.get_tenant_browser_worker(tenant_id)
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
            "message": "Connect your X account before scanning your feed."
        }

    state.tenant_scrape_queue.put_nowait(tenant_id)
    state.scrape_now_flag.set()
    logger.info(f"Manual feed scan queued for tenant '{tenant_id}'.")
    return {
        "status": "triggered",
        "message": "Scanning feed and generating drafts..."
    }


@router.post("/api/browser/launch-login")
@router.post("/api/login-browser")
async def launch_headful_login(tenant_id: str = Depends(get_current_tenant)):
    """Launches an interactive browser window for manual X login."""
    try:
        state.is_manual_login_active = True
        worker = state.get_tenant_browser_worker(tenant_id)

        marker_path = os.path.join(worker.profile_dir, ".disconnected")
        if os.path.isfile(marker_path):
            try:
                os.remove(marker_path)
            except Exception:
                pass

        asyncio.create_task(worker.open_headful_for_login())

        return {
            "status": "browser_opened",
            "open_url": "https://x.com/login",
            "message": "X login window opened. Sign into X, then return here and click 'Verify Connection'."
        }
    except Exception as e:
        state.is_manual_login_active = False
        raise HTTPException(status_code=500, detail=f"Failed to open browser: {str(e)}")


@router.post("/api/browser/release")
async def release_browser_profile(tenant_id: str = Depends(get_current_tenant)):
    """Releases locks on the browser profile folder."""
    state.is_manual_login_active = True
    worker = state.get_tenant_browser_worker(tenant_id)
    await worker.stop()
    return {"status": "released"}


@router.post("/api/browser/check-session")
async def check_session(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Checks whether the browser session for the requesting tenant is currently logged into X."""
    state.is_manual_login_active = False
    worker = state.get_tenant_browser_worker(tenant_id)
    logged_in = False
    try:
        logged_in = await asyncio.wait_for(worker.check_login_status(), timeout=12.0)
    except asyncio.TimeoutError:
        logger.warning(f"Session check timed out for tenant {tenant_id}")
        logged_in = False
    except Exception as e:
        logger.warning(f"Session check error for tenant {tenant_id}: {e}")
        logged_in = False

    state.tenant_login_states[tenant_id] = logged_in
    if tenant_id == "default":
        state.is_session_logged_in = logged_in
    if logged_in:
        state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
    cfg = get_agent_config(db, tenant_id=tenant_id)
    return {
        "is_logged_in": logged_in,
        "linked_username": worker.logged_in_username or cfg.linked_username or None
    }


@router.post("/api/browser/connect-session")
async def connect_session_endpoint(
    payload: ConnectSessionPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    SaaS & Cloud Account Connection Endpoint:
    Imports auth_token or full cookie session into the tenant's isolated browser profile,
    validates the session live with X, and links the detected handle.
    """
    state.is_manual_login_active = False
    try:
        cookies = parse_cookie_payload(payload)
        worker = state.get_tenant_browser_worker(tenant_id)
        is_logged = await worker.import_cookies(cookies)
        state.tenant_login_states[tenant_id] = is_logged
        if tenant_id == "default":
            state.is_session_logged_in = is_logged
        if is_logged:
            state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
            cfg = get_agent_config(db, tenant_id=tenant_id)
            handle = worker.logged_in_username or cfg.linked_username or "Connected Account"
            return {
                "success": True,
                "is_logged_in": True,
                "linked_username": handle,
                "message": f"Connected {handle} to your workspace."
            }
        else:
            return {
                "success": False,
                "is_logged_in": False,
                "message": "X rejected or expired this session token. Copy a fresh auth_token from x.com and try again."
            }
    except Exception as e:
        logger.warning(f"Connect session error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/browser/disconnect")
async def disconnect_account_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Disconnects the X account from the tenant's isolated sandbox."""
    worker = state.get_tenant_browser_worker(tenant_id)
    await worker.disconnect()
    state.tenant_login_states[tenant_id] = False
    if tenant_id == "default":
        state.is_session_logged_in = False
    cfg = get_agent_config(db, tenant_id=tenant_id)
    cfg.linked_username = None
    db.commit()
    return {"success": True, "message": "X account disconnected."}


@router.get("/api/browser/cookies")
@router.get("/api/cookies")
@router.get("/api/cookies/export")
async def export_cookies_endpoint(tenant_id: str = Depends(get_current_tenant)):
    """Exports session cookies as JSON for the active tenant."""
    worker = state.get_tenant_browser_worker(tenant_id)
    cookies = await worker.export_cookies()
    return JSONResponse(content={"cookies": cookies, "count": len(cookies)})


@router.post("/api/browser/cookies")
@router.post("/api/cookies")
@router.post("/api/cookies/import")
async def import_cookies_endpoint(
    payload: CookiesImportPayload,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Imports session cookies into the active tenant's isolated profile and verifies login."""
    worker = state.get_tenant_browser_worker(tenant_id)
    logged_in = await worker.import_cookies(payload.cookies)
    state.tenant_login_states[tenant_id] = logged_in
    if tenant_id == "default":
        state.is_session_logged_in = logged_in
    if logged_in:
        state.sync_detected_username(db, tenant_id=tenant_id, worker=worker)
    cfg = get_agent_config(db, tenant_id=tenant_id)
    return {
        "is_logged_in": logged_in,
        "linked_username": worker.logged_in_username or cfg.linked_username
    }


@router.post("/api/start-worker")
async def start_worker_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Enables autonomous agent background activity for this tenant."""
    cfg = update_agent_config(db, {"is_active": True}, tenant_id=tenant_id)
    state.tenant_scrape_queue.put_nowait(tenant_id)
    state.scrape_now_flag.set()
    logger.info(f"Worker enabled for tenant '{tenant_id}'.")
    return {"status": "started", "is_active": cfg.is_active}


@router.post("/api/stop-worker")
async def stop_worker_endpoint(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Disables autonomous background activity and stops active browser execution for this tenant."""
    cfg = update_agent_config(db, {"is_active": False}, tenant_id=tenant_id)
    worker = state.get_tenant_browser_worker(tenant_id)
    await worker.stop()
    logger.info(f"Worker stopped for tenant '{tenant_id}'.")
    return {"status": "stopped", "is_active": cfg.is_active}
