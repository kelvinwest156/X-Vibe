"""
System & Operational Health Router for X-VibeBot.
Provides health monitoring, live diagnostic log streaming, and web dashboard hosting.
"""

import os
from typing import List
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session

from models import SystemLogEntry
from database import get_db
import core.state as state

router = APIRouter(tags=["system"])

NEXT_OUT_DIR = os.path.join(state.BASE_DIR, "frontend", "out")
STATIC_DIR = os.path.join(state.BASE_DIR, "static")


@router.get("/api/logs", response_model=List[SystemLogEntry])
async def get_system_logs(limit: int = 50):
    """Returns recent runtime diagnostic logs from the in-memory buffer."""
    entries = list(state.log_buffer)
    selected = entries[-limit:] if limit > 0 else entries
    return [
        SystemLogEntry(
            timestamp=entry["timestamp"],
            level=entry["level"],
            message=entry["message"]
        )
        for entry in selected
    ]


@router.get("/api/health")
@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint to verify database and runtime operational readiness."""
    try:
        # Simple DB ping
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "app": "X-VibeBot",
        "version": "2.0.0",
        "database": db_status,
        "active_workers": len(state.tenant_workers)
    }


@router.get("/robots.txt")
async def serve_robots():
    """Serves generated robots.txt for search engines."""
    robots_path = os.path.join(NEXT_OUT_DIR, "robots.txt")
    if os.path.exists(robots_path):
        return FileResponse(robots_path, media_type="text/plain")
    return HTMLResponse("User-agent: *\nAllow: /", media_type="text/plain")


@router.get("/sitemap.xml")
async def serve_sitemap():
    """Serves generated sitemap.xml for search engines."""
    sitemap_path = os.path.join(NEXT_OUT_DIR, "sitemap.xml")
    if os.path.exists(sitemap_path):
        return FileResponse(sitemap_path, media_type="application/xml")
    return HTMLResponse("<urlset></urlset>", media_type="application/xml")


@router.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the Next.js static production export or the fallback static dashboard."""
    next_index = os.path.join(NEXT_OUT_DIR, "index.html")
    if os.path.exists(next_index):
        return FileResponse(next_index)
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Static dashboard not found.</h1>", status_code=404)
