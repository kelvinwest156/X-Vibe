"""
Web & Internet Trend Scouting Engine for X-VibeBot.
Fetches breaking news and hot discussions from Google News RSS and synthesizes them into:
1. High-signal 2-4 word X search queries (to find real-time live conversations).
2. Standalone original tweets and mini-threads for creator inspo in the Review Queue.
"""

import os
import re
import json
import logging
import asyncio
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx
import xml.etree.ElementTree as ET

from ai_engine import (
    get_gemini_client,
    get_deepseek_client,
    get_active_provider,
    sanitize_model_for_provider,
    log_deepseek_usage,
    _clean_json_markdown,
)

logger = logging.getLogger("x_vibebot.web_scout")

# In-memory cached topics per niche to avoid redundant requests: {niche: (timestamp, [topics])}
_TOPIC_CACHE: Dict[str, Any] = {}
CACHE_TTL_SECONDS = 7200  # 2 hours (default; dynamically overridden by PlatformSettings)


def _get_effective_cache_ttl() -> int:
    """Reads dynamic web_radar_cache_seconds from PlatformSettings, falling back to 7200s (2h)."""
    try:
        from database import SessionLocal, get_platform_settings
        db = SessionLocal()
        try:
            ps = get_platform_settings(db)
            if ps and ps.web_radar_cache_seconds and ps.web_radar_cache_seconds > 0:
                return int(ps.web_radar_cache_seconds)
        finally:
            db.close()
    except Exception:
        pass
    return CACHE_TTL_SECONDS


