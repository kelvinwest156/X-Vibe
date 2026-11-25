"""
Free $0 Python Tweet Pre-Filter ("Spam Bouncer") for X-VibeBot.
Drops obvious spam, retweets, empty/ultra-short noise, link/emoji-only posts,
and hashtag stuffing before spending a single AI token.
"""

import re
from typing import Dict, Any, Tuple

_MAX_TWEET_SCAN_CHARS = 2000

_URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.co/\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)
_WORD_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")

_SPAM_PATTERNS = [
    (re.compile(r"\b(airdrop|presale|pre-sale|whitelist|wl spot)\b", re.IGNORECASE), "crypto airdrop/presale promo"),
    (re.compile(r"\b(giveaway|follow\s*(&|and)\s*rt|like\s*(&|and)\s*rt|rt\s*(&|and)\s*follow)\b", re.IGNORECASE), "giveaway/engagement bait"),
    (re.compile(r"\b(dm\s+(me\s+)?for\s+promo|paid\s+promo|promo\s+dm|collab\s+dm)\b", re.IGNORECASE), "promo spam"),
    (re.compile(r"\b(selling\s+tickets?|tickets?\s+available|vip\s+tickets?)\b", re.IGNORECASE), "ticket-selling spam"),
    (re.compile(r"\b(whatsapp|wa\.me/|telegram|t\.me/)\b", re.IGNORECASE), "off-platform spam link"),
    (re.compile(r"\b(?:bit\.ly|discord\.gg|tinyurl\.com)/\S*", re.IGNORECASE), "shortened/invite spam link"),
    (re.compile(r"\b(claim\s+your|100x\s+gem|1000x|drop\s+your\s+(sol|eth|btc|wallet)|free\s+(sol|eth|usdt|crypto))\b", re.IGNORECASE), "crypto scam/spam"),
    (re.compile(r"\b(betting\s+tips?|fixed\s+match|casino\s+bonus|sportsbook|onlyfans\.com)\b", re.IGNORECASE), "betting/adult spam"),
]


def should_prefilter_skip(tweet: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Fast, zero-token Python pre-filter run before sending tweets to AI evaluation.
    Returns (True, "Pre-filtered: <reason>") if the tweet should be skipped immediately,
    or (False, "") if it should proceed to AI evaluation.
    """
    raw_text = str(tweet.get("text") or tweet.get("tweet_text") or "").strip()[:_MAX_TWEET_SCAN_CHARS]
    has_media = bool(tweet.get("media_url"))

    if not raw_text:
        return True, "Pre-filtered: empty post"

    # 1. Pure retweets
    if raw_text.startswith("RT @"):
        return True, "Pre-filtered: retweet"

    # 2. Excessive hashtag spam (>= 6 hashtags)
    hashtags = _HASHTAG_RE.findall(raw_text)
    if len(hashtags) >= 6:
        return True, f"Pre-filtered: hashtag spam ({len(hashtags)} tags)"

    # 3. Obvious spam / giveaway / crypto / shortened-link / ticket promo regexes
    for pattern, reason in _SPAM_PATTERNS:
        if pattern.search(raw_text):
            return True, f"Pre-filtered: {reason}"

    # Strip URLs & mentions to inspect real conversational text
    no_urls = _URL_RE.sub("", raw_text).strip()
    no_mentions = _MENTION_RE.sub("", no_urls).strip()
    clean_text = " ".join(no_mentions.split())
    words = _WORD_RE.findall(clean_text)
    word_chars = sum(len(w) for w in words)

    # 4. Basic link-only / empty-caption checks apply even when media is attached
    if not clean_text:
        if _URL_RE.search(raw_text):
            return True, "Pre-filtered: link-only post"
        return True, "Pre-filtered: empty caption"

    if _URL_RE.search(raw_text) and len(clean_text) < 12 and len(words) < 2 and word_chars < 8:
        return True, "Pre-filtered: link-only post"

    # 5. Emoji-only or low-word noise without media (supports spaced & CJK Unicode text)
    if not has_media and len(words) < 3 and word_chars < 12:
        if _URL_RE.search(raw_text) and len(clean_text) < 15:
            return True, "Pre-filtered: link-only post"
        return True, "Pre-filtered: emoji or low-word noise"

    # 6. Ultra-short tweets without attached media (<25 chars, or <12 for compact CJK scripts)
    min_chars = 12 if _CJK_RE.search(clean_text) else 25
    if not has_media and len(clean_text) < min_chars:
        return True, f"Pre-filtered: too short (<{min_chars} chars)"

    return False, ""
