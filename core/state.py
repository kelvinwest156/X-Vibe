"""
Core Application State, Per-Tenant Isolation & SSE Event Bus for X-VibeBot.
Maintains tenant-scoped cooldowns, active queries, manual login flags,
isolated browser worker registries, encrypted cookie sync, and SSE event queues.
"""

import os
import sys
import re
import time
import random
import logging
import asyncio
import threading
import contextvars
from collections import deque, defaultdict
from typing import Dict, Optional, Any, Tuple, Set
from sqlalchemy.orm import Session

from browser_worker import XBrowserWorker
from database import get_agent_config
from core.security import (
    encrypt_secret,
    scrub_secrets,
    deterministic_profile_dirname,
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger("x_vibebot.state")

# ContextVar tracks the active tenant inside background/request execution for per-tenant log routing
_current_log_tenant: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_log_tenant", default=None
)

# ==============================================================================
# In-Memory Log Buffers (Scrubbed & Tenant-Isolated)
# ==============================================================================

MAX_LOGS = 150
MAX_TENANT_LOGS = 40
log_buffer = deque(maxlen=MAX_LOGS)
tenant_logs: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_TENANT_LOGS))
_log_lock = threading.Lock()
_env_lock = threading.Lock()


def set_log_tenant_context(tenant_id: Optional[str]):
    """Binds current asyncio context to a tenant for scoped status logs."""
    return _current_log_tenant.set(tenant_id)


def reset_log_tenant_context(token) -> None:
    try:
        _current_log_tenant.reset(token)
    except Exception:
        pass


class DashboardLogHandler(logging.Handler):
    """Buffers scrubbed diagnostic log entries globally (Super Admin) and per-tenant (Creator UI)."""

    def emit(self, record):
        try:
            raw_msg = self.format(record)
            clean_msg = scrub_secrets(raw_msg)
            entry = {
                "timestamp": time.strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": clean_msg,
            }
            ctx_tenant = getattr(record, "tenant_id", None) or _current_log_tenant.get()
            with _log_lock:
                log_buffer.append(entry)
                if ctx_tenant:
                    tenant_logs[ctx_tenant].append(entry)
        except Exception:
            pass


def get_tenant_logs(tenant_id: str, limit: int = 25) -> list:
    """Returns scrubbed recent log entries belonging exclusively to `tenant_id`."""
    with _log_lock:
        buf = list(tenant_logs.get(tenant_id) or ())
    return buf[-limit:] if limit > 0 else buf


