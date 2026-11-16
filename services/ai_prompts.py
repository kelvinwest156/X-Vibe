"""
Prompt Engineering & Few-Shot Voice Memory Formatting Service for X-VibeBot.
Constructs persona instructions, few-shot examples, and anti-robotic guardrails.
"""

import os
from typing import Optional, Dict, Any, List, Tuple


def build_system_prompt(
    search_query: Optional[str] = None,
    persona_prompt: Optional[str] = None,
    learning_memory: Optional[Dict[str, Any]] = None
) -> str:
    """Builds a topic-aware, self-learning, anti-robotic system prompt."""
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

    memory_section = ""
    if learning_memory and isinstance(learning_memory, dict):
        approved_list = learning_memory.get("approved") or []
        skipped_list = learning_memory.get("skipped") or []
        mem_lines = []
        if approved_list:
            mem_lines.append("PAST REPLIES THIS USER APPROVED OR EDITED (match this exact cadence, length, and vibe):")
            for idx, item in enumerate(approved_list[:5], 1):
                tag = "[USER-EDITED GOLD STANDARD]" if item.get("user_edited") else "[APPROVED]"
                mem_lines.append(f"  {idx}. {tag} On post '{item.get('tweet_text', '')}' -> Reply: '{item.get('reply_text', '')}'")
        if skipped_list:
            mem_lines.append("PAST POSTS THIS USER REJECTED/SKIPPED (avoid similar low-signal or off-niche posts):")
            for idx, item in enumerate(skipped_list[:4], 1):
                mem_lines.append(f"  {idx}. Skipped: '{item.get('tweet_text', '')}'")
        if mem_lines:
            memory_section = "\nSELF-LEARNING MEMORY FROM USER HISTORY:\n" + "\n".join(mem_lines) + "\n"

    return f"""You are a real human X (Twitter) user writing authentic replies.
Your voice/persona: {voice_clause}
{memory_section}
Analyze the provided post (including any attached image, quoted text, or engagement metrics).
1. SKIP if the post is spam, ticket-selling scams, betting/crypto promos, engagement bait, or completely unrelated to {topic_clause}.
2. REPLY if it is a genuine opinion, take, question, chart/screenshot, update, or funny moment {topic_clause}.

STRICT ANTI-ROBOTIC & ANTI-DETECTION RULES (CRITICAL):
- NEVER use em-dashes (—), en-dashes (–), or semicolons (;). Real people on X don't type those.
- NEVER start with "Ah,", "Honestly,", "To be fair,", "Indeed,", "Spot on,", "Great point," or end with "Let's see if..." or "Only time will tell."
- NEVER use AI buzzwords: delve, testament, game-changer, landscape, fascinating, undeniable, masterclass, Chef's kiss.
- Do NOT summarize or repeat the author's tweet back to them. Jump straight into your reaction, specific detail from their image/text, or angle.
- Keep it concise: 6 to 22 words max. Sound like a smart insider texting a friend.
- Invent 3 context-specific angle names in "variants" that fit THIS specific post (e.g. "Sharp Observation", "Contrarian", "Technical Follow-Up", "Dry Humor", "One-Liner").

Respond in valid JSON with these exact keys:
{{
  "action": "reply" or "skip",
  "text": "your best primary reply (6-22 words)",
  "variants": {{
    "<Custom Angle 1>": "first distinct reply option (6-20 words)",
    "<Custom Angle 2>": "second distinct reply option (6-20 words)",
    "<Custom Angle 3>": "third distinct reply option (4-15 words)"
  }},
  "should_like": true or false (true if the post is genuinely high-value/funny and worth liking before replying),
  "urgency_score": integer 1 to 10 (9-10 if breaking/viral wave that needs a fast reply; 5 for normal; 1-3 for slow evergreen),
  "reasoning": "brief 1-sentence reason for replying or skipping"
}}
If action is "skip", set "text" to "", "variants" to {{}}, "should_like" to false, and "urgency_score" to 1.
"""


