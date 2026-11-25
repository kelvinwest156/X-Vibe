"""
Core module for X-VibeBot.
Uses lazy attribute imports (PEP 562) to avoid eager import-order cycles across core submodules.
"""

import importlib
from typing import Any

__all__ = ["security", "state", "dependencies", "background", "web_scout"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return importlib.import_module(f"core.{name}")
    raise AttributeError(f"module 'core' has no attribute {name!r}")
