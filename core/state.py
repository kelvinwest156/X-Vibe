"""
Core Application State & Browser Worker Registry for X-VibeBot.
Maintains in-memory queues, logging buffer, cooldown counters, and tenant browser workers.
"""

import os
import sys
import re
import time
import random
import logging
import asyncio
from collections import deque
from typing import Dict, Optional, Any
from sqlalchemy.orm import Session

from browser_worker import XBrowserWorker
from database import get_agent_config

# Root directory reference
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ==============================================================================
# In-Memory Log Buffer for Live Dashboard Stream
# ==============================================================================

MAX_LOGS = 100
log_buffer = deque(maxlen=MAX_LOGS)


class DashboardLogHandler(logging.Handler):
    """Custom logging handler that buffers recent log entries for the web dashboard."""
    def emit(self, record):
        try:
            msg = self.format(record)
            log_buffer.append({
                "timestamp": time.strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": msg
            })
        except Exception:
            pass


def setup_logging():
    """Configures console and in-memory dashboard logging handlers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup_logging is called multiple times
    if not any(isinstance(h, DashboardLogHandler) for h in root_logger.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s"))
        
        dashboard_handler = DashboardLogHandler()
        dashboard_handler.setFormatter(logging.Formatter("%(message)s"))
        
        root_logger.addHandler(stream_handler)
        root_logger.addHandler(dashboard_handler)


# ==============================================================================
# Global Browser Worker & Multi-Tenancy Registry
# ==============================================================================

HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
DEFAULT_PROFILE_DIR = os.path.abspath(os.getenv("BROWSER_PROFILE_DIR", os.path.join(BASE_DIR, "x_browser_profile")))

# Primary worker for default tenant
browser_worker = XBrowserWorker(profile_dir=DEFAULT_PROFILE_DIR, headless=HEADLESS)
tenant_workers: Dict[str, XBrowserWorker] = {"default": browser_worker}

# Runtime coordination states
last_interaction_timestamp: float = 0.0
current_random_cooldown_seconds: int = 0
is_session_logged_in: bool = False
tenant_login_states: Dict[str, bool] = {}
is_manual_login_active: bool = False
active_search_query_state: Optional[str] = None

# Background asynchronous tasks and events
bg_worker_task: Optional[asyncio.Task] = None
scheduler_worker_task: Optional[asyncio.Task] = None
scrape_now_flag = asyncio.Event()
tenant_scrape_queue: asyncio.Queue = asyncio.Queue()


def get_tenant_browser_worker(tenant_id: str = "default") -> XBrowserWorker:
    """Returns an isolated XBrowserWorker instance with an isolated profile directory per tenant."""
    clean_tenant = re.sub(r"[^a-zA-Z0-9_\-]", "_", tenant_id or "default")
    if clean_tenant not in tenant_workers:
        profile_dir = (
            DEFAULT_PROFILE_DIR
            if clean_tenant == "default"
            else os.path.abspath(os.path.join(BASE_DIR, f"x_browser_profile_{clean_tenant}"))
        )
        tenant_workers[clean_tenant] = XBrowserWorker(profile_dir=profile_dir, headless=HEADLESS)
    return tenant_workers[clean_tenant]


def get_cooldown_remaining() -> int:
    """Returns seconds remaining in the current randomized cooldown window."""
    global last_interaction_timestamp, current_random_cooldown_seconds
    if last_interaction_timestamp <= 0 or current_random_cooldown_seconds <= 0:
        return 0
    elapsed = time.time() - last_interaction_timestamp
    return max(0, int(current_random_cooldown_seconds - elapsed))


def set_new_random_cooldown(min_mins: int, max_mins: int):
    """Sets a randomized cooldown duration after a post to avoid robotic intervals."""
    global last_interaction_timestamp, current_random_cooldown_seconds
    last_interaction_timestamp = time.time()
    low = max(1, min_mins) * 60
    high = max(low + 60, max_mins * 60)
    current_random_cooldown_seconds = random.randint(low, high)


def sync_detected_username(db: Session, tenant_id: str = "default", worker: Optional[XBrowserWorker] = None):
    """Saves worker.logged_in_username to AgentConfig for the specified tenant if newly detected."""
    w = worker or get_tenant_browser_worker(tenant_id)
    if w.logged_in_username:
        cfg = get_agent_config(db, tenant_id=tenant_id)
        if cfg.linked_username != w.logged_in_username:
            cfg.linked_username = w.logged_in_username
            db.commit()


def update_env_variable(key: str, value: str):
    """Updates a key in the project root .env file and in-memory environment."""
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    os.environ[key] = value
