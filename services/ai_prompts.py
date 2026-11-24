"""
Prompt Engineering & Few-Shot Voice Memory Formatting Service for X-VibeBot.
Constructs prefix-cache-optimized persona instructions, batched evaluation prompts,
on-demand 3-angle variant prompts, few-shot memory snippets, and anti-robotic guardrails.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple


# 100% STATIC PREFIXES (placed first in system prompts to maximize DeepSeek 90% prefix caching)
_STATIC_EVAL_RULES = """You are a real human X (Twitter) user writing authentic, high-signal replies.

EVALUATION CRITERIA:
1. SKIP if the post is spam, scams, betting/crypto promos, engagement bait, or unrelated to the target topic below.
2. REPLY if it is a genuine opinion, take, question, chart/screenshot, product update, or funny moment relevant to the target topic below.

STRICT ANTI-ROBOTIC & ANTI-DETECTION RULES (CRITICAL):
- NEVER use em-dashes (—), en-dashes (–), or semicolons (;). Real people on X don't type those.
- NEVER start with "Ah,", "Honestly,", "To be fair,", "Indeed,", "Spot on,", "Great point," or end with "Let's see if..." or "Only time will tell."
- NEVER use AI buzzwords: delve, testament, game-changer, landscape, fascinating, undeniable, masterclass, Chef's kiss.
- Do NOT summarize or repeat the author's tweet back to them. Jump straight into your reaction, specific detail from their post, or fresh angle.
- Keep replies concise: 6 to 22 words max. Sound like a smart insider texting a friend.
- Keep "reasoning" ultra-brief: 2 to 5 words max (e.g. "crypto spam", "off-topic", "sharp dev take")."""

_STATIC_SINGLE_JSON_NO_VARIANTS = """
Respond ONLY in valid JSON with these exact keys:
{
  "action": "reply" or "skip",
  "text": "your single best primary reply (6-22 words)",
  "should_like": true or false,
  "urgency_score": integer 1 to 10 (9-10 breaking/viral wave; 5 normal; 1-3 evergreen),
  "reasoning": "2-5 words"
}
If action is "skip", set "text" to "", "should_like" to false, and "urgency_score" to 1."""

_STATIC_SINGLE_JSON_WITH_VARIANTS = """
- Invent 3 context-specific angle names in "variants" that fit THIS specific post (e.g. "Sharp Observation", "Contrarian", "Technical Follow-Up", "Dry Humor", "One-Liner").

Respond ONLY in valid JSON with these exact keys:
{
  "action": "reply" or "skip",
  "text": "your best primary reply (6-22 words)",
  "variants": {
    "<Custom Angle 1>": "first distinct reply option (6-20 words)",
    "<Custom Angle 2>": "second distinct reply option (6-20 words)",
    "<Custom Angle 3>": "third distinct reply option (4-15 words)"
  },
  "should_like": true or false,
  "urgency_score": integer 1 to 10 (9-10 breaking/viral wave; 5 normal; 1-3 evergreen),
  "reasoning": "2-5 words"
}
If action is "skip", set "text" to "", "variants" to {}, "should_like" to false, and "urgency_score" to 1."""

_STATIC_BATCH_JSON_NO_VARIANTS = """
You will receive a numbered list of candidate X posts, each with an "id".
Evaluate EVERY post independently and return one result object per post.

Respond ONLY in valid JSON with this exact schema:
{
  "results": [
    {
      "id": "exact tweet id from input",
      "action": "reply" or "skip",
      "text": "your single best primary reply (6-22 words) or empty string if skip",
      "should_like": true or false,
      "urgency_score": integer 1 to 10,
      "reasoning": "2-5 words"
    }
  ]
}
If action is "skip", set "text" to "", "should_like" to false, and "urgency_score" to 1."""

_STATIC_BATCH_JSON_WITH_VARIANTS = """
You will receive a numbered list of candidate X posts, each with an "id".
Evaluate EVERY post independently and return one result object per post.
For posts with action="reply", invent 3 context-specific angle names in "variants".

