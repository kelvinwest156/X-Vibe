"""
AI Tweet Evaluation Service for X-VibeBot.
Evaluates incoming tweets using Google Gemini Multimodal Vision + Few-Shot Memory,
or DeepSeek API as fallback. Generates dynamic context-aware angles, like decisions,
and urgency scores.
"""

import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any

from services.ai_client import (
    get_active_provider,
    get_gemini_client,
    get_deepseek_client,
    format_ai_error,
    _fetch_image_bytes,
    _sanitize_ai_tells,
    _clean_json_markdown,
)
from services.ai_prompts import build_system_prompt

logger = logging.getLogger("x_vibebot.services.ai_evaluator")

# Track the last working Gemini model across evaluations
_last_working_gemini_model: Optional[str] = None


def _parse_ai_json_payload(raw_output: str) -> Dict[str, Any]:
    """Parses the JSON response and preserves dynamic context-aware reply angles, should_like, and urgency_score."""
    cleaned = _clean_json_markdown(raw_output)
    data = json.loads(cleaned)

    action = str(data.get("action", "")).strip().lower()
    raw_variants = data.get("variants") if isinstance(data.get("variants"), dict) else {}

    variants: Dict[str, str] = {}
    for k, v in list(raw_variants.items())[:4]:
        clean_key = str(k).strip()
        clean_val = _sanitize_ai_tells(str(v or ""))
        if clean_key and clean_val:
            variants[clean_key] = clean_val

    first_variant = next(iter(variants.values()), "")
    primary = _sanitize_ai_tells(str(data.get("text", "") or "")) or first_variant
    reasoning = str(data.get("reasoning", "")).strip()
    should_like = bool(data.get("should_like", False))
    try:
        urgency_score = max(1, min(10, int(data.get("urgency_score", 5))))
    except Exception:
        urgency_score = 5

    if primary and not variants:
        variants["Primary Angle"] = primary

    if action == "reply" and primary and "skip" not in primary.lower():
        return {
            "should_reply": True,
            "reply_text": primary,
            "variants": variants,
            "variants_json": json.dumps(variants, ensure_ascii=False),
            "should_like": should_like,
            "urgency_score": urgency_score,
            "reasoning": reasoning or "Relevant post",
            "raw_response": raw_output
        }
    return {
        "should_reply": False,
        "reply_text": None,
        "variants": {},
        "variants_json": None,
        "should_like": False,
        "urgency_score": 1,
        "reasoning": reasoning or "Skipped by AI filter",
        "raw_response": raw_output
    }


async def _evaluate_with_gemini(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: str = "gemini-2.0-flash",
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    extra_context: Optional[str] = None,
    temperature: float = 0.75,
    media_url: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Generates evaluation, dynamic reply angles, like decision, and urgency score using Google Gemini + Vision."""
    client = get_gemini_client(custom_key=custom_key)
    if not client:
        logger.warning("GEMINI_API_KEY not configured. Skipping AI evaluation.")
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "should_like": False,
            "urgency_score": 1,
            "reasoning": "Google Gemini API key is not configured",
            "raw_response": "NO_API_KEY"
        }

    chosen_model = model_name or "gemini-2.0-flash"
    clean_model = chosen_model.replace("models/", "")
    user_content_text = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"
    if extra_context:
        user_content_text += f"\nContext / Quoted / Media Info: {extra_context}"

    try:
        from google.genai import types

        contents_payload: Any = user_content_text
        if media_url:
            img_fetched = await _fetch_image_bytes(media_url)
            if img_fetched:
                img_bytes, mime_type = img_fetched
                contents_payload = [
                    user_content_text + "\n[An image is attached to this tweet. Inspect the visual details to make your reply hyper-relevant.]",
                    types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                ]

        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(search_query, persona_prompt, learning_memory=learning_memory),
            response_mime_type="application/json",
            temperature=temperature,
            max_output_tokens=1500
        )

        global _last_working_gemini_model
        fallback_candidates = []
        if _last_working_gemini_model:
            fallback_candidates.append(_last_working_gemini_model)
        fallback_candidates.extend([
            clean_model,
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
            "gemini-2.5-flash",
            "gemini-3.8-flash"
        ])
        models_to_try = list(dict.fromkeys(fallback_candidates))

        response = None
        last_err = None
        for candidate_model in models_to_try:
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=candidate_model,
                        contents=contents_payload,
                        config=config
                    ),
                    timeout=9.0
                )
                clean_model = candidate_model
                _last_working_gemini_model = candidate_model
                break
            except asyncio.TimeoutError as te:
                last_err = te
                logger.info(f"Model {candidate_model} timed out (>9s); failing over to next model...")
                continue
            except Exception as try_err:
                last_err = try_err
                err_str = str(try_err)
                if any(code in err_str for code in ["404", "NOT_FOUND", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"]):
                    logger.info(f"Model {candidate_model} busy ({err_str[:65]}); failing over to next model...")
                    continue
                raise try_err

        if response is None and last_err is not None:
            raise last_err

        raw_output = response.text or "" if response else ""
        logger.info(f"Gemini ({clean_model}) evaluated @{tweet_author} (vision={bool(media_url)})")
        return _parse_ai_json_payload(raw_output)

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error calling Google Gemini API ({clean_model}): {err_msg}")
        clean_err = format_ai_error(e)
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "should_like": False,
            "urgency_score": 1,
            "reasoning": clean_err,
            "raw_response": f"ERROR: {err_msg}"
        }


async def _evaluate_with_deepseek(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: str = "deepseek-chat",
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    extra_context: Optional[str] = None,
    temperature: float = 0.75,
    learning_memory: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Fallback evaluation with DeepSeek API."""
    client = get_deepseek_client(custom_key=custom_key)
    if not client:
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "should_like": False,
            "urgency_score": 1,
            "reasoning": "DeepSeek API key not configured",
            "raw_response": "NO_API_KEY"
        }

    chosen_model = model_name or "deepseek-chat"
    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"
    if extra_context:
        user_content += f"\nContext: {extra_context}"

    try:
        kwargs = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": build_system_prompt(search_query, persona_prompt, learning_memory=learning_memory)},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 500
        }
        if "reasoner" not in chosen_model.lower():
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["temperature"] = temperature

        response = await client.chat.completions.create(**kwargs)
        raw_output = response.choices[0].message.content or ""
        return _parse_ai_json_payload(raw_output)
    except Exception as e:
        err_msg = str(e)
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "should_like": False,
            "urgency_score": 1,
            "reasoning": f"DeepSeek API Error: {err_msg[:120]}",
            "raw_response": f"ERROR: {err_msg}"
        }


async def evaluate_tweet(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    extra_context: Optional[str] = None,
    temperature: float = 0.75,
    media_url: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates a scraped tweet using Google Gemini Multimodal Vision + Few-Shot Memory (or DeepSeek fallback).
    Returns should_reply, reply_text, dynamic variants, should_like, urgency_score, and reasoning.
    """
    provider = get_active_provider(custom_key)

    if provider == "gemini":
        return await _evaluate_with_gemini(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            custom_key=custom_key,
            search_query=search_query,
            persona_prompt=persona_prompt,
            extra_context=extra_context,
            temperature=temperature,
            media_url=media_url,
            learning_memory=learning_memory
        )
    else:
        return await _evaluate_with_deepseek(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=model_name or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            custom_key=custom_key,
            search_query=search_query,
            persona_prompt=persona_prompt,
            extra_context=extra_context,
            temperature=temperature,
            learning_memory=learning_memory
        )
