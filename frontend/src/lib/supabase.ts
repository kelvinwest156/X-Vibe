import { createClient, SupabaseClient, User, Session } from "@supabase/supabase-js";

const DEFAULT_SUPABASE_URL = "https://gvmgoqsinfvuwezszmjd.supabase.co";
const DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd2bWdvcXNpbmZ2dXdlenN6bWpkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMxOTQ0NTEsImV4cCI6MjEwODc3MDQ1MX0.fTjCup-vjlk3Y7ZAWmNsBGz05YfysQrClzQJJ8IJb1A";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || DEFAULT_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || DEFAULT_SUPABASE_ANON_KEY;

export const isSupabaseConfigured = Boolean(
  supabaseUrl &&
  supabaseAnonKey &&
  supabaseUrl.startsWith("http")
);

export const supabase: SupabaseClient = createClient(
  supabaseUrl,
  supabaseAnonKey,
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storage: typeof window !== "undefined" ? window.localStorage : undefined,
    },
  }
);

// Sign In with Email & Password
export async function signInWithEmail(email: string, pass: string): Promise<{ user: User | null; session: Session | null; error: Error | null }> {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to .env.local.");
  }
  const { data, error } = await supabase.auth.signInWithPassword({
    email: email.trim(),
    password: pass,
  });
  if (error) return { user: null, session: null, error };
  return { user: data.user, session: data.session, error: null };
}

// Sign Up with Email & Password
export async function signUpWithEmail(email: string, pass: string, name?: string): Promise<{ user: User | null; session: Session | null; error: Error | null }> {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to .env.local.");
  }
  const { data, error } = await supabase.auth.signUp({
    email: email.trim(),
    password: pass,
    options: {
      data: {
        name: name || email.split("@")[0],
      },
    },
  });
  if (error) return { user: null, session: null, error };
  return { user: data.user, session: data.session, error: null };
}

// Sign in with Google OAuth
export async function signInWithGoogle(): Promise<{ error: Error | null }> {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to .env.local.");
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: typeof window !== "undefined" ? window.location.origin : undefined,
    },
  });
  return { error };
}

// Sign in with Twitter / X OAuth
export async function signInWithTwitter(): Promise<{ error: Error | null }> {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to .env.local.");
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "twitter",
    options: {
      redirectTo: typeof window !== "undefined" ? window.location.origin : undefined,
    },
  });
  return { error };
}

// Sign Out
export async function signOutUser(): Promise<{ error: Error | null }> {
  if (!isSupabaseConfigured) {
    return { error: null };
  }
  const { error } = await supabase.auth.signOut();
  return { error };
}

// Request password reset email via Supabase
export async function resetPasswordForEmail(email: string): Promise<{ error: Error | null }> {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured.");
  }
  const redirectTo = typeof window !== "undefined" ? `${window.location.origin}/?mode=reset` : undefined;
  const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
    redirectTo,
  });
  return { error };
}

// Update user password after recovery
export async function updateUserPassword(newPassword: string): Promise<{ error: Error | null }> {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured.");
  }
  const { error } = await supabase.auth.updateUser({
    password: newPassword,
  });
  return { error };
}

// Get current session
export async function getSession(): Promise<Session | null> {
  if (!isSupabaseConfigured) return null;
  const { data } = await supabase.auth.getSession();
  return data.session;
}

// Real-time auth state listener
export function subscribeToAuth(callback: (event: string, session: Session | null) => void) {
  if (!isSupabaseConfigured) {
    return { data: { subscription: { unsubscribe: () => {} } } };
  }
  return supabase.auth.onAuthStateChange((event, session) => {
    callback(event, session);
  });
}
