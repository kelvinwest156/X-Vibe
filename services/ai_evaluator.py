"""
AI Tweet Evaluation Service for X-VibeBot.
Evaluates incoming tweets in batches (1 API call for up to 8 tweets) using DeepSeek
with prefix-cached prompts and exact token telemetry, plus on-demand 3-angle variant generation
and Gemini fallback.
"""

import json
import asyncio
import logging
from typing import Optional, Dict, Any, List

from services.ai_client import (
    get_best_available_model,
    sanitize_model_for_provider,
    get_gemini_client,
    get_deepseek_client,
    format_ai_error,
    log_deepseek_usage,
    _fetch_image_bytes,
    _sanitize_ai_tells,
    _clean_json_markdown,
)
from services.ai_prompts import (
    build_system_prompt,
    build_batch_evaluation_prompt,
    build_variants_prompt,
)

logger = logging.getLogger("x_vibebot.services.ai_evaluator")

# Track the last working Gemini model across evaluations
_last_working_gemini_model: Optional[str] = None


def _normalize_eval_dict(
    data: Dict[str, Any],
    raw_output: str = "",
    include_variants: bool = False,
) -> Dict[str, Any]:
    """Normalizes a single evaluation JSON object into the standard response shape."""
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

    if include_variants and primary and not variants:
        variants["Primary Angle"] = primary

    if action == "reply" and primary and "skip" not in primary.lower():
        return {
            "should_reply": True,
            "reply_text": primary,
            "variants": variants,
            "variants_json": json.dumps(variants, ensure_ascii=False) if variants else None,
            "should_like": should_like,
            "urgency_score": urgency_score,
            "reasoning": reasoning or "Relevant post",
            "raw_response": raw_output,
        }
    return {
        "should_reply": False,
        "reply_text": None,
        "variants": {},
        "variants_json": None,
        "should_like": False,
        "urgency_score": 1,
        "reasoning": reasoning or "Skipped by AI filter",
        "raw_response": raw_output,
    }


def _parse_ai_json_payload(raw_output: str, include_variants: bool = False) -> Dict[str, Any]:
    """Parses the JSON response and preserves optional reply angles, should_like, and urgency_score."""
    cleaned = _clean_json_markdown(raw_output)
    data = json.loads(cleaned)
    return _normalize_eval_dict(data, raw_output=raw_output, include_variants=include_variants)


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
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
) -> Dict[str, Any]:
    """Generates evaluation, optional reply angles, like decision, and urgency score using Google Gemini + Vision."""
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
            "raw_response": "NO_API_KEY",
        }

    chosen_model = sanitize_model_for_provider("gemini", model_name)
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
                    types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                ]

        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(
                search_query,
                persona_prompt,
                learning_memory=learning_memory,
                include_variants=include_variants,
            ),
            response_mime_type="application/json",
            temperature=temperature,
            max_output_tokens=1000 if include_variants else 350,
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
            "gemini-3.8-flash",
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
                        config=config,
                    ),
                    timeout=9.0,
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
        return _parse_ai_json_payload(raw_output, include_variants=include_variants)

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
            "raw_response": f"ERROR: {err_msg}",
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
    media_url: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Single-tweet evaluation with DeepSeek API, prefix-cached prompt, and token telemetry."""
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
            "raw_response": "NO_API_KEY",
        }

    chosen_model = sanitize_model_for_provider("deepseek", model_name)
    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"
    if extra_context:
        user_content += f"\nContext: {extra_context}"
    if media_url:
        user_content += f"\n[Note: An image is attached to this tweet: {media_url}]"

    try:
        kwargs: Dict[str, Any] = {
            "model": chosen_model,
            "messages": [
                {
                    "role": "system",
                    "content": build_system_prompt(
                        search_query,
                        persona_prompt,
                        learning_memory=learning_memory,
                        include_variants=include_variants,
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 900 if include_variants else 260,
        }
        if "reasoner" not in chosen_model.lower():
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["temperature"] = temperature

        response = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=15.0)
        log_deepseek_usage(
            response,
            tenant_id=tenant_id,
            task_type="evaluate_single",
            model_name=chosen_model,
        )
        raw_output = response.choices[0].message.content or ""
        logger.info(f"DeepSeek ({chosen_model}) evaluated @{tweet_author}")
        return _parse_ai_json_payload(raw_output, include_variants=include_variants)
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error calling DeepSeek API ({chosen_model}): {err_msg}")
        clean_err = format_ai_error(e)
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "should_like": False,
            "urgency_score": 1,
            "reasoning": clean_err,
            "raw_response": f"ERROR: {err_msg}",
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
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    Evaluates a single scraped tweet using DeepSeek API (with prefix-cached prompt & few-shot memory).
    Returns should_reply, reply_text, optional variants, should_like, urgency_score, and reasoning.
    """
    provider, resolved_model = get_best_available_model(task_type="evaluate", custom_key=custom_key)
    if model_name and model_name != "auto":
        resolved_model = sanitize_model_for_provider(provider, model_name)

    if provider == "gemini":
        return await _evaluate_with_gemini(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=resolved_model,
            custom_key=custom_key,
            search_query=search_query,
            persona_prompt=persona_prompt,
            extra_context=extra_context,
            temperature=temperature,
            media_url=media_url,
            learning_memory=learning_memory,
            include_variants=include_variants,
        )
    else:
        res = await _evaluate_with_deepseek(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=resolved_model,
            custom_key=custom_key,
            search_query=search_query,
            persona_prompt=persona_prompt,
            extra_context=extra_context,
            temperature=temperature,
            media_url=media_url,
            learning_memory=learning_memory,
            include_variants=include_variants,
            tenant_id=tenant_id,
        )
        if res.get("reply_text") or (
            res.get("should_reply") is False
            and res.get("raw_response") != "NO_API_KEY"
            and "ERROR:" not in res.get("raw_response", "")
        ):
            return res
        if get_gemini_client(custom_key=custom_key):
            logger.info("DeepSeek call did not complete; falling back to Gemini...")
            return await _evaluate_with_gemini(
                tweet_text=tweet_text,
                tweet_author=tweet_author,
                model_name=sanitize_model_for_provider("gemini"),
                custom_key=custom_key,
                search_query=search_query,
                persona_prompt=persona_prompt,
                extra_context=extra_context,
                temperature=temperature,
                media_url=media_url,
                learning_memory=learning_memory,
                include_variants=include_variants,
            )
        return res


