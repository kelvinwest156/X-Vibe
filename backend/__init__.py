"""
Backend package for X-VibeBot.
Re-exports routers, dependencies, and core modules.
"""

from core import state, dependencies, background
import routers

__all__ = ["state", "dependencies", "background", "routers"]
