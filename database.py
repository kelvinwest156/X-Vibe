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
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger("x_vibebot.database")
from typing import Optional, List, Dict, Any, Iterable, Set, Tuple
from sqlalchemy import create_engine, func, event, case, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, Session

from models import (
    Base,
    ProcessedTweet,
    AgentConfig,
    User,
    TokenUsageLog,
    PlatformSettings,
    WebhookEvent,
    _utc_naive,
)
from core.security import (
    get_master_secret,
    derive_subkey,
    encrypt_secret,
    decrypt_secret,
)

AUTH_SECRET_KEY = get_master_secret()

DB_FILE = os.getenv("DATABASE_URL", "sqlite:///./vibebot.db")
if DB_FILE.startswith("postgres://"):
    DB_FILE = DB_FILE.replace("postgres://", "postgresql://", 1)

# Ensure resilient driver routing for PostgreSQL across psycopg 3 and psycopg2
has_psycopg3 = False
has_psycopg2 = False
if DB_FILE.startswith("postgresql://") or DB_FILE.startswith("postgresql+"):
    try:
        import psycopg  # noqa: F401
        has_psycopg3 = True
    except ImportError:
        has_psycopg3 = False

    try:
        import psycopg2  # noqa: F401
        has_psycopg2 = True
    except ImportError:
        has_psycopg2 = False

    if DB_FILE.startswith("postgresql://"):
        if has_psycopg3:
            DB_FILE = DB_FILE.replace("postgresql://", "postgresql+psycopg://", 1)
        elif has_psycopg2:
            DB_FILE = DB_FILE.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif DB_FILE.startswith("postgresql+psycopg://") and not has_psycopg3 and has_psycopg2:
        DB_FILE = DB_FILE.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif DB_FILE.startswith("postgresql+psycopg2://") and not has_psycopg2 and has_psycopg3:
        DB_FILE = DB_FILE.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)

engine_kwargs: Dict[str, Any] = {"echo": False}
IS_SQLITE = "sqlite" in DB_FILE
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
else:
    # Production connection pool for Supabase / PostgreSQL (PgBouncer safe)
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300
    engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
    engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    if DB_FILE.startswith("postgresql+psycopg://"):
        # PgBouncer transaction pool (port 6543) breaks psycopg3 auto-prepared statements
        engine_kwargs["connect_args"] = {"prepare_threshold": None}

engine = create_engine(DB_FILE, **engine_kwargs)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_decrypted_api_key(config: Optional[AgentConfig]) -> Optional[str]:
    """Safely decrypts a tenant's stored AI API key."""
    if not config:
        return None
    raw = getattr(config, "api_key", None)
    if not raw:
        return None
    dec = decrypt_secret(raw)
    return dec.strip() if dec and dec.strip() else None


def get_decrypted_cookies_json(config: Optional[AgentConfig]) -> Optional[str]:
    """Safely decrypts a tenant's stored browser cookies JSON."""
    if not config:
        return None
    raw = getattr(config, "cookies_json", None)
    if not raw:
        return None
    return decrypt_secret(raw)