def setup_logging():
    """Configures console and scrubbed dashboard logging handlers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(isinstance(h, DashboardLogHandler) for h in root_logger.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
        )
        dashboard_handler = DashboardLogHandler()
        dashboard_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger.addHandler(stream_handler)
        root_logger.addHandler(dashboard_handler)


# ==============================================================================
# Global Browser Worker & Isolated Multi-Tenancy Registry
# ==============================================================================

HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")

_env_profile = os.getenv("BROWSER_PROFILE_DIR")
if _env_profile:
    DEFAULT_PROFILE_DIR = os.path.abspath(_env_profile)
elif os.path.exists(os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile")):
    DEFAULT_PROFILE_DIR = os.path.abspath(
        os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile")
    )
elif os.path.exists(os.path.join(BASE_DIR, "x_browser_profile")):
    DEFAULT_PROFILE_DIR = os.path.abspath(os.path.join(BASE_DIR, "x_browser_profile"))
else:
    DEFAULT_PROFILE_DIR = os.path.abspath(
        os.path.join(BASE_DIR, "data", "browser_profiles", "x_browser_profile")
    )

# Persistent profile root honors persistent cloud volume (e.g. /data/browser_profiles on Railway/Render)
PROFILE_ROOT_DIR = os.path.dirname(DEFAULT_PROFILE_DIR)

browser_worker = XBrowserWorker(profile_dir=DEFAULT_PROFILE_DIR, headless=HEADLESS, tenant_id="default")
tenant_workers: Dict[str, XBrowserWorker] = {"default": browser_worker}
_worker_registry_lock = threading.Lock()

# Per-tenant isolated coordination state
tenant_cooldowns: Dict[str, Tuple[float, int]] = {}
tenant_login_states: Dict[str, bool] = {}
tenant_manual_login_flags: Dict[str, float] = {}  # tenant_id -> expiration timestamp
tenant_active_queries: Dict[str, str] = {}

# Backwards-compatible scalar defaults (do not use for multi-tenant isolation)
last_interaction_timestamp: float = 0.0
current_random_cooldown_seconds: int = 0
is_session_logged_in: bool = False
is_manual_login_active: bool = False
active_search_query_state: Optional[str] = None

# Background asynchronous tasks and bounded queues
bg_worker_task: Optional[asyncio.Task] = None
scheduler_worker_task: Optional[asyncio.Task] = None
action_dispatcher_task: Optional[asyncio.Task] = None
scrape_now_flag = asyncio.Event()
tenant_scrape_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
action_dispatch_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

# Real-time Server-Sent Events (SSE) push subscribers keyed by tenant_id
_sse_subscribers: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
_sse_lock = threading.Lock()


def subscribe_tenant_events(tenant_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    with _sse_lock:
        _sse_subscribers[tenant_id].add(q)
    return q


def unsubscribe_tenant_events(tenant_id: str, q: asyncio.Queue) -> None:
    with _sse_lock:
        subs = _sse_subscribers.get(tenant_id)
        if subs and q in subs:
            subs.discard(q)
        if subs is not None and len(subs) == 0:
            _sse_subscribers.pop(tenant_id, None)


def emit_tenant_event(tenant_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Non-blocking publish to any open SSE connections for `tenant_id`."""
    payload = {"type": event_type, "ts": int(time.time()), "data": data or {}}
    with _sse_lock:
        targets = list(_sse_subscribers.get(tenant_id) or ())
    for q in targets:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass


def is_manual_login(tenant_id: Optional[str] = None) -> bool:
    """Checks whether manual login is currently active for a specific tenant (with 6m auto-expiry)."""
    now = time.time()
    if tenant_id is not None:
        exp = tenant_manual_login_flags.get(tenant_id, 0.0)
        if exp > now:
            return True
        if tenant_id in tenant_manual_login_flags:
            tenant_manual_login_flags.pop(tenant_id, None)
        return False
    return any(exp > now for exp in list(tenant_manual_login_flags.values()))


def set_manual_login(tenant_id: str, active: bool, ttl_seconds: int = 360) -> None:
    """Sets or clears manual login lock strictly for `tenant_id` (auto-expires after ttl_seconds)."""
    global is_manual_login_active
    tid = tenant_id or "default"
    if active:
        tenant_manual_login_flags[tid] = time.time() + max(30, ttl_seconds)
    else:
        tenant_manual_login_flags.pop(tid, None)
    is_manual_login_active = is_manual_login()


def get_active_search_query(tenant_id: str = "default") -> Optional[str]:
    return tenant_active_queries.get(tenant_id or "default")


def set_active_search_query(tenant_id: str, query: Optional[str]) -> None:
    global active_search_query_state
    tid = tenant_id or "default"
    if query:
        tenant_active_queries[tid] = query
        if tid == "default":
            active_search_query_state = query
    else:
        tenant_active_queries.pop(tid, None)


