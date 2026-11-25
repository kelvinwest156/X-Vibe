"""
AI Client and API Management Service for X-VibeBot.
Handles Google Gemini and DeepSeek client instantiation, model discovery,
credential health checks, token accounting, and payload sanitization.
"""

import os
import re
import time
import asyncio
import hashlib
import logging
import threading
from collections import OrderedDict
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("x_vibebot.services.ai_client")


def _scrub(text: Any) -> str:
    """Lazily delegates to core.security.scrub_secrets to avoid circular imports with core.__init__."""
    from core.security import scrub_secrets as _sec_scrub
    return _sec_scrub(text)

# Cache for the last known responsive Gemini model to avoid re-probing on every cycle
_last_working_gemini_model: Optional[str] = None

# Bounded LRU cache for HTTP/SDK clients keyed by (provider, key_hash)
_MAX_CLIENT_CACHE = 32
_client_cache: "OrderedDict[Tuple[str, str], Any]" = OrderedDict()
_client_cache_lock = threading.Lock()

# Conservative DB failure grace state for check_tenant_token_budget
_BUDGET_GRACE_LIMIT = 2
_BUDGET_GRACE_WINDOW_SECONDS = 300.0
_BUDGET_GRACE_CAP = 15000
_budget_db_failures: "OrderedDict[str, Tuple[int, float]]" = OrderedDict()
_budget_db_lock = threading.Lock()

_MAX_IMAGE_BYTES = 6_000_000
_ALLOWED_IMAGE_MIME_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
})

_PLACEHOLDER_KEYS = frozenset({
    "your_gemini_api_key_here",
    "your_deepseek_api_key_here",
})


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
]

_VALID_GEMINI_MODELS = frozenset({m["id"] for m in KNOWN_GEMINI_MODELS} | {"gemini-1.5-pro"})
_VALID_DEEPSEEK_MODELS = frozenset({"deepseek-chat", "deepseek-reasoner"})

KNOWN_DEEPSEEK_MODELS: List[Dict[str, str]] = [
    {
        "id": "deepseek-chat",
        "name": "DeepSeek-V3 (deepseek-chat - Recommended)",
        "description": "High-speed flagship conversational model for authentic X replies & threads."
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek-R1 (deepseek-reasoner)",
        "description": "Advanced reasoning model for deep strategic analysis."
    }
]


def _resolve_tenant_db_key(tenant_id: Optional[str]) -> Optional[str]:
    """
    Resolves and decrypts a tenant's BYOK API key strictly for the supplied `tenant_id`.
    Returns None when `tenant_id` is omitted or no key is stored — never reads across tenants.
    """
    clean_tid = (tenant_id or "").strip()
    if not clean_tid:
        return None
    try:
        from database import SessionLocal, get_decrypted_api_key
        from models import AgentConfig

        db = SessionLocal()
        try:
            cfg = db.query(AgentConfig).filter(AgentConfig.tenant_id == clean_tid).first()
            if cfg:
                dec = get_decrypted_api_key(cfg)
                if dec and dec not in _PLACEHOLDER_KEYS:
                    return dec
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"Tenant DB key lookup notice for '{clean_tid}': {_scrub(e)}")
    return None


