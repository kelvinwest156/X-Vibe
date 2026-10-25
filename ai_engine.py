"""
AI Decision Engine powered by Google Gemini API (google-genai SDK).
Analyzes scraped X (Twitter) posts, decides relevance, and crafts witty, high-value replies.
Also provides fallback support for DeepSeek API if configured.
"""

import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("x_vibebot.ai")

def build_system_prompt(search_query: Optional[str] = None) -> str:
    """Builds a topic-aware system prompt based on the user's active search query."""
    topic_clause = (
        f"relevant to the topic/search query '{search_query}' (or tech, AI, sports, or culture related to it)"
        if search_query and search_query.strip()
        else "relevant to coding, AI, tech development, or the current timeline topic"
    )
    return f"""You are a sharp, witty, knowledgeable commentator on X (Twitter).
Analyze the provided post.
If it is {topic_clause} and worth engaging with, write a witty, value-adding, authentic reply between 1 to 2 sentences.
Do not use generic spam filler, fake hype, ticket-selling spam, or excessive emojis.
If the post is spam, a ticket scam, toxic, or pure promotion, reply with SKIP.

Respond in JSON format with three keys:
1. "action": either "reply" or "skip"
2. "text": your generated 1-2 sentence reply (or empty string if action is "skip")
3. "reasoning": brief 1-sentence explanation of your decision
"""


KNOWN_GEMINI_MODELS: List[Dict[str, str]] = [
    {
        "id": "gemini-3.8-flash",
        "name": "Gemini 3.8 Flash (Recommended)",
        "description": "Google's latest ultra-fast flagship Flash model. Ideal for sharp, witty 1–2 sentence X replies."
    },
    {
        "id": "gemini-3.8-pro",
        "name": "Gemini 3.8 Pro",
        "description": "Google's latest deep reasoning model for complex analysis and nuanced commentary."
    },
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "description": "Previous-gen Flash model (available to legacy projects)."
    },
    {
        "id": "gemini-2.0-flash",
        "name": "Gemini 2.0 Flash",
        "description": "High-frequency multimodal model engineered for low-latency generation."
    }
]

KNOWN_DEEPSEEK_MODELS: List[Dict[str, str]] = [
    {
        "id": "deepseek-chat",
        "name": "DeepSeek-V3 (deepseek-chat)",
        "description": "General conversational & coding model. Fast, cost-efficient."
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek-R1 (deepseek-reasoner)",
        "description": "Advanced reasoning and chain-of-thought model."
    }
]


def get_active_provider(custom_key: Optional[str] = None) -> str:
    """Determines whether to use Google Gemini or DeepSeek based on keys/config."""
    if custom_key:
        if custom_key.strip().startswith("sk-"):
            return "deepseek"
        return "gemini"

    # Default to Google Gemini as the primary engine
    provider = os.getenv("AI_PROVIDER", "gemini").lower()
    if provider == "deepseek":
        return "deepseek"
    return "gemini"


_last_working_gemini_model: Optional[str] = None


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
    """
    Tests the AI credentials against Google Gemini (or DeepSeek if key starts with sk-).
    Returns status, error details, and available models.
    """
    provider = get_active_provider(custom_key)

    if provider == "deepseek":
        return await _test_deepseek_api(custom_key)
    else:
        return await _test_gemini_api(custom_key)


async def _test_gemini_api(custom_key: Optional[str] = None) -> Dict[str, Any]:
    """Tests Google Gemini API credentials."""
    api_key = custom_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        return {
            "success": False,
            "provider": "gemini",
            "error": "API key is empty or not configured",
            "hint": "Please enter your free Google Gemini API key. Get one instantly at https://aistudio.google.com/app/apikey",
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
                if "gemini" in short_id.lower() and not any(x in short_id.lower() for x in ["embedding", "imagen", "veo", "aqa", "tts", "audio"]):
                    display = getattr(m, "display_name", short_id) or short_id
                    discovered_models.append({
                        "id": short_id,
                        "name": f"{display} ({short_id})" if short_id not in display else display,
                        "description": getattr(m, "description", "Google Gemini generative AI model.") or "Google Gemini generative AI model."
                    })
        except Exception as list_err:
            logger.debug(f"Model list fallback notice: {list_err}")

        if not discovered_models:
            # Probe candidate models in order
            for candidate in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]:
                try:
                    await client.aio.models.generate_content(
                        model=candidate,
                        contents="ping",
                        config=types.GenerateContentConfig(max_output_tokens=2, temperature=0.0)
                    )
                    break
                except Exception as probe_err:
                    if "404" in str(probe_err) or "NOT_FOUND" in str(probe_err):
                        continue
                    raise probe_err

        # Sort discovered models so 3.8-flash or latest flash is at top
        if discovered_models:
            discovered_models.sort(
                key=lambda x: (
                    0 if x["id"] == "gemini-3.8-flash" else
                    (1 if "3.8" in x["id"] and "flash" in x["id"] else
                    (2 if "flash" in x["id"] else 3))
                )
            )

        models_to_return = discovered_models if discovered_models else KNOWN_GEMINI_MODELS
        return {
            "success": True,
            "provider": "gemini",
            "error": None,
            "hint": f"API key verified & saved! Connected to Google Gemini ({models_to_return[0]['id']}).",
            "models": models_to_return
        }
    except Exception as e:
        err_msg = str(e)
        logger.warning(f"Google Gemini test key error: {err_msg}")
        hint = "Failed to authenticate with Google Gemini. Ensure you copied your API key from https://aistudio.google.com/app/apikey."
        if "API key not valid" in err_msg or "INVALID_ARGUMENT" in err_msg or "400" in err_msg:
            hint = "Google Gemini rejected this key (API key not valid). Please check your key at https://aistudio.google.com/app/apikey."
        elif "quota" in err_msg.lower() or "429" in err_msg:
            hint = "Google Gemini rate limit or quota exceeded. Free tier allows up to 15 requests/minute."

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
            "hint": "Please enter your DeepSeek API key.",
            "models": KNOWN_DEEPSEEK_MODELS
        }
    try:
        model_list_resp = await client.models.list()
        return {
            "success": True,
            "provider": "deepseek",
            "error": None,
            "hint": "Connected to DeepSeek server.",
            "models": KNOWN_DEEPSEEK_MODELS
        }
    except Exception as e:
        return {
            "success": False,
            "provider": "deepseek",
            "error": str(e),
            "hint": f"DeepSeek authentication failed: {str(e)}",
            "models": KNOWN_DEEPSEEK_MODELS
        }


