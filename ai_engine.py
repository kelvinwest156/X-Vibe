"""
AI Decision Engine powered by Google Gemini API (google-genai SDK).
Analyzes scraped X (Twitter) posts, filters out low-value/spam posts, and crafts
authentic, human-sounding replies in 3 quick vibe variants (Witty, Question, Punchy).
"""

import os
import re
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("x_vibebot.ai")

_last_working_gemini_model: Optional[str] = None


def _sanitize_ai_tells(text: str) -> str:
    """Removes dead-giveaway AI punctuation like em-dashes and double-hyphens."""
    if not text:
        return ""
    cleaned = text.strip()
    # Replace em-dashes and en-dashes with a natural comma or space-hyphen
    cleaned = re.sub(r"\s*[—–]\s*", ", ", cleaned)
    cleaned = re.sub(r"\s*--\s*", " - ", cleaned)
    # Strip wrapping quotes if AI wrapped the reply in quotes
    if len(cleaned) >= 2 and cleaned[0] in ('"', "'") and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def build_system_prompt(
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None
) -> str:
    """Builds a topic-aware, anti-robotic system prompt with custom persona."""
    topic_clause = (
        f"relevant to '{search_query}' (or the surrounding conversation/culture)"
        if search_query and search_query.strip()
        else "relevant to tech, coding, AI, or the timeline topic"
    )
    voice_clause = (
        persona_prompt.strip()
        if persona_prompt and persona_prompt.strip()
        else "Casual, sharp, dry humor, short sentences, zero corporate buzzwords"
    )

    return f"""You are a real human X (Twitter) user writing authentic replies.
Your voice/persona: {voice_clause}

Analyze the provided post (and any quoted text or media description).
1. SKIP if the post is spam, ticket-selling scams, betting/crypto promos, engagement bait, or completely unrelated to {topic_clause}.
2. REPLY if it is a genuine opinion, take, question, update, or funny moment {topic_clause}.

STRICT ANTI-ROBOTIC RULES (CRITICAL):
- NEVER use em-dashes (—), en-dashes (–), or semicolons (;). Real people on X don't type those.
- NEVER start with "Ah,", "Honestly,", "To be fair,", "Indeed,", or end with "Let's see if..." or "Only time will tell."
- NEVER use AI buzzwords: delve, testament, game-changer, landscape, fascinating, undeniable, masterclass, Chef's kiss.
- Do NOT summarize or repeat the author's tweet back to them. Jump straight into your reaction or angle.
- Keep it concise: 6 to 22 words max. Sound like a smart insider texting a friend.

Respond in valid JSON with these exact keys:
{{
  "action": "reply" or "skip",
  "text": "your best primary reply (6-22 words)",
  "variants": {{
    "witty": "sharp, clever observation or dry humor (6-20 words)",
    "question": "curious, specific follow-up question that makes the author want to reply back (6-18 words)",
    "punchy": "ultra-short, casual 4-12 word one-liner (natural X style)"
  }},
  "reasoning": "brief 1-sentence reason for replying or skipping"
}}
If action is "skip", set "text" to "" and "variants" to {{}}.
"""


KNOWN_GEMINI_MODELS: List[Dict[str, str]] = [
    {
        "id": "gemini-3.8-flash",
        "name": "Gemini 3.8 Flash (Recommended)",
        "description": "Google's latest ultra-fast flagship Flash model."
    },
    {
        "id": "gemini-3.7-flash",
        "name": "Gemini 3.7 Flash",
        "description": "High-speed Flash model with reliable low-latency availability."
    },
    {
        "id": "gemini-3.6-flash",
        "name": "Gemini 3.6 Flash",
        "description": "Fast, balanced model for natural conversational replies."
    },
    {
        "id": "gemini-3.5-flash",
        "name": "Gemini 3.5 Flash",
        "description": "Lightweight Flash model with generous quota headroom."
    },
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "description": "Previous-gen Flash model."
    }
]

