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


def get_deepseek_client() -> Optional[AsyncOpenAI]:
    """Returns an AsyncOpenAI client configured for DeepSeek, or None if key is missing."""
    api_key = os.getenv("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY)
    if not api_key or api_key == "your_deepseek_api_key_here":
        return None
    return AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL)
    )


async def evaluate_tweet(tweet_text: str, tweet_author: Optional[str] = None) -> Dict[str, Any]:
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
    client = get_deepseek_client()
    if not client:
        logger.warning("DEEPSEEK_API_KEY not configured. Skipping AI evaluation.")
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": "DeepSeek API key is not configured in .env",
            "raw_response": "NO_API_KEY"
        }

    user_content = f"Author: @{tweet_author or 'unknown'}\nTweet Text: {tweet_text}"

    try:
        response = await client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=250
        )

        raw_output = response.choices[0].message.content or ""
        logger.info(f"DeepSeek response: {raw_output}")

        data = json.loads(raw_output)
        action = str(data.get("action", "")).strip().lower()
        reply_text = str(data.get("text", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()

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
        logger.error(f"Error calling DeepSeek API: {e}", exc_info=True)
        return {
            "should_reply": False,
            "reply_text": None,
            "reasoning": f"DeepSeek API Error: {str(e)}",
            "raw_response": f"ERROR: {str(e)}"
        }