async def evaluate_tweet(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates a scraped tweet using Google Gemini (or DeepSeek as fallback).
    """
    provider = get_active_provider(custom_key)

    if provider == "gemini":
        return await _evaluate_with_gemini(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            custom_key=custom_key,
            search_query=search_query
        )
    else:
        return await _evaluate_with_deepseek(
            tweet_text=tweet_text,
            tweet_author=tweet_author,
            model_name=model_name or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            custom_key=custom_key,
            search_query=search_query
        )


async def _evaluate_with_gemini(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: str = "gemini-3.8-flash",
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None
) -> Dict[str, Any]:
    """Generates evaluation and reply using Google Gemini."""
    client = get_gemini_client(custom_key=custom_key)
    if not client:
        logger.warning("GEMINI_API_KEY not configured. Skipping AI evaluation.")
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": "Google Gemini API key is not configured in .env or dashboard (Get free key: https://aistudio.google.com/app/apikey)",
            "raw_response": "NO_API_KEY"
        }

    chosen_model = model_name or "gemini-3.8-flash"
    clean_model = chosen_model.replace("models/", "")
    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"

    try:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(search_query),
            response_mime_type="application/json",
            temperature=0.7,
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
        # Deduplicate while preserving order
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
                logger.info(f"Model {candidate_model} timed out (>10s due to high demand); falling back to next Gemini model...")
                continue
            except Exception as try_err:
                last_err = try_err
                err_str = str(try_err)
                if any(code in err_str for code in ["404", "NOT_FOUND", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"]):
                    logger.info(f"Model {candidate_model} busy/unavailable ({err_str[:80]}); falling back to next Gemini model...")
                    continue
                raise try_err

        if response is None and last_err is not None:
            raise last_err

        raw_output = response.text or ""
        logger.info(f"Google Gemini ({clean_model}) response: {raw_output}")

        cleaned = _clean_json_markdown(raw_output)
        data = json.loads(cleaned)

        action = str(data.get("action", "")).strip().lower()
        reply_text = str(data.get("text", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()

        if action == "reply" and reply_text and "skip" not in reply_text.lower():
            return {
                "should_reply": True,
                "reply_text": reply_text,
                "reasoning": reasoning or "Relevant tech/AI topic",
                "raw_response": raw_output
            }
        else:
            return {
                "should_reply": False,
                "reply_text": None,
                "reasoning": reasoning or "Not relevant or skipped by AI",
                "raw_response": raw_output
            }

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error calling Google Gemini API ({clean_model}): {err_msg}")
        user_friendly_reason = f"Google Gemini Error: {err_msg}"
        if "API key not valid" in err_msg or "INVALID_ARGUMENT" in err_msg:
            user_friendly_reason = "Google Gemini API key invalid. Please verify your key at https://aistudio.google.com/app/apikey"
        elif "quota" in err_msg.lower() or "429" in err_msg:
            user_friendly_reason = "Google Gemini free quota limit reached. Pausing until quota resets."

        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": user_friendly_reason,
            "raw_response": f"ERROR: {err_msg}"
        }


async def _evaluate_with_deepseek(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: str = "deepseek-chat",
    custom_key: Optional[str] = None,
    search_query: Optional[str] = None
) -> Dict[str, Any]:
    """Fallback evaluation with DeepSeek API."""
    client = get_deepseek_client(custom_key=custom_key)
    if not client:
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": "DeepSeek API key is not configured in .env",
            "raw_response": "NO_API_KEY"
        }

    chosen_model = model_name or "deepseek-chat"
    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"

    try:
        kwargs = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": build_system_prompt(search_query)},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 300
        }
        if "reasoner" not in chosen_model.lower():
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["temperature"] = 0.7

        response = await client.chat.completions.create(**kwargs)
        raw_output = response.choices[0].message.content or ""
        logger.info(f"DeepSeek ({chosen_model}) response: {raw_output}")

        cleaned = _clean_json_markdown(raw_output)
        data = json.loads(cleaned)

        action = str(data.get("action", "")).strip().lower()
        reply_text = str(data.get("text", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()

        if action == "reply" and reply_text and "skip" not in reply_text.lower():
            return {
                "should_reply": True,
                "reply_text": reply_text,
                "reasoning": reasoning or "Relevant tech/AI topic",
                "raw_response": raw_output
            }
        else:
            return {
                "should_reply": False,
                "reply_text": None,
                "reasoning": reasoning or "Not relevant or skipped by AI",
                "raw_response": raw_output
            }
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Error calling DeepSeek API ({chosen_model}): {err_msg}")
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": f"DeepSeek API Error: {err_msg}",
            "raw_response": f"ERROR: {err_msg}"
        }


def _clean_json_markdown(raw: str) -> str:
    """Strips markdown code fences from JSON output."""
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()