Respond ONLY in valid JSON with this exact schema:
{
  "results": [
    {
      "id": "exact tweet id from input",
      "action": "reply" or "skip",
      "text": "your best primary reply (6-22 words) or empty string if skip",
      "variants": {
        "<Custom Angle 1>": "option 1 (6-20 words)",
        "<Custom Angle 2>": "option 2 (6-20 words)",
        "<Custom Angle 3>": "option 3 (4-15 words)"
      },
      "should_like": true or false,
      "urgency_score": integer 1 to 10,
      "reasoning": "2-5 words"
    }
  ]
}
If action is "skip", set "text" to "", "variants" to {}, "should_like" to false, and "urgency_score" to 1."""

_STATIC_VARIANTS_SYSTEM = """You are a real human X (Twitter) user generating 3 distinct alternative reply angles for a tweet.

STRICT ANTI-ROBOTIC RULES:
- NEVER use em-dashes (—), en-dashes (–), or semicolons (;).
- NEVER start with "Ah,", "Honestly,", "To be fair,", "Indeed,", "Spot on,", "Great point,".
- NEVER use AI buzzwords: delve, testament, game-changer, landscape, fascinating, undeniable, masterclass.
- Keep each angle concise: 6 to 22 words max. Each option must take a genuinely different angle from the current draft.
- Invent 3 punchy, context-specific angle names (e.g. "Contrarian", "Dry Wit", "Builder Take", "Sharp Question", "One-Liner").

Respond ONLY in valid JSON with this exact schema:
{
  "variants": {
    "<Angle 1>": "first distinct reply (6-20 words)",
    "<Angle 2>": "second distinct reply (6-20 words)",
    "<Angle 3>": "third distinct reply (4-18 words)"
  }
}"""


def _format_dynamic_context(
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None,
) -> str:
    """Formats dynamic per-tenant voice, topic, and trimmed few-shot memory to append AFTER static prefix."""
    topic_clause = (
        f"'{search_query.strip()}' (or surrounding conversation/culture)"
        if search_query and search_query.strip()
        else "tech, coding, AI, or the active timeline topic"
    )
    voice_clause = (
        persona_prompt.strip()
        if persona_prompt and persona_prompt.strip()
        else "Casual, sharp, dry humor, short sentences, zero corporate buzzwords"
    )

    memory_section = ""
    if learning_memory and isinstance(learning_memory, dict):
        approved_list = learning_memory.get("approved") or []
        skipped_list = learning_memory.get("skipped") or []
        mem_lines: List[str] = []
        if approved_list:
            mem_lines.append("APPROVED VOICE SAMPLES (match this cadence & brevity):")
            for idx, item in enumerate(approved_list[:4], 1):
                tag = "[EDITED]" if item.get("user_edited") else "[OK]"
                t_snip = str(item.get("tweet_text", "") or "").replace("\n", " ").strip()[:90]
                r_snip = str(item.get("reply_text", "") or "").replace("\n", " ").strip()[:140]
                mem_lines.append(f"  {idx}. {tag} '{t_snip}' -> '{r_snip}'")
        if skipped_list:
            mem_lines.append("REJECTED/SKIPPED EXAMPLES (avoid similar posts):")
            for idx, item in enumerate(skipped_list[:3], 1):
                t_snip = str(item.get("tweet_text", "") or "").replace("\n", " ").strip()[:90]
                mem_lines.append(f"  {idx}. '{t_snip}'")
        if mem_lines:
            memory_section = "\nUSER MEMORY:\n" + "\n".join(mem_lines)

    return f"\n\nTARGET TOPIC: {topic_clause}\nVOICE/PERSONA: {voice_clause}{memory_section}"


def build_system_prompt(
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
) -> str:
    """
    Builds a prefix-cache-optimized, topic-aware, self-learning, anti-robotic system prompt.
    Static rules & JSON schema come FIRST so DeepSeek hits its 90% prefix cache discount;
    dynamic voice, topic, and trimmed learning memory appear at the BOTTOM.
    """
    json_schema = _STATIC_SINGLE_JSON_WITH_VARIANTS if include_variants else _STATIC_SINGLE_JSON_NO_VARIANTS
    dynamic_tail = _format_dynamic_context(
        search_query=search_query,
        persona_prompt=persona_prompt,
        learning_memory=learning_memory,
    )
    return f"{_STATIC_EVAL_RULES}\n{json_schema}{dynamic_tail}\n"


def build_batch_evaluation_prompt(
    tweets: List[Dict[str, Any]],
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
) -> Tuple[str, str]:
    """
    Builds (system_prompt, user_prompt) to evaluate up to 8 candidate tweets in a single AI call.
    Static prefix comes FIRST for DeepSeek prefix caching; dynamic context at the bottom.
    """
    json_schema = _STATIC_BATCH_JSON_WITH_VARIANTS if include_variants else _STATIC_BATCH_JSON_NO_VARIANTS
    dynamic_tail = _format_dynamic_context(
        search_query=search_query,
        persona_prompt=persona_prompt,
        learning_memory=learning_memory,
    )
    system_prompt = f"{_STATIC_EVAL_RULES}\n{json_schema}{dynamic_tail}\n"

    tweet_blocks: List[str] = []
    for idx, t in enumerate(tweets, 1):
        tid = str(t.get("tweet_id") or t.get("id") or f"idx_{idx}")
        author = str(t.get("author") or t.get("tweet_author") or "unknown").lstrip("@")
        text = str(t.get("text") or t.get("tweet_text") or "").replace("\n", " ").strip()[:420]
        metrics = str(t.get("metrics") or t.get("tweet_metrics") or "").strip()
        extra = str(t.get("extra_context") or "").replace("\n", " ").strip()[:200]
        media_note = " [Has attached image]" if t.get("media_url") else ""
        line = f'{idx}. id="{tid}" | @{author}'
        if metrics:
            line += f" ({metrics})"
        line += f"{media_note}\n   Text: {text}"
        if extra:
            line += f"\n   Context: {extra}"
        tweet_blocks.append(line)

    user_prompt = "Evaluate these candidate X posts:\n\n" + "\n\n".join(tweet_blocks)
    return system_prompt, user_prompt


def build_variants_prompt(
    tweet_text: str,
    tweet_author: str,
    current_reply: str,
    persona_prompt: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Builds a lightweight (system_prompt, user_prompt) pair for on-demand 3-angle variant generation.
    """
    voice_clause = (
        persona_prompt.strip()
        if persona_prompt and persona_prompt.strip()
        else "Casual, sharp, dry humor, short sentences, zero corporate buzzwords"
    )
    system_prompt = f"{_STATIC_VARIANTS_SYSTEM}\n\nVOICE/PERSONA: {voice_clause}\n"
    author_clean = (tweet_author or "creator").lstrip("@")
    user_prompt = (
        f"Original post by @{author_clean}:\n"
        f"{(tweet_text or '')[:400]}\n\n"
        f"Current draft reply:\n"
        f"{(current_reply or '')[:280]}\n\n"
        f"Write 3 fresh, distinct alternative angles in JSON."
    )
    return system_prompt, user_prompt


