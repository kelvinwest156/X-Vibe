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
    Stores all scraped, evaluated, pending, and published tweets.
    Acts as a persistent audit log and prevents duplicate interactions.
    """
    __tablename__ = "processed_tweets"

    tweet_id = Column(String(64), primary_key=True, index=True)
    action_type = Column(String(32), default="reply")  # "reply" or "post"
    tweet_text = Column(Text, nullable=True)           # Original scraped tweet
    tweet_author = Column(String(128), nullable=True)  # @handle
    tweet_url = Column(String(512), nullable=True)     # Link to tweet
    generated_text = Column(Text, nullable=True)       # DeepSeek generated reply
    status = Column(String(32), default="pending_approval", index=True)  # "pending_approval", "posted", "skipped", "failed"
    error_message = Column(Text, nullable=True)        # If failed, store error reason
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class AgentConfig(Base):
    """
    Persists runtime configuration toggles for the bot in SQLite.
    Maintains a single configuration record (id=1).
    """
    __tablename__ = "agent_config"

    id = Column(Integer, primary_key=True, default=1)
    is_active = Column(Boolean, default=False)                # Master switch
    auto_pilot_mode = Column(Boolean, default=False)          # Human-in-the-loop toggle
    polling_interval_minutes = Column(Integer, default=15)    # Delay between background runs
    daily_action_cap = Column(Integer, default=15)            # Max daily interactions (anti-suspension)
    min_cooldown_minutes = Column(Integer, default=15)        # Min delay between individual posts
    search_query = Column(String(256), default="buildinpublic OR #ai")
    selected_model = Column(String(64), default="gemini-2.5-flash") # Chosen AI model
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
    status: str = "pending_approval"
    error_message: Optional[str] = None


class ProcessedTweetResponse(ProcessedTweetBase):
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentConfigUpdate(BaseModel):
    is_active: Optional[bool] = None
    auto_pilot_mode: Optional[bool] = None
    polling_interval_minutes: Optional[int] = None
    daily_action_cap: Optional[int] = None
    min_cooldown_minutes: Optional[int] = None
    search_query: Optional[str] = None
    selected_model: Optional[str] = None
    api_key: Optional[str] = None


class AgentConfigResponse(BaseModel):
    id: int
    is_active: bool
    auto_pilot_mode: bool
    polling_interval_minutes: int
    daily_action_cap: int
    min_cooldown_minutes: int
    search_query: str
    selected_model: str
    masked_api_key: Optional[str] = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ApproveDraftRequest(BaseModel):
    custom_text: Optional[str] = None  # User can edit the AI draft before approving


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
    cooldown_active: bool
    cooldown_seconds_remaining: int
    browser_connected: bool
    is_logged_in: bool
    pending_approvals_count: int
    total_processed_count: int
    selected_model: str
    recent_logs: List[SystemLogEntry]