def _migrate_processed_tweets_composite_pk(inspector):
    """
    Safely migrates legacy single-PK processed_tweets (PK: tweet_id) to multi-tenant
    composite PK (tenant_id, tweet_id) without data loss.
    """
    try:
        pk_info = inspector.get_pk_constraint("processed_tweets")
        pk_cols = pk_info.get("constrained_columns") or []
    except Exception:
        return

    if "tenant_id" in pk_cols and "tweet_id" in pk_cols:
        return

    logger.info("Migrating processed_tweets primary key to multi-tenant composite (tenant_id, tweet_id)...")
    with engine.begin() as conn:
        if IS_SQLITE:
            conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS processed_tweets_v2 (
                    tweet_id VARCHAR(64) NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
                    action_type VARCHAR(32),
                    tweet_text TEXT,
                    tweet_author VARCHAR(128),
                    tweet_url VARCHAR(512),
                    generated_text TEXT,
                    variants_json TEXT,
                    tweet_metrics VARCHAR(128),
                    media_url VARCHAR(512),
                    should_like BOOLEAN DEFAULT 0,
                    urgency_score INTEGER DEFAULT 5,
                    user_edited BOOLEAN DEFAULT 0,
                    status VARCHAR(32),
                    scheduled_for DATETIME,
                    error_message TEXT,
                    timestamp DATETIME,
                    PRIMARY KEY (tenant_id, tweet_id)
                )
            """)
            conn.exec_driver_sql("""
                INSERT OR IGNORE INTO processed_tweets_v2 (
                    tweet_id, tenant_id, action_type, tweet_text, tweet_author, tweet_url,
                    generated_text, variants_json, tweet_metrics, media_url, should_like,
                    urgency_score, user_edited, status, scheduled_for, error_message, timestamp
                )
                SELECT
                    tweet_id, COALESCE(NULLIF(tenant_id, ''), 'default'), action_type, tweet_text, tweet_author, tweet_url,
                    generated_text, variants_json, tweet_metrics, media_url, COALESCE(should_like, 0),
                    COALESCE(urgency_score, 5), COALESCE(user_edited, 0), COALESCE(status, 'pending_approval'),
                    scheduled_for, error_message, timestamp
                FROM processed_tweets
            """)
            conn.exec_driver_sql("DROP TABLE processed_tweets")
            conn.exec_driver_sql("ALTER TABLE processed_tweets_v2 RENAME TO processed_tweets")
        else:
            conn.exec_driver_sql("UPDATE processed_tweets SET tenant_id = 'default' WHERE tenant_id IS NULL OR tenant_id = ''")
            conn.exec_driver_sql("ALTER TABLE processed_tweets ALTER COLUMN tenant_id SET NOT NULL")
            pk_name = pk_info.get("name") or "processed_tweets_pkey"
            conn.exec_driver_sql(f'ALTER TABLE processed_tweets DROP CONSTRAINT IF EXISTS "{pk_name}"')
            conn.exec_driver_sql("ALTER TABLE processed_tweets ADD PRIMARY KEY (tenant_id, tweet_id)")


def init_db(retries: int = 3, delay: float = 2.0):
    """Initializes database tables, auto-migrates new columns & indexes, and seeds default AgentConfig."""
    last_err = None
    for attempt in range(retries):
        try:
            Base.metadata.create_all(bind=engine)

            from sqlalchemy import inspect
            inspector = inspect(engine)
            existing_tables = inspector.get_table_names()
            break
        except Exception as e:
            last_err = e
            logger.warning(f"Database init connection attempt {attempt + 1}/{retries} failed: {e}. Retrying in {delay}s...")
            time.sleep(delay)
    else:
        logger.error(f"Failed to connect to database in init_db after {retries} attempts: {last_err}. Proceeding with caution.")
        return

    if "users" in existing_tables:
        user_cols = [c["name"] for c in inspector.get_columns("users")]
        if "token_version" not in user_cols:
            with engine.connect() as conn:
                try:
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 1 NOT NULL")
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.debug(f"users token_version migration notice: {exc}")

    if "agent_config" in existing_tables:
        cfg_cols = [c["name"] for c in inspector.get_columns("agent_config")]
        migrations_cfg = [
            ("tenant_id", "VARCHAR(128) DEFAULT 'default'"),
            ("selected_model", "VARCHAR(64) DEFAULT 'auto'"),
            ("max_cooldown_minutes", "INTEGER DEFAULT 45"),
            ("active_hours_start", "INTEGER DEFAULT 8"),
            ("active_hours_end", "INTEGER DEFAULT 23"),
            ("persona_prompt", "TEXT DEFAULT 'Casual, sharp, dry humor, short sentences, no corporate buzzwords'"),
            ("linked_username", "VARCHAR(128)"),
            ("hourly_action_cap", "INTEGER DEFAULT 6"),
            ("smart_query_enabled", "BOOLEAN DEFAULT 1" if IS_SQLITE else "BOOLEAN DEFAULT true"),
            ("warmup_mode", "BOOLEAN DEFAULT 0" if IS_SQLITE else "BOOLEAN DEFAULT false"),
            ("cookies_json", "TEXT"),
            ("api_key", "VARCHAR(512)"),
            ("daily_token_cap", "INTEGER DEFAULT 50000"),
            ("max_pending_queue", "INTEGER DEFAULT 8"),
            ("auto_sleep_browser", "BOOLEAN DEFAULT 1" if IS_SQLITE else "BOOLEAN DEFAULT true"),
            ("is_suspended", "BOOLEAN DEFAULT 0" if IS_SQLITE else "BOOLEAN DEFAULT false"),
            ("plan_tier", "VARCHAR(32) DEFAULT 'trial'"),
            ("subscription_status", "VARCHAR(32) DEFAULT 'trialing'"),
            ("trial_ends_at", "TIMESTAMP" if not IS_SQLITE else "DATETIME"),
            ("daily_original_post_cap", "INTEGER DEFAULT 3"),
            ("payment_customer_id", "VARCHAR(128)"),
        ]
        with engine.connect() as conn:
            for col_name, col_def in migrations_cfg:
                if col_name not in cfg_cols:
                    try:
                        conn.exec_driver_sql(f"ALTER TABLE agent_config ADD COLUMN {col_name} {col_def}")
                        conn.commit()
                    except Exception as exc:
                        conn.rollback()
                        logger.debug(f"agent_config column '{col_name}' migration notice: {exc}")
            # Backfill NULL selected_model without wiping explicit user selections
            try:
                conn.exec_driver_sql(
                    "UPDATE agent_config SET selected_model = 'auto' WHERE selected_model IS NULL"
                )
                conn.commit()
            except Exception:
                conn.rollback()

    if "processed_tweets" in existing_tables:
        tweet_cols = [c["name"] for c in inspector.get_columns("processed_tweets")]
        migrations_tweet = [
            ("tenant_id", "VARCHAR(128) DEFAULT 'default'"),
            ("variants_json", "TEXT"),
            ("tweet_metrics", "VARCHAR(128)"),
            ("scheduled_for", "TIMESTAMP" if not IS_SQLITE else "DATETIME"),
            ("media_url", "VARCHAR(512)"),
            ("should_like", "BOOLEAN DEFAULT 0" if IS_SQLITE else "BOOLEAN DEFAULT false"),
            ("urgency_score", "INTEGER DEFAULT 5"),
            ("user_edited", "BOOLEAN DEFAULT 0" if IS_SQLITE else "BOOLEAN DEFAULT false"),
            ("timestamp", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()" if not IS_SQLITE else "DATETIME"),
        ]
        with engine.connect() as conn:
            for col_name, col_def in migrations_tweet:
                if col_name not in tweet_cols:
                    try:
                        conn.exec_driver_sql(f"ALTER TABLE processed_tweets ADD COLUMN {col_name} {col_def}")
                        conn.commit()
                    except Exception as exc:
                        conn.rollback()
                        logger.debug(f"processed_tweets column '{col_name}' migration notice: {exc}")

        from sqlalchemy import inspect as _re_inspect
        _migrate_processed_tweets_composite_pk(_re_inspect(engine))

    # Ensure composite performance indexes exist on migrated & fresh tables
    index_ddl = [
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_agent_config_tenant_unique ON agent_config (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_config_active_susp ON agent_config (is_active, is_suspended)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tweet_id ON processed_tweets (tweet_id)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_id ON processed_tweets (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_status ON processed_tweets (status)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_timestamp ON processed_tweets (timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_status_ts ON processed_tweets (tenant_id, status, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_status_sched ON processed_tweets (status, scheduled_for)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_status_sched ON processed_tweets (tenant_id, status, scheduled_for)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_type_ts ON processed_tweets (tenant_id, action_type, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_ts ON processed_tweets (tenant_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_url ON processed_tweets (tenant_id, tweet_url)",
        "CREATE INDEX IF NOT EXISTS ix_token_usage_tenant_ts ON token_usage_logs (tenant_id, timestamp)",
        "CREATE INDEX IF NOT EXISTS ix_token_usage_ts_task_tenant ON token_usage_logs (timestamp, task_type, tenant_id)",
    ]
    with engine.connect() as conn:
        for stmt in index_ddl:
            try:
                conn.exec_driver_sql(stmt)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.debug(f"Index creation notice ({stmt}): {exc}")

    db = SessionLocal()
    try:
        config = db.query(AgentConfig).filter(AgentConfig.tenant_id == "default").first()
        if not config:
            config = db.query(AgentConfig).filter(AgentConfig.id == 1).first()
        if not config:
            config = AgentConfig(
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
                selected_model="auto",
                plan_tier="pro",
                subscription_status="active",
                daily_original_post_cap=6,
            )
            db.add(config)
            db.commit()
        else:
            changed = False
            if not getattr(config, "tenant_id", None):
                config.tenant_id = "default"
                changed = True
            if not getattr(config, "plan_tier", None):
                config.plan_tier = "pro"
                changed = True
            if not getattr(config, "subscription_status", None):
                config.subscription_status = "active"
                changed = True
            if getattr(config, "daily_original_post_cap", None) is None:
                config.daily_original_post_cap = 6
                changed = True
            if not config.selected_model:
                config.selected_model = "auto"
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
            if getattr(config, "daily_token_cap", None) is None:
                config.daily_token_cap = 50000
                changed = True
            if getattr(config, "max_pending_queue", None) is None:
                config.max_pending_queue = 8
                changed = True
            if getattr(config, "auto_sleep_browser", None) is None:
                config.auto_sleep_browser = True
                changed = True
            if getattr(config, "is_suspended", None) is None:
                config.is_suspended = False
                changed = True
            if changed:
                db.commit()

        # Sync Postgres sequences if rows were inserted manually earlier
        if not IS_SQLITE:
            try:
                db.execute(
                    text("SELECT setval(pg_get_serial_sequence('agent_config', 'id'), COALESCE((SELECT MAX(id) FROM agent_config), 1))")
                )
                db.commit()
            except Exception:
                db.rollback()

        # Seed singleton PlatformSettings row (id=1)
        ps = db.query(PlatformSettings).filter(PlatformSettings.id == 1).first()
        if not ps:
            ps = PlatformSettings(
                id=1,
                default_daily_token_cap=50000,
                web_radar_cache_seconds=7200,
                browser_idle_sleep_minutes=15,
                auto_sleep_browsers_enabled=True,
                global_pause_bots=False,
            )
            db.add(ps)
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
    - Scoped strictly to config.tenant_id so one tenant never delays another tenant's queue.
    """
    now_utc = datetime.utcnow()
    eff_tenant = getattr(config, "tenant_id", None) or "default"
    latest_scheduled_raw = (
        db.query(func.max(ProcessedTweet.scheduled_for))
        .filter(
            ProcessedTweet.tenant_id == eff_tenant,
            ProcessedTweet.status == "scheduled",
            ProcessedTweet.scheduled_for > now_utc,
        )
        .scalar()
    )
    latest_scheduled = _utc_naive(latest_scheduled_raw)
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
        next_wake = target_local.replace(hour=start_hr, minute=0, second=0, microsecond=0)
        if next_wake <= target_local:
            next_wake += timedelta(days=1)
        next_wake += timedelta(seconds=random.randint(180, 1680))
        target_utc = next_wake - utc_to_local_offset

    return target_utc


