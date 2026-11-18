"""
AI Content Generation & Strategy Service for X-VibeBot.
Handles autonomous trend query discovery with Google Search Grounding,
original post/thread drafting, and executive AI strategy briefs for analytics telemetry.
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List

from services.ai_client import (
    get_active_provider,
    get_best_available_model,
    get_gemini_client,
    get_deepseek_client,
    format_ai_error,
    _sanitize_ai_tells,
    _clean_json_markdown,
)
from services.ai_prompts import _build_original_prompt_and_instructions

logger = logging.getLogger("x_vibebot.services.ai_generator")

_last_working_gemini_model: Optional[str] = None
_strategy_brief_cache: Dict[str, Any] = {"timestamp": 0.0, "data": None}


def _parse_original_json_payload(raw_text: str, requested_mode: str, topic: str) -> Dict[str, Any]:
    """Safely extracts JSON payload from Gemini or DeepSeek output."""
    cleaned = _clean_json_markdown(raw_text)
    data = json.loads(cleaned)

    resolved_mode = str(data.get("chosen_mode") or ("post" if requested_mode == "auto" else requested_mode)).strip().lower()
    if resolved_mode not in ("post", "thread"):
        resolved_mode = "post" if requested_mode == "auto" else requested_mode

    try:
        urgency_score = max(1, min(10, int(data.get("urgency_score", 6))))
    except Exception:
        urgency_score = 6

    def clean_item(val: str) -> str:
        if resolved_mode == "thread":
            parts = [_sanitize_ai_tells(p.strip()) for p in val.split("---") if p.strip()]
            return "\n---\n".join(parts)
        return _sanitize_ai_tells(val)

    raw_variants = data.get("variants") if isinstance(data.get("variants"), dict) else {}
    variants = {}
    for k, v in list(raw_variants.items())[:4]:
        if v and str(v).strip():
            variants[str(k).strip()] = clean_item(str(v))

    primary = clean_item(str(data.get("text", "") or ""))
    if not primary and variants:
        primary = next(iter(variants.values()))
    if primary and not variants:
        variants["Primary Angle"] = primary

    topic_summary = str(data.get("topic_summary", f"Live pulse on {topic}")).strip()

    return {
        "success": True,
        "action_type": resolved_mode,
        "text": primary,
        "variants": variants,
        "variants_json": json.dumps(variants, ensure_ascii=False),
        "urgency_score": urgency_score,
        "topic_summary": topic_summary
    }


async def _generate_original_with_deepseek(
    mode: str = "auto",
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    live_tweets: Optional[List[Dict[str, Any]]] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Generates original post or thread with DeepSeek API."""
    client = get_deepseek_client(custom_key=custom_key)
    if not client:
        return {
            "success": False,
            "action_type": "post" if mode == "auto" else mode,
            "text": None,
            "variants_json": None,
            "urgency_score": 5,
            "topic_summary": "DeepSeek API key is not configured",
            "error": "DeepSeek API key is not configured",
            "error_code": 401
        }
    topic = (search_query or "tech, AI, and culture").strip()
    voice = (persona_prompt or "Casual, sharp, dry humor, short sentences, zero corporate buzzwords").strip()
    prompt, _ = _build_original_prompt_and_instructions(
        mode=mode,
        topic=topic,
        voice=voice,
        live_tweets=live_tweets,
        learning_memory=learning_memory
    )
    chosen_model = model_name or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    kwargs = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": "You are a professional social media strategist writing real, punchy X posts. Output valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1500
    }
    if "reasoner" not in chosen_model.lower():
        kwargs["response_format"] = {"type": "json_object"}
        kwargs["temperature"] = 0.82

    try:
        response = await asyncio.wait_for(client.chat.completions.create(**kwargs), timeout=20.0)
        raw_text = response.choices[0].message.content or ""
        logger.info(f"DeepSeek ({chosen_model}) generated original {mode} on '{topic[:40]}'")
        return _parse_original_json_payload(raw_text, requested_mode=mode, topic=topic)
    except Exception as e:
        logger.error(f"Error calling DeepSeek API for original {mode}: {e}")
        clean_err = format_ai_error(e)
        return {
            "success": False,
            "action_type": "post" if mode == "auto" else mode,
            "text": None,
            "variants_json": None,
            "urgency_score": 5,
            "topic_summary": clean_err,
            "error": clean_err,
            "error_code": 500
        }