def _resolve_api_key(
    provider: str,
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Optional[str]:
    """
    Resolves an API key for `provider` ('gemini' | 'deepseek') without mutating os.environ.
    Priority: custom_key (matching provider) -> tenant DB BYOK key (when tenant_id given) -> env var.
    """
    prov = (provider or "deepseek").strip().lower()
    ck = custom_key.strip() if isinstance(custom_key, str) else ""

    if ck:
        if ck in _PLACEHOLDER_KEYS:
            return None
        if prov == "gemini" and ck.startswith("sk-"):
            return None
        if prov == "deepseek" and ck.startswith("AIza"):
            return None
        return ck

    if tenant_id:
        tkey = _resolve_tenant_db_key(tenant_id)
        if tkey:
            if prov == "gemini" and not tkey.startswith("sk-"):
                return tkey
            if prov == "deepseek" and tkey.startswith("sk-"):
                return tkey

    if prov == "gemini":
        env_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    else:
        env_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()

    if not env_key or env_key in _PLACEHOLDER_KEYS:
        return None
    return env_key


def _close_client_best_effort(provider: str, client: Any) -> None:
    """Schedules or performs best-effort cleanup of an evicted sync/async SDK client."""
    if client is None:
        return
    try:
        if provider == "deepseek":
            if hasattr(client, "close"):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(client.close())
                except RuntimeError:
                    pass
        elif provider == "gemini":
            aio = getattr(client, "aio", None)
            if aio and hasattr(aio, "aclose"):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(aio.aclose())
                except RuntimeError:
                    pass
            if hasattr(client, "close"):
                client.close()
    except Exception:
        pass


async def close_ai_clients() -> None:
    """Cleanly closes all cached HTTP/SDK clients on application shutdown."""
    with _client_cache_lock:
        entries = list(_client_cache.items())
        _client_cache.clear()

    for (provider, _), client in entries:
        try:
            if provider == "deepseek":
                if hasattr(client, "close"):
                    res = client.close()
                    if asyncio.iscoroutine(res):
                        await res
            elif provider == "gemini":
                aio = getattr(client, "aio", None)
                if aio and hasattr(aio, "aclose"):
                    await aio.aclose()
                if hasattr(client, "close"):
                    client.close()
        except Exception as e:
            logger.debug(f"Client shutdown cleanup notice ({provider}): {_scrub(e)}")


def sanitize_model_for_provider(provider: str, model_name: Optional[str] = None) -> str:
    """
    Ensures the model name sent to an AI provider is always valid for that specific provider.
    Eliminates 400 Bad Request errors when switching providers or running autonomous mode.
    """
    if provider == "deepseek":
        if model_name:
            clean = model_name.strip().lower()
            if clean in _VALID_DEEPSEEK_MODELS:
                return clean
        env_ds = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip().lower()
        return env_ds if env_ds in _VALID_DEEPSEEK_MODELS else "deepseek-chat"
    elif provider == "gemini":
        if model_name:
            clean = model_name.strip().lower().removeprefix("models/")
            if clean in _VALID_GEMINI_MODELS:
                return clean
        env_gem = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip().lower().removeprefix("models/")
        return env_gem if env_gem in _VALID_GEMINI_MODELS else "gemini-2.0-flash"
    return model_name or "deepseek-chat"


def get_active_provider(
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """Determines whether to use DeepSeek or Google Gemini based on keys/config."""
    if custom_key and isinstance(custom_key, str) and custom_key.strip():
        if custom_key.strip().startswith("AIza"):
            return "gemini"
        return "deepseek"

    if tenant_id:
        tkey = _resolve_tenant_db_key(tenant_id)
        if tkey:
            return "gemini" if not tkey.startswith("sk-") else "deepseek"

    provider = (os.getenv("AI_PROVIDER") or "deepseek").strip().lower()
    if provider == "gemini":
        return "gemini"
    return "deepseek"


def get_best_available_model(
    task_type: str = "general",
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Intelligently determines the best provider and model for the task at execution time.
    Priority honors custom_key / tenant BYOK key / AI_PROVIDER preference, then falls back cleanly.
    """
    provider = get_active_provider(custom_key=custom_key, tenant_id=tenant_id)
    if provider == "deepseek":
        ds_client = get_deepseek_client(custom_key=custom_key, tenant_id=tenant_id)
        if ds_client:
            return "deepseek", sanitize_model_for_provider("deepseek")
        gemini_client = get_gemini_client(custom_key=custom_key, tenant_id=tenant_id)
        if gemini_client:
            return "gemini", sanitize_model_for_provider("gemini")
    else:
        gemini_client = get_gemini_client(custom_key=custom_key, tenant_id=tenant_id)
        if gemini_client:
            return "gemini", sanitize_model_for_provider("gemini")
        ds_client = get_deepseek_client(custom_key=custom_key, tenant_id=tenant_id)
        if ds_client:
            return "deepseek", sanitize_model_for_provider("deepseek")

    return "deepseek", "deepseek-chat"


def get_gemini_client(
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Returns a cached Google GenAI Client or None if unconfigured."""
    api_key = _resolve_api_key("gemini", custom_key=custom_key, tenant_id=tenant_id)
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    cache_key = ("gemini", key_hash)
    with _client_cache_lock:
        cached = _client_cache.get(cache_key)
        if cached is not None:
            _client_cache.move_to_end(cache_key)
            return cached

    client = None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            )
        )
    except Exception:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to create Google GenAI client: {_scrub(e)}")
            return None

    evicted: Optional[Tuple[str, Any]] = None
    with _client_cache_lock:
        existing = _client_cache.get(cache_key)
        if existing is not None:
            _client_cache.move_to_end(cache_key)
            _close_client_best_effort("gemini", client)
            return existing
        _client_cache[cache_key] = client
        _client_cache.move_to_end(cache_key)
        if len(_client_cache) > _MAX_CLIENT_CACHE:
            (ev_prov, _), ev_cli = _client_cache.popitem(last=False)
            evicted = (ev_prov, ev_cli)

    if evicted:
        _close_client_best_effort(evicted[0], evicted[1])
    return client


def get_deepseek_client(
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Returns a cached AsyncOpenAI client configured for DeepSeek or None."""
    api_key = _resolve_api_key("deepseek", custom_key=custom_key, tenant_id=tenant_id)
    if not api_key:
        return None

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    key_hash = hashlib.sha256(f"{base_url}|{api_key}".encode("utf-8")).hexdigest()
    cache_key = ("deepseek", key_hash)

    with _client_cache_lock:
        cached = _client_cache.get(cache_key)
        if cached is not None:
            is_closed = getattr(cached, "is_closed", None)
            if not (callable(is_closed) and is_closed()):
                _client_cache.move_to_end(cache_key)
                return cached
            _client_cache.pop(cache_key, None)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as e:
        logger.error(f"Failed to create DeepSeek client: {_scrub(e)}")
        return None

    evicted: Optional[Tuple[str, Any]] = None
    with _client_cache_lock:
        existing = _client_cache.get(cache_key)
        if existing is not None:
            is_closed = getattr(existing, "is_closed", None)
            if not (callable(is_closed) and is_closed()):
                _client_cache.move_to_end(cache_key)
                _close_client_best_effort("deepseek", client)
                return existing
        _client_cache[cache_key] = client
        _client_cache.move_to_end(cache_key)
        if len(_client_cache) > _MAX_CLIENT_CACHE:
            (ev_prov, _), ev_cli = _client_cache.popitem(last=False)
            evicted = (ev_prov, ev_cli)

    if evicted:
        _close_client_best_effort(evicted[0], evicted[1])
    return client


def format_ai_error(err: Any, provider: str = "deepseek") -> str:
    """Translates raw AI provider error objects into clean, scrubbed, human-readable explanations."""
    err_str = _scrub(str(err or ""))
    err_lower = err_str.lower()
    prov = (provider or "deepseek").strip().lower()
    label = "Google Gemini" if prov == "gemini" else "DeepSeek"

    if prov == "deepseek" and (
        "Insufficient Balance" in err_str
        or "insufficient_quota" in err_lower
        or "balance" in err_lower
    ):
        return "DeepSeek account balance is low. Please check or top up credits at platform.deepseek.com."
    if (
        "401" in err_str
        or "AuthenticationError" in err_str
        or "API_KEY_INVALID" in err_str
        or "invalid_api_key" in err_lower
        or "api key not valid" in err_lower
    ):
        return f"Invalid {label} API key. Please check or replace your key in Settings."
    if (
        "429" in err_str
        or "RESOURCE_EXHAUSTED" in err_str
        or "rate_limit" in err_lower
        or "quota" in err_lower
    ):
        return f"{label} rate limit reached. Retrying automatically in a moment..."
    if "403" in err_str or "PERMISSION_DENIED" in err_str:
        return f"{label} API permission denied. Ensure your API key has proper access."
    if "503" in err_str or "UNAVAILABLE" in err_str or "ServiceUnavailable" in err_str:
        return f"{label} servers are temporarily busy. Retrying automatically..."
    if "Timeout" in err_str or "timed out" in err_lower:
        return f"{label} API response timed out. Retrying automatically..."
    clean = re.sub(r"\{.*?\}", "", err_str).replace("\n", " ").strip()
    clean = _scrub(clean)
    return clean[:180] if clean else err_str[:180]


async def _fetch_image_bytes(media_url: Optional[str]) -> Optional[Tuple[bytes, str]]:
    """
    Safely downloads tweet image bytes for Gemini Multimodal Vision analysis.
    Enforces HTTPS, strict media host allowlist, DNS SSRF checks, no redirects,
    strict image MIME types, and a hard 6 MB streaming size cap.
    """
    if not media_url or not isinstance(media_url, str):
        return None
    from core.security import async_validate_external_url, ALLOWED_MEDIA_HOSTS
    try:
        safe_url = await async_validate_external_url(
            media_url,
            allowed_hosts=ALLOWED_MEDIA_HOSTS,
            require_https=True,
            resolve_dns=True,
        )
    except ValueError as ve:
        logger.debug(f"Blocked unsafe media_url in _fetch_image_bytes: {_scrub(ve)}")
        return None

    try:
        import httpx
        async with httpx.AsyncClient(timeout=4.5, follow_redirects=False) as http_client:
            async with http_client.stream("GET", safe_url) as resp:
                if resp.status_code != 200:
                    return None
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype not in _ALLOWED_IMAGE_MIME_TYPES:
                    logger.debug(f"Rejected non-image or disallowed MIME type '{ctype}' for media_url")
                    return None
                clen_raw = resp.headers.get("content-length")
                if clen_raw:
                    try:
                        if int(clen_raw) > _MAX_IMAGE_BYTES:
                            return None
                    except ValueError:
                        pass
                buf = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    if not chunk:
                        continue
                    if len(buf) + len(chunk) > _MAX_IMAGE_BYTES:
                        logger.debug("Aborted media_url stream exceeding 6 MB cap.")
                        return None
                    buf.extend(chunk)
                if not buf:
                    return None
                return bytes(buf), ctype
    except Exception as e:
        logger.debug(f"Could not fetch media_url for vision analysis: {_scrub(e)}")
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
    """Strips markdown code fences and extracts the outermost JSON object or array."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return ""
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1]
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1]
    if "```" in cleaned:
        cleaned = cleaned.rsplit("```", 1)[0]

    obj_start = cleaned.find("{")
    arr_start = cleaned.find("[")
    if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
        end = cleaned.rfind("}")
        if end > obj_start:
            cleaned = cleaned[obj_start:end + 1]
    elif arr_start != -1:
        end = cleaned.rfind("]")
        if end > arr_start:
            cleaned = cleaned[arr_start:end + 1]

    return cleaned.strip()


