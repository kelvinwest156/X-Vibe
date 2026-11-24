"""
Free $0 Python Tweet Pre-Filter ("Spam Bouncer") for X-VibeBot.
Drops obvious spam, retweets, empty/ultra-short noise, link/emoji-only posts,
and hashtag stuffing before spending a single AI token.
"""

import re
from typing import Dict, Any, Tuple

_URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.co/\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#\w+")
_WORD_RE = re.compile(r"[A-Za-z0-9]{2,}")

_SPAM_PATTERNS = [
    (re.compile(r"\b(airdrop|presale|pre-sale|whitelist|wl spot)\b", re.IGNORECASE), "crypto airdrop/presale promo"),
    (re.compile(r"\b(giveaway|follow\s*(&|and)\s*rt|like\s*(&|and)\s*rt|rt\s*(&|and)\s*follow)\b", re.IGNORECASE), "giveaway/engagement bait"),
    (re.compile(r"\b(dm\s+(me\s+)?for\s+promo|paid\s+promo|promo\s+dm|collab\s+dm)\b", re.IGNORECASE), "promo spam"),
    (re.compile(r"\b(selling\s+tickets?|tickets?\s+available|vip\s+tickets?)\b", re.IGNORECASE), "ticket-selling spam"),
    (re.compile(r"\b(whatsapp|wa\.me/|telegram|t\.me/)\b", re.IGNORECASE), "off-platform spam link"),
    (re.compile(r"\b(claim\s+your|100x\s+gem|1000x|drop\s+your\s+(sol|eth|btc|wallet)|free\s+(sol|eth|usdt|crypto))\b", re.IGNORECASE), "crypto scam/spam"),
    (re.compile(r"\b(betting\s+tips?|fixed\s+match|casino\s+bonus|sportsbook|onlyfans\.com)\b", re.IGNORECASE), "betting/adult spam"),
]


def should_prefilter_skip(tweet: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Fast, zero-token Python pre-filter run before sending tweets to DeepSeek.
    Returns (True, "Pre-filtered: <reason>") if the tweet should be skipped immediately,
    or (False, "") if it should proceed to AI evaluation.
    """
    raw_text = str(tweet.get("text") or tweet.get("tweet_text") or "").strip()
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

    # 3. Obvious spam / giveaway / crypto / ticket promo regexes
    for pattern, reason in _SPAM_PATTERNS:
        if pattern.search(raw_text):
            return True, f"Pre-filtered: {reason}"

    # Strip URLs & mentions to inspect real conversational text
    no_urls = _URL_RE.sub("", raw_text).strip()
    no_mentions = _MENTION_RE.sub("", no_urls).strip()
    clean_text = " ".join(no_mentions.split())
    words = _WORD_RE.findall(clean_text)

    # 4. Link-only or emoji-only posts (no meaningful conversational words)
    if not has_media and len(words) < 3:
        if _URL_RE.search(raw_text) and len(clean_text) < 15:
            return True, "Pre-filtered: link-only post"
        return True, "Pre-filtered: emoji or low-word noise"

    # 5. Ultra-short tweets without attached media (< 25 chars)
    if not has_media and len(clean_text) < 25:
        return True, "Pre-filtered: too short (<25 chars)"

    return False, ""
