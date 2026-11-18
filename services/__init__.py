"""
Services package for X-VibeBot.
Houses modular AI reasoning, content generation, and Playwright browser automation engines.
"""

from services.ai_client import (
    KNOWN_GEMINI_MODELS,
    KNOWN_DEEPSEEK_MODELS,
    get_active_provider,
    get_best_available_model,
    get_gemini_client,
    get_deepseek_client,
    format_ai_error,
    test_ai_api,
)
from services.ai_prompts import (
    build_system_prompt,
)
from services.ai_evaluator import (
    evaluate_tweet,
)
from services.ai_generator import (
    generate_original_content,
    generate_smart_search_query,
    generate_strategy_brief,
)
from services.browser import (
    XBrowserWorker,
    DEFAULT_PROFILE_DIR,
    get_default_chromium_path,
    kill_profile_browser_processes,
)

__all__ = [
    # AI client & models
    "KNOWN_GEMINI_MODELS",
    "KNOWN_DEEPSEEK_MODELS",
    "get_active_provider",
    "get_best_available_model",
    "get_gemini_client",
    "get_deepseek_client",
    "format_ai_error",
    "test_ai_api",
    # Prompts
    "build_system_prompt",
    # Evaluator
    "evaluate_tweet",
    # Generator
    "generate_original_content",
    "generate_smart_search_query",
    "generate_strategy_brief",
    # Browser
    "XBrowserWorker",
    "DEFAULT_PROFILE_DIR",
    "get_default_chromium_path",
    "kill_profile_browser_processes",
]
