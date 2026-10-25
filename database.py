"""
Database session management and query helpers for X-VibeBot.
Uses SQLite via SQLAlchemy.
"""

import os
from datetime import datetime, date
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
    """Initializes database tables and seeds default AgentConfig if empty."""
    Base.metadata.create_all(bind=engine)
    
    # Auto-migration: check if selected_model exists in agent_config
    with engine.connect() as conn:
        try:
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(agent_config)").fetchall()]
            if "selected_model" not in columns:
                conn.exec_driver_sql("ALTER TABLE agent_config ADD COLUMN selected_model VARCHAR(64) DEFAULT 'deepseek-chat'")
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
                polling_interval_minutes=15,
                daily_action_cap=15,
                min_cooldown_minutes=15,
                search_query="buildinpublic OR #ai OR #python",
                selected_model="gemini-2.5-flash"
            )
            db.add(config)
            db.commit()
        elif config.selected_model and "deepseek" in config.selected_model:
            config.selected_model = "gemini-2.5-flash"
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
# Helper Queries
# ==============================================================================

def is_tweet_already_processed(db: Session, tweet_id: str) -> bool:
    """Returns True if this tweet_id has already been evaluated or replied to."""
    return db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first() is not None


def record_processed_tweet(
    db: Session,
    tweet_id: str,
    action_type: str,
    tweet_text: Optional[str],
    tweet_author: Optional[str],
    tweet_url: Optional[str],
    generated_text: Optional[str],
    status: str,
    error_message: Optional[str] = None
) -> ProcessedTweet:
    """Saves a tweet interaction or evaluation record."""
    item = ProcessedTweet(
        tweet_id=tweet_id,
        action_type=action_type,
        tweet_text=tweet_text,
        tweet_author=tweet_author,
        tweet_url=tweet_url,
        generated_text=generated_text,
        status=status,
        error_message=error_message,
        timestamp=datetime.utcnow()
    )
    db.merge(item)  # Insert or update
    db.commit()
    return item


def update_tweet_status(
    db: Session,
    tweet_id: str,
    status: str,
    generated_text: Optional[str] = None,
    error_message: Optional[str] = None
) -> Optional[ProcessedTweet]:
    """Updates the status and optional text/error of an existing tweet record."""
    item = db.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == tweet_id).first()
    if item:
        item.status = status
        if generated_text is not None:
            item.generated_text = generated_text
        if error_message is not None:
            item.error_message = error_message
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
    """Retrieves all tweets waiting for manual user approval."""
    return (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status == "pending_approval")
        .order_by(ProcessedTweet.timestamp.desc())
        .all()
    )


def get_recent_tweets(db: Session, limit: int = 50) -> List[ProcessedTweet]:
    """Retrieves recent tweet interactions (posted, skipped, failed, pending)."""
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
