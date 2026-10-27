"""
Models definition for X-VibeBot.
Defines SQLAlchemy ORM models for database persistence and Pydantic schemas for API request/response validation.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ==============================================================================
# SQLAlchemy ORM Models (Stored in SQLite)
# ==============================================================================

class ProcessedTweet(Base):
    """
    Stores all scraped, evaluated, pending, scheduled, and published tweets.
    Acts as a persistent audit log and prevents duplicate interactions.
    """
    __tablename__ = "processed_tweets"

    tweet_id = Column(String(64), primary_key=True, index=True)
    action_type = Column(String(32), default="reply")  # "reply" or "post"
    tweet_text = Column(Text, nullable=True)           # Original scraped tweet
    tweet_author = Column(String(128), nullable=True)  # @handle
    tweet_url = Column(String(512), nullable=True)     # Link to tweet
    generated_text = Column(Text, nullable=True)       # Primary AI generated reply
    variants_json = Column(Text, nullable=True)        # JSON of {"witty": ..., "question": ..., "punchy": ...}
    tweet_metrics = Column(String(128), nullable=True) # Engagement summary (e.g. "24 likes · 5 replies")
    media_url = Column(String(512), nullable=True)     # Attached tweet image URL for Gemini Vision & UI preview
    should_like = Column(Boolean, default=False)       # AI decision whether to naturally like before replying
    urgency_score = Column(Integer, default=5)         # 1-10 AI urgency score (high = breaking wave, schedule sooner)
    user_edited = Column(Boolean, default=False)       # True if human edited the draft before approving (prioritized in memory)
    status = Column(String(32), default="pending_approval", index=True)  # "pending_approval", "scheduled", "posted", "skipped", "failed"
    scheduled_for = Column(DateTime, nullable=True)    # Randomized future UTC time for organic posting
    error_message = Column(Text, nullable=True)        # AI reasoning or error reason
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class AgentConfig(Base):
    """
    Persists runtime configuration toggles for the bot in SQLite.
    Maintains a single configuration record (id=1).
    """
    __tablename__ = "agent_config"

    id = Column(Integer, primary_key=True, default=1)
    is_active = Column(Boolean, default=False)                # Master switch
    auto_pilot_mode = Column(Boolean, default=False)          # Human-in-the-loop vs random auto-schedule
    polling_interval_minutes = Column(Integer, default=20)    # Base interval between scans (jittered randomly)
    daily_action_cap = Column(Integer, default=15)            # Max daily interactions
    hourly_action_cap = Column(Integer, default=6)            # Rolling 60-min anti-detection velocity cap (<10/hr safe zone)
    min_cooldown_minutes = Column(Integer, default=10)        # Min random delay (minutes)
    max_cooldown_minutes = Column(Integer, default=45)        # Max random delay (minutes)
    active_hours_start = Column(Integer, default=8)           # Waking hours start (0-23 local hour, e.g. 8 AM)
    active_hours_end = Column(Integer, default=23)            # Waking hours end (0-23 local hour, e.g. 11 PM)
    search_query = Column(String(256), default="buildinpublic OR #ai")
    smart_query_enabled = Column(Boolean, default=True)       # Let AI + Google Search invent fresh search queries per scan
    warmup_mode = Column(Boolean, default=False)              # Gentle account warmup mode (caps daily to 5 & widens delays)
    persona_prompt = Column(Text, default="Casual, sharp, dry humor, short sentences, no corporate buzzwords")
    selected_model = Column(String(64), default="gemini-3.8-flash")
    linked_username = Column(String(128), nullable=True)       # Detected @handle of logged-in X account
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==============================================================================
# Pydantic Schemas (FastAPI API validation & serialization)
# ==============================================================================

class ProcessedTweetBase(BaseModel):
    tweet_id: str
    action_type: str = "reply"
    tweet_text: Optional[str] = None
    tweet_author: Optional[str] = None
    tweet_url: Optional[str] = None
    generated_text: Optional[str] = None
    variants_json: Optional[str] = None
    tweet_metrics: Optional[str] = None
    media_url: Optional[str] = None
    should_like: Optional[bool] = False
    urgency_score: Optional[int] = 5
    user_edited: Optional[bool] = False
    status: str = "pending_approval"
    scheduled_for: Optional[datetime] = None
    error_message: Optional[str] = None


class ProcessedTweetResponse(ProcessedTweetBase):
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentConfigUpdate(BaseModel):
    is_active: Optional[bool] = None
    auto_pilot_mode: Optional[bool] = None
    polling_interval_minutes: Optional[int] = None
    daily_action_cap: Optional[int] = None
    hourly_action_cap: Optional[int] = None
    min_cooldown_minutes: Optional[int] = None
    max_cooldown_minutes: Optional[int] = None
    active_hours_start: Optional[int] = None
    active_hours_end: Optional[int] = None
    search_query: Optional[str] = None
    smart_query_enabled: Optional[bool] = None
    warmup_mode: Optional[bool] = None
    persona_prompt: Optional[str] = None
    selected_model: Optional[str] = None
    api_key: Optional[str] = None


class AgentConfigResponse(BaseModel):
    id: int
    is_active: bool
    auto_pilot_mode: bool
    polling_interval_minutes: int
    daily_action_cap: int
    hourly_action_cap: int = 6
    min_cooldown_minutes: int
    max_cooldown_minutes: int
    active_hours_start: int
    active_hours_end: int
    search_query: str
    smart_query_enabled: bool = True
    warmup_mode: bool = False
    persona_prompt: Optional[str] = None
    selected_model: str
    linked_username: Optional[str] = None
    masked_api_key: Optional[str] = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ApproveDraftRequest(BaseModel):
    custom_text: Optional[str] = None
    schedule_random: bool = False


class SystemLogEntry(BaseModel):
    timestamp: str
    level: str
    message: str


class AgentStatusResponse(BaseModel):
    is_active: bool
    auto_pilot_mode: bool
    polling_interval_minutes: int
    daily_action_cap: int
    daily_actions_used: int
    hourly_action_cap: int = 6
    hourly_actions_used: int = 0
    smart_query_enabled: bool = True
    warmup_mode: bool = False
    active_search_query: Optional[str] = None
    learned_examples_count: int = 0
    cooldown_active: bool
    cooldown_seconds_remaining: int
    within_active_hours: bool
    scheduled_count: int
    browser_connected: bool
    is_logged_in: bool
    linked_username: Optional[str] = None
    pending_approvals_count: int
    total_processed_count: int
    selected_model: str
    recent_logs: List[SystemLogEntry]