async def test_ai_api(
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tests the AI credentials against Google Gemini or DeepSeek."""
    provider = get_active_provider(custom_key=custom_key, tenant_id=tenant_id)
    if provider == "deepseek":
        return await _test_deepseek_api(custom_key=custom_key, tenant_id=tenant_id)
    return await _test_gemini_api(custom_key=custom_key, tenant_id=tenant_id)


async def _test_gemini_api(
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tests Google Gemini API credentials and discovers available models."""
    api_key = _resolve_api_key("gemini", custom_key=custom_key, tenant_id=tenant_id)
    if not api_key:
        return {
            "success": False,
            "provider": "gemini",
            "error": "API key is empty or not configured",
            "hint": "Paste your free Google Gemini key from aistudio.google.com/app/apikey",
            "models": KNOWN_GEMINI_MODELS
        }

    client = get_gemini_client(custom_key=api_key, tenant_id=tenant_id)
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
            pager = await asyncio.wait_for(client.aio.models.list(), timeout=8.0)
            async for m in pager:
                m_name = getattr(m, "name", "") or ""
                short_id = m_name.replace("models/", "")
                if "gemini" in short_id.lower() and not any(
                    x in short_id.lower()
                    for x in [
                        "embedding", "imagen", "veo", "aqa", "tts", "audio",
                        "image", "robotics", "computer-use", "translate", "transcribe", "live",
                    ]
                ):
                    display = getattr(m, "display_name", short_id) or short_id
                    discovered_models.append({
                        "id": short_id,
                        "name": f"{display} ({short_id})" if short_id not in display else display,
                        "description": getattr(m, "description", "Google Gemini model") or "Google Gemini model"
                    })
        except Exception as list_err:
            logger.debug(f"Model list fallback notice: {_scrub(list_err)}")

        if not discovered_models:
            for candidate in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.5-flash"]:
                try:
                    await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=candidate,
                            contents="ping",
                            config=types.GenerateContentConfig(max_output_tokens=5, temperature=0.0)
                        ),
                        timeout=6.0,
                    )
                    break
                except Exception as probe_err:
                    p_str = str(probe_err)
                    if "404" in p_str or "NOT_FOUND" in p_str or "503" in p_str:
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
        err_msg = _scrub(str(e))
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


