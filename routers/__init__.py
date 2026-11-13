"""
Routers package for X-VibeBot.
Aggregates all domain routers for authentication, configuration, queue management,
browser automation, analytics, and system monitoring.
"""

from routers.auth import router as auth_router
from routers.config import router as config_router
from routers.queue import router as queue_router
from routers.browser import router as browser_router
from routers.analytics import router as analytics_router
from routers.system import router as system_router

__all__ = [
    "auth_router",
    "config_router",
    "queue_router",
    "browser_router",
    "analytics_router",
    "system_router"
]