KNOWN_DEEPSEEK_MODELS: List[Dict[str, str]] = [
    {
        "id": "deepseek-chat",
        "name": "DeepSeek-V3 (deepseek-chat)",
        "description": "General conversational & coding model."
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek-R1 (deepseek-reasoner)",
        "description": "Advanced reasoning model."
    }
]


def get_active_provider(custom_key: Optional[str] = None) -> str:
    """Determines whether to use Google Gemini or DeepSeek based on keys/config."""
    if custom_key:
        if custom_key.strip().startswith("sk-"):
            return "deepseek"
        return "gemini"

    provider = os.getenv("AI_PROVIDER", "gemini").lower()
    if provider == "deepseek":
        return "deepseek"
    return "gemini"


def get_gemini_client(custom_key: Optional[str] = None):
    """Returns a Google GenAI Client or None if unconfigured."""
    api_key = custom_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        return None
    try:
        from google import genai
        from google.genai import types
        return genai.Client(
            api_key=api_key.strip(),
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            )
        )
    except Exception:
        try:
            from google import genai
            return genai.Client(api_key=api_key.strip())
        except Exception as e:
            logger.error(f"Failed to create Google GenAI client: {e}")
            return None


def get_deepseek_client(custom_key: Optional[str] = None):
    """Returns an AsyncOpenAI client configured for DeepSeek or None."""
    api_key = custom_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key or api_key == "your_deepseek_api_key_here":
        return None
    try:
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key=api_key.strip(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        )
    except Exception as e:
        logger.error(f"Failed to create DeepSeek client: {e}")
        return None


async def test_ai_api(custom_key: Optional[str] = None) -> Dict[str, Any]:
    """Tests the AI credentials against Google Gemini (or DeepSeek if key starts with sk-)."""
    provider = get_active_provider(custom_key)
    if provider == "deepseek":
        return await _test_deepseek_api(custom_key)
    return await _test_gemini_api(custom_key)


async def _test_gemini_api(custom_key: Optional[str] = None) -> Dict[str, Any]:
    """Tests Google Gemini API credentials and discovers available models."""
    api_key = custom_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        return {
            "success": False,
            "provider": "gemini",
            "error": "API key is empty or not configured",
            "hint": "Paste your free Google Gemini key from aistudio.google.com/app/apikey",
            "models": KNOWN_GEMINI_MODELS
        }

    client = get_gemini_client(custom_key=api_key)
    if not client:
        return {
            "success": False,
            "provider": "gemini",
            "error": "google-genai library not initialized",
            "hint": "Ensure 'google-genai' is installed.",
            "models": KNOWN_GEMINI_MODELS
        }

    try:
        from google.genai import types
        discovered_models: List[Dict[str, str]] = []
        try:
            pager = await client.aio.models.list()
            async for m in pager:
                m_name = getattr(m, "name", "") or ""
                short_id = m_name.replace("models/", "")
                if "gemini" in short_id.lower() and not any(
                    x in short_id.lower() for x in ["embedding", "imagen", "veo", "aqa", "tts", "audio", "image", "robotics", "computer-use", "translate", "transcribe", "live"]
                ):
                    display = getattr(m, "display_name", short_id) or short_id
                    discovered_models.append({
                        "id": short_id,
                        "name": f"{display} ({short_id})" if short_id not in display else display,
                        "description": getattr(m, "description", "Google Gemini model") or "Google Gemini model"
                    })
        except Exception as list_err:
            logger.debug(f"Model list fallback notice: {list_err}")

        if not discovered_models:
            for candidate in ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash"]:
                try:
                    await client.aio.models.generate_content(
                        model=candidate,
                        contents="ping",
                        config=types.GenerateContentConfig(max_output_tokens=5, temperature=0.0)
                    )
                    break
                except Exception as probe_err:
                    if "404" in str(probe_err) or "NOT_FOUND" in str(probe_err) or "503" in str(probe_err):
                        continue
                    raise probe_err

        if discovered_models:
            discovered_models.sort(
                key=lambda x: (
                    0 if x["id"] == "gemini-3.8-flash" else
                    (1 if x["id"] == "gemini-3.7-flash" else
                    (2 if x["id"] == "gemini-3.6-flash" else
                    (3 if "flash" in x["id"] else 4)))
                )
            )

        models_to_return = discovered_models if discovered_models else KNOWN_GEMINI_MODELS
        return {
            "success": True,
            "provider": "gemini",
            "error": None,
            "hint": f"Connected ({models_to_return[0]['id']})",
            "models": models_to_return
        }
    except Exception as e:
        err_msg = str(e)
        logger.warning(f"Google Gemini test key error: {err_msg}")
        hint = "Invalid API key. Check your key at aistudio.google.com/app/apikey"
        if "quota" in err_msg.lower() or "429" in err_msg:
            hint = "Rate limit reached. Wait a moment and try again."
        return {
            "success": False,
            "provider": "gemini",
            "error": err_msg,
            "hint": hint,
            "models": KNOWN_GEMINI_MODELS
        }


