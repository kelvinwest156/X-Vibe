"""
Database session management and query helpers for X-VibeBot.
Uses SQLite via SQLAlchemy with automatic schema migration.
"""

import os
import re
import random
import hashlib
import hmac
import base64
import json
import secrets
import time
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

from models import Base, ProcessedTweet, AgentConfig, User

AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "x-vibebot-creator-studio-secret-key-salt-2026")

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
                ("tenant_id", "VARCHAR(128) DEFAULT 'default'"),
                ("selected_model", "VARCHAR(64) DEFAULT 'gemini-3.8-flash'"),
                ("max_cooldown_minutes", "INTEGER DEFAULT 45"),
                ("active_hours_start", "INTEGER DEFAULT 8"),
                ("active_hours_end", "INTEGER DEFAULT 23"),
                ("persona_prompt", "TEXT DEFAULT 'Casual, sharp, dry humor, short sentences, no corporate buzzwords'"),
                ("linked_username", "VARCHAR(128)"),
                ("hourly_action_cap", "INTEGER DEFAULT 6"),
                ("smart_query_enabled", "BOOLEAN DEFAULT 1"),
                ("warmup_mode", "BOOLEAN DEFAULT 0"),
            ]
            for col_name, col_def in migrations_cfg:
                if col_name not in cfg_cols:
                    conn.exec_driver_sql(f"ALTER TABLE agent_config ADD COLUMN {col_name} {col_def}")
                    conn.commit()

            tweet_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(processed_tweets)").fetchall()]
            migrations_tweet = [
                ("tenant_id", "VARCHAR(128) DEFAULT 'default'"),
                ("variants_json", "TEXT"),
                ("tweet_metrics", "VARCHAR(128)"),
                ("scheduled_for", "DATETIME"),
                ("media_url", "VARCHAR(512)"),
                ("should_like", "BOOLEAN DEFAULT 0"),
                ("urgency_score", "INTEGER DEFAULT 5"),
                ("user_edited", "BOOLEAN DEFAULT 0"),
            ]
            for col_name, col_def in migrations_tweet:
                if col_name not in tweet_cols:
                    conn.exec_driver_sql(f"ALTER TABLE processed_tweets ADD COLUMN {col_name} {col_def}")
                    conn.commit()
        except Exception:
            pass

    db = SessionLocal()
    try:
        config = db.query(AgentConfig).filter((AgentConfig.id == 1) | (AgentConfig.tenant_id == "default")).first()
        if not config:
            config = AgentConfig(
                id=1,
                tenant_id="default",
                is_active=False,
                auto_pilot_mode=False,
                polling_interval_minutes=20,
                daily_action_cap=15,
                hourly_action_cap=6,
                min_cooldown_minutes=10,
                max_cooldown_minutes=45,
                active_hours_start=8,
                active_hours_end=23,
                search_query="buildinpublic OR #ai",
                smart_query_enabled=True,
                warmup_mode=False,
                persona_prompt="Casual, sharp, dry humor, short sentences, no corporate buzzwords",
                selected_model="gemini-3.8-flash"
            )
            db.add(config)
            db.commit()
        else:
            changed = False
            if not getattr(config, "tenant_id", None):
                config.tenant_id = "default"
                changed = True
            if not config.selected_model or "deepseek" in config.selected_model or config.selected_model == "gemini-2.5-flash":
                config.selected_model = "gemini-3.8-flash"
                changed = True
            if config.max_cooldown_minutes is None:
                config.max_cooldown_minutes = max(30, (config.min_cooldown_minutes or 15) * 2)
                changed = True
            if config.hourly_action_cap is None:
                config.hourly_action_cap = 6
                changed = True
            if config.smart_query_enabled is None:
                config.smart_query_enabled = True
                changed = True
            if config.warmup_mode is None:
                config.warmup_mode = False
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