def _build_original_prompt_and_instructions(
    mode: str,
    topic: str,
    voice: str,
    live_tweets: Optional[List[Dict[str, Any]]] = None,
    learning_memory: Optional[Dict[str, Any]] = None
) -> Tuple[str, str]:
    """Helper to assemble prompt and formatting instructions for original posts and threads."""
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

    memory_context = ""
    if learning_memory and learning_memory.get("approved"):
        samples = [item.get("reply_text", "") for item in learning_memory["approved"][:3] if item.get("reply_text")]
        if samples:
            memory_context = "USER'S PAST APPROVED VOICE SAMPLES:\n- " + "\n- ".join(samples)

    if mode == "auto":
        format_instructions = """Decide autonomously whether the current live conversation warrants a single punchy standalone X POST ("chosen_mode": "post") OR a deeper 3-post X THREAD ("chosen_mode": "thread").
- Choose "post" (8-30 words, <240 chars) for sharp hot takes, quick observations, or reactions.
- Choose "thread" (3 posts separated by "\\n---\\n", each <240 chars, NO "🧵" or "1/") when breaking down a multi-step insight or comparison.
- NEVER use em-dashes (—), semicolons, or AI buzzwords.
- Invent 3 context-specific angle names in "variants" (e.g. "Hot Take", "Builder Insight", "Contrarian", "Question").

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "post" or "thread",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the real-time conversation angle",
  "text": "your primary post (or thread separated by \\n---\\n)",
  "variants": {
    "<Custom Angle 1>": "first distinct version",
    "<Custom Angle 2>": "second distinct version",
    "<Custom Angle 3>": "third distinct version"
  }
}"""
    elif mode == "thread":
        format_instructions = """Create an original, high-signal 3 to 4 post X THREAD based on the real-time conversation and current facts around this topic.
STRICT THREAD RULES:
- Separate each post in the thread with exactly "\\n---\\n".
- Each individual post MUST be under 240 characters (1-2 punchy sentences per post).
- Post 1 must be a strong, natural hook (NO "🧵", NO "1/4", NO "Let's dive in", NO "A thread:").
- Posts 2-4 should drop specific insights, real-time observations, or sharp takes that build on the hook.
- NEVER use em-dashes (—), semicolons, or AI buzzwords.
- Invent 3 context-specific angle names in "variants".

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "thread",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the real-time conversation angle this thread covers",
  "text": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
  "variants": {
    "<Custom Angle 1>": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
    "<Custom Angle 2>": "Post 1\\n---\\nPost 2\\n---\\nPost 3",
    "<Custom Angle 3>": "Post 1\\n---\\nPost 2\\n---\\nPost 3"
  }
}"""
    else:
        format_instructions = """Create an original, standalone X POST based on the real-time conversation and current facts around this topic.
STRICT POST RULES:
- 8 to 30 words max. Under 240 characters.
- Sound like an authentic human insider sharing a sharp observation, hot take, or timely reaction.
- NEVER use hashtags unless essential to the topic. NEVER use em-dashes (—), semicolons, or AI buzzwords.
- Invent 3 context-specific angle names in "variants".

Respond ONLY in valid JSON with these exact keys:
{
  "chosen_mode": "post",
  "urgency_score": integer 1 to 10,
  "topic_summary": "1-line summary of the real-time conversation or event this post reacts to",
  "text": "your primary standalone post",
  "variants": {
    "<Custom Angle 1>": "first distinct version",
    "<Custom Angle 2>": "second distinct version",
    "<Custom Angle 3>": "third distinct version"
  }
}"""

    prompt = f"""Topic / Search Pulse: {topic}
Your Voice / Persona: {voice}
Current Date: {os.popen('date /t').read().strip() if os.name == 'nt' else 'Today'}
{memory_context}
{live_feed_context}

{format_instructions}"""
    return prompt, format_instructions
