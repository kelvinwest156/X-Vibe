"""
AI Decision Engine Facade for X-VibeBot.
Re-exports modularized AI services from `services/` (ai_client, ai_prompts, ai_evaluator, ai_generator).
Maintains 100% backward compatibility for all routers and core background workflows.
"""

# AI Client & API Connection Services
from services.ai_client import (
    KNOWN_GEMINI_MODELS,
    KNOWN_DEEPSEEK_MODELS,
    get_active_provider,
    get_best_available_model,
    sanitize_model_for_provider,
    get_gemini_client,
    get_deepseek_client,
    close_ai_clients,
    format_ai_error,
    test_ai_api,
    log_deepseek_usage,
    log_gemini_usage,
    async_log_ai_usage,
    check_tenant_token_budget,
    async_check_tenant_token_budget,
    _test_gemini_api,
    _test_deepseek_api,
    _fetch_image_bytes,
    _sanitize_ai_tells,
    _clean_json_markdown,
)

# Prompt Engineering & Few-Shot Voice Memory
from services.ai_prompts import (
    build_system_prompt,
    build_batch_evaluation_prompt,
    build_variants_prompt,
    build_prompt_user_examples,
    _build_original_prompt_and_instructions,
)

# Multimodal Evaluation, Batching & Angle Discovery
from services.ai_evaluator import (
    evaluate_tweet,
    evaluate_tweets_batch,
    generate_reply_variants,
    _evaluate_with_gemini,
    _evaluate_with_deepseek,
    _parse_ai_json_payload,
)

# Zero-Token Python Spam Pre-Filter
from services.tweet_filter import should_prefilter_skip

# Content Generation, Query Scout & Telemetry Strategy Brief
from services.ai_generator import (
    generate_original_content,
    generate_smart_search_query,
    generate_strategy_brief,
    _generate_original_with_deepseek,
    _parse_original_json_payload,
    _strategy_brief_cache,
)

__all__ = [
    "KNOWN_GEMINI_MODELS",
    "KNOWN_DEEPSEEK_MODELS",
    "get_active_provider",
    "get_best_available_model",
    "sanitize_model_for_provider",
    "get_gemini_client",
    "get_deepseek_client",
    "close_ai_clients",
    "format_ai_error",
    "test_ai_api",
    "log_deepseek_usage",
    "log_gemini_usage",
    "async_log_ai_usage",
    "check_tenant_token_budget",
    "async_check_tenant_token_budget",
    "_test_gemini_api",
    "_test_deepseek_api",
    "_fetch_image_bytes",
    "_sanitize_ai_tells",
    "_clean_json_markdown",
    "build_system_prompt",
    "build_batch_evaluation_prompt",
    "build_variants_prompt",
    "build_prompt_user_examples",
    "_build_original_prompt_and_instructions",
    "evaluate_tweet",
    "evaluate_tweets_batch",
    "generate_reply_variants",
    "should_prefilter_skip",
    "_evaluate_with_gemini",
    "_evaluate_with_deepseek",
    "_parse_ai_json_payload",
    "generate_original_content",
    "generate_smart_search_query",
    "generate_strategy_brief",
    "_generate_original_with_deepseek",
    "_parse_original_json_payload",
    "_strategy_brief_cache",
]