def compute_random_schedule_time(db: Session, config: AgentConfig, urgency_score: int = 5) -> datetime:
    """
    Computes an urgency-aware randomized future UTC timestamp for organic reply scheduling.
    - Staggers after the latest currently scheduled tweet (if any).
    - Scales delay between [min_cooldown_minutes, max_cooldown_minutes] using AI urgency_score (1-10):
      High urgency (8-10) schedules faster (20%-45% of window) to catch breaking conversation waves;
      Low urgency (1-3) schedules slower (60%-100% of window).
    - Multiplies delay by 1.5x if warmup_mode is enabled.
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
    span = max(60, max_sec - min_sec)

    urgency = max(1, min(10, int(urgency_score or 5)))
    if urgency >= 8:
        low_bound = min_sec + int(span * 0.15)
        high_bound = min_sec + int(span * 0.45)
    elif urgency <= 3:
        low_bound = min_sec + int(span * 0.60)
        high_bound = max_sec
    else:
        low_bound = min_sec
        high_bound = max_sec

    random_offset_seconds = random.randint(low_bound, max(low_bound + 30, high_bound)) + random.randint(1, 59)
    if getattr(config, "warmup_mode", False):
        random_offset_seconds = int(random_offset_seconds * 1.5)

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

def is_tweet_already_processed(db: Session, tweet_id: str, tenant_id: str = "default") -> bool:
    """
    Returns True if this tweet_id has already been genuinely evaluated or replied to for this tenant.
    If it was previously skipped solely due to a missing/invalid API key or transient error, allow re-evaluation.
    """
    existing = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.tweet_id == tweet_id, ProcessedTweet.tenant_id == tenant_id)
        .first()
    )
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
    scheduled_for: Optional[datetime] = None,
    media_url: Optional[str] = None,
    should_like: Optional[bool] = False,
    urgency_score: Optional[int] = 5,
    user_edited: Optional[bool] = False,
    tenant_id: str = "default"
) -> ProcessedTweet:
    """Saves a tweet interaction or evaluation record scoped to a tenant."""
    item = ProcessedTweet(
        tweet_id=tweet_id,
        tenant_id=tenant_id,
        action_type=action_type,
        tweet_text=tweet_text,
        tweet_author=tweet_author,
        tweet_url=tweet_url,
        media_url=media_url,
        generated_text=generated_text,
        variants_json=variants_json,
        tweet_metrics=tweet_metrics,
        should_like=bool(should_like),
        urgency_score=int(urgency_score if urgency_score is not None else 5),
        user_edited=bool(user_edited),
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
    scheduled_for: Optional[datetime] = None,
    user_edited: Optional[bool] = None,
    should_like: Optional[bool] = None
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
        if user_edited is not None:
            item.user_edited = user_edited
        if should_like is not None:
            item.should_like = should_like
        if status != "scheduled":
            item.scheduled_for = None
        elif scheduled_for is not None:
            item.scheduled_for = scheduled_for
        db.commit()
        db.refresh(item)
    return item


def get_daily_actions_count(db: Session, tenant_id: Optional[str] = None) -> int:
    """Counts how many actions (replies or posts) were posted today UTC."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    q = db.query(func.count(ProcessedTweet.tweet_id)).filter(
        ProcessedTweet.status == "posted",
        ProcessedTweet.timestamp >= today_start
    )
    if tenant_id:
        if tenant_id != "default":
            q = q.filter(ProcessedTweet.tenant_id.in_([tenant_id, "default"]))
        else:
            q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return q.scalar() or 0


def get_hourly_actions_count(db: Session, tenant_id: Optional[str] = None) -> int:
    """Counts how many actions were posted in the rolling last 60 minutes (anti-detection velocity cap)."""
    one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
    q = db.query(func.count(ProcessedTweet.tweet_id)).filter(
        ProcessedTweet.status == "posted",
        ProcessedTweet.timestamp >= one_hour_ago
    )
    if tenant_id:
        if tenant_id != "default":
            q = q.filter(ProcessedTweet.tenant_id.in_([tenant_id, "default"]))
        else:
            q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return q.scalar() or 0


