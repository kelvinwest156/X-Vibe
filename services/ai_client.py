"""
AI Client and API Management Service for X-VibeBot.
Handles Google Gemini and DeepSeek client instantiation, model discovery,
credential health checks, and payload sanitization.
"""

import os
import re
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("x_vibebot.services.ai_client")

# Cache for the last known responsive Gemini model to avoid re-probing on every cycle
_last_working_gemini_model: Optional[str] = None


KNOWN_GEMINI_MODELS: List[Dict[str, str]] = [
    {
        "id": "gemini-2.0-flash",
        "name": "Gemini 2.0 Flash (Recommended - 1,500 req/day)",
        "description": "Google's high-speed production model with generous 1,500 requests/day quota."
    },
    {
        "id": "gemini-1.5-flash",
        "name": "Gemini 1.5 Flash (Production Standard - 1,500 req/day)",
        "description": "Battle-tested, reliable Flash model with 1,500 requests/day headroom."
    },
    {
        "id": "gemini-1.5-flash-8b",
        "name": "Gemini 1.5 Flash 8B (High Speed & Quota)",
        "description": "Ultra-lightweight, lowest-latency model for rapid evaluations."
    },
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "description": "Next-generation Flash model preview."
    },
    {
        "id": "gemini-3.8-flash",
        "name": "Gemini 3.8 Flash (Experimental - 20 req/day limit)",
        "description": "Preview model with strict 20 requests/day limit on Free Tier."
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
    if not api_key:
        try:
            from database import SessionLocal, AgentConfig
            db = SessionLocal()
            try:
                cfg = db.query(AgentConfig).filter(AgentConfig.api_key.isnot(None)).first()
                if cfg and cfg.api_key and not cfg.api_key.startswith("sk-"):
                    api_key = cfg.api_key
            finally:
                db.close()
        except Exception:
            pass

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
    if not api_key:
        try:
            from database import SessionLocal, AgentConfig
            db = SessionLocal()
            try:
                cfg = db.query(AgentConfig).filter(AgentConfig.api_key.isnot(None)).first()
                if cfg and cfg.api_key and cfg.api_key.startswith("sk-"):
                    api_key = cfg.api_key
            finally:
                db.close()
        except Exception:
            pass

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


def format_ai_error(err: Any) -> str:
    """Translates raw AI provider error objects into clean, helpful, human-readable explanations."""
    err_str = str(err)
    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
        m_delay = re.search(r"retry in ([\d\w\.]+)", err_str, re.IGNORECASE)
        delay_info = f" (resets in {m_delay.group(1)})" if m_delay else ""
        return (
            f"Gemini API rate limit or model quota reached{delay_info}. "
            f"Bot will automatically fail over to Gemini 2.0/1.5 Flash (1,500 req/day quota) or DeepSeek."
        )
    if "400" in err_str or "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
        return "Invalid Gemini API key. Please check or replace your key in Settings."
    if "403" in err_str or "PERMISSION_DENIED" in err_str:
        return "Gemini API permission denied. Ensure Generative Language API is enabled on your Google Cloud project."
    if "503" in err_str or "UNAVAILABLE" in err_str:
        return "Google Gemini models are temporarily busy. Retrying automatically in a moment..."
    if "Timeout" in err_str or "timed out" in err_str.lower():
        return "AI model response timed out. Please try again or switch model in Settings."
    clean = re.sub(r"\{.*?\}", "", err_str).replace("\n", " ").strip()
    return clean[:180] if clean else err_str[:180]


async def _fetch_image_bytes(media_url: Optional[str]) -> Optional[Tuple[bytes, str]]:
    """Downloads tweet image bytes for Gemini Multimodal Vision analysis."""
    if not media_url or not media_url.startswith("http"):
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=4.5, follow_redirects=True) as http_client:
            resp = await http_client.get(media_url)
            if resp.status_code == 200 and resp.content and len(resp.content) < 6_000_000:
                ctype = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    ctype = "image/jpeg"
                return resp.content, ctype
    except Exception as e:
        logger.debug(f"Could not fetch media_url for vision analysis: {e}")
    return None


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
            for candidate in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.5-flash", "gemini-3.8-flash"]:
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
                    0 if x["id"] == "gemini-2.0-flash" else
                    (1 if x["id"] == "gemini-1.5-flash" else
                    (2 if x["id"] == "gemini-1.5-flash-8b" else
                    (3 if x["id"] == "gemini-2.5-flash" else
                    (4 if "flash" in x["id"] else 5))))
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