async def _test_deepseek_api(
    custom_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tests DeepSeek API credentials."""
    client = get_deepseek_client(custom_key=custom_key, tenant_id=tenant_id)
    if not client:
        return {
            "success": False,
            "provider": "deepseek",
            "error": "DeepSeek API key is not configured",
            "hint": "Paste your DeepSeek API key (sk-...) in Settings.",
            "models": KNOWN_DEEPSEEK_MODELS
        }
    try:
        await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5
            ),
            timeout=8.0
        )
        return {
            "success": True,
            "provider": "deepseek",
            "error": None,
            "hint": "Connected to DeepSeek (deepseek-chat)",
            "models": KNOWN_DEEPSEEK_MODELS
        }
    except Exception as e:
        err_str = _scrub(str(e))
        logger.warning(f"DeepSeek test key error: {err_str}")
        return {
            "success": False,
            "provider": "deepseek",
            "error": err_str,
            "hint": format_ai_error(e, provider="deepseek"),
            "models": KNOWN_DEEPSEEK_MODELS
        }


def log_deepseek_usage(
    response: Any,
    tenant_id: str = "default",
    task_type: str = "general",
    model_name: str = "deepseek-chat",
) -> Optional[Dict[str, Any]]:
    """
    Safely extracts prompt_tokens, completion_tokens, prompt_cache_hit_tokens,
    and prompt_cache_miss_tokens from a DeepSeek/OpenAI completion response
    and persists it to TokenUsageLog. Never raises on telemetry errors.
    """
    if response is None:
        return None
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    try:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        cache_hit = getattr(usage, "prompt_cache_hit_tokens", None)
        cache_miss = getattr(usage, "prompt_cache_miss_tokens", None)

        extra = getattr(usage, "model_extra", None) or {}
        if cache_hit is None and isinstance(extra, dict):
            cache_hit = extra.get("prompt_cache_hit_tokens")
        if cache_miss is None and isinstance(extra, dict):
            cache_miss = extra.get("prompt_cache_miss_tokens")

        if cache_hit is None:
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                cache_hit = getattr(details, "cached_tokens", None)
                if cache_hit is None and isinstance(details, dict):
                    cache_hit = details.get("cached_tokens")

        hit_tokens = max(0, int(cache_hit or 0))
        if cache_miss is not None:
            miss_tokens = max(0, int(cache_miss or 0))
        else:
            miss_tokens = max(0, prompt_tokens - hit_tokens)

        from database import SessionLocal, record_token_usage

        db = SessionLocal()
        try:
            row = record_token_usage(
                db=db,
                tenant_id=tenant_id or "default",
                provider="deepseek",
                model=model_name or "deepseek-chat",
                task_type=task_type or "general",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_hit_tokens=hit_tokens,
                cache_miss_tokens=miss_tokens,
            )
            logger.debug(
                f"Token telemetry [{tenant_id}/{task_type}]: prompt={prompt_tokens} "
                f"(hit={hit_tokens}, miss={miss_tokens}), completion={completion_tokens}, "
                f"cost=${row.estimated_cost_usd:.6f}"
            )
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_hit_tokens": hit_tokens,
                "cache_miss_tokens": miss_tokens,
                "estimated_cost_usd": row.estimated_cost_usd,
            }
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"Token telemetry logging skipped: {_scrub(e)}")
        return None


def log_gemini_usage(
    response: Any,
    tenant_id: str = "default",
    task_type: str = "general",
    model_name: str = "gemini-2.0-flash",
) -> Optional[Dict[str, Any]]:
    """
    Safely extracts prompt_token_count, candidates_token_count, and cached_content_token_count
    from a Google GenAI response.usage_metadata and persists it to TokenUsageLog.
    Never raises on telemetry errors.
    """
    if response is None:
        return None
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None

    try:
        if isinstance(meta, dict):
            prompt_tokens = max(0, int(meta.get("prompt_token_count") or 0))
            completion_tokens = max(0, int(meta.get("candidates_token_count") or 0))
            cached_tokens = max(0, int(meta.get("cached_content_token_count") or 0))
        else:
            prompt_tokens = max(0, int(getattr(meta, "prompt_token_count", 0) or 0))
            completion_tokens = max(0, int(getattr(meta, "candidates_token_count", 0) or 0))
            cached_tokens = max(0, int(getattr(meta, "cached_content_token_count", 0) or 0))

        hit_tokens = min(prompt_tokens, cached_tokens)
        miss_tokens = max(0, prompt_tokens - hit_tokens)

        from database import SessionLocal, record_token_usage

        db = SessionLocal()
        try:
            row = record_token_usage(
                db=db,
                tenant_id=tenant_id or "default",
                provider="gemini",
                model=model_name or "gemini-2.0-flash",
                task_type=task_type or "general",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_hit_tokens=hit_tokens,
                cache_miss_tokens=miss_tokens,
            )
            logger.debug(
                f"Gemini token telemetry [{tenant_id}/{task_type}]: prompt={prompt_tokens} "
                f"(hit={hit_tokens}, miss={miss_tokens}), completion={completion_tokens}, "
                f"cost=${row.estimated_cost_usd:.6f}"
            )
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_hit_tokens": hit_tokens,
                "cache_miss_tokens": miss_tokens,
                "estimated_cost_usd": row.estimated_cost_usd,
            }
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"Gemini token telemetry logging skipped: {_scrub(e)}")
        return None


async def async_log_ai_usage(
    response: Any = None,
    provider: str = "deepseek",
    tenant_id: str = "default",
    task_type: str = "general",
    model_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Non-blocking async wrapper that offloads AI token usage DB persistence to a worker thread.
    Accepts either (response, provider=...) or (provider, response, ...).
    """
    if isinstance(response, str) and response.strip().lower() in ("deepseek", "gemini") and not isinstance(provider, str):
        response, provider = provider, response

    prov = (provider or "deepseek").strip().lower()
    if prov == "gemini":
        return await asyncio.to_thread(
            log_gemini_usage,
            response,
            tenant_id or "default",
            task_type or "general",
            model_name or "gemini-2.0-flash",
        )
    return await asyncio.to_thread(
        log_deepseek_usage,
        response,
        tenant_id or "default",
        task_type or "general",
        model_name or "deepseek-chat",
    )


def check_tenant_token_budget(tenant_id: str = "default") -> Tuple[bool, int, int]:
    """
    Checks whether a tenant is within their daily AI token budget.
    Returns (allowed, used_today, daily_cap).
    Handles DB failures conservatively: grants a tiny transient grace window at trial cap,
    then fails closed on repeated DB errors so unbilled runaway usage cannot occur.
    """
    eff_tid = (tenant_id or "default").strip() or "default"
    try:
        from database import SessionLocal, get_agent_config, get_tenant_daily_tokens, get_platform_settings

        db = SessionLocal()
        try:
            cfg = get_agent_config(db, tenant_id=eff_tid)
            ps = get_platform_settings(db)
            plan_cap: Optional[int] = None
            try:
                from services.plans import get_plan
                tier = getattr(cfg, "plan_tier", None)
                if tier:
                    plan_cap = int(get_plan(tier).get("daily_token_cap") or 0) or None
            except Exception:
                plan_cap = None

            raw_cap = getattr(cfg, "daily_token_cap", None)
            if raw_cap is None:
                raw_cap = plan_cap or getattr(ps, "default_daily_token_cap", None) or _BUDGET_GRACE_CAP
            daily_cap = max(0, int(raw_cap))
            used_today = int(get_tenant_daily_tokens(db, tenant_id=eff_tid) or 0)

            with _budget_db_lock:
                _budget_db_failures.pop(eff_tid, None)

            return (used_today < daily_cap), used_today, daily_cap
        finally:
            db.close()
    except Exception as e:
        now = time.monotonic()
        with _budget_db_lock:
            prev_count, first_ts = _budget_db_failures.get(eff_tid, (0, now))
            if (now - first_ts) > _BUDGET_GRACE_WINDOW_SECONDS:
                prev_count = 0
                first_ts = now
            new_count = prev_count + 1
            _budget_db_failures[eff_tid] = (new_count, first_ts)
            _budget_db_failures.move_to_end(eff_tid)
            while len(_budget_db_failures) > 256:
                _budget_db_failures.popitem(last=False)

        safe_err = _scrub(e)
        if new_count <= _BUDGET_GRACE_LIMIT:
            logger.warning(
                f"Token budget DB check error for '{eff_tid}' (grace {new_count}/{_BUDGET_GRACE_LIMIT}): {safe_err}"
            )
            return True, 0, _BUDGET_GRACE_CAP

        logger.error(
            f"Repeated token budget DB failures for '{eff_tid}' ({new_count}); failing closed: {safe_err}"
        )
        return False, 0, 0


async def async_check_tenant_token_budget(tenant_id: str = "default") -> Tuple[bool, int, int]:
    """Non-blocking async wrapper for check_tenant_token_budget using asyncio.to_thread."""
    return await asyncio.to_thread(check_tenant_token_budget, tenant_id)