async def generate_original_content(
    mode: str = "auto",
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    live_tweets: Optional[List[Dict[str, Any]]] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generates an original standalone X post (mode='post'), a multi-post thread (mode='thread'),
    or lets the AI autonomously choose the best format (mode='auto') synthesized from real-time
    X conversations, user voice memory, and live Google Search grounding.
    """
    if not model_name or model_name == "auto":
        provider, resolved_model = get_best_available_model(task_type=mode, custom_key=custom_key)
    else:
        provider = get_active_provider(custom_key=custom_key)
        resolved_model = model_name

    if provider == "deepseek":
        res = await _generate_original_with_deepseek(
            mode=mode,
            search_query=search_query,
            persona_prompt=persona_prompt,
            live_tweets=live_tweets,
            model_name=resolved_model,
            custom_key=custom_key,
            learning_memory=learning_memory
        )
        if res.get("success") and res.get("text"):
            return res
        if get_gemini_client(custom_key=custom_key):
            logger.info("DeepSeek original generation failed; attempting fallback to Gemini...")
        else:
            return res

    client = get_gemini_client(custom_key=custom_key)
    if not client:
        # Check if DeepSeek fallback is configured
        if get_deepseek_client(custom_key=custom_key):
            logger.info("Gemini key missing; falling back to configured DeepSeek API for original content generation.")
            return await _generate_original_with_deepseek(
                mode=mode,
                search_query=search_query,
                persona_prompt=persona_prompt,
                live_tweets=live_tweets,
                model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                custom_key=custom_key,
                learning_memory=learning_memory
            )
        fallback_mode = "post" if mode == "auto" else mode
        msg = "DeepSeek API key not configured. Enter your key in Settings to generate content."
        return {
            "success": False,
            "action_type": fallback_mode,
            "text": None,
            "variants_json": None,
            "urgency_score": 5,
            "topic_summary": msg,
            "error": msg,
            "error_code": 401
        }

    topic = (search_query or "tech, AI, and culture").strip()
    voice = (persona_prompt or "Casual, sharp, dry humor, short sentences, zero corporate buzzwords").strip()
    prompt, _ = _build_original_prompt_and_instructions(
        mode=mode,
        topic=topic,
        voice=voice,
        live_tweets=live_tweets,
        learning_memory=learning_memory
    )

    chosen_model = (model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")).replace("models/", "")

    try:
        from google.genai import types
        global _last_working_gemini_model

        fallback_candidates = []
        if _last_working_gemini_model:
            fallback_candidates.append(_last_working_gemini_model)
        fallback_candidates.extend([
            chosen_model,
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
            for use_search in (True, False):
                try:
                    if use_search:
                        cfg = types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                            temperature=0.82,
                            max_output_tokens=1800
                        )
                    else:
                        cfg = types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.82,
                            max_output_tokens=1800
                        )

                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=candidate_model,
                            contents=prompt,
                            config=cfg
                        ),
                        timeout=8.5
                    )
                    if response and response.text and "{" in response.text:
                        _last_working_gemini_model = candidate_model
                        break
                    response = None
                except Exception as e:
                    last_err = e
                    response = None
                    err_str = str(e)
                    # If this model hit 429 quota exhaustion or 404 not found, immediately cascade to next model
                    if any(code in err_str for code in ["429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND"]):
                        logger.info(f"Model {candidate_model} busy/quota ({err_str[:60]}); cascading to next fallback model...")
                        break
                    if use_search and ("503" not in err_str and "UNAVAILABLE" not in err_str):
                        continue
                    break
            if response and response.text:
                break

        if not response or not response.text:
            raise last_err or RuntimeError("Empty response from Gemini")

        return _parse_original_json_payload(response.text, requested_mode=mode, topic=topic)

    except Exception as e:
        logger.error(f"Error generating original {mode}: {e}")
        # If Gemini hit quota or 429, attempt seamless failover to DeepSeek if key is present
        is_quota = "429" in str(e) or "quota" in str(e).lower() or "RESOURCE_EXHAUSTED" in str(e)
        if is_quota and get_deepseek_client(custom_key=custom_key):
            try:
                logger.info("Gemini quota exhausted; attempting failover to DeepSeek...")
                return await _generate_original_with_deepseek(
                    mode=mode,
                    search_query=search_query,
                    persona_prompt=persona_prompt,
                    live_tweets=live_tweets,
                    model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                    custom_key=custom_key,
                    learning_memory=learning_memory
                )
            except Exception as ds_err:
                logger.error(f"DeepSeek failover error: {ds_err}")

        clean_err = format_ai_error(e)
        return {
            "success": False,
            "action_type": "post" if mode == "auto" else mode,
            "text": None,
            "variants_json": None,
            "urgency_score": 5,
            "topic_summary": clean_err,
            "error": clean_err,
            "error_code": 429 if is_quota else 500
        }


async def generate_smart_search_query(
    niche_topic: str,
    recent_tweets: Optional[List[Dict[str, Any]]] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None
) -> str:
    """
    Autonomous Trend & Search Query Discovery:
    Uses Google Search Grounding + the user's high-level niche description to invent a fresh,
    natural 2-to-4 word X search query on each scan cycle so the bot never camps on one stale keyword.
    """
    base_niche = (niche_topic or "AI agents, coding, and tech").strip()
    provider = get_active_provider(custom_key=custom_key)

    recent_context = ""
    if recent_tweets:
        samples = [
            (t.get("text") or t.get("tweet_text") or "")[:120]
            for t in recent_tweets[:5]
            if (t.get("text") or t.get("tweet_text"))
        ]
        if samples:
            recent_context = "Recent timeline snippets:\n- " + "\n- ".join(samples)

    prompt = f"""You are an expert X (Twitter) trend scout.
User's Niche / Interest Area: "{base_niche}"
{recent_context}

Invent ONE fresh, high-signal X search query (2 to 4 words max) that will surface active, genuine discussions right now in this niche.
Rules:
- Keep it simple (2 to 4 words) so X search returns plenty of live posts.
- Do NOT use complex boolean operators, quotes, or hashtags.
- Vary the angle from the literal niche string (e.g. specific tools, hot debates, builder problems, or breaking topics within "{base_niche}").
- Respond ONLY with JSON: {{"query": "your 2-4 word search query"}}"""

    if provider == "deepseek":
        ds_client = get_deepseek_client(custom_key=custom_key)
        if ds_client:
            try:
                resp = await asyncio.wait_for(
                    ds_client.chat.completions.create(
                        model=model_name or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                        messages=[
                            {"role": "system", "content": "You are a trend scout inventing concise 2-4 word X search queries in JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.88,
                        max_tokens=100
                    ),
                    timeout=8.0
                )
                raw = resp.choices[0].message.content or ""
                data = json.loads(_clean_json_markdown(raw))
                q = str(data.get("query", "")).strip().strip('"').strip("'")
                if 2 <= len(q) <= 48:
                    logger.info(f"DeepSeek Smart Query invented search query: '{q}' (from niche '{base_niche}')")
                    return q
            except Exception as e:
                logger.debug(f"DeepSeek smart query notice: {e}")

    client = get_gemini_client(custom_key=custom_key)
    if not client:
        return base_niche

    chosen_model = (model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")).replace("models/", "")
    try:
        from google.genai import types
        for candidate in list(dict.fromkeys([chosen_model, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.5-flash"])):
            try:
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=candidate,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.88,
                            max_output_tokens=150
                        )
                    ),
                    timeout=6.0
                )
                if resp and resp.text:
                    data = json.loads(_clean_json_markdown(resp.text))
                    q = str(data.get("query", "")).strip().strip('"').strip("'")
                    if 2 <= len(q) <= 48:
                        logger.info(f"Smart Query AI invented search query: '{q}' (from niche '{base_niche}')")
                        return q
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"Smart search query fallback to base niche: {e}")

    return base_niche


async def generate_strategy_brief(
    kpis: Dict[str, Any],
    top_authors: List[Dict[str, Any]],
    learning_memory: Dict[str, Any],
    niche: str,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    force_refresh: bool = False
) -> Dict[str, str]:
    """
    Generates an executive AI Strategy Brief for the Power BI Analytics tab.
    Cached for 10 minutes so dashboard loads remain instantaneous.
    """
    global _strategy_brief_cache
    now_ts = time.time()
    if not force_refresh and _strategy_brief_cache.get("data") and (now_ts - float(_strategy_brief_cache.get("timestamp", 0))) < 600:
        return _strategy_brief_cache["data"]

    fallback_brief = {
        "headline": f"Active Growth & Anti-Detection Telemetry on '{niche or 'Timeline'}'",
        "insight": f"Processed {kpis.get('total_evaluated', 0)} posts with {kpis.get('published_count', 0)} organic engagements published and {learning_memory.get('total_learned', 0)} learned voice samples.",
        "recommended_action": "Edit 1-2 queued drafts before approving to further sharpen few-shot voice cloning, and keep hourly velocity under 6/hr.",
        "suggested_query": niche or "AI agents coding"
    }

    provider = get_active_provider(custom_key=custom_key)
    top_handles = ", ".join([f"{a.get('author')} ({a.get('score', 0)} score)" for a in (top_authors or [])[:4]]) or "Building initial author sample"
    prompt = f"""You are an executive X (Twitter) Growth Strategist analyzing live telemetry for an autonomous browser agent.
Niche: {niche or 'General Tech & AI'}
KPIs: {json.dumps(kpis)}
Top Engaged Authors: {top_handles}
Learned Voice Examples Count: {learning_memory.get('total_learned', 0)}

Write a crisp, high-signal executive brief in JSON with these exact keys:
{{
  "headline": "6-12 word executive headline summarizing momentum",
  "insight": "1 sentence analyzing what is working best based on the KPIs and top authors",
  "recommended_action": "1 specific, actionable next step for the user to boost engagement safely",
  "suggested_query": "a fresh 2-4 word X search query to test next"
}}"""

    if provider == "deepseek":
        ds_client = get_deepseek_client(custom_key=custom_key)
        if ds_client:
            try:
                resp = await asyncio.wait_for(
                    ds_client.chat.completions.create(
                        model=model_name or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                        messages=[
                            {"role": "system", "content": "You are an executive growth strategist analyzing telemetry in JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.75,
                        max_tokens=300
                    ),
                    timeout=8.0
                )
                raw = resp.choices[0].message.content or ""
                parsed = json.loads(_clean_json_markdown(raw))
                brief = {
                    "headline": str(parsed.get("headline") or fallback_brief["headline"]).strip(),
                    "insight": str(parsed.get("insight") or fallback_brief["insight"]).strip(),
                    "recommended_action": str(parsed.get("recommended_action") or fallback_brief["recommended_action"]).strip(),
                    "suggested_query": str(parsed.get("suggested_query") or fallback_brief["suggested_query"]).strip(),
                }
                _strategy_brief_cache = {"timestamp": now_ts, "data": brief}
                return brief
            except Exception as e:
                logger.debug(f"DeepSeek strategy brief notice: {e}")

    client = get_gemini_client(custom_key=custom_key)
    if not client:
        return fallback_brief

    try:
        from google.genai import types
        chosen = (model_name or _last_working_gemini_model or "gemini-2.0-flash").replace("models/", "")
        candidates = list(dict.fromkeys([chosen, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.5-flash"]))

        async def _try_candidates() -> Optional[Dict[str, str]]:
            for cand in candidates:
                try:
                    resp = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=cand,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.75,
                                max_output_tokens=300
                            )
                        ),
                        timeout=3.5
                    )
                    if resp and resp.text:
                        parsed = json.loads(_clean_json_markdown(resp.text))
                        return {
                            "headline": str(parsed.get("headline") or fallback_brief["headline"]).strip(),
                            "insight": str(parsed.get("insight") or fallback_brief["insight"]).strip(),
                            "recommended_action": str(parsed.get("recommended_action") or fallback_brief["recommended_action"]).strip(),
                            "suggested_query": str(parsed.get("suggested_query") or fallback_brief["suggested_query"]).strip(),
                        }
                except Exception:
                    continue
            return None

        brief = await asyncio.wait_for(_try_candidates(), timeout=5.0)
        if brief:
            _strategy_brief_cache = {"timestamp": now_ts, "data": brief}
            return brief
    except Exception as e:
        logger.debug(f"Strategy brief fallback notice: {e}")

    _strategy_brief_cache = {"timestamp": now_ts, "data": fallback_brief}
    return fallback_brief
