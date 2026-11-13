"""
X-VibeBot FastAPI Entrypoint.
Clean, modular orchestration of routers, lifespan background tasks, and web assets.
"""

import sys
import asyncio

# Critical fix for Windows: Playwright subprocesses require ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        import uvicorn.loops.asyncio
        uvicorn.loops.asyncio.asyncio_setup = lambda use_subprocess=False: None
    except Exception:
        pass

import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from database import init_db
import core.state as state
from core.background import scheduled_queue_dispatcher_loop, background_automation_loop
from core.dependencies import get_current_tenant, get_current_user
from routers import (
    auth_router,
    config_router,
    queue_router,
    browser_router,
    analytics_router,
    system_router
)

# Re-export common handles for backwards compatibility
browser_worker = state.browser_worker
tenant_workers = state.tenant_workers
get_tenant_browser_worker = state.get_tenant_browser_worker
log_buffer = state.log_buffer

state.setup_logging()
logger = logging.getLogger("x_vibebot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup (database init, background worker loops) and graceful shutdown."""
    init_db()
    logger.info("Database verified.")
    state.bg_worker_task = asyncio.create_task(background_automation_loop())
    state.scheduler_worker_task = asyncio.create_task(scheduled_queue_dispatcher_loop())
    yield
    logger.info("Shutting down X-VibeBot...")
    for task in (state.bg_worker_task, state.scheduler_worker_task):
        if task:
            task.cancel()
    for w in list(state.tenant_workers.values()):
        try:
            await w.stop()
        except Exception:
            pass


app = FastAPI(
    title="X-VibeBot",
    description="Minimal AI Browser-Agent for X (Twitter)",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static asset directories
static_dir = os.path.join(state.BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

next_out_dir = os.path.join(state.BASE_DIR, "frontend", "out")
if os.path.isdir(os.path.join(next_out_dir, "_next")):
    app.mount("/_next", StaticFiles(directory=os.path.join(next_out_dir, "_next")), name="next_assets")
elif os.path.isdir(os.path.join(static_dir, "_next")):
    app.mount("/_next", StaticFiles(directory=os.path.join(static_dir, "_next")), name="next_static_assets")

# Mount logos directory for avatar and branding assets
logos_dir = os.path.join(next_out_dir, "logos")
if os.path.isdir(logos_dir):
    app.mount("/logos", StaticFiles(directory=logos_dir), name="logos")
elif os.path.isdir(os.path.join(static_dir, "logos")):
    app.mount("/logos", StaticFiles(directory=os.path.join(static_dir, "logos")), name="logos")
elif os.path.isdir(os.path.join(state.BASE_DIR, "frontend", "public", "logos")):
    app.mount("/logos", StaticFiles(directory=os.path.join(state.BASE_DIR, "frontend", "public", "logos")), name="logos")

# Include modular domain routers
app.include_router(auth_router)
app.include_router(config_router)
app.include_router(queue_router)
app.include_router(browser_router)
app.include_router(analytics_router)
app.include_router(system_router)

if __name__ == "__main__":
    import uvicorn
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            import uvicorn.loops.asyncio
            uvicorn.loops.asyncio.asyncio_setup = lambda use_subprocess=False: None
        except Exception:
            pass
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