async def _test_deepseek_api(custom_key: Optional[str] = None) -> Dict[str, Any]:
    """Tests DeepSeek API credentials."""
    client = get_deepseek_client(custom_key)
    if not client:
        return {
            "success": False,
            "provider": "deepseek",
            "error": "DeepSeek API key is not configured",
            "hint": "Enter your DeepSeek API key.",
            "models": KNOWN_DEEPSEEK_MODELS
        }
    try:
        await client.models.list()
        return {
            "success": True,
            "provider": "deepseek",
            "error": None,
            "hint": "Connected to DeepSeek",
            "models": KNOWN_DEEPSEEK_MODELS
        }
    except Exception as e:
        return {
            "success": False,
            "provider": "deepseek",
            "error": str(e),
            "hint": f"DeepSeek auth failed: {str(e)}",
            "models": KNOWN_DEEPSEEK_MODELS
        }


async def evaluate_tweet(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    extra_context: Optional[str] = None,
    temperature: float = 0.75
) -> Dict[str, Any]:
    """
    Evaluates a scraped tweet using Google Gemini (or DeepSeek fallback).
    Returns should_reply, reply_text, variants (witty/question/punchy), and reasoning.
    """
    provider = get_active_provider(custom_key)

    if provider == "gemini":
        return await _evaluate_with_gemini(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            custom_key=custom_key,
            search_query=search_query,
            persona_prompt=persona_prompt,
            extra_context=extra_context,
            temperature=temperature
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
            temperature=temperature
        )


def _parse_ai_json_payload(raw_output: str) -> Dict[str, Any]:
    """Parses the JSON response and sanitizes all reply variants against AI tells."""
    cleaned = _clean_json_markdown(raw_output)
    data = json.loads(cleaned)

    action = str(data.get("action", "")).strip().lower()
    raw_variants = data.get("variants") if isinstance(data.get("variants"), dict) else {}

    witty = _sanitize_ai_tells(str(raw_variants.get("witty", "") or ""))
    question = _sanitize_ai_tells(str(raw_variants.get("question", "") or ""))
    punchy = _sanitize_ai_tells(str(raw_variants.get("punchy", "") or ""))

    primary = _sanitize_ai_tells(str(data.get("text", "") or "")) or witty or punchy or question
    reasoning = str(data.get("reasoning", "")).strip()

    variants = {}
    if witty:
        variants["witty"] = witty
    if question:
        variants["question"] = question
    if punchy:
        variants["punchy"] = punchy
    if primary and not variants:
        variants["witty"] = primary

    if action == "reply" and primary and "skip" not in primary.lower():
        return {
            "should_reply": True,
            "reply_text": primary,
            "variants": variants,
            "variants_json": json.dumps(variants, ensure_ascii=False),
            "reasoning": reasoning or "Relevant post",
            "raw_response": raw_output
        }
    return {
        "should_reply": False,
        "reply_text": None,
        "variants": {},
        "variants_json": None,
        "reasoning": reasoning or "Skipped by AI filter",
        "raw_response": raw_output
    }