def _build_original_prompt_and_instructions(
    mode: str,
    topic: str,
    voice: str,
    live_tweets: Optional[List[Dict[str, Any]]] = None,
    learning_memory: Optional[Dict[str, Any]] = None,
    include_variants: bool = False,
) -> Tuple[str, str]:
    """
    Assembles prompt and formatting instructions for original posts and threads.
    Defaults to include_variants=False to generate 1 crisp post/thread without 4x output token bloat.
    Static format instructions are placed before dynamic context for prefix caching.
    """
    live_feed_context = ""
    if live_tweets:
        snippets = []
        for idx, t in enumerate(live_tweets[:6], 1):
            author = t.get("author") or t.get("tweet_author") or "user"
            txt = (t.get("text") or t.get("tweet_text") or "").replace("\n", " ").strip()
            metrics = t.get("metrics") or t.get("tweet_metrics") or ""
            if txt:
                snippets.append(f"{idx}. @{author} ({metrics}): {txt[:160]}")
        if snippets:
            live_feed_context = "LIVE CONVERSATIONS HAPPENING RIGHT NOW ON X:\n" + "\n".join(snippets)

    memory_context = ""
    if learning_memory and learning_memory.get("approved"):
        samples = [
            str(item.get("reply_text", "")).replace("\n", " ").strip()[:140]
            for item in learning_memory["approved"][:3]
            if item.get("reply_text")
        ]
        if samples:
            memory_context = "USER'S PAST APPROVED VOICE SAMPLES:\n- " + "\n- ".join(samples)

    if mode == "auto":
        if include_variants:
            format_instructions = """Decide autonomously whether the live conversation warrants a punchy standalone X POST ("chosen_mode": "post") OR a 3-post X THREAD ("chosen_mode": "thread").
- Choose "post" (8-30 words, <240 chars) for sharp hot takes, quick observations, or reactions.
- Choose "thread" (3 posts separated by "\\n---\\n", each <240 chars, NO "🧵" or "1/") when breaking down a multi-step insight.
- NEVER use em-dashes (—), semicolons, or AI buzzwords.
- Invent 3 context-specific angle names in "variants".

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "post" or "thread",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the conversation angle",
  "text": "your primary post (or thread separated by \\n---\\n)",
  "variants": {
    "<Custom Angle 1>": "first distinct version",
    "<Custom Angle 2>": "second distinct version",
    "<Custom Angle 3>": "third distinct version"
  }
}"""
        else:
            format_instructions = """Decide autonomously whether the live conversation warrants a punchy standalone X POST ("chosen_mode": "post") OR a 3-post X THREAD ("chosen_mode": "thread").
- Choose "post" (8-30 words, <240 chars) for sharp hot takes, quick observations, or reactions.
- Choose "thread" (3 posts separated by "\\n---\\n", each <240 chars, NO "🧵" or "1/") when breaking down a multi-step insight.
- NEVER use em-dashes (—), semicolons, or AI buzzwords.

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "post" or "thread",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the conversation angle",
  "text": "your single best post (or 3-part thread separated by \\n---\\n)"
}"""
    elif mode == "thread":
        if include_variants:
            format_instructions = """Create an original, high-signal 3-post X THREAD based on the real-time conversation around this topic.
STRICT THREAD RULES:
- Separate each post with exactly "\\n---\\n".
- Each post MUST be under 240 characters (1-2 punchy sentences).
- Post 1 must be a strong natural hook (NO "🧵", NO "1/3", NO "Let's dive in", NO "A thread:").
- NEVER use em-dashes (—), semicolons, or AI buzzwords.
- Invent 3 context-specific angle names in "variants".

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "thread",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of this thread angle",
  "text": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
  "variants": {
    "<Custom Angle 1>": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
    "<Custom Angle 2>": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
    "<Custom Angle 3>": "Post 1\\n---\\nPost 2\\n---\\nPost 3"
  }
}"""
        else:
            format_instructions = """Create ONE original, high-signal 3-post X THREAD based on the real-time conversation around this topic.
STRICT THREAD RULES:
- Separate each post with exactly "\\n---\\n".
- Each post MUST be under 240 characters (1-2 punchy sentences).
- Post 1 must be a strong natural hook (NO "🧵", NO "1/3", NO "Let's dive in", NO "A thread:").
- Posts 2-3 should drop specific insights or sharp takes building on Post 1.
- NEVER use em-dashes (—), semicolons, or AI buzzwords.

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "thread",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of this thread angle",
  "text": "Post 1\\n---\\nPost 2\\n---\\nPost 3"
}"""
    else:
        if include_variants:
            format_instructions = """Create an original, standalone X POST based on the real-time conversation around this topic.
STRICT POST RULES:
- 8 to 30 words max. Under 240 characters.
- Sound like an authentic human insider sharing a sharp observation, hot take, or timely reaction.
- NEVER use hashtags unless essential. NEVER use em-dashes (—), semicolons, or AI buzzwords.
- Invent 3 context-specific angle names in "variants".

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "post",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the angle",
  "text": "your primary standalone post",
  "variants": {
    "<Custom Angle 1>": "first distinct version",
    "<Custom Angle 2>": "second distinct version",
    "<Custom Angle 3>": "third distinct version"
  }
}"""
        else:
            format_instructions = """Create ONE original, standalone X POST based on the real-time conversation around this topic.
STRICT POST RULES:
- 8 to 30 words max. Under 240 characters.
- Sound like an authentic human insider sharing a sharp observation, hot take, or timely reaction.
- NEVER use hashtags unless essential. NEVER use em-dashes (—), semicolons, or AI buzzwords.

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "post",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the angle",
  "text": "your single best standalone post"
}"""

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    prompt = f"""{format_instructions}

Current Date: {today_str}
Topic / Search Pulse: {topic}
Your Voice / Persona: {voice}
{memory_context}
{live_feed_context}"""
    return prompt, format_instructions
