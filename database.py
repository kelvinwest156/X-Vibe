"""
Database session management and query helpers for X-VibeBot.
Uses SQLite via SQLAlchemy with automatic schema migration.
"""

import os
import random
from datetime import datetime, date, timedelta
from typing import Optional, List
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

from models import Base, ProcessedTweet, AgentConfig

DB_FILE = os.getenv("DATABASE_URL", "sqlite:///./vibebot.db")

engine = create_engine(
    DB_FILE,
    connect_args={"check_same_thread": False} if "sqlite" in DB_FILE else {},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initializes database tables, auto-migrates new columns, and seeds default AgentConfig."""
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        try:
            cfg_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(agent_config)").fetchall()]
            migrations_cfg = [
                ("selected_model", "VARCHAR(64) DEFAULT 'gemini-3.8-flash'"),
                ("max_cooldown_minutes", "INTEGER DEFAULT 45"),
                ("active_hours_start", "INTEGER DEFAULT 8"),
                ("active_hours_end", "INTEGER DEFAULT 23"),
                ("persona_prompt", "TEXT DEFAULT 'Casual, sharp, dry humor, short sentences, no corporate buzzwords'"),
                ("linked_username", "VARCHAR(128)")
            ]
            for col_name, col_def in migrations_cfg:
                if col_name not in cfg_cols:
                    conn.exec_driver_sql(f"ALTER TABLE agent_config ADD COLUMN {col_name} {col_def}")
                    conn.commit()

            tweet_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(processed_tweets)").fetchall()]
            migrations_tweet = [
                ("variants_json", "TEXT"),
                ("tweet_metrics", "VARCHAR(128)"),
                ("scheduled_for", "DATETIME")
            ]
            for col_name, col_def in migrations_tweet:
                if col_name not in tweet_cols:
                    conn.exec_driver_sql(f"ALTER TABLE processed_tweets ADD COLUMN {col_name} {col_def}")
                    conn.commit()
        except Exception:
            pass

    db = SessionLocal()
    try:
        config = db.query(AgentConfig).filter(AgentConfig.id == 1).first()
        if not config:
            config = AgentConfig(
                id=1,
                is_active=False,
                auto_pilot_mode=False,
                polling_interval_minutes=20,
                daily_action_cap=15,
                min_cooldown_minutes=10,
                max_cooldown_minutes=45,
                active_hours_start=8,
                active_hours_end=23,
                search_query="buildinpublic OR #ai",
                persona_prompt="Casual, sharp, dry humor, short sentences, no corporate buzzwords",
                selected_model="gemini-3.8-flash"
            )
            db.add(config)
            db.commit()
        else:
            changed = False
            if not config.selected_model or "deepseek" in config.selected_model or config.selected_model == "gemini-2.5-flash":
                config.selected_model = "gemini-3.8-flash"
                changed = True
            if config.max_cooldown_minutes is None:
                config.max_cooldown_minutes = max(30, (config.min_cooldown_minutes or 15) * 2)
                changed = True
            if config.active_hours_start is None:
                config.active_hours_start = 8
                changed = True
            if config.active_hours_end is None:
                config.active_hours_end = 23
                changed = True
            if not config.persona_prompt:
                config.persona_prompt = "Casual, sharp, dry humor, short sentences, no corporate buzzwords"
                changed = True
            if changed:
                db.commit()
    finally:
        db.close()


def get_db():
    """FastAPI dependency to provide a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# Active Hours & Randomized Scheduling Helpers
# ==============================================================================

def is_within_active_hours(start_hour: int = 8, end_hour: int = 23, now_local: Optional[datetime] = None) -> bool:
    """Checks if local time falls within the user's configured active waking hours."""
    if start_hour == end_hour:
        return True  # 24/7 if set identical
    now_dt = now_local or datetime.now()
    hr = now_dt.hour
    if start_hour < end_hour:
        return start_hour <= hr < end_hour
    else:
        # Overnight window (e.g. 22:00 to 06:00)
        return hr >= start_hour or hr < end_hour


def compute_random_schedule_time(db: Session, config: AgentConfig) -> datetime:
    """
    Computes a completely random future UTC timestamp for organic reply scheduling.
    - Staggers after the latest currently scheduled tweet (if any).
    - Adds a randomized delay between [min_cooldown_minutes, max_cooldown_minutes] down to random seconds.
    - Shifts into the next active waking window if the resulting local time falls during sleep hours.
    """
    now_utc = datetime.utcnow()
    latest_scheduled = (
        db.query(func.max(ProcessedTweet.scheduled_for))
        .filter(ProcessedTweet.status == "scheduled")
        .filter(ProcessedTweet.scheduled_for > now_utc)
        .scalar()
    )
    base_utc = latest_scheduled if (latest_scheduled and latest_scheduled > now_utc) else now_utc

    min_sec = max(60, (config.min_cooldown_minutes or 10) * 60)
    max_sec = max(min_sec + 120, (config.max_cooldown_minutes or 45) * 60)
    random_offset_seconds = random.randint(min_sec, max_sec) + random.randint(1, 59)

    target_utc = base_utc + timedelta(seconds=random_offset_seconds)

    # Convert target_utc to local time to verify active hours window
    utc_to_local_offset = datetime.now() - datetime.utcnow()
    target_local = target_utc + utc_to_local_offset

    start_hr = config.active_hours_start if config.active_hours_start is not None else 8
    end_hr = config.active_hours_end if config.active_hours_end is not None else 23

    if not is_within_active_hours(start_hr, end_hr, target_local):
        # Advance to next start_hr plus a random 3-28 minute morning jitter
        next_wake = target_local.replace(hour=start_hr, minute=0, second=0, microsecond=0)
        if next_wake <= target_local:
            next_wake += timedelta(days=1)
        next_wake += timedelta(seconds=random.randint(180, 1680))
        target_utc = next_wake - utc_to_local_offset

    return target_utc


# ==============================================================================
# Helper Queries
# ==============================================================================

def is_tweet_already_processed(db: Session, tweet_id: str) -> bool:
    """
    Returns True if this tweet_id has already been genuinely evaluated or replied to.
    If it was previously skipped solely due to a missing/invalid API key or transient error, allow re-evaluation.
    """
    existing = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if not existing:
        return False
    if existing.status == "skipped" and existing.error_message:
        err_lower = existing.error_message.lower()
        if "api key" in err_lower or "error" in err_lower or "not configured" in err_lower or "503" in err_lower:
            return False
    return True


def record_processed_tweet(
    db: Session,
    tweet_id: str,
    action_type: str,
    tweet_text: Optional[str],
    tweet_author: Optional[str],
    tweet_url: Optional[str],
    generated_text: Optional[str],
    status: str,
    error_message: Optional[str] = None,
    variants_json: Optional[str] = None,
    tweet_metrics: Optional[str] = None,
    scheduled_for: Optional[datetime] = None
) -> ProcessedTweet:
    """Saves a tweet interaction or evaluation record."""
    item = ProcessedTweet(
        tweet_id=tweet_id,
        action_type=action_type,
        tweet_text=tweet_text,
        tweet_author=tweet_author,
        tweet_url=tweet_url,
        generated_text=generated_text,
        variants_json=variants_json,
        tweet_metrics=tweet_metrics,
        status=status,
        scheduled_for=scheduled_for,
        error_message=error_message,
        timestamp=datetime.utcnow()
    )
    db.merge(item)
    db.commit()
    return item


def update_tweet_status(
    db: Session,
    tweet_id: str,
    status: str,
    generated_text: Optional[str] = None,
    error_message: Optional[str] = None,
    variants_json: Optional[str] = None,
    scheduled_for: Optional[datetime] = None
) -> Optional[ProcessedTweet]:
    """Updates the status and optional text/error/schedule of an existing tweet record."""
    item = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if item:
        item.status = status
        if generated_text is not None:
            item.generated_text = generated_text
        if error_message is not None:
            item.error_message = error_message
        if variants_json is not None:
            item.variants_json = variants_json
        if status != "scheduled":
            item.scheduled_for = None
        elif scheduled_for is not None:
            item.scheduled_for = scheduled_for
        db.commit()
        db.refresh(item)
    return item


def get_daily_actions_count(db: Session) -> int:
    """Counts how many actions (replies or posts) were posted today UTC."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    return (
        db.query(func.count(ProcessedTweet.tweet_id))
        .filter(ProcessedTweet.status == "posted")
        .filter(ProcessedTweet.timestamp >= today_start)
        .scalar() or 0
    )


def get_pending_tweets(db: Session) -> List[ProcessedTweet]:
    """Retrieves all tweets waiting for manual approval OR scheduled in the queue."""
    return (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status.in_(["pending_approval", "scheduled"]))
        .order_by(ProcessedTweet.timestamp.desc())
        .all()
    )


def get_due_scheduled_tweets(db: Session) -> List[ProcessedTweet]:
    """Retrieves scheduled tweets whose randomized scheduled_for time has arrived."""
    now_utc = datetime.utcnow()
    return (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status == "scheduled")
        .filter(ProcessedTweet.scheduled_for <= now_utc)
        .order_by(ProcessedTweet.scheduled_for.asc())
        .all()
    )


def get_scheduled_count(db: Session) -> int:
    """Counts how many tweets are currently queued for random future posting."""
    return (
        db.query(func.count(ProcessedTweet.tweet_id))
        .filter(ProcessedTweet.status == "scheduled")
        .scalar() or 0
    )


def get_recent_tweets(db: Session, limit: int = 50) -> List[ProcessedTweet]:
    """Retrieves recent tweet interactions (posted, skipped, failed, pending, scheduled)."""
    return (
        db.query(ProcessedTweet)
        .order_by(ProcessedTweet.timestamp.desc())
        .limit(limit)
        .all()
    )


def get_agent_config(db: Session) -> AgentConfig:
    """Retrieves the singleton agent configuration row."""
    config = db.query(AgentConfig).filter(AgentConfig.id == 1).first()
    if not config:
        config = AgentConfig(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def update_agent_config(db: Session, updates: dict) -> AgentConfig:
    """Updates runtime configuration toggles."""
    config = get_agent_config(db)
    for key, value in updates.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config