# ==============================================================================
# Helper Queries
# ==============================================================================

def _is_transient_skip(status: Optional[str], error_message: Optional[str]) -> bool:
    if status == "skipped" and error_message:
        err_lower = error_message.lower()
        if any(k in err_lower for k in ("api key", "error", "not configured", "503", "timeout", "rate limit")):
            return True
    return False


def is_tweet_already_processed(db: Session, tweet_id: str, tenant_id: str = "default") -> bool:
    """
    Returns True if this tweet_id has already been genuinely evaluated or replied to for this tenant.
    """
    row = (
        db.query(ProcessedTweet.status, ProcessedTweet.error_message)
        .filter(ProcessedTweet.tweet_id == tweet_id, ProcessedTweet.tenant_id == (tenant_id or "default"))
        .first()
    )
    if not row:
        return False
    return not _is_transient_skip(row[0], row[1])


def get_processed_tweet_ids_batch(db: Session, tweet_ids: Iterable[str], tenant_id: str = "default") -> Set[str]:
    """
    Checks a batch of candidate tweet_ids in a SINGLE SQL query (eliminating N+1 SELECTs).
    Returns tweet_ids that have already been genuinely processed for this tenant.
    """
    clean_ids = [str(tid) for tid in tweet_ids if tid]
    if not clean_ids:
        return set()
    rows = (
        db.query(ProcessedTweet.tweet_id, ProcessedTweet.status, ProcessedTweet.error_message)
        .filter(
            ProcessedTweet.tenant_id == (tenant_id or "default"),
            ProcessedTweet.tweet_id.in_(clean_ids),
        )
        .all()
    )
    return {tid for tid, status, err in rows if not _is_transient_skip(status, err)}


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
    tenant_id: str = "default",
    commit: bool = True,
) -> ProcessedTweet:
    """Saves or updates a tweet interaction record strictly scoped by (tenant_id, tweet_id)."""
    eff_tenant = tenant_id or "default"
    existing = (
        db.query(ProcessedTweet)
        .filter(ProcessedTweet.tenant_id == eff_tenant, ProcessedTweet.tweet_id == tweet_id)
        .first()
    )
    now_utc = datetime.utcnow()
    sched_clean = _utc_naive(scheduled_for)

    if existing:
        existing.action_type = action_type
        existing.tweet_text = tweet_text
        existing.tweet_author = tweet_author
        existing.tweet_url = tweet_url
        existing.media_url = media_url
        existing.generated_text = generated_text
        existing.variants_json = variants_json
        existing.tweet_metrics = tweet_metrics
        existing.should_like = bool(should_like)
        existing.urgency_score = int(urgency_score if urgency_score is not None else 5)
        existing.user_edited = bool(user_edited)
        existing.status = status
        existing.scheduled_for = sched_clean
        existing.error_message = error_message
        existing.timestamp = now_utc
        item = existing
    else:
        item = ProcessedTweet(
            tweet_id=tweet_id,
            tenant_id=eff_tenant,
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
            scheduled_for=sched_clean,
            error_message=error_message,
            timestamp=now_utc,
        )
        db.add(item)

    if commit:
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
    should_like: Optional[bool] = None,
    tenant_id: Optional[str] = None
) -> Optional[ProcessedTweet]:
    """Updates an existing tweet record with strict tenant isolation (no cross-tenant fallback)."""
    eff_tenant = tenant_id or "default"
    item = (
        db.query(ProcessedTweet)
        .filter(
            ProcessedTweet.tweet_id == tweet_id,
            ProcessedTweet.tenant_id == eff_tenant,
        )
        .first()
    )
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
            item.scheduled_for = _utc_naive(scheduled_for)
        if status in ("posted", "dispatching"):
            item.timestamp = datetime.utcnow()
        db.commit()
        db.refresh(item)
    return item


def claim_tweet_for_dispatch(
    db: Session,
    tweet_id: str,
    tenant_id: str,
    allowed_from_statuses: Iterable[str] = ("pending_approval", "scheduled", "failed"),
    new_status: str = "dispatching",
    generated_text: Optional[str] = None,
    user_edited: Optional[bool] = None,
    should_like: Optional[bool] = None,
    scheduled_for: Optional[datetime] = None,
) -> bool:
    """
    Atomically transitions a tweet only if it currently belongs to `tenant_id`
    and its status is in `allowed_from_statuses`. Prevents concurrent double-dispatch races.
    """
    values: Dict[str, Any] = {
        "status": new_status,
        "timestamp": datetime.utcnow(),
    }
    if generated_text is not None:
        values["generated_text"] = generated_text
    if user_edited is not None:
        values["user_edited"] = user_edited
    if should_like is not None:
        values["should_like"] = should_like
    if new_status != "scheduled":
        values["scheduled_for"] = None
    elif scheduled_for is not None:
        values["scheduled_for"] = _utc_naive(scheduled_for)

    rows_affected = (
        db.query(ProcessedTweet)
        .filter(
            ProcessedTweet.tweet_id == tweet_id,
            ProcessedTweet.tenant_id == (tenant_id or "default"),
            ProcessedTweet.status.in_(list(allowed_from_statuses)),
        )
        .update(values, synchronize_session=False)
    )
    db.commit()
    return rows_affected == 1


