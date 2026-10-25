"""
AI Decision Engine powered by DeepSeek API.
Analyzes scraped X (Twitter) posts, decides relevance, and crafts witty, high-value replies.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

logger = logging.getLogger("x_vibebot.ai")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# System prompt specified in the architecture instructions
SYSTEM_PROMPT = """You are an expert AI developer and tech commentator on X.
Analyze the provided post.
If it is relevant to coding, AI, or tech development, write a witty, value-adding reply between 1 to 2 sentences.
Do not use generic spam filler, fake hype, or excessive emojis.
If it is irrelevant, toxic, or promotional, reply with SKIP.

Respond in JSON format with two keys:
1. "action": either "reply" or "skip"
2. "text": your generated 1-2 sentence reply (or empty string if action is "skip")
3. "reasoning": brief 1-sentence explanation of your decision
"""


KNOWN_DEEPSEEK_MODELS = [
    {
        "id": "deepseek-chat",
        "name": "DeepSeek-V3 (deepseek-chat)",
        "description": "General conversational & coding model. Fast, cost-efficient, optimal for tweets and quick replies."
    },
    {
        "id": "deepseek-reasoner",
        "name": "DeepSeek-R1 (deepseek-reasoner)",
        "description": "Advanced reasoning and chain-of-thought model. Delivers deep analysis for technical discussions."
    }
]


def get_deepseek_client(custom_key: Optional[str] = None) -> Optional[AsyncOpenAI]:
    """Returns an AsyncOpenAI client configured for DeepSeek, or None if key is missing."""
    api_key = custom_key or os.getenv("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY)
    if not api_key or api_key == "your_deepseek_api_key_here":
        return None
    return AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL)
    )


async def test_deepseek_api(custom_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Tests the DeepSeek API credentials against the /models endpoint.
    Returns status, error details, and available models.
    """
    api_key = custom_key or os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key or api_key == "your_deepseek_api_key_here":
        return {
            "success": False,
            "error": "API key is empty or not configured",
            "hint": "Please enter your DeepSeek API key (starts with 'sk-'). Get one at https://platform.deepseek.com/",
            "models": KNOWN_DEEPSEEK_MODELS
        }

    client = get_deepseek_client(custom_key=api_key)
    try:
        model_list_resp = await client.models.list()
        fetched_models = []
        for m in model_list_resp.data:
            fetched_models.append({
                "id": m.id,
                "name": m.id,
                "description": "Available on your DeepSeek account"
            })
        return {
            "success": True,
            "error": None,
            "hint": "API key is valid and connected to DeepSeek!",
            "models": fetched_models if fetched_models else KNOWN_DEEPSEEK_MODELS
        }
    except Exception as e:
        err_msg = str(e)
        hint = "Authentication failed. DeepSeek API keys typically start with 'sk-'. Ensure you copied the full key from platform.deepseek.com."
        if "401" in err_msg or "Authentication" in err_msg:
            hint = "DeepSeek rejected this key (HTTP 401 Unauthorized). Check that your key is active and formatted like 'sk-...'."
        return {
            "success": False,
            "error": err_msg,
            "hint": hint,
            "models": KNOWN_DEEPSEEK_MODELS
        }


async def evaluate_tweet(
    tweet_text: str,
    tweet_author: Optional[str] = None,
    model_name: Optional[str] = None,
    custom_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates a scraped tweet using DeepSeek.

    Returns:
        dict: {
            "should_reply": bool,
            "reply_text": str or None,
            "reasoning": str,
            "raw_response": str
        }
    """
    client = get_deepseek_client(custom_key=custom_key)
    if not client:
        logger.warning("DEEPSEEK_API_KEY not configured. Skipping AI evaluation.")
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": "DeepSeek API key is not configured in .env",
            "raw_response": "NO_API_KEY"
        }

    chosen_model = model_name or os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL)
    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"

    try:
        # Note: deepseek-reasoner does not support response_format={"type": "json_object"} on some endpoints,
        # so we handle standard json text parsing safely.
        kwargs = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
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

        # Extract JSON content even if wrapped in markdown fences
        cleaned = raw_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
            action = str(data.get("action", "")).strip().lower()
            reply_text = str(data.get("text", "")).strip()
            reasoning = str(data.get("reasoning", "")).strip()
        except json.JSONDecodeError:
            # Fallback if reasoning model gave text response
            if "SKIP" in raw_output.upper() and len(raw_output) < 30:
                action = "skip"
                reply_text = ""
                reasoning = "Skipped by AI"
            else:
                action = "reply"
                reply_text = raw_output.replace('"', '').strip()
                reasoning = "Generated direct reply"

        # Check if model opted to skip or reply
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
        logger.error(f"Error calling DeepSeek API ({chosen_model}): {e}", exc_info=True)
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": f"DeepSeek API Error: {str(e)}",
            "raw_response": f"ERROR: {str(e)}"
        }