def get_learning_memory(db: Session, limit_approved: int = 5, limit_skipped: int = 5, tenant_id: Optional[str] = None) -> dict:
    """
    Retrieves recent approved/posted drafts (prioritizing user-edited replies) and skipped tweets
    so the AI engine can continuously learn the user's exact voice and preferences.
    """
    q_app = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status.in_(["posted", "scheduled"]))
        .filter(ProcessedTweet.generated_text.isnot(None))
    )
    q_skip = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status == "skipped")
        .filter(ProcessedTweet.tweet_text.isnot(None))
    )
    q_total = (
        db.query(func.count(ProcessedTweet.tweet_id))
        .filter(ProcessedTweet.status.in_(["posted", "scheduled"]))
        .filter(ProcessedTweet.generated_text.isnot(None))
    )

    if tenant_id and tenant_id != "default":
        approved_rows = (
            q_app.filter(ProcessedTweet.tenant_id == tenant_id)
            .order_by(ProcessedTweet.user_edited.desc(), ProcessedTweet.timestamp.desc())
            .limit(limit_approved)
            .all()
        )
        if not approved_rows:
            approved_rows = (
                q_app.filter(ProcessedTweet.tenant_id == "default")
                .order_by(ProcessedTweet.user_edited.desc(), ProcessedTweet.timestamp.desc())
                .limit(limit_approved)
                .all()
            )
        skipped_rows = (
            q_skip.filter(ProcessedTweet.tenant_id == tenant_id)
            .order_by(ProcessedTweet.timestamp.desc())
            .limit(limit_skipped)
            .all()
        )
        if not skipped_rows:
            skipped_rows = (
                q_skip.filter(ProcessedTweet.tenant_id == "default")
                .order_by(ProcessedTweet.timestamp.desc())
                .limit(limit_skipped)
                .all()
            )
        total_learned = q_total.filter(ProcessedTweet.tenant_id == tenant_id).scalar() or 0
        if total_learned == 0:
            total_learned = q_total.filter(ProcessedTweet.tenant_id == "default").scalar() or 0
    else:
        if tenant_id == "default":
            q_app = q_app.filter(ProcessedTweet.tenant_id == "default")
            q_skip = q_skip.filter(ProcessedTweet.tenant_id == "default")
            q_total = q_total.filter(ProcessedTweet.tenant_id == "default")
        approved_rows = q_app.order_by(ProcessedTweet.user_edited.desc(), ProcessedTweet.timestamp.desc()).limit(limit_approved).all()
        skipped_rows = q_skip.order_by(ProcessedTweet.timestamp.desc()).limit(limit_skipped).all()
        total_learned = q_total.scalar() or 0

    return {
        "approved": [
            {
                "tweet_text": (r.tweet_text or "")[:180],
                "reply_text": (r.generated_text or "")[:240],
                "user_edited": bool(r.user_edited),
            }
            for r in approved_rows
            if r.generated_text
        ],
        "skipped": [
            {
                "tweet_text": (r.tweet_text or "")[:180],
                "reason": (r.error_message or "Low value / off-niche")[:120],
            }
            for r in skipped_rows
            if r.tweet_text
        ],
        "total_learned": total_learned,
    }


