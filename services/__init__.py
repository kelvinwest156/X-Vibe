"""
Services package for X-VibeBot.
Houses modular AI reasoning, content generation, and Playwright browser automation engines.
"""

from services.ai_client import (
    KNOWN_GEMINI_MODELS,
    KNOWN_DEEPSEEK_MODELS,
    get_active_provider,
    get_best_available_model,
    sanitize_model_for_provider,
    get_gemini_client,
    get_deepseek_client,
    format_ai_error,
    test_ai_api,
    log_deepseek_usage,
    check_tenant_token_budget,
)
from services.ai_prompts import (
    build_system_prompt,
    build_batch_evaluation_prompt,
    build_variants_prompt,
)
from services.ai_evaluator import (
    evaluate_tweet,
    evaluate_tweets_batch,
    generate_reply_variants,
)
from services.tweet_filter import (
    should_prefilter_skip,
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
    "sanitize_model_for_provider",
    "get_gemini_client",
    "get_deepseek_client",
    "format_ai_error",
    "test_ai_api",
    "log_deepseek_usage",
    "check_tenant_token_budget",
    # Prompts
    "build_system_prompt",
    "build_batch_evaluation_prompt",
    "build_variants_prompt",
    # Evaluator & pre-filter
    "evaluate_tweet",
    "evaluate_tweets_batch",
    "generate_reply_variants",
    "should_prefilter_skip",
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
