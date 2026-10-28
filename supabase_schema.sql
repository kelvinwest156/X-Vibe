-- ==============================================================================
-- Supabase Schema & Row-Level Security (RLS) for X-VibeBot Creator Studio
-- Run this in your Supabase Project: SQL Editor -> New Query -> Run
-- ==============================================================================

-- 1. Create Profiles table linked to Supabase auth.users
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    tenant_id TEXT NOT NULL,
    avatar_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on profiles
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

-- 2. Create Agent Configuration Table
CREATE TABLE IF NOT EXISTS public.agent_config (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT UNIQUE NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT false,
    auto_pilot_mode BOOLEAN DEFAULT false,
    polling_interval_minutes INTEGER DEFAULT 20,
    daily_action_cap INTEGER DEFAULT 15,
    hourly_action_cap INTEGER DEFAULT 6,
    min_cooldown_minutes INTEGER DEFAULT 10,
    max_cooldown_minutes INTEGER DEFAULT 45,
    active_hours_start INTEGER DEFAULT 8,
    active_hours_end INTEGER DEFAULT 23,
    search_query TEXT DEFAULT 'buildinpublic OR #ai',
    smart_query_enabled BOOLEAN DEFAULT true,
    warmup_mode BOOLEAN DEFAULT false,
    persona_prompt TEXT DEFAULT 'Casual, sharp, dry humor, short sentences, no corporate buzzwords',
    selected_model TEXT DEFAULT 'gemini-3.8-flash',
    linked_username TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on agent_config
ALTER TABLE public.agent_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own agent config"
    ON public.agent_config FOR SELECT
    USING (auth.uid() = user_id OR tenant_id = auth.uid()::text);

CREATE POLICY "Users can update their own agent config"
    ON public.agent_config FOR UPDATE
    USING (auth.uid() = user_id OR tenant_id = auth.uid()::text);

CREATE POLICY "Users can insert their own agent config"
    ON public.agent_config FOR INSERT
    WITH CHECK (auth.uid() = user_id OR tenant_id = auth.uid()::text);

-- 3. Create Processed Tweets Table (Queue, History, Scheduled)
CREATE TABLE IF NOT EXISTS public.processed_tweets (
    tweet_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    action_type TEXT DEFAULT 'reply',
    tweet_text TEXT,
    tweet_author TEXT,
    tweet_url TEXT,
    generated_text TEXT,
    variants_json TEXT,
    tweet_metrics TEXT,
    media_url TEXT,
    should_like BOOLEAN DEFAULT false,
    urgency_score INTEGER DEFAULT 5,
    user_edited BOOLEAN DEFAULT false,
    status TEXT DEFAULT 'pending_approval',
    scheduled_for TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on processed_tweets
ALTER TABLE public.processed_tweets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own tweets"
    ON public.processed_tweets FOR SELECT
    USING (auth.uid() = user_id OR tenant_id = auth.uid()::text);

CREATE POLICY "Users can update their own tweets"
    ON public.processed_tweets FOR UPDATE
    USING (auth.uid() = user_id OR tenant_id = auth.uid()::text);

CREATE POLICY "Users can insert their own tweets"
    ON public.processed_tweets FOR INSERT
    WITH CHECK (auth.uid() = user_id OR tenant_id = auth.uid()::text);

-- 4. Automatic Trigger: Creates profile & agent_config on user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, name, tenant_id)
    VALUES (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data->>'name', split_part(new.email, '@', 1)),
        new.id::text
    );

    INSERT INTO public.agent_config (tenant_id, user_id, is_active, selected_model)
    VALUES (
        new.id::text,
        new.id,
        false,
        'gemini-3.8-flash'
    )
    ON CONFLICT (tenant_id) DO NOTHING;

    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger definition
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