async def _evaluate_with_gemini(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: str = "gemini-3.8-flash",
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    extra_context: Optional[str] = None,
    temperature: float = 0.75
) -> Dict[str, Any]:
    """Generates evaluation and 3 human-styled reply variants using Google Gemini."""
    client = get_gemini_client(custom_key=custom_key)
    if not client:
        logger.warning("GEMINI_API_KEY not configured. Skipping AI evaluation.")
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "reasoning": "Google Gemini API key is not configured",
            "raw_response": "NO_API_KEY"
        }

    chosen_model = model_name or "gemini-3.8-flash"
    clean_model = chosen_model.replace("models/", "")
    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"
    if extra_context:
        user_content += f"\nContext / Quoted / Media Info: {extra_context}"

    try:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(search_query, persona_prompt),
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
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite"
        ])
        models_to_try = list(dict.fromkeys(fallback_candidates))

        response = None
        last_err = None
        for candidate_model in models_to_try:
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=candidate_model,
                        contents=user_content,
                        config=config
                    ),
                    timeout=8.0
                )
                clean_model = candidate_model
                _last_working_gemini_model = candidate_model
                break
            except asyncio.TimeoutError as te:
                last_err = te
                logger.info(f"Model {candidate_model} timed out (>8s); failing over to next model...")
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

        raw_output = response.text or ""
        logger.info(f"Gemini ({clean_model}) evaluated @{tweet_author}")
        return _parse_ai_json_payload(raw_output)

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error calling Google Gemini API ({clean_model}): {err_msg}")
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
            "reasoning": f"Google Gemini Error: {err_msg[:120]}",
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
    temperature: float = 0.75
) -> Dict[str, Any]:
    """Fallback evaluation with DeepSeek API."""
    client = get_deepseek_client(custom_key=custom_key)
    if not client:
        return {
            "should_reply": False,
            "reply_text": None,
            "variants": {},
            "variants_json": None,
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
                {"role": "system", "content": build_system_prompt(search_query, persona_prompt)},
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
            "reasoning": f"DeepSeek API Error: {err_msg[:120]}",
            "raw_response": f"ERROR: {err_msg}"
        }


def _clean_json_markdown(raw: str) -> str:
    """Strips markdown code fences from JSON output."""
    cleaned = raw.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1]
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1]
    if "```" in cleaned:
        cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return cleaned.strip()