async def evaluate_tweets_batch(
    tweets: List[Dict[str, Any]],
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    temperature: float = 0.75,
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
    tenant_id: str = "default",
) -> Dict[str, Dict[str, Any]]:
    """
    Evaluates a batch of candidate tweets (up to 8 per request) in ONE single DeepSeek API call.
    Dramatically cuts repeated system-prompt tokens and hits DeepSeek's 90% prefix cache discount.
    Maps results back by tweet_id; safely falls back to individual evaluation if batch parsing fails.
    """
    if not tweets:
        return {}

    results_by_id: Dict[str, Dict[str, Any]] = {}
    client = get_deepseek_client(custom_key=custom_key)

    if not client:
        # No DeepSeek key configured; fall back to evaluate_tweet (which handles Gemini or returns NO_API_KEY)
        for t in tweets:
            tid = str(t.get("tweet_id") or t.get("id") or "")
            if not tid:
                continue
            res = await evaluate_tweet(
                tweet_text=str(t.get("text") or t.get("tweet_text") or ""),
                tweet_author=t.get("author") or t.get("tweet_author"),
                model_name=model_name,
                custom_key=custom_key,
                search_query=search_query,
                persona_prompt=persona_prompt,
                extra_context=t.get("extra_context"),
                temperature=temperature,
                media_url=t.get("media_url"),
                learning_memory=learning_memory,
                include_variants=include_variants,
                tenant_id=tenant_id,
            )
            results_by_id[tid] = res
            if res.get("raw_response") == "NO_API_KEY":
                break
        return results_by_id

    chosen_model = sanitize_model_for_provider("deepseek", None if model_name == "auto" else model_name)

    # Chunk into batches of at most 8 tweets
    chunk_size = 8
    for start_idx in range(0, len(tweets), chunk_size):
        chunk = tweets[start_idx : start_idx + chunk_size]
        sys_prompt, usr_prompt = build_batch_evaluation_prompt(
            tweets=chunk,
            search_query=search_query,
            persona_prompt=persona_prompt,
            learning_memory=learning_memory,
            include_variants=include_variants,
        )

        batch_parsed_ok = False
        try:
            max_tok = (len(chunk) * 320 + 200) if include_variants else (len(chunk) * 140 + 150)
            kwargs: Dict[str, Any] = {
                "model": chosen_model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": usr_prompt},
                ],
                "max_tokens": min(2800, max(400, max_tok)),
            }
            if "reasoner" not in chosen_model.lower():
                kwargs["response_format"] = {"type": "json_object"}
                kwargs["temperature"] = temperature

            response = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=25.0)
            log_deepseek_usage(
                response,
                tenant_id=tenant_id,
                task_type="evaluate_batch",
                model_name=chosen_model,
            )
            raw_output = response.choices[0].message.content or ""
            cleaned = _clean_json_markdown(raw_output)
            parsed = json.loads(cleaned)

            items_list = parsed.get("results") if isinstance(parsed, dict) else parsed
            if isinstance(items_list, list):
                for entry in items_list:
                    if not isinstance(entry, dict):
                        continue
                    eid = str(entry.get("id") or entry.get("tweet_id") or "").strip()
                    if eid:
                        results_by_id[eid] = _normalize_eval_dict(
                            entry,
                            raw_output=raw_output,
                            include_variants=include_variants,
                        )
                batch_parsed_ok = True
                logger.info(
                    f"DeepSeek ({chosen_model}) batch-evaluated {len(chunk)} tweets in 1 API call "
                    f"(matched {sum(1 for t in chunk if str(t.get('tweet_id') or t.get('id') or '') in results_by_id)}/{len(chunk)})."
                )
        except Exception as e:
            logger.warning(f"Batch evaluation error ({chosen_model}); falling back to per-tweet evaluation: {e}")

        # Fallback for any tweets not matched in the batch response
        if not batch_parsed_ok:
            for t in chunk:
                tid = str(t.get("tweet_id") or t.get("id") or "")
                if not tid or tid in results_by_id:
                    continue
                results_by_id[tid] = await evaluate_tweet(
                    tweet_text=str(t.get("text") or t.get("tweet_text") or ""),
                    tweet_author=t.get("author") or t.get("tweet_author"),
                    model_name=model_name,
                    custom_key=custom_key,
                    search_query=search_query,
                    persona_prompt=persona_prompt,
                    extra_context=t.get("extra_context"),
                    temperature=temperature,
                    media_url=t.get("media_url"),
                    learning_memory=learning_memory,
                    include_variants=include_variants,
                    tenant_id=tenant_id,
                )

    return results_by_id


