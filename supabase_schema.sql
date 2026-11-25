-- ==============================================================================
-- Supabase Schema & Row-Level Security (RLS) for X-VibeBot Creator Studio
-- Mirrors models.py 1:1 (Composite Multi-Tenant PKs, Users, Token Telemetry, Settings)
-- Run in Supabase SQL Editor -> New Query -> Run
-- ==============================================================================

-- 1. Creator Accounts Table (matches models.User)
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(128),
    tenant_id VARCHAR(128) UNIQUE NOT NULL,
    token_version INTEGER DEFAULT 1 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- 2. Agent Configuration Table (matches models.AgentConfig)
CREATE TABLE IF NOT EXISTS public.agent_config (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(128) UNIQUE NOT NULL DEFAULT 'default',
    is_active BOOLEAN DEFAULT false,
    auto_pilot_mode BOOLEAN DEFAULT false,
    polling_interval_minutes INTEGER DEFAULT 20,
    daily_action_cap INTEGER DEFAULT 15,
    hourly_action_cap INTEGER DEFAULT 6,
    min_cooldown_minutes INTEGER DEFAULT 10,
    max_cooldown_minutes INTEGER DEFAULT 45,
    active_hours_start INTEGER DEFAULT 8,
    active_hours_end INTEGER DEFAULT 23,
    search_query VARCHAR(256) DEFAULT 'buildinpublic OR #ai',
    smart_query_enabled BOOLEAN DEFAULT true,
    warmup_mode BOOLEAN DEFAULT false,
    persona_prompt TEXT DEFAULT 'Casual, sharp, dry humor, short sentences, no corporate buzzwords',
    selected_model VARCHAR(64) DEFAULT 'auto',
    linked_username VARCHAR(128),
    cookies_json TEXT,
    api_key VARCHAR(512),
    daily_token_cap INTEGER DEFAULT 50000,
    max_pending_queue INTEGER DEFAULT 8,
    auto_sleep_browser BOOLEAN DEFAULT true,
    is_suspended BOOLEAN DEFAULT false,
    plan_tier VARCHAR(32) DEFAULT 'trial',
    subscription_status VARCHAR(32) DEFAULT 'trialing',
    trial_ends_at TIMESTAMP WITH TIME ZONE,
    daily_original_post_cap INTEGER DEFAULT 3,
    payment_customer_id VARCHAR(128),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_config_active_susp ON public.agent_config (is_active, is_suspended);

ALTER TABLE public.agent_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own agent config"
    ON public.agent_config FOR SELECT
    USING (tenant_id = auth.uid()::text);

CREATE POLICY "Users can update their own agent config"
    ON public.agent_config FOR UPDATE
    USING (tenant_id = auth.uid()::text);

CREATE POLICY "Users can insert their own agent config"
    ON public.agent_config FOR INSERT
    WITH CHECK (tenant_id = auth.uid()::text);

-- 3. Processed Tweets Table (Composite PK (tenant_id, tweet_id) matches models.ProcessedTweet)
CREATE TABLE IF NOT EXISTS public.processed_tweets (
    tweet_id VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    action_type VARCHAR(32) DEFAULT 'reply',
    tweet_text TEXT,
    tweet_author VARCHAR(128),
    tweet_url VARCHAR(512),
    generated_text TEXT,
    variants_json TEXT,
    tweet_metrics VARCHAR(128),
    media_url VARCHAR(512),
    should_like BOOLEAN DEFAULT false,
    urgency_score INTEGER DEFAULT 5,
    user_edited BOOLEAN DEFAULT false,
    status VARCHAR(32) DEFAULT 'pending_approval',
    scheduled_for TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    PRIMARY KEY (tenant_id, tweet_id)
);

CREATE INDEX IF NOT EXISTS ix_processed_tweets_tweet_id ON public.processed_tweets (tweet_id);
CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_status_ts ON public.processed_tweets (tenant_id, status, timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_processed_tweets_status_sched ON public.processed_tweets (status, scheduled_for);
CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_status_sched ON public.processed_tweets (tenant_id, status, scheduled_for);
CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_type_ts ON public.processed_tweets (tenant_id, action_type, timestamp);
CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_ts ON public.processed_tweets (tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_processed_tweets_tenant_url ON public.processed_tweets (tenant_id, tweet_url);

ALTER TABLE public.processed_tweets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own tweets"
    ON public.processed_tweets FOR SELECT
    USING (tenant_id = auth.uid()::text);

CREATE POLICY "Users can update their own tweets"
    ON public.processed_tweets FOR UPDATE
    USING (tenant_id = auth.uid()::text);

CREATE POLICY "Users can insert their own tweets"
    ON public.processed_tweets FOR INSERT
    WITH CHECK (tenant_id = auth.uid()::text);

-- 4. AI Token Usage Logs Table (matches models.TokenUsageLog)
CREATE TABLE IF NOT EXISTS public.token_usage_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
    provider VARCHAR(64) NOT NULL DEFAULT 'deepseek',
    model VARCHAR(64) NOT NULL DEFAULT 'deepseek-chat',
    task_type VARCHAR(64) NOT NULL DEFAULT 'general',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
    cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_token_usage_tenant_ts ON public.token_usage_logs (tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_token_usage_ts_task_tenant ON public.token_usage_logs (timestamp, task_type, tenant_id);

ALTER TABLE public.token_usage_logs ENABLE ROW LEVEL SECURITY;

-- 5. Platform Settings & Webhook Idempotency Tables
CREATE TABLE IF NOT EXISTS public.platform_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    default_daily_token_cap INTEGER NOT NULL DEFAULT 50000,
    web_radar_cache_seconds INTEGER NOT NULL DEFAULT 7200,
    browser_idle_sleep_minutes INTEGER NOT NULL DEFAULT 15,
    auto_sleep_browsers_enabled BOOLEAN NOT NULL DEFAULT true,
    global_pause_bots BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE TABLE IF NOT EXISTS public.webhook_events (
    event_id VARCHAR(128) PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.platform_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;

-- 6. Automatic Trigger: Provisions agent_config row on Supabase auth signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.agent_config (tenant_id, is_active, selected_model, plan_tier, subscription_status, trial_ends_at)
    VALUES (
        new.id::text,
        false,
        'auto',
        'trial',
        'trialing',
        timezone('utc'::text, now()) + interval '7 days'
    )
    ON CONFLICT (tenant_id) DO NOTHING;

    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