async def generate_original_content(
    mode: str = "post",
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    live_tweets: Optional[List[Dict[str, Any]]] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates an original standalone X post (mode='post') or a multi-post thread (mode='thread')
    synthesized from real-time X conversations and live Google Search grounding.
    """
    client = get_gemini_client(custom_key=custom_key)
    if not client:
        return {
            "success": False,
            "action_type": mode,
            "text": None,
            "variants_json": None,
            "topic_summary": "Google Gemini API key not configured"
        }

    topic = (search_query or "tech, AI, and culture").strip()
    voice = (persona_prompt or "Casual, sharp, dry humor, short sentences, zero corporate buzzwords").strip()

    # Format real-time scraped X conversations
    live_feed_context = ""
    if live_tweets:
        snippets = []
        for idx, t in enumerate(live_tweets[:8], 1):
            author = t.get("author") or t.get("tweet_author") or "user"
            txt = (t.get("text") or t.get("tweet_text") or "").replace("\n", " ").strip()
            metrics = t.get("metrics") or t.get("tweet_metrics") or ""
            if txt:
                snippets.append(f"{idx}. @{author} ({metrics}): {txt[:200]}")
        if snippets:
            live_feed_context = "LIVE CONVERSATIONS HAPPENING RIGHT NOW ON X:\n" + "\n".join(snippets)

    if mode == "thread":
        format_instructions = """Create an original, high-signal 3 to 4 post X THREAD based on the real-time conversation and current facts around this topic.
STRICT THREAD RULES:
- Separate each post in the thread with exactly "\\n---\\n".
- Each individual post MUST be under 240 characters (1-2 punchy sentences per post).
- Post 1 must be a strong, natural hook (NO "🧵", NO "1/4", NO "Let's dive in", NO "A thread:").
- Posts 2-4 should drop specific insights, real-time observations, or sharp takes that build on the hook.
- NEVER use em-dashes (—), semicolons, or AI buzzwords.

Respond ONLY in valid JSON with these exact keys:
{
  "topic_summary": "1-line summary of the real-time conversation angle this thread covers",
  "text": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
  "variants": {
    "witty": "Post 1 (witty/sharp angle)\\n---\\nPost 2\\n---\\nPost 3",
    "insight": "Post 1 (deep/analytical angle)\\n---\\nPost 2\\n---\\nPost 3",
    "punchy": "Post 1 (short/bold hot take)\\n---\\nPost 2\\n---\\nPost 3"
  }
}"""
    else:
        format_instructions = """Create an original, standalone X POST based on the real-time conversation and current facts around this topic.
STRICT POST RULES:
- 8 to 30 words max. Under 240 characters.
- Sound like an authentic human insider sharing a sharp observation, hot take, or timely reaction.
- NEVER use hashtags unless essential to the topic. NEVER use em-dashes (—), semicolons, or AI buzzwords.

Respond ONLY in valid JSON with these exact keys:
{
  "topic_summary": "1-line summary of the real-time conversation or event this post reacts to",
  "text": "your primary standalone post",
  "variants": {
    "witty": "sharp, clever observation or dry humor",
    "question": "provoking question that sparks replies on the timeline",
    "punchy": "ultra-short 5-14 word bold one-liner"
  }
}"""

    prompt = f"""Topic / Search Pulse: {topic}
Your Voice / Persona: {voice}
Current Date: {os.popen('date /t').read().strip() if os.name == 'nt' else 'Today'}

{live_feed_context}

{format_instructions}"""

    chosen_model = (model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")).replace("models/", "")

    try:
        from google.genai import types
        global _last_working_gemini_model

        fallback_candidates = []
        if _last_working_gemini_model:
            fallback_candidates.append(_last_working_gemini_model)
        fallback_candidates.extend([
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.7-flash",
            chosen_model,
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
                        timeout=8.0
                    )
                    if response and response.text and "{" in response.text:
                        _last_working_gemini_model = candidate_model
                        break
                    response = None
                except Exception as e:
                    last_err = e
                    response = None
                    if use_search and ("503" not in str(e) and "UNAVAILABLE" not in str(e)):
                        continue
                    break
            if response and response.text:
                break

        if not response or not response.text:
            raise last_err or RuntimeError("Empty response from Gemini")

        cleaned = _clean_json_markdown(response.text)
        data = json.loads(cleaned)

        def clean_item(val: str) -> str:
            if mode == "thread":
                parts = [_sanitize_ai_tells(p.strip()) for p in val.split("---") if p.strip()]
                return "\n---\n".join(parts)
            return _sanitize_ai_tells(val)

        raw_variants = data.get("variants") if isinstance(data.get("variants"), dict) else {}
        variants = {}
        for k, v in raw_variants.items():
            if v and str(v).strip():
                variants[k] = clean_item(str(v))

        primary = clean_item(str(data.get("text", "") or ""))
        if not primary and variants:
            primary = next(iter(variants.values()))
        if primary and not variants:
            variants["witty"] = primary

        topic_summary = str(data.get("topic_summary", f"Live pulse on {topic}")).strip()

        return {
            "success": True,
            "action_type": mode,
            "text": primary,
            "variants": variants,
            "variants_json": json.dumps(variants, ensure_ascii=False),
            "topic_summary": topic_summary
        }

    except Exception as e:
        logger.error(f"Error generating original {mode}: {e}")
        return {
            "success": False,
            "action_type": mode,
            "text": None,
            "variants_json": None,
            "topic_summary": f"Error: {str(e)[:100]}"
        }