def recover_stale_dispatching_tweets(db: Session, max_age_minutes: int = 10) -> int:
    """Reverts orphaned 'dispatching' rows left behind by crashes back to 'failed' so they never stay wedged."""
    cutoff = datetime.utcnow() - timedelta(minutes=max(1, max_age_minutes))
    count = (
        db.query(ProcessedTweet)
        .filter(
            ProcessedTweet.status == "dispatching",
            ProcessedTweet.timestamp <= cutoff,
        )
        .update(
            {
                ProcessedTweet.status: "failed",
                ProcessedTweet.error_message: "Recovered interrupted dispatch after worker restart",
            },
            synchronize_session=False,
        )
    )
    if count > 0:
        db.commit()
    return int(count or 0)


def clear_all_pending_tweets(db: Session, tenant_id: str) -> int:
    """Dismisses all pending_approval drafts for the specific tenant in one bulk SQL UPDATE."""
    count = (
        db.query(ProcessedTweet)
        .filter(
            ProcessedTweet.tenant_id == (tenant_id or "default"),
            ProcessedTweet.status == "pending_approval",
        )
        .update(
            {
                ProcessedTweet.status: "skipped",
                ProcessedTweet.error_message: "Dismissed by creator",
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return int(count or 0)


def get_daily_actions_count(db: Session, tenant_id: Optional[str] = None) -> int:
    """Counts actions posted or actively dispatching today UTC."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = db.query(func.count(ProcessedTweet.tweet_id)).filter(
        ProcessedTweet.status.in_(["posted", "dispatching"]),
        ProcessedTweet.timestamp >= today_start,
    )
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return int(q.scalar() or 0)


def get_hourly_actions_count(db: Session, tenant_id: Optional[str] = None) -> int:
    """Counts actions posted or actively dispatching in the rolling last 60 minutes UTC."""
    one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
    q = db.query(func.count(ProcessedTweet.tweet_id)).filter(
        ProcessedTweet.status.in_(["posted", "dispatching"]),
        ProcessedTweet.timestamp >= one_hour_ago,
    )
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return int(q.scalar() or 0)


def get_status_tweet_stats(db: Session, tenant_id: str = "default") -> Dict[str, int]:
    """
    Collapses 6+ ProcessedTweet KPI queries into ONE single SQL aggregate query for /api/status & /api/stats.
    Also accurately distinguishes pending_approval vs scheduled counts.
    """
    now_utc = datetime.utcnow()
    today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    one_hour_ago = now_utc - timedelta(minutes=60)

    row = (
        db.query(
            func.count(ProcessedTweet.tweet_id).label("total_processed"),
            func.coalesce(func.sum(case((ProcessedTweet.status == "pending_approval", 1), else_=0)), 0).label("pending_approvals"),
            func.coalesce(func.sum(case((ProcessedTweet.status == "scheduled", 1), else_=0)), 0).label("scheduled"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (ProcessedTweet.status.in_(["posted", "dispatching"])) & (ProcessedTweet.timestamp >= today_utc),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("daily_used"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (ProcessedTweet.status.in_(["posted", "dispatching"])) & (ProcessedTweet.timestamp >= one_hour_ago),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("hourly_used"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (ProcessedTweet.status.in_(["posted", "scheduled"])) & ProcessedTweet.generated_text.isnot(None),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("learned_count"),
        )
        .filter(ProcessedTweet.tenant_id == (tenant_id or "default"))
        .one()
    )
    return {
        "total_processed": int(row.total_processed or 0),
        "pending_approvals": int(row.pending_approvals or 0),
        "scheduled": int(row.scheduled or 0),
        "daily_used": int(row.daily_used or 0),
        "hourly_used": int(row.hourly_used or 0),
        "learned_count": int(row.learned_count or 0),
    }


def get_learning_memory(db: Session, limit_approved: int = 5, limit_skipped: int = 5, tenant_id: Optional[str] = None, include_total: bool = True) -> dict:
    """
    Retrieves recent approved/posted drafts and skipped tweets (column-projected)
    so the AI engine learns the tenant's voice without over-fetching wide columns.
    """
    q_app = (
        db.query(ProcessedTweet.tweet_text, ProcessedTweet.generated_text, ProcessedTweet.user_edited)
        .filter(ProcessedTweet.status.in_(["posted", "scheduled"]))
        .filter(ProcessedTweet.generated_text.isnot(None))
    )
    q_skip = (
        db.query(ProcessedTweet.tweet_text, ProcessedTweet.error_message)
        .filter(ProcessedTweet.status == "skipped")
        .filter(ProcessedTweet.tweet_text.isnot(None))
    )

    if tenant_id:
        q_app = q_app.filter(ProcessedTweet.tenant_id == tenant_id)
        q_skip = q_skip.filter(ProcessedTweet.tenant_id == tenant_id)

    approved_rows = q_app.order_by(ProcessedTweet.user_edited.desc(), ProcessedTweet.timestamp.desc()).limit(limit_approved).all()
    skipped_rows = q_skip.order_by(ProcessedTweet.timestamp.desc()).limit(limit_skipped).all()

    total_learned = 0
    if include_total:
        q_total = (
            db.query(func.count(ProcessedTweet.tweet_id))
            .filter(ProcessedTweet.status.in_(["posted", "scheduled"]))
            .filter(ProcessedTweet.generated_text.isnot(None))
        )
        if tenant_id:
            q_total = q_total.filter(ProcessedTweet.tenant_id == tenant_id)
        total_learned = int(q_total.scalar() or 0)

    return {
        "approved": [
            {
                "tweet_text": (t_text or "")[:180],
                "reply_text": (g_text or "")[:240],
                "user_edited": bool(u_ed),
            }
            for t_text, g_text, u_ed in approved_rows
            if g_text
        ],
        "skipped": [
            {
                "tweet_text": (t_text or "")[:180],
                "reason": (err_msg or "Low value / off-niche")[:120],
            }
            for t_text, err_msg in skipped_rows
            if t_text
        ],
        "total_learned": total_learned,
    }


def get_recent_reply_texts(db: Session, tenant_id: Optional[str] = None, limit: int = 20) -> List[str]:
    """Fetches only generated_text for the last N active/posted replies (lightweight column projection)."""
    q = (
        db.query(ProcessedTweet.generated_text)
        .filter(ProcessedTweet.status.in_(["posted", "scheduled", "dispatching", "pending_approval"]))
        .filter(ProcessedTweet.generated_text.isnot(None))
    )
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    rows = q.order_by(ProcessedTweet.timestamp.desc()).limit(limit).all()
    return [r[0] for r in rows if r[0]]


def is_text_too_similar_to_list(candidate_text: str, recent_texts: Iterable[str]) -> bool:
    """In-memory similarity check: shares 3-word prefix or >65% Jaccard word overlap."""
    if not candidate_text or not candidate_text.strip():
        return False
    clean_cand = candidate_text.strip().lower()
    cand_words = [w.strip(".,!?:;\"'()[]{}") for w in clean_cand.split() if w.strip(".,!?:;\"'()[]{}")]
    if not cand_words:
        return False
    cand_prefix = " ".join(cand_words[:3]) if len(cand_words) >= 3 else ""
    cand_set = set(cand_words)

    for existing_raw in recent_texts:
        existing_clean = (existing_raw or "").strip().lower()
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


def is_reply_too_similar(db: Session, candidate_text: str, tenant_id: Optional[str] = None) -> bool:
    """Anti-Detection Duplicate & Template Guard backed by column-projected query."""
    if not candidate_text or not candidate_text.strip():
        return False
    recent_texts = get_recent_reply_texts(db, tenant_id=tenant_id, limit=20)
    return is_text_too_similar_to_list(candidate_text, recent_texts)


def get_pending_tweets(
    db: Session, tenant_id: Optional[str] = None, limit: int = 100, offset: int = 0
) -> List[ProcessedTweet]:
    """Retrieves tweets waiting for manual approval OR scheduled in the queue."""
    q = db.query(ProcessedTweet).filter(ProcessedTweet.status.in_(["pending_approval", "scheduled"]))
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return q.order_by(ProcessedTweet.timestamp.desc()).offset(max(0, offset)).limit(max(1, min(limit, 200))).all()


def get_due_scheduled_tweets(db: Session, tenant_id: Optional[str] = None) -> List[ProcessedTweet]:
    """Retrieves scheduled tweets whose randomized scheduled_for time has arrived."""
    now_utc = datetime.utcnow()
    q = db.query(ProcessedTweet).filter(
        ProcessedTweet.status == "scheduled",
        ProcessedTweet.scheduled_for <= now_utc,
    )
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    return q.order_by(ProcessedTweet.scheduled_for.asc()).limit(50).all()


def get_scheduled_count(db: Session, tenant_id: Optional[str] = None) -> int:
    """Counts how many tweets are currently queued for random future posting."""
    q = db.query(func.count(ProcessedTweet.tweet_id)).filter(ProcessedTweet.status == "scheduled")
    if tenant_id:
        return int(q.filter(ProcessedTweet.tenant_id == tenant_id).scalar() or 0)
    return int(q.scalar() or 0)


def get_recent_tweets(
    db: Session, limit: int = 50, tenant_id: Optional[str] = None, offset: int = 0, status_filter: Optional[str] = None
) -> List[ProcessedTweet]:
    """Retrieves recent tweet interactions with bounded limit/offset."""
    q = db.query(ProcessedTweet)
    if tenant_id:
        q = q.filter(ProcessedTweet.tenant_id == tenant_id)
    if status_filter and status_filter != "all":
        q = q.filter(ProcessedTweet.status == status_filter)
    return q.order_by(ProcessedTweet.timestamp.desc()).offset(max(0, offset)).limit(max(1, min(limit, 200))).all()


def expire_stale_drafts(db: Session, tenant_id: Optional[str] = None, max_age_hours: int = 24) -> int:
    """
    Auto-expires unapproved drafts older than max_age_hours via one bulk SQL UPDATE.
    """
    safe_hours = max(1, min(720, int(max_age_hours or 24)))
    cutoff = datetime.utcnow() - timedelta(hours=safe_hours)
    query = db.query(ProcessedTweet).filter(
        ProcessedTweet.status == "pending_approval",
        ProcessedTweet.timestamp <= cutoff,
    )
    if tenant_id:
        query = query.filter(ProcessedTweet.tenant_id == tenant_id)

    count = query.update(
        {
            ProcessedTweet.status: "skipped",
            ProcessedTweet.error_message: f"Auto-expired stale draft (unreviewed >{safe_hours}h)",
        },
        synchronize_session=False,
    )
    if count > 0:
        db.commit()
        logger.info(f"Auto-expired {count} stale draft(s) older than {safe_hours}h (tenant='{tenant_id or 'all'}').")
    return int(count or 0)


def get_agent_config(db: Session, tenant_id: str = "default") -> AgentConfig:
    """Retrieves the configuration row for a specific tenant cleanly (race-safe under concurrent creation)."""
    eff_tenant = tenant_id or "default"
    config = db.query(AgentConfig).filter(AgentConfig.tenant_id == eff_tenant).first()
    if not config:
        from services.plans import apply_plan_to_config
        config = AgentConfig(tenant_id=eff_tenant)
        if eff_tenant == "default":
            apply_plan_to_config(config, "pro", status="active")
        else:
            apply_plan_to_config(config, "trial", status="trialing", trial_days=7)
        try:
            db.add(config)
            db.commit()
            db.refresh(config)
        except IntegrityError:
            db.rollback()
            config = db.query(AgentConfig).filter(AgentConfig.tenant_id == eff_tenant).first()
    return config


def update_agent_config(db: Session, updates: dict, tenant_id: str = "default") -> AgentConfig:
    """Updates runtime configuration toggles for a tenant, encrypting sensitive credentials at rest."""
    config = get_agent_config(db, tenant_id=tenant_id)
    for key, value in updates.items():
        if value is not None and hasattr(config, key):
            if key in ("api_key", "cookies_json"):
                setattr(config, key, encrypt_secret(str(value)))
            else:
                setattr(config, key, value)
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


# ==============================================================================
# Authentication & User Management Helpers
# ==============================================================================

_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hashes a plaintext password using versioned PBKDF2-HMAC-SHA256 (600,000 iterations)."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${pwd_hash}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a plaintext password against versioned or legacy salt$hash strings."""
    try:
        if not stored_hash or "$" not in stored_hash:
            return False
        parts = stored_hash.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            iterations = int(parts[1])
            salt, expected_hash = parts[2], parts[3]
        elif len(parts) == 2:
            iterations = 100_000
            salt, expected_hash = parts[0], parts[1]
        else:
            return False
        calc_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(calc_hash, expected_hash)
    except Exception:
        return False


def create_auth_token(
    user_id: str,
    email: str,
    tenant_id: str,
    exp_days: int = 30,
    token_version: int = 1,
) -> str:
    """Generates a domain-separated HMAC-SHA256 signed creator session token."""
    payload = {
        "uid": user_id,
        "email": email,
        "tenant_id": tenant_id,
        "ver": int(token_version or 1),
        "exp": int(time.time()) + (exp_days * 86400),
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    b64_payload = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    sig = hmac.new(derive_subkey("auth_session"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifies a creator session token with strict expiration checking."""
    try:
        if not token or "." not in token:
            return None
        b64_payload, sig = token.split(".", 1)
        expected_sig = hmac.new(derive_subkey("auth_session"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padded = b64_payload + "=" * ((4 - len(b64_payload) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp <= time.time():
            return None
        return payload
    except Exception:
        return None


def create_user(db: Session, email: str, password_plain: str, name: Optional[str] = None) -> User:
    """Creates a new user record with isolated tenant_id and default agent config."""
    clean_email = email.strip().lower()
    user_id = f"u_{uuid.uuid4().hex[:12]}"
    tenant_id = user_id
    pwd_hash = hash_password(password_plain)
    user = User(
        user_id=user_id,
        email=clean_email,
        password_hash=pwd_hash,
        name=name.strip() if name else clean_email.split("@")[0],
        tenant_id=tenant_id,
        token_version=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    get_agent_config(db, tenant_id=tenant_id)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Retrieves a user by email address (case-insensitive)."""
    clean_email = (email or "").strip().lower()
    if not clean_email:
        return None
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    return user


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    """Retrieves a user by unique user_id string."""
    return db.query(User).filter(User.user_id == user_id).first()


def _password_fingerprint(password_hash: Optional[str]) -> str:
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(
    email: str, exp_minutes: int = 60, password_hash: Optional[str] = None
) -> str:
    """
    Generates a domain-separated HMAC-SHA256 signed password reset token.
    Binds to current password fingerprint so token immediately invalidates after one use.
    """
    payload: Dict[str, Any] = {
        "action": "reset_password",
        "email": email.strip().lower(),
        "jti": secrets.token_hex(8),
        "exp": int(time.time()) + (exp_minutes * 60),
    }
    if password_hash is not None:
        payload["pfp"] = _password_fingerprint(password_hash)
    payload_json = json.dumps(payload, separators=(",", ":"))
    b64_payload = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    sig = hmac.new(derive_subkey("password_reset"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_password_reset_token(token: str, db: Optional[Session] = None) -> Optional[str]:
    """Verifies a password reset token, checks expiration, and enforces single-use via password fingerprint."""
    try:
        if not token or "." not in token:
            return None
        b64_payload, sig = token.split(".", 1)
        expected_sig = hmac.new(derive_subkey("password_reset"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padded = b64_payload + "=" * ((4 - len(b64_payload) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        if payload.get("action") != "reset_password":
            return None
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp <= time.time():
            return None
        email = payload.get("email")
        if not email:
            return None
        if db is not None and payload.get("pfp"):
            user = get_user_by_email(db, email)
            if not user or not hmac.compare_digest(payload["pfp"], _password_fingerprint(user.password_hash)):
                return None
        return email
    except Exception:
        return None


def update_user_password(db: Session, email: str, new_password_plain: str) -> Optional[User]:
    """Updates password hash and increments token_version to revoke prior sessions & reset tokens."""
    user = get_user_by_email(db, email)
    if not user:
        return None
    user.password_hash = hash_password(new_password_plain)
    user.token_version = int(getattr(user, "token_version", 1) or 1) + 1
    db.commit()
    db.refresh(user)
    return user


# ==============================================================================
# Super Admin Auth, Token Telemetry & Platform Settings Helpers
# ==============================================================================

def create_super_admin_token(email: str, expires_hours: int = 12) -> str:
    """Generates a domain-separated HMAC-SHA256 signed Super Admin session token."""
    payload = {
        "role": "super_admin",
        "email": (email or "").strip().lower(),
        "exp": int(time.time()) + (expires_hours * 3600),
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    b64_payload = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    sig = hmac.new(derive_subkey("super_admin"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_super_admin_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifies a domain-separated Super Admin token and ensures valid non-expired signature."""
    try:
        if not token or "." not in token:
            return None
        b64_payload, sig = token.split(".", 1)
        expected_sig = hmac.new(derive_subkey("super_admin"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padded = b64_payload + "=" * ((4 - len(b64_payload) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        if payload.get("role") != "super_admin":
            return None
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp <= time.time():
            return None
        return payload
    except Exception:
        return None


def record_token_usage(
    db: Session,
    tenant_id: str,
    provider: str,
    model: str,
    task_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
) -> TokenUsageLog:
    """
    Records AI token usage and calculates estimated USD cost per provider/model:
    - deepseek-reasoner: cache hit $0.14/1M, miss $0.55/1M, output $2.19/1M
    - deepseek-chat (V3): cache hit $0.07/1M, miss $0.27/1M, output $1.10/1M
    - gemini (Flash): cache hit $0.025/1M, miss $0.10/1M, output $0.40/1M
    """
    p_tok = max(0, int(prompt_tokens or 0))
    c_tok = max(0, int(completion_tokens or 0))
    hit_tok = max(0, int(cache_hit_tokens or 0))
    miss_tok = max(0, int(cache_miss_tokens or 0))

    if miss_tok == 0 and hit_tok == 0 and p_tok > 0:
        miss_tok = p_tok

    prov = (provider or "deepseek").lower()
    mod = (model or "deepseek-chat").lower()
    if prov == "gemini":
        r_hit, r_miss, r_out = 0.025, 0.10, 0.40
    elif "reasoner" in mod:
        r_hit, r_miss, r_out = 0.14, 0.55, 2.19
    else:
        r_hit, r_miss, r_out = 0.07, 0.27, 1.10

    cost_usd = ((hit_tok * r_hit) + (miss_tok * r_miss) + (c_tok * r_out)) / 1_000_000.0

    entry = TokenUsageLog(
        tenant_id=tenant_id or "default",
        provider=provider or "deepseek",
        model=model or "deepseek-chat",
        task_type=task_type or "general",
        prompt_tokens=p_tok,
        completion_tokens=c_tok,
        cache_hit_tokens=hit_tok,
        cache_miss_tokens=miss_tok,
        estimated_cost_usd=round(cost_usd, 8),
        timestamp=datetime.utcnow(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_tenant_daily_tokens(db: Session, tenant_id: str = "default") -> int:
    """Returns total tokens (prompt + completion) consumed by a tenant since UTC midnight today."""
    today_utc_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        db.query(func.coalesce(func.sum(TokenUsageLog.prompt_tokens + TokenUsageLog.completion_tokens), 0))
        .filter(
            TokenUsageLog.tenant_id == (tenant_id or "default"),
            TokenUsageLog.timestamp >= today_utc_start,
        )
        .scalar()
    )
    return int(total or 0)


def get_tenant_daily_cost_usd(db: Session, tenant_id: str = "default") -> float:
    """Returns total estimated USD spend for a tenant since UTC midnight today."""
    today_utc_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        db.query(func.coalesce(func.sum(TokenUsageLog.estimated_cost_usd), 0.0))
        .filter(
            TokenUsageLog.tenant_id == (tenant_id or "default"),
            TokenUsageLog.timestamp >= today_utc_start,
        )
        .scalar()
    )
    return round(float(total or 0.0), 6)


def get_daily_original_posts_count(db: Session, tenant_id: str = "default") -> int:
    """Counts non-skipped/non-failed original posts or threads created for a tenant today UTC."""
    today_utc_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        db.query(func.count(ProcessedTweet.tweet_id))
        .filter(
            ProcessedTweet.tenant_id == (tenant_id or "default"),
            ProcessedTweet.action_type.in_(["post", "thread"]),
            ProcessedTweet.status.in_(["pending_approval", "scheduled", "dispatching", "posted"]),
            ProcessedTweet.timestamp >= today_utc_start,
        )
        .scalar()
    )
    return int(count or 0)


def get_pending_approval_count(db: Session, tenant_id: str = "default") -> int:
    """Counts drafts currently waiting in 'pending_approval' for a tenant."""
    count = (
        db.query(func.count(ProcessedTweet.tweet_id))
        .filter(
            ProcessedTweet.tenant_id == (tenant_id or "default"),
            ProcessedTweet.status == "pending_approval",
        )
        .scalar()
    )
    return int(count or 0)


def get_platform_settings(db: Session) -> PlatformSettings:
    """Retrieves or creates the singleton PlatformSettings row (id=1) safely under concurrency."""
    ps = db.query(PlatformSettings).filter(PlatformSettings.id == 1).first()
    if not ps:
        ps = PlatformSettings(
            id=1,
            default_daily_token_cap=50000,
            web_radar_cache_seconds=7200,
            browser_idle_sleep_minutes=15,
            auto_sleep_browsers_enabled=True,
            global_pause_bots=False,
        )
        try:
            db.add(ps)
            db.commit()
            db.refresh(ps)
        except IntegrityError:
            db.rollback()
            ps = db.query(PlatformSettings).filter(PlatformSettings.id == 1).first()
    return ps


def update_platform_settings(db: Session, updates: Dict[str, Any]) -> PlatformSettings:
    """Updates fields on the singleton PlatformSettings row (id=1)."""
    ps = get_platform_settings(db)
    allowed_fields = {
        "default_daily_token_cap",
        "web_radar_cache_seconds",
        "browser_idle_sleep_minutes",
        "auto_sleep_browsers_enabled",
        "global_pause_bots",
    }
    for key, value in updates.items():
        if key in allowed_fields and value is not None:
            setattr(ps, key, value)
    ps.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ps)
    return ps


def check_and_record_webhook_event(db: Session, event_id: str, provider: str) -> bool:
    """
    Atomically checks & marks a billing webhook event_id as processed to prevent replay attacks.
    Returns True if this is a NEW event, False if already processed.
    """
    clean_id = (event_id or "").strip()
    if not clean_id:
        return False
    existing = db.query(WebhookEvent.event_id).filter(WebhookEvent.event_id == clean_id).first()
    if existing:
        return False
    try:
        db.add(WebhookEvent(event_id=clean_id, provider=provider, processed_at=datetime.utcnow()))
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        return False


def get_admin_user_aggregates(db: Session) -> Tuple[Dict[str, Tuple[int, int]], Dict[str, Tuple[int, float]]]:
    """
    Eliminates N+1 queries in GET /api/admin/users:
    Returns (tweet_stats_by_tenant, token_stats_by_tenant) in 2 constant GROUP BY SQL queries.
    """
    today_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    tweet_rows = (
        db.query(
            ProcessedTweet.tenant_id,
            func.coalesce(
                func.sum(
                    case(
                        (
                            (ProcessedTweet.status.in_(["posted", "dispatching"])) & (ProcessedTweet.timestamp >= today_utc),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("daily_actions_used"),
            func.coalesce(
                func.sum(case((ProcessedTweet.status == "pending_approval", 1), else_=0)),
                0,
            ).label("pending_count"),
        )
        .filter(
            (ProcessedTweet.status == "pending_approval")
            | ((ProcessedTweet.status.in_(["posted", "dispatching"])) & (ProcessedTweet.timestamp >= today_utc))
        )
        .group_by(ProcessedTweet.tenant_id)
        .all()
    )
    tweet_stats = {
        tid: (int(d_used or 0), int(pend or 0)) for tid, d_used, pend in tweet_rows
    }

    token_rows = (
        db.query(
            TokenUsageLog.tenant_id,
            func.coalesce(func.sum(TokenUsageLog.prompt_tokens + TokenUsageLog.completion_tokens), 0).label("daily_tokens"),
            func.coalesce(func.sum(TokenUsageLog.estimated_cost_usd), 0.0).label("daily_cost"),
        )
        .filter(TokenUsageLog.timestamp >= today_utc)
        .group_by(TokenUsageLog.tenant_id)
        .all()
    )
    token_stats = {
        tid: (int(tok or 0), round(float(cost or 0.0), 6)) for tid, tok, cost in token_rows
    }
    return tweet_stats, token_stats


def get_admin_platform_metrics(db: Session, days: int = 7) -> Dict[str, Any]:
    """
    SQL-aggregated platform telemetry (no full-table .all() scans into Python).
    Computes daily series, task breakdown, 24h KPIs, and user/tweet totals via SQL GROUP BY.
    """
    days = max(1, min(90, int(days or 7)))
    now_utc = datetime.utcnow()
    since_24h = now_utc - timedelta(hours=24)
    start_day = (now_utc - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    daily_map: Dict[str, Dict[str, Any]] = {}
    for offset in range(days):
        d = (start_day + timedelta(days=offset)).date()
        key = d.isoformat()
        daily_map[key] = {
            "date": key,
            "label": d.strftime("%b %d"),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "total_tokens": 0,
            "tokens": 0,
            "cost_usd": 0.0,
            "calls": 0,
        }

    day_expr = func.date(TokenUsageLog.timestamp)
    daily_rows = (
        db.query(
            day_expr.label("day"),
            func.count(TokenUsageLog.id).label("calls"),
            func.coalesce(func.sum(TokenUsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(TokenUsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(TokenUsageLog.cache_hit_tokens), 0).label("cache_hit_tokens"),
            func.coalesce(func.sum(TokenUsageLog.cache_miss_tokens), 0).label("cache_miss_tokens"),
            func.coalesce(func.sum(TokenUsageLog.estimated_cost_usd), 0.0).label("cost_usd"),
        )
        .filter(TokenUsageLog.timestamp >= start_day)
        .group_by(day_expr)
        .order_by(day_expr)
        .all()
    )

    spend_period = 0.0
    tokens_period = 0
    calls_period = 0
    cache_hit_period = 0
    cache_miss_period = 0

    for row in daily_rows:
        d_key = row.day.isoformat() if hasattr(row.day, "isoformat") else str(row.day)
        p_tok = int(row.prompt_tokens or 0)
        c_tok = int(row.completion_tokens or 0)
        ch_tok = int(row.cache_hit_tokens or 0)
        cm_tok = int(row.cache_miss_tokens or 0)
        if ch_tok == 0 and cm_tok == 0 and p_tok > 0:
            cm_tok = p_tok
        tot_tok = p_tok + c_tok
        cost = float(row.cost_usd or 0.0)
        calls = int(row.calls or 0)

        spend_period += cost
        tokens_period += tot_tok
        calls_period += calls
        cache_hit_period += ch_tok
        cache_miss_period += cm_tok

        if d_key in daily_map:
            b = daily_map[d_key]
            b["prompt_tokens"] = p_tok
            b["completion_tokens"] = c_tok
            b["cache_hit_tokens"] = ch_tok
            b["cache_miss_tokens"] = cm_tok
            b["total_tokens"] = tot_tok
            b["tokens"] = tot_tok
            b["cost_usd"] = round(cost, 6)
            b["calls"] = calls

    task_rows = (
        db.query(
            TokenUsageLog.task_type,
            func.count(TokenUsageLog.id).label("calls"),
            func.coalesce(func.sum(TokenUsageLog.prompt_tokens + TokenUsageLog.completion_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TokenUsageLog.estimated_cost_usd), 0.0).label("cost_usd"),
        )
        .filter(TokenUsageLog.timestamp >= start_day)
        .group_by(TokenUsageLog.task_type)
        .all()
    )
    task_breakdown = []
    for t_type, calls, tot_tok, cost in task_rows:
        tot_int = int(tot_tok or 0)
        c_float = round(float(cost or 0.0), 6)
        share = (tot_int / tokens_period * 100.0) if tokens_period > 0 else 0.0
        task_breakdown.append({
            "task_type": str(t_type or "general"),
            "calls": int(calls or 0),
            "total_tokens": tot_int,
            "tokens": tot_int,
            "cost_usd": c_float,
            "share_pct": round(share, 1),
        })
    task_breakdown.sort(key=lambda x: (x["cost_usd"], x["total_tokens"]), reverse=True)

    s24 = (
        db.query(
            func.count(TokenUsageLog.id).label("calls_24h"),
            func.count(func.distinct(TokenUsageLog.tenant_id)).label("active_users_24h"),
            func.coalesce(func.sum(TokenUsageLog.prompt_tokens), 0).label("prompt_24h"),
            func.coalesce(func.sum(TokenUsageLog.completion_tokens), 0).label("completion_24h"),
            func.coalesce(func.sum(TokenUsageLog.cache_hit_tokens), 0).label("hit_24h"),
            func.coalesce(func.sum(TokenUsageLog.cache_miss_tokens), 0).label("miss_24h"),
            func.coalesce(func.sum(TokenUsageLog.estimated_cost_usd), 0.0).label("spend_24h"),
        )
        .filter(TokenUsageLog.timestamp >= since_24h)
        .one()
    )
    prompt_24h = int(s24.prompt_24h or 0)
    completion_24h = int(s24.completion_24h or 0)
    cache_hit_24h = int(s24.hit_24h or 0)
    cache_miss_24h = int(s24.miss_24h or 0)
    if cache_hit_24h == 0 and cache_miss_24h == 0 and prompt_24h > 0:
        cache_miss_24h = prompt_24h

    savings_rate = 0.20 / 1_000_000.0
    denom_24h = cache_hit_24h + cache_miss_24h
    denom_period = cache_hit_period + cache_miss_period
    if denom_24h > 0:
        cache_hit_rate_pct = round((cache_hit_24h / denom_24h) * 100.0, 1)
    elif denom_period > 0:
        cache_hit_rate_pct = round((cache_hit_period / denom_period) * 100.0, 1)
    else:
        cache_hit_rate_pct = 0.0

    user_count = int(db.query(func.count(User.id)).scalar() or 0)
    cfg_agg = (
        db.query(
            func.count(AgentConfig.id).label("total_cfgs"),
            func.coalesce(func.sum(case(((AgentConfig.is_active == True) & (AgentConfig.is_suspended == False), 1), else_=0)), 0).label("active_bots"),
            func.coalesce(func.sum(case((AgentConfig.is_suspended == True, 1), else_=0)), 0).label("suspended_users"),
        )
        .one()
    )
    tweet_agg = (
        db.query(
            func.coalesce(func.sum(case(((ProcessedTweet.status == "posted") & (ProcessedTweet.timestamp >= since_24h), 1), else_=0)), 0).label("published_24h"),
            func.coalesce(func.sum(case((ProcessedTweet.status == "posted", 1), else_=0)), 0).label("published_all"),
            func.coalesce(func.sum(case((ProcessedTweet.status == "pending_approval", 1), else_=0)), 0).label("pending_total"),
        )
        .one()
    )

    total_users = max(user_count, int(cfg_agg.total_cfgs or 0))
    return {
        "days": days,
        "summary": {
            "spend_24h_usd": round(float(s24.spend_24h or 0.0), 6),
            "spend_period_usd": round(spend_period, 6),
            "tokens_24h": prompt_24h + completion_24h,
            "prompt_tokens_24h": prompt_24h,
            "completion_tokens_24h": completion_24h,
            "tokens_period": tokens_period,
            "calls_24h": int(s24.calls_24h or 0),
            "calls_period": calls_period,
            "active_users_24h": int(s24.active_users_24h or 0),
            "cache_hit_rate_pct": cache_hit_rate_pct,
            "cache_savings_24h_usd": round(cache_hit_24h * savings_rate, 6),
            "cache_savings_period_usd": round(cache_hit_period * savings_rate, 6),
            "total_users": total_users,
            "active_bots": int(cfg_agg.active_bots or 0),
            "suspended_users": int(cfg_agg.suspended_users or 0),
            "published_24h": int(tweet_agg.published_24h or 0),
            "pending_queue_total": int(tweet_agg.pending_total or 0),
        },
        "spend_24h_usd": round(float(s24.spend_24h or 0.0), 6),
        "tokens_24h": prompt_24h + completion_24h,
        "calls_24h": int(s24.calls_24h or 0),
        "spend_period_usd": round(spend_period, 6),
        "tokens_period": tokens_period,
        "calls_period": calls_period,
        "cache_hit_tokens": cache_hit_period,
        "cache_miss_tokens": cache_miss_period,
        "cache_hit_rate_pct": cache_hit_rate_pct,
        "estimated_cache_savings_usd": round(cache_hit_period * savings_rate, 6),
        "daily_series": [daily_map[k] for k in sorted(daily_map.keys())],
        "task_breakdown": task_breakdown,
        "total_users": total_users,
        "active_bots": int(cfg_agg.active_bots or 0),
        "total_published_24h": int(tweet_agg.published_24h or 0),
        "total_published_all": int(tweet_agg.published_all or 0),
    }