def _clean_headline(raw_title: str) -> tuple[str, str]:
    """Separates the headline from the publisher source, e.g. 'Headline - Reuters' -> ('Headline', 'Reuters')."""
    if not raw_title:
        return "", "Google News"
    parts = raw_title.rsplit(" - ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return raw_title.strip(), "Google News"


async def fetch_google_news_topics(query: str = "artificial intelligence", limit: int = 5) -> List[Dict[str, Any]]:
    """
    Fetches breaking news articles from Google News RSS without requiring an API key.
    Extracts title, source publisher, link, and publication date.
    """
    # Sanitize search query for Google News RSS: remove #, @, quotes, and boolean operators like OR/AND
    raw = query or "technology"
    clean_query = re.sub(r"[#@\"']", " ", raw)
    clean_query = re.sub(r"\bOR\b|\bAND\b", " ", clean_query, flags=re.IGNORECASE)
    clean_query = " ".join(clean_query.split())
    if not clean_query or len(clean_query) < 2:
        clean_query = "technology"

    encoded_query = urllib.parse.quote_plus(clean_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

    items: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(rss_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if resp.status_code != 200:
                logger.warning(f"Google News RSS returned status {resp.status_code}")
                return []

            tree = ET.fromstring(resp.text)
            for item in tree.findall(".//item")[:limit * 2]:
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_elem = item.find("pubDate")
                source_elem = item.find("source")

                if title_elem is None or not title_elem.text:
                    continue

                raw_title = title_elem.text.strip()
                title, source = _clean_headline(raw_title)
                if source_elem is not None and source_elem.text:
                    source = source_elem.text.strip()

                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

                # Avoid duplicates
                if any(it["title"].lower() == title.lower() for it in items):
                    continue

                items.append({
                    "title": title,
                    "source": source,
                    "link": link,
                    "pub_date": pub_date,
                    "raw_title": raw_title
                })
                if len(items) >= limit:
                    break

    except Exception as e:
        logger.error(f"Failed to fetch Google News RSS for '{query}': {e}")

    return items


async def scout_and_rank_topics(
    niche: str = "tech",
    limit: int = 4,
    custom_key: Optional[str] = None,
    tenant_id: str = "default",
) -> List[Dict[str, Any]]:
    """
    Scouts the web for breaking niche topics, asks DeepSeek/Gemini to extract an optimal 2-4 word X search query,
    and returns a ranked list of creator-ready trend items with hot-take summaries.
    Cached for 2 hours (or PlatformSettings.web_radar_cache_seconds).
    """
    global _TOPIC_CACHE
    niche_key = (niche or "tech").strip().lower()
    cache_ttl = _get_effective_cache_ttl()

    # Check cache
    now = datetime.utcnow().timestamp()
    if niche_key in _TOPIC_CACHE:
        cached_time, cached_items = _TOPIC_CACHE[niche_key]
        if now - cached_time < cache_ttl and cached_items:
            return cached_items[:limit]

    raw_news = await fetch_google_news_topics(query=niche, limit=limit + 2)
    if not raw_news:
        return []

    provider = get_active_provider(custom_key=custom_key)
    titles_list = "\n".join([f"{i+1}. {it['title']} (Source: {it['source']})" for i, it in enumerate(raw_news)])
    prompt = f"""You are an elite X (Twitter) creator trend strategist.
User's Niche: "{niche}"

Here are breaking news headlines from Google News:
{titles_list}

For each headline, generate:
1. "suggested_query": A razor-sharp 2 to 4 word search phrase to find live X discussions right now. (No quotes, no hashtags, no punctuation).
2. "hook_summary": A 1-sentence punchy, thought-provoking hook or angle an influencer can tweet about this topic.
3. "relevance_score": An integer from 1 to 10 measuring viral/discussion potential on X.

Respond ONLY with valid JSON array of objects:
[
  {{
    "index": 1,
    "suggested_query": "2 to 4 word query",
    "hook_summary": "1 sentence hook",
    "relevance_score": 9
  }}
]"""

    enriched_map: Dict[int, Dict[str, Any]] = {}
    if provider == "deepseek":
        ds_client = get_deepseek_client(custom_key=custom_key)
        if ds_client:
            try:
                ds_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
                resp = await asyncio.wait_for(
                    ds_client.chat.completions.create(
                        model=ds_model,
                        messages=[
                            {"role": "system", "content": "You are a trend strategist analyzing news for creators. Output valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.7,
                        max_tokens=800
                    ),
                    timeout=8.0
                )
                log_deepseek_usage(
                    resp,
                    tenant_id=tenant_id,
                    task_type="web_scout",
                    model_name=ds_model,
                )
                raw = resp.choices[0].message.content or ""
                cleaned = _clean_json_markdown(raw)
                data = json.loads(cleaned)
                items = data if isinstance(data, list) else (data.get("topics") or data.get("headlines") or (list(data.values())[0] if data and isinstance(list(data.values())[0], list) else []))
                if isinstance(items, list):
                    for item in items:
                        idx = item.get("index")
                        if idx:
                            enriched_map[idx] = item
            except Exception as e:
                logger.debug(f"DeepSeek trend enrichment fallback: {e}")

    client = get_gemini_client(custom_key=custom_key)
    if client and not enriched_map:
        try:
            from google.genai import types
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7,
                        max_output_tokens=500
                    )
                ),
                timeout=4.5
            )
            if resp and resp.text:
                cleaned = _clean_json_markdown(resp.text)
                data = json.loads(cleaned)
                if isinstance(data, list):
                    for item in data:
                        idx = item.get("index")
                        if idx:
                            enriched_map[idx] = item
        except Exception as e:
            logger.debug(f"Gemini trend enrichment fast fallback: {e}")

    results: List[Dict[str, Any]] = []
    for i, it in enumerate(raw_news):
        idx = i + 1
        meta = enriched_map.get(idx, {})
        s_query = meta.get("suggested_query")
        if not s_query or len(s_query) < 2:
            s_query = " ".join([w for w in re.sub(r"[^\w\s]", "", it["title"]).split() if len(w) > 3][:3])

        hook = meta.get("hook_summary") or f"Breaking story on {it['title']} via {it['source']}."
        score = meta.get("relevance_score") or 8

        results.append({
            "title": it["title"],
            "source": it["source"],
            "url": it["link"],
            "suggested_query": s_query.strip(),
            "hook_summary": hook.strip(),
            "relevance_score": score,
            "timestamp": datetime.utcnow().isoformat()
        })

    # Sort by relevance
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    _TOPIC_CACHE[niche_key] = (now, results)
    return results[:limit]


async def generate_draft_from_web_topic(
    topic: Dict[str, Any],
    persona_prompt: str = "Casual, sharp, dry humor, short sentences",
    model_name: str = "deepseek-chat",
    custom_key: Optional[str] = None,
    draft_type: str = "tweet",
    tenant_id: str = "default",
) -> Dict[str, str]:
    """
    Synthesizes an original standalone tweet OR a 3-tweet thread based on a breaking web topic.
    Only generates the requested format (draft_type='tweet' by default) to save output tokens.
    """
    title = topic.get("title", "")
    source = topic.get("source", "Google News")
    url = topic.get("url", "")
    hook_summary = topic.get("hook_summary", "")
    req_type = (draft_type or "tweet").strip().lower()

    if req_type == "thread":
        format_req = (
            'Requirement:\n'
            '- "thread": A punchy 3-tweet thread separated by "\\n---\\n" (each <240 chars, NO "1/3" or "🧵"). '
            'Breaks down the news, why it matters, and asks the audience for their reaction.\n\n'
            'Respond ONLY with valid JSON:\n{\n  "thread": "Post 1\\n---\\nPost 2\\n---\\nPost 3"\n}'
        )
        max_tok = 420
    elif req_type == "both":
        format_req = (
            'Requirements:\n'
            '1. "single_tweet": A standalone, viral X post (under 240 chars). Engaging hook, opinionated take or sharp question, NO hashtag overload.\n'
            '2. "thread": A punchy 3-tweet thread separated by "\\n---\\n". Breaks down the news, why it matters, and asks for reaction.\n\n'
            'Respond ONLY with valid JSON:\n{\n  "single_tweet": "Your punchy standalone tweet",\n  "thread": "Post 1\\n---\\nPost 2\\n---\\nPost 3"\n}'
        )
        max_tok = 600
    else:
        format_req = (
            'Requirement:\n'
            '- "single_tweet": A standalone, punchy X post (under 240 chars). Sharp take or question, NO corporate clichés, NO em-dashes, max 0-1 hashtags.\n\n'
            'Respond ONLY with valid JSON:\n{\n  "single_tweet": "Your punchy standalone tweet"\n}'
        )
        max_tok = 220

    prompt = f"""You are an influential creator on X (Twitter).
{format_req}

Persona Voice: "{persona_prompt}"
Breaking Story from {source}:
Title: "{title}"
Context / Hook: "{hook_summary}" """

    provider = get_active_provider(custom_key=custom_key)
    if provider == "deepseek":
        ds_client = get_deepseek_client(custom_key=custom_key)
        if ds_client:
            try:
                ds_model = sanitize_model_for_provider("deepseek", model_name)
                resp = await asyncio.wait_for(
                    ds_client.chat.completions.create(
                        model=ds_model,
                        messages=[
                            {"role": "system", "content": "You are an influential creator on X. Respond ONLY with valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.85,
                        max_tokens=max_tok
                    ),
                    timeout=10.0
                )
                log_deepseek_usage(
                    resp,
                    tenant_id=tenant_id,
                    task_type="web_draft",
                    model_name=ds_model,
                )
                raw = resp.choices[0].message.content or ""
                data = json.loads(_clean_json_markdown(raw))
                return {
                    "single_tweet": str(data.get("single_tweet", "")).strip(),
                    "thread": str(data.get("thread", "")).strip()
                }
            except Exception as e:
                logger.debug(f"DeepSeek web topic draft fallback: {e}")

    client = get_gemini_client(custom_key=custom_key)
    if not client:
        return {
            "single_tweet": f"Interesting development: {title}.\n\nWhat's your take on this?",
            "thread": f"Breaking: {title} via {source}.\n---\nHere is why this matters for creators and builders.\n---\nFull details: {url}"
        }

    try:
        from google.genai import types
        chosen = (model_name if "gemini" in model_name else "gemini-2.0-flash").replace("models/", "")
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=chosen,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.85,
                    max_output_tokens=max_tok
                )
            ),
            timeout=5.0
        )
        if resp and resp.text:
            data = json.loads(_clean_json_markdown(resp.text))
            return {
                "single_tweet": str(data.get("single_tweet", "")).strip(),
                "thread": str(data.get("thread", "")).strip()
            }
    except Exception as e:
        logger.error(f"Failed to generate draft from web topic (fallback used): {e}")

    return {
        "single_tweet": f"Interesting shift: {title}.\n\nCurious how this plays out.",
        "thread": f"New update: {title}.\n---\nThe implications for builders are huge.\n---\nWhat are your thoughts?"
    }
