"""
System & Operational Health Router for X-VibeBot.
Provides health monitoring, live diagnostic log streaming, and web dashboard hosting.
"""

import os
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session

from models import SystemLogEntry
from core.dependencies import require_super_admin
from core.security import scrub_secrets
import core.state as state
from database import get_db

logger = logging.getLogger("x_vibebot.system")
router = APIRouter(tags=["system"])

NEXT_OUT_DIR = os.path.join(state.BASE_DIR, "frontend", "out")
STATIC_DIR = os.path.join(state.BASE_DIR, "static")


@router.get("/api/logs", response_model=List[SystemLogEntry])
async def get_system_logs(
    limit: int = Query(50, ge=1, le=200),
    _admin: Dict[str, Any] = Depends(require_super_admin),
):
    """Returns recent runtime diagnostic logs from the in-memory buffer (Super Admin only)."""
    entries = list(state.log_buffer)
    selected = entries[-limit:]
    return [
        SystemLogEntry(
            timestamp=entry["timestamp"],
            level=entry["level"],
            message=scrub_secrets(entry["message"])
        )
        for entry in selected
    ]


@router.get("/api/health")
@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint to verify database and runtime operational readiness."""
    try:
        # Simple DB ping
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.warning(f"Health check database ping failed: {scrub_secrets(e)}")
        db_status = "unavailable"

    return {
        "status": "ok" if db_status == "connected" else "error",
        "app": "X-VibeBot",
        "version": "2.0.0",
        "database": db_status,
        "active_workers": len(state.tenant_workers)
    }


@router.get("/robots.txt")
async def serve_robots():
    """Serves generated robots.txt for search engines."""
    for candidate in [
        os.path.join(NEXT_OUT_DIR, "robots.txt"),
        os.path.join(STATIC_DIR, "robots.txt"),
    ]:
        if os.path.exists(candidate):
            return FileResponse(candidate, media_type="text/plain")
    return HTMLResponse("User-agent: *\nAllow: /", media_type="text/plain")


@router.get("/sitemap.xml")
async def serve_sitemap():
    """Serves generated sitemap.xml for search engines."""
    for candidate in [
        os.path.join(NEXT_OUT_DIR, "sitemap.xml"),
        os.path.join(STATIC_DIR, "sitemap.xml"),
    ]:
        if os.path.exists(candidate):
            return FileResponse(candidate, media_type="application/xml")
    return HTMLResponse("<urlset></urlset>", media_type="application/xml")


@router.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the Next.js static production export or the fallback static dashboard."""
    for candidate in [
        os.path.join(NEXT_OUT_DIR, "index.html"),
        os.path.join(STATIC_DIR, "index.html"),
    ]:
        if os.path.exists(candidate):
            return FileResponse(candidate)
    return HTMLResponse("<h1>Static dashboard not found.</h1>", status_code=404)


@router.get("/login", response_class=HTMLResponse)
@router.get("/auth", response_class=HTMLResponse)
@router.get("/signup", response_class=HTMLResponse)
async def serve_login():
    """Serves the dedicated login and signup page."""
    for candidate in [
        os.path.join(NEXT_OUT_DIR, "login.html"),
        os.path.join(NEXT_OUT_DIR, "login", "index.html"),
        os.path.join(STATIC_DIR, "login.html"),
        os.path.join(STATIC_DIR, "login", "index.html"),
        os.path.join(NEXT_OUT_DIR, "index.html"),
        os.path.join(STATIC_DIR, "index.html"),
    ]:
        if os.path.exists(candidate):
            return FileResponse(candidate)
    return HTMLResponse("<h1>Login page not found.</h1>", status_code=404)


@router.get("/reset-password", response_class=HTMLResponse)
async def serve_reset_password():
    """Serves the dedicated reset password page."""
    for candidate in [
        os.path.join(NEXT_OUT_DIR, "reset-password.html"),
        os.path.join(NEXT_OUT_DIR, "reset-password", "index.html"),
        os.path.join(STATIC_DIR, "reset-password.html"),
        os.path.join(STATIC_DIR, "reset-password", "index.html"),
        os.path.join(NEXT_OUT_DIR, "index.html"),
        os.path.join(STATIC_DIR, "index.html"),
    ]:
        if os.path.exists(candidate):
            return FileResponse(candidate)
    return HTMLResponse("<h1>Reset password page not found.</h1>", status_code=404)