def get_tenant_browser_worker(tenant_id: str = "default") -> XBrowserWorker:
    """
    Returns an isolated XBrowserWorker with a deterministic collision-free profile directory.
    NEVER copies or seeds another tenant's cookies!
    """
    tid = (tenant_id or "default").strip() or "default"
    with _worker_registry_lock:
        if tid in tenant_workers:
            return tenant_workers[tid]

        if tid == "default":
            profile_dir = DEFAULT_PROFILE_DIR
        else:
            folder = deterministic_profile_dirname(tid)
            os.makedirs(PROFILE_ROOT_DIR, exist_ok=True)
            profile_dir = os.path.abspath(os.path.join(PROFILE_ROOT_DIR, folder))
            real_root = os.path.realpath(PROFILE_ROOT_DIR)
            real_target = os.path.realpath(profile_dir)
            if not (real_target == real_root or real_target.startswith(real_root + os.sep)):
                raise ValueError("Invalid tenant browser profile path.")
            os.makedirs(profile_dir, exist_ok=True)

        worker = XBrowserWorker(profile_dir=profile_dir, headless=HEADLESS, tenant_id=tid)
        tenant_workers[tid] = worker
        return worker


def evict_stopped_worker(tenant_id: str) -> None:
    """Evicts an idle stopped worker from memory registry (except 'default') to keep memory bounded."""
    if tenant_id == "default":
        return
    with _worker_registry_lock:
        w = tenant_workers.get(tenant_id)
        if w and not getattr(w, "is_running", False):
            tenant_workers.pop(tenant_id, None)


def get_cooldown_remaining(tenant_id: str = "default") -> int:
    """Returns seconds remaining in the current randomized cooldown window for `tenant_id`."""
    tid = tenant_id or "default"
    last_ts, dur = tenant_cooldowns.get(tid, (0.0, 0))
    if last_ts <= 0 or dur <= 0:
        return 0
    return max(0, int(dur - (time.time() - last_ts)))


def set_new_random_cooldown(min_mins: int, max_mins: int, tenant_id: str = "default"):
    """Sets a randomized cooldown duration scoped strictly to `tenant_id`."""
    global last_interaction_timestamp, current_random_cooldown_seconds
    tid = tenant_id or "default"
    now = time.time()
    low = max(1, min_mins) * 60
    high = max(low + 60, max_mins * 60)
    dur = random.randint(low, high)
    tenant_cooldowns[tid] = (now, dur)
    if tid == "default":
        last_interaction_timestamp = now
        current_random_cooldown_seconds = dur


def sync_detected_username(
    db: Session, tenant_id: str = "default", worker: Optional[XBrowserWorker] = None
):
    """Saves worker.logged_in_username and ENCRYPTED session cookies to AgentConfig."""
    tid = tenant_id or "default"
    w = worker or get_tenant_browser_worker(tid)
    cfg = get_agent_config(db, tenant_id=tid)
    changed = False

    if w.logged_in_username and cfg.linked_username != w.logged_in_username:
        cfg.linked_username = w.logged_in_username
        changed = True

    if os.path.isfile(w.cookies_backup_path):
        try:
            with open(w.cookies_backup_path, "r", encoding="utf-8") as f:
                c_data = f.read()
            if c_data and len(c_data) > 10:
                from database import get_decrypted_cookies_json
                current_plain = get_decrypted_cookies_json(cfg)
                if c_data != current_plain or not (getattr(cfg, "cookies_json", "") or "").startswith("enc::"):
                    cfg.cookies_json = encrypt_secret(c_data)
                    changed = True
        except Exception as e:
            logger.debug(f"Cookie sync notice for '{tid}': {e}")

    if changed:
        try:
            db.commit()
        except Exception as ce:
            db.rollback()
            logger.debug(f"DB commit error during sync: {ce}")


def update_env_variable(key: str, value: str):
    """Thread-safe sanitized .env updater (strips newlines to block .env directive injection)."""
    clean_key = re.sub(r"[^A-Za-z0-9_]", "", key or "")
    clean_val = str(value or "").replace("\r", "").replace("\n", "").strip()
    if not clean_key:
        return
    env_path = os.path.join(BASE_DIR, ".env")
    with _env_lock:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            found = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{clean_key}="):
                    new_lines.append(f"{clean_key}={clean_val}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{clean_key}={clean_val}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        os.environ[clean_key] = clean_val