async def generate_reply_variants(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    current_reply: str = "",
    persona_prompt: Optional[str] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """
    On-demand generation of 3 distinct reply angle variants for a single queued draft.
    Called only when the user clicks "Generate 3 angles" in the Review Queue.
    """
    sys_prompt, usr_prompt = build_variants_prompt(
        tweet_text=tweet_text or "",
        tweet_author=tweet_author or "creator",
        current_reply=current_reply or "",
        persona_prompt=persona_prompt,
    )

    def _extract_variants(raw_str: str) -> Dict[str, str]:
        cleaned = _clean_json_markdown(raw_str)
        data = json.loads(cleaned)
        raw_vars = data.get("variants") if isinstance(data, dict) and isinstance(data.get("variants"), dict) else data
        out: Dict[str, str] = {}
        if isinstance(raw_vars, dict):
            for k, v in list(raw_vars.items())[:3]:
                ck = str(k).strip()
                cv = _sanitize_ai_tells(str(v or ""))
                if ck and cv:
                    out[ck] = cv
        return out

    ds_client = get_deepseek_client(custom_key=custom_key)
    if ds_client:
        chosen_model = sanitize_model_for_provider("deepseek", None if model_name == "auto" else model_name)
        try:
            kwargs: Dict[str, Any] = {
                "model": chosen_model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": usr_prompt},
                ],
                "max_tokens": 450,
            }
            if "reasoner" not in chosen_model.lower():
                kwargs["response_format"] = {"type": "json_object"}
                kwargs["temperature"] = 0.85

            resp = await asyncio.wait_for(ds_client.chat.completions.create(**kwargs), timeout=15.0)
            log_deepseek_usage(
                resp,
                tenant_id=tenant_id,
                task_type="variants",
                model_name=chosen_model,
            )
            raw_out = resp.choices[0].message.content or ""
            variants = _extract_variants(raw_out)
            if variants:
                return {
                    "success": True,
                    "variants": variants,
                    "variants_json": json.dumps(variants, ensure_ascii=False),
                }
        except Exception as e:
            logger.error(f"DeepSeek generate_reply_variants error: {e}")
            if not get_gemini_client(custom_key=custom_key):
                return {"success": False, "variants": {}, "variants_json": None, "error": format_ai_error(e)}

    gem_client = get_gemini_client(custom_key=custom_key)
    if gem_client:
        try:
            from google.genai import types
            resp = await asyncio.wait_for(
                gem_client.aio.models.generate_content(
                    model=sanitize_model_for_provider("gemini"),
                    contents=usr_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=sys_prompt,
                        response_mime_type="application/json",
                        temperature=0.85,
                        max_output_tokens=500,
                    ),
                ),
                timeout=10.0,
            )
            if resp and resp.text:
                variants = _extract_variants(resp.text)
                if variants:
                    return {
                        "success": True,
                        "variants": variants,
                        "variants_json": json.dumps(variants, ensure_ascii=False),
                    }
        except Exception as e:
            logger.error(f"Gemini generate_reply_variants error: {e}")
            return {"success": False, "variants": {}, "variants_json": None, "error": format_ai_error(e)}

    return {
        "success": False,
        "variants": {},
        "variants_json": None,
        "error": "DeepSeek API key not configured",
    }
