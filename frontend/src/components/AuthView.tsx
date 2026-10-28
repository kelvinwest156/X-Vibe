"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { ShieldCheck, ArrowRight, Lock, Sparkles, CheckCircle2, Loader2, AlertCircle, Sun, Moon } from "lucide-react";
import {
  isSupabaseConfigured,
  signInWithEmail,
  signUpWithEmail,
  signInWithGoogle,
  signInWithTwitter,
} from "@/lib/supabase";

interface AuthViewProps {
  onLoginWithX: () => Promise<void> | void;
  onExploreDemo?: () => void;
  busyLogin?: boolean;
  onAuthenticated?: (user: { uid: string; email?: string | null; displayName?: string | null }, token: string) => void;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
}

export default function AuthView({
  onLoginWithX,
  onExploreDemo,
  busyLogin = false,
  onAuthenticated,
  theme = "light",
  onToggleTheme,
}: AuthViewProps) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [localMessage, setLocalMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  const handleGoogleAuth = async () => {
    setIsSubmitting(true);
    setLocalMessage(null);
    setIsError(false);
    try {
      if (isSupabaseConfigured) {
        const { error } = await signInWithGoogle();
        if (error) throw error;
      } else {
        setLocalMessage("Supabase demo mode: connect with X directly or sign in with email.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Google authentication failed";
      setLocalMessage(msg);
      setIsError(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTwitterAuth = async () => {
    setIsSubmitting(true);
    setLocalMessage(null);
    setIsError(false);
    try {
      if (isSupabaseConfigured) {
        const { error } = await signInWithTwitter();
        if (error) throw error;
      } else {
        await onLoginWithX();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "X authentication failed";
      setLocalMessage(msg);
      setIsError(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setLocalMessage(null);
    setIsError(false);
    try {
      if (isSupabaseConfigured) {
        if (mode === "signin") {
          const { user, session, error } = await signInWithEmail(email, password);
          if (error) throw error;
          if (user && session) {
            setLocalMessage(`Signed in as ${user.email}!`);
            onAuthenticated?.(
              {
                uid: user.id,
                email: user.email,
                displayName: user.user_metadata?.name || user.email?.split("@")[0],
              },
              session.access_token
            );
            return;
          }
        } else {
          const { user, session, error } = await signUpWithEmail(email, password);
          if (error) throw error;
          if (user) {
            setLocalMessage(
              session
                ? "Account created successfully!"
                : "Check your email for the confirmation link to complete registration."
            );
            if (session) {
              onAuthenticated?.(
                {
                  uid: user.id,
                  email: user.email,
                  displayName: user.user_metadata?.name || user.email?.split("@")[0],
                },
                session.access_token
              );
            }
            return;
          }
        }
      }

      // Direct FastAPI fallback if Supabase is in local/demo mode
      const endpoint = mode === "signin" ? "/api/auth/signin" : "/api/auth/signup";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          password,
          name: email.split("@")[0],
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || "Authentication failed");
      }

      setLocalMessage(data.message || (mode === "signin" ? "Signed in successfully!" : "Account created successfully!"));
      if (typeof window !== "undefined") {
        localStorage.setItem("xvibebot_auth_token", data.token);
        localStorage.setItem("xvibebot_tenant_id", data.tenant_id);
        localStorage.setItem("xvibebot_user_email", data.user.email);
      }
      onAuthenticated?.(data.user, data.token);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Authentication error";
      setLocalMessage(msg);
      setIsError(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#121212] text-slate-900 dark:text-[#F3F3F3] flex flex-col justify-between selection:bg-neutral-900 selection:text-white transition-colors duration-200">
      {/* Top minimal header */}
      <header className="w-full max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-black text-white flex items-center justify-center font-bold text-lg shadow-sm shrink-0">
            <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-[15px] tracking-tight text-slate-900 dark:text-white">
                X-VibeBot
              </span>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-100 dark:bg-[#222222] text-slate-600 dark:text-[#A3A3A3] border border-slate-200 dark:border-[#2E2E2E]">
                v2.0
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {onToggleTheme && (
            <button
              type="button"
              onClick={onToggleTheme}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-[#222222] transition-colors"
              title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              aria-label="Toggle theme"
            >
              {theme === "light" ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4 text-amber-400" />}
            </button>
          )}

          {onExploreDemo && (
            <button
              onClick={onExploreDemo}
              className="text-[13px] font-medium text-slate-600 dark:text-[#D4D4D4] hover:text-slate-900 dark:hover:text-white transition-colors flex items-center gap-1.5"
            >
              <span>Sneak Peek</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </header>

      {/* Main Hero & Auth Card */}
      <main className="flex-1 flex items-center justify-center p-4 sm:p-6 my-2 sm:my-4">
        <div className="w-full max-w-[460px] space-y-6">
          {/* Headline */}
          <div className="text-center">
            <motion.h1
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-2xl sm:text-3xl font-semibold text-slate-900 dark:text-white tracking-tight"
            >
              Sign in to your Creator Studio
            </motion.h1>
          </div>

          {/* Auth Card */}
          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.2 }}
            className="bg-white dark:bg-[#181818] border border-slate-200 dark:border-[#262626] rounded-2xl p-6 sm:p-8 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.05)] dark:shadow-[0_4px_20px_-4px_rgba(0,0,0,0.7)] space-y-5"
          >
            {/* Primary OAuth Actions */}
            <div className="space-y-2.5">
              {/* Continue with X */}
              <button
                type="button"
                onClick={handleTwitterAuth}
                disabled={busyLogin || isSubmitting}
                className="w-full h-11 px-4 rounded-xl bg-black hover:bg-neutral-900 dark:bg-white dark:hover:bg-[#EDEDED] dark:text-black active:scale-[0.99] text-white font-medium text-[13.5px] transition-all flex items-center justify-center gap-3 shadow-sm disabled:opacity-60"
              >
                {busyLogin || isSubmitting ? (
                  <Loader2 className="w-4 h-4 animate-spin text-white dark:text-black" />
                ) : (
                  <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                  </svg>
                )}
                <span>{busyLogin ? "Launching Isolated Browser..." : "Continue with X (Twitter)"}</span>
              </button>

              {/* Continue with Google */}
              <button
                type="button"
                onClick={handleGoogleAuth}
                disabled={isSubmitting}
                className="w-full h-11 px-4 rounded-xl bg-white dark:bg-[#202020] hover:bg-slate-50 dark:hover:bg-[#282828] active:scale-[0.99] text-slate-800 dark:text-[#E5E5E5] font-medium text-[13.5px] border border-slate-200 dark:border-[#2E2E2E] transition-all flex items-center justify-center gap-3 shadow-xs disabled:opacity-60"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24">
                  <path
                    fill="#4285F4"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                  />
                </svg>
                <span>Continue with Google</span>
              </button>
            </div>

            {/* Subtle Divider */}
            <div className="relative flex items-center justify-center h-4">
              <div className="absolute inset-x-0 top-1/2 border-t border-slate-200 dark:border-[#262626]" />
              <span className="relative bg-white dark:bg-[#181818] px-3 text-[11px] font-medium text-slate-400 dark:text-[#737373] uppercase tracking-wider whitespace-nowrap">
                or with email
              </span>
            </div>

            {/* Mode switch */}
            <div className="flex p-1 bg-slate-100 dark:bg-[#202020] rounded-lg text-[12px] font-medium text-slate-600 dark:text-[#A3A3A3]">
              <button
                type="button"
                onClick={() => setMode("signin")}
                className={`flex-1 py-1.5 rounded-md transition-all ${
                  mode === "signin"
                    ? "bg-white dark:bg-[#141414] text-slate-900 dark:text-white shadow-xs font-semibold"
                    : "hover:text-slate-900 dark:hover:text-white"
                }`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => setMode("signup")}
                className={`flex-1 py-1.5 rounded-md transition-all ${
                  mode === "signup"
                    ? "bg-white dark:bg-[#141414] text-slate-900 dark:text-white shadow-xs font-semibold"
                    : "hover:text-slate-900 dark:hover:text-white"
                }`}
              >
                Create Account
              </button>
            </div>

            {/* Email form */}
            <form onSubmit={handleEmailAuth} className="space-y-3.5">
              <div>
                <label className="block text-[12px] font-medium text-slate-700 dark:text-[#D4D4D4] mb-1.5">
                  Email
                </label>
                <input
                  type="email"
                  required
                  placeholder="alex@buildspace.so"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full h-10 px-3.5 rounded-lg border border-slate-200 dark:border-[#2E2E2E] bg-white dark:bg-[#121212] text-[13px] text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-[#666666] focus:outline-none focus:border-slate-900 dark:focus:border-[#555555] focus:ring-2 focus:ring-slate-900/5 transition-all"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-700 dark:text-[#D4D4D4] mb-1.5">
                  Password {mode === "signup" && <span className="text-[11px] text-slate-400 dark:text-[#737373] font-normal">(min 6 characters)</span>}
                </label>
                <input
                  type="password"
                  required
                  minLength={6}
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full h-10 px-3.5 rounded-lg border border-slate-200 dark:border-[#2E2E2E] bg-white dark:bg-[#121212] text-[13px] text-slate-900 dark:text-white placeholder:text-slate-400 dark:placeholder:text-[#666666] focus:outline-none focus:border-slate-900 dark:focus:border-[#555555] focus:ring-2 focus:ring-slate-900/5 transition-all"
                />
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full h-10 rounded-lg bg-slate-900 hover:bg-black dark:bg-white dark:hover:bg-[#EDEDED] text-white dark:text-black text-[13px] font-medium transition-all flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <Loader2 className="w-4 h-4 animate-spin text-white dark:text-black" />
                ) : (
                  <span>{mode === "signin" ? "Sign In to Studio" : "Create Studio Account"}</span>
                )}
              </button>
            </form>

            {localMessage && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                className={`p-3 rounded-lg text-[12px] flex items-start gap-2 border ${
                  isError
                    ? "bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60 text-rose-800 dark:text-rose-200"
                    : "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-900/60 text-emerald-800 dark:text-emerald-200"
                }`}
              >
                {isError ? (
                  <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                )}
                <span>{localMessage}</span>
              </motion.div>
            )}

            {/* Reassuring Security Notice */}
            <div className="pt-2 border-t border-slate-100 dark:border-[#262626] flex items-start gap-2.5 text-left">
              <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
              <p className="text-[11.5px] leading-relaxed text-slate-500 dark:text-[#A3A3A3]">
                <strong className="text-slate-700 dark:text-[#E5E5E5] font-medium">Direct X sync:</strong> your
                workspace and browser profile are isolated and 100% private. We never store or
                share your credentials.
              </p>
            </div>
          </motion.div>

          {/* Bottom Security / Feature badges */}
          <div className="flex items-center justify-center gap-4 text-[12px] text-slate-500 dark:text-[#737373] flex-wrap">
            <span className="flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-slate-400 dark:text-[#666666]" />
              Isolated Browser Sandbox
            </span>
            <span>·</span>
            <span className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-slate-400 dark:text-[#666666]" />
              Few-Shot Voice Cloning
            </span>
            <span>·</span>
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
              Bézier Biometrics Active
            </span>
          </div>
        </div>
      </main>

    </div>
  );
}
