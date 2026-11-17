"""
Data Models & Schema Definitions for X-VibeBot.
Defines SQLAlchemy ORM models for database persistence and Pydantic v2 schemas
for API request validation and response serialization.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ==============================================================================
# SQLAlchemy ORM Models (Persistent State in SQLite / PostgreSQL)
# ==============================================================================

class ProcessedTweet(Base):
    """
    Stores all scraped, evaluated, pending, scheduled, and published tweets.
    Acts as a persistent audit log, multi-tenant state repository, and prevents duplicate interactions.
    """
    __tablename__ = "processed_tweets"

    tweet_id = Column(String(64), primary_key=True, index=True)
    tenant_id = Column(String(128), default="default", index=True, nullable=False)
    action_type = Column(String(32), default="reply")  # "reply", "post", or "thread"
    tweet_text = Column(Text, nullable=True)           # Original scraped tweet or prompt topic
    tweet_author = Column(String(128), nullable=True)  # @handle of the original poster
    tweet_url = Column(String(512), nullable=True)     # Direct link to post on X
    generated_text = Column(Text, nullable=True)       # Primary AI generated reply or standalone post
    variants_json = Column(Text, nullable=True)        # JSON dictionary of angle variants e.g. {"Hot Take": ...}
    tweet_metrics = Column(String(128), nullable=True) # Engagement snapshot e.g. "24 likes · 5 replies"
    media_url = Column(String(512), nullable=True)     # Attached tweet image URL for Multimodal Vision & UI preview
    should_like = Column(Boolean, default=False)       # AI decision whether to naturally like before replying
    urgency_score = Column(Integer, default=5)         # 1-10 AI urgency score (9-10 = breaking viral wave)
    user_edited = Column(Boolean, default=False)       # True if human edited before approving (prioritized in few-shot memory)
    status = Column(String(32), default="pending_approval", index=True)  # "pending_approval", "scheduled", "posted", "skipped", "failed"
    scheduled_for = Column(DateTime, nullable=True)    # Randomized future UTC time for organic posting
    error_message = Column(Text, nullable=True)        # AI reasoning or failure message
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    def is_due(self, now: Optional[datetime] = None) -> bool:
        """Checks if a scheduled tweet is due for immediate organic dispatch."""
        if self.status != "scheduled" or not self.scheduled_for:
            return False
        current_time = now or datetime.utcnow()
        return current_time >= self.scheduled_for

    def is_terminal(self) -> bool:
        """Returns True if the tweet interaction has reached a terminal state."""
        return self.status in ("posted", "skipped", "failed")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ORM instance into a clean Python dictionary."""
        return {
            "tweet_id": self.tweet_id,
            "tenant_id": self.tenant_id,
            "action_type": self.action_type,
            "tweet_text": self.tweet_text,
            "tweet_author": self.tweet_author,
            "tweet_url": self.tweet_url,
            "generated_text": self.generated_text,
            "variants_json": self.variants_json,
            "tweet_metrics": self.tweet_metrics,
            "media_url": self.media_url,
            "should_like": self.should_like,
            "urgency_score": self.urgency_score,
            "user_edited": self.user_edited,
            "status": self.status,
            "scheduled_for": self.scheduled_for.isoformat() if self.scheduled_for else None,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class AgentConfig(Base):
    """
    Persists runtime configuration toggles for the bot in SQLite.
    Maintains a configuration record per tenant_id (default='default').
    """
    __tablename__ = "agent_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(128), default="default", unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=False)                # Master switch enabling background scanner
    auto_pilot_mode = Column(Boolean, default=False)          # Human-in-the-loop vs autonomous auto-schedule
    polling_interval_minutes = Column(Integer, default=20)    # Base interval between scans (randomly jittered)
    daily_action_cap = Column(Integer, default=15)            # Max daily interactions permitted
    hourly_action_cap = Column(Integer, default=6)            # Rolling 60-min velocity cap (<10/hr safe zone)
    min_cooldown_minutes = Column(Integer, default=10)        # Min delay between actions (minutes)
    max_cooldown_minutes = Column(Integer, default=45)        # Max delay between actions (minutes)
    active_hours_start = Column(Integer, default=8)           # Waking hours start (0-23 local hour, e.g. 8 AM)
    active_hours_end = Column(Integer, default=23)            # Waking hours end (0-23 local hour, e.g. 11 PM)
    search_query = Column(String(256), default="buildinpublic OR #ai") # High-level niche keyword
    smart_query_enabled = Column(Boolean, default=True)       # Let AI + Google Search invent fresh queries per scan
    warmup_mode = Column(Boolean, default=False)              # Gentle account warmup mode (caps daily to 8 & widens delays)
    persona_prompt = Column(Text, default="Casual, sharp, dry humor, short sentences, no corporate buzzwords")
    selected_model = Column(String(64), default="gemini-3.8-flash")
    linked_username = Column(String(128), nullable=True)       # Detected @handle of logged-in X account
    cookies_json = Column(Text, nullable=True)                 # Persisted session cookies for surviving cloud container restarts
    api_key = Column(String(512), nullable=True)              # Persisted Gemini or DeepSeek API key
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def effective_daily_cap(self) -> int:
        """Calculates effective daily action ceiling considering warmup restrictions."""
        if self.warmup_mode:
            return min(8, self.daily_action_cap or 15)
        return self.daily_action_cap or 15

    def effective_hourly_cap(self) -> int:
        """Calculates effective hourly velocity ceiling considering warmup restrictions."""
        if self.warmup_mode:
            return 3
        return self.hourly_action_cap or 6


class User(Base):
    """
    Stores authenticated creator accounts for Multi-Tenancy and Access Control.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(128), nullable=True)
    tenant_id = Column(String(128), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_response(self) -> "UserResponse":
        """Converts ORM User model to UserResponse schema."""
        return UserResponse(
            uid=self.user_id,
            email=self.email,
            name=self.name,
            tenant_id=self.tenant_id,
            created_at=self.created_at
        )


# ==============================================================================
# Pydantic Schemas: Request Payloads (FastAPI validation)
# ==============================================================================

class SignUpRequest(BaseModel):
    """Payload for registering a new creator tenant account."""
    email: str = Field(..., description="Creator email address")
    password: str = Field(..., min_length=6, description="Account password (min 6 chars)")
    name: Optional[str] = Field(None, description="Creator display name")


class SignInRequest(BaseModel):
    """Payload for authenticating an existing creator."""
    email: str = Field(..., description="Creator email address")
    password: str = Field(..., description="Account password")


class ForgotPasswordRequest(BaseModel):
    """Payload for requesting a password reset token/link."""
    email: str = Field(..., description="Creator email address")
    app_url: Optional[str] = Field(None, description="Client origin URL for reset link construction")


class ForgotPasswordResponse(BaseModel):
    """Result of requesting password reset."""
    success: bool
    message: str
    reset_token: Optional[str] = None  # Returned for seamless local/self-hosted reset


class ResetPasswordRequest(BaseModel):
    """Payload for updating password with a signed reset token."""
    token: str = Field(..., description="Signed password reset token")
    new_password: str = Field(..., min_length=6, description="New password (min 6 chars)")


class AgentConfigUpdate(BaseModel):
    """Payload for updating runtime configuration toggles."""
    is_active: Optional[bool] = Field(None, description="Master background scanning toggle")
    auto_pilot_mode: Optional[bool] = Field(None, description="Enable autonomous auto-scheduling")
    polling_interval_minutes: Optional[int] = Field(None, ge=5, le=180, description="Base scan interval in minutes")
    daily_action_cap: Optional[int] = Field(None, ge=1, le=50, description="Maximum posts/replies allowed per day")
    hourly_action_cap: Optional[int] = Field(None, ge=1, le=15, description="Maximum posts/replies allowed per hour")
    min_cooldown_minutes: Optional[int] = Field(None, ge=1, le=120, description="Minimum random post delay")
    max_cooldown_minutes: Optional[int] = Field(None, ge=5, le=240, description="Maximum random post delay")
    active_hours_start: Optional[int] = Field(None, ge=0, le=23, description="Local waking hour start (0-23)")
    active_hours_end: Optional[int] = Field(None, ge=0, le=23, description="Local waking hour end (0-23)")
    search_query: Optional[str] = Field(None, max_length=256, description="Target niche topic or keywords")
    smart_query_enabled: Optional[bool] = Field(None, description="Enable autonomous Google Search trend discovery")
    warmup_mode: Optional[bool] = Field(None, description="Activate gentle anti-detection account warmup")
    persona_prompt: Optional[str] = Field(None, description="Voice and tone instructions for the AI")
    selected_model: Optional[str] = Field(None, description="Model ID e.g. gemini-3.8-flash")
    api_key: Optional[str] = Field(None, description="Optional custom Gemini or DeepSeek API key")


class ApproveDraftRequest(BaseModel):
    """Payload for approving, editing, or scheduling a draft in the queue."""
    custom_text: Optional[str] = Field(None, description="Human-edited replacement text for the draft")
    schedule_random: bool = Field(False, description="Schedule for randomized future organic delivery")
    should_like: Optional[bool] = Field(None, description="Override AI like decision (True/False)")


class ConnectSessionPayload(BaseModel):
    """Payload for importing an X browser session via cookies or tokens."""
    auth_token: Optional[str] = Field(None, description="X auth_token cookie value")
    ct0: Optional[str] = Field(None, description="X ct0 CSRF cookie value")
    raw_cookies: Optional[str] = Field(None, description="Raw Netscape or JSON cookie string")
    cookies: Optional[List[Dict[str, Any]]] = Field(None, description="Structured cookie dictionary list")


class CookiesImportPayload(BaseModel):
    """Payload for restoring cookies directly into the browser profile."""
    cookies: List[Dict[str, Any]] = Field(..., description="List of cookie dictionaries")


class TestKeyPayload(BaseModel):
    """Payload for testing Gemini or DeepSeek credentials."""
    api_key: Optional[str] = Field(None, description="API key to validate")


class GenerateOriginalPayload(BaseModel):
    """Payload for generating an on-demand original post or thread."""
    mode: str = Field("auto", description="Generation mode: 'auto', 'post', or 'thread'")
    custom_topic: Optional[str] = Field(None, description="Optional custom topic or pulse to write about")


class TopicDraftPayload(BaseModel):
    """Payload for turning a Google News radar trend into a draft."""
    title: str = Field(..., description="News story headline")
    source: str = Field(..., description="Publisher name")
    url: str = Field(..., description="Article URL")
    hook_summary: Optional[str] = Field("", description="Story summary hook")
    suggested_query: Optional[str] = Field("", description="Suggested X search query")
    draft_type: Optional[str] = Field("tweet", description="'tweet' or 'thread'")


# ==============================================================================
# Pydantic Schemas: Response Models (FastAPI serialization)
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
    """API response model for processed tweets and queue items."""
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentConfigResponse(BaseModel):
    """API response model representing tenant bot configuration."""
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


class SystemLogEntry(BaseModel):
    """Single diagnostic log entry returned in live telemetry streams."""
    timestamp: str
    level: str
    message: str


class AgentStatusResponse(BaseModel):
    """Complete runtime diagnostic and KPI telemetry response."""
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
    active_hours_start: int = 8
    active_hours_end: int = 23
    scheduled_count: int
    browser_connected: bool
    is_logged_in: bool
    linked_username: Optional[str] = None
    pending_approvals_count: int
    total_processed_count: int
    selected_model: str
    recent_logs: List[SystemLogEntry]


class UserResponse(BaseModel):
    """Sanitized creator profile representation."""
    uid: str
    email: str
    name: Optional[str] = None
    tenant_id: str
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    """Authentication reply with signed session token and user details."""
    success: bool
    token: str
    user: UserResponse
    tenant_id: str
    message: str


class AIModelInfo(BaseModel):
    """Metadata describing an available AI model option."""
    id: str
    name: str
    description: str


class AITestResponse(BaseModel):
    """Result of testing AI API credentials."""
    success: bool
    provider: str
    error: Optional[str] = None
    hint: Optional[str] = None
    models: List[AIModelInfo] = []


class StrategyBriefResponse(BaseModel):
    """Executive AI Strategy Brief for telemetry dashboard."""
    headline: str
    insight: str
    recommended_action: str
    suggested_query: str


class RadarTopicResponse(BaseModel):
    """Google News trending topic discovered by web scout."""
    title: str
    source: str
    link: str
    pub_date: Optional[str] = None
    raw_title: Optional[str] = None


class GenericActionResponse(BaseModel):
    """Standard success/failure response envelope."""
    status: str
    message: Optional[str] = None
    detail: Optional[Any] = None