def is_reply_too_similar(db: Session, candidate_text: str, tenant_id: Optional[str] = None) -> bool:
    """
    Anti-Detection Duplicate & Template Guard:
    Checks whether a candidate reply shares the exact same 3-word opening prefix
    or >65% Jaccard word overlap with any of the last 20 posted/scheduled drafts.
    """
    if not candidate_text or not candidate_text.strip():
        return False
    clean_cand = candidate_text.strip().lower()
    cand_words = [w.strip(".,!?:;\"'()[]{}") for w in clean_cand.split() if w.strip(".,!?:;\"'()[]{}")]
    if not cand_words:
        return False
    cand_prefix = " ".join(cand_words[:3]) if len(cand_words) >= 3 else ""
    cand_set = set(cand_words)

    q = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.status.in_(["posted", "scheduled", "pending_approval"]))
        .filter(ProcessedTweet.generated_text.isnot(None))
    )
    if tenant_id:
        if tenant_id != "default":
            q = q.filter(ProcessedTweet.tenant_id.in_([tenant_id, "default"]))
        else:
            q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    recent_items = q.order_by(ProcessedTweet.timestamp.desc()).limit(20).all()

    for item in recent_items:
        existing_clean = (item.generated_text or "").strip().lower()
        if not existing_clean:
            continue
        if existing_clean == clean_cand:
            return True
        ex_words = [w.strip(".,!?:;\"'()[]{}") for w in existing_clean.split() if w.strip(".,!?:;\"'()[]{}")]
        if not ex_words:
            continue
        ex_prefix = " ".join(ex_words[:3]) if len(ex_words) >= 3 else ""
        if cand_prefix and ex_prefix and cand_prefix == ex_prefix:
            return True
        ex_set = set(ex_words)
        union_len = len(cand_set | ex_set)
        if union_len > 0 and (len(cand_set & ex_set) / union_len) > 0.65:
            return True
    return False


def get_pending_tweets(db: Session, tenant_id: Optional[str] = None) -> List[ProcessedTweet]:
    """Retrieves all tweets waiting for manual approval OR scheduled in the queue."""
    q = db.query(ProcessedTweet).filter(ProcessedTweet.status.in_(["pending_approval", "scheduled"]))
    if tenant_id and tenant_id != "default":
        items = q.filter(ProcessedTweet.tenant_id == tenant_id).order_by(ProcessedTweet.timestamp.desc()).all()
        default_items = q.filter(ProcessedTweet.tenant_id == "default").order_by(ProcessedTweet.timestamp.desc()).all()
        if default_items:
            seen_ids = {it.tweet_id for it in items}
            for d_item in default_items:
                if d_item.tweet_id not in seen_ids:
                    items.append(d_item)
            items.sort(key=lambda x: x.timestamp or datetime.min, reverse=True)
        return items
    elif tenant_id == "default":
        return q.filter(ProcessedTweet.tenant_id == "default").order_by(ProcessedTweet.timestamp.desc()).all()
    return q.order_by(ProcessedTweet.timestamp.desc()).all()


def get_due_scheduled_tweets(db: Session, tenant_id: Optional[str] = None) -> List[ProcessedTweet]:
    """Retrieves scheduled tweets whose randomized scheduled_for time has arrived."""
    now_utc = datetime.utcnow()
    q = db.query(ProcessedTweet).filter(
        ProcessedTweet.status == "scheduled",
        ProcessedTweet.scheduled_for <= now_utc
    )
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return q.order_by(ProcessedTweet.scheduled_for.asc()).all()


def get_scheduled_count(db: Session, tenant_id: Optional[str] = None) -> int:
    """Counts how many tweets are currently queued for random future posting."""
    q = db.query(func.count(ProcessedTweet.tweet_id)).filter(ProcessedTweet.status == "scheduled")
    if tenant_id and tenant_id != "default":
        count = q.filter(ProcessedTweet.tenant_id == tenant_id).scalar() or 0
        if count == 0:
            count = q.filter(ProcessedTweet.tenant_id == "default").scalar() or 0
        return count
    elif tenant_id == "default":
        return q.filter(ProcessedTweet.tenant_id == "default").scalar() or 0
    return q.scalar() or 0


def get_recent_tweets(db: Session, limit: int = 50, tenant_id: Optional[str] = None) -> List[ProcessedTweet]:
    """Retrieves recent tweet interactions (posted, skipped, failed, pending, scheduled)."""
    q = db.query(ProcessedTweet)
    if tenant_id and tenant_id != "default":
        items = q.filter(ProcessedTweet.tenant_id == tenant_id).order_by(ProcessedTweet.timestamp.desc()).limit(limit).all()
        if len(items) < limit:
            default_items = q.filter(ProcessedTweet.tenant_id == "default").order_by(ProcessedTweet.timestamp.desc()).limit(limit).all()
            seen_ids = {it.tweet_id for it in items}
            for d_item in default_items:
                if d_item.tweet_id not in seen_ids:
                    items.append(d_item)
            items.sort(key=lambda x: x.timestamp or datetime.min, reverse=True)
            return items[:limit]
        return items
    elif tenant_id == "default":
        return q.filter(ProcessedTweet.tenant_id == "default").order_by(ProcessedTweet.timestamp.desc()).limit(limit).all()
    return q.order_by(ProcessedTweet.timestamp.desc()).limit(limit).all()


def get_agent_config(db: Session, tenant_id: str = "default") -> AgentConfig:
    """Retrieves the configuration row for a specific tenant (defaults to 'default')."""
    config = db.query(AgentConfig).filter(AgentConfig.tenant_id == tenant_id).first()
    if not config:
        config = AgentConfig(tenant_id=tenant_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def update_agent_config(db: Session, updates: dict, tenant_id: str = "default") -> AgentConfig:
    """Updates runtime configuration toggles for a tenant."""
    config = get_agent_config(db, tenant_id=tenant_id)
    for key, value in updates.items():
        if value is not None and hasattr(config, key):
            setattr(config, key, value)
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


# ==============================================================================
# Authentication & User Management Helpers
# ==============================================================================

def hash_password(password: str) -> str:
    """Hashes a plaintext password using salted PBKDF2-HMAC-SHA256 (100,000 iterations)."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    ).hex()
    return f"{salt}${pwd_hash}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a plaintext password against a stored salt$hash string."""
    try:
        if not stored_hash or "$" not in stored_hash:
            return False
        salt, expected_hash = stored_hash.split("$", 1)
        calc_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000
        ).hex()
        return hmac.compare_digest(calc_hash, expected_hash)
    except Exception:
        return False


def create_auth_token(user_id: str, email: str, tenant_id: str, exp_days: int = 365) -> str:
    """Generates an HMAC-SHA256 signed session token for a user (valid for 365 days)."""
    payload = {
        "uid": user_id,
        "email": email,
        "tenant_id": tenant_id,
        "exp": int(time.time()) + (exp_days * 86400)
    }
    payload_json = json.dumps(payload, separators=(',', ':'))
    b64_payload = base64.urlsafe_b64encode(payload_json.encode('utf-8')).decode('utf-8').rstrip('=')
    sig = hmac.new(AUTH_SECRET_KEY.encode('utf-8'), b64_payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifies an HMAC-SHA256 signed token and returns its payload if valid and not expired."""
    try:
        if not token or "." not in token:
            return None
        b64_payload, sig = token.split(".", 1)
        expected_sig = hmac.new(AUTH_SECRET_KEY.encode('utf-8'), b64_payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padded = b64_payload + "=" * ((4 - len(b64_payload) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode('utf-8')).decode('utf-8'))
        exp = payload.get("exp")
        if exp and exp < time.time():
            return None
        return payload
    except Exception:
        return None


def create_user(db: Session, email: str, password_plain: str, name: Optional[str] = None) -> User:
    """Creates a new user record in SQLite with isolated tenant_id and default agent config."""
    clean_email = email.strip().lower()
    user_id = f"u_{uuid.uuid4().hex[:12]}"
    tenant_id = user_id
    pwd_hash = hash_password(password_plain)
    user = User(
        user_id=user_id,
        email=clean_email,
        password_hash=pwd_hash,
        name=name.strip() if name else clean_email.split("@")[0],
        tenant_id=tenant_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # Ensure this user gets an isolated AgentConfig record
    get_agent_config(db, tenant_id=tenant_id)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Retrieves a user by email address (case-insensitive)."""
    clean_email = email.strip().lower()
    return db.query(User).filter(func.lower(User.email) == clean_email).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    """Retrieves a user by unique user_id string."""
    return db.query(User).filter(User.user_id == user_id).first()

