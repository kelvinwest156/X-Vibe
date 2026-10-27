"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { ShieldCheck, ArrowRight, Lock, Sparkles, CheckCircle2, Loader2, AlertCircle, Sun, Moon } from "lucide-react";
import {
  isFirebaseConfigured,
  loginWithGoogle,
  loginWithTwitter,
  loginWithEmail,
  registerWithEmail,
} from "@/lib/firebase";

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
      if (isFirebaseConfigured) {
        const { user, token } = await loginWithGoogle();
        if (user && token) {
          setLocalMessage(`Signed in as ${user.displayName || user.email}!`);
          onAuthenticated?.(user, token);
        }
      } else {
        setLocalMessage("Firebase demo mode: connect with X directly to link your browser session.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Authentication failed";
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
      if (isFirebaseConfigured) {
        try {
          const { user, token } = await loginWithTwitter();
          if (user && token) {
            setLocalMessage(`Authenticated with X! Launching browser session...`);
            onAuthenticated?.(user, token);
          }
        } catch {
          // If popup blocked or cancelled, fall back to direct browser session
          await onLoginWithX();
        }
      } else {
        // Direct browser session launch
        await onLoginWithX();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Authentication failed";
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
      if (isFirebaseConfigured) {
        const { user, token } = mode === "signin"
          ? await loginWithEmail(email, password)
          : await registerWithEmail(email, password);
        if (user && token) {
          setLocalMessage(
            mode === "signin"
              ? "Signed in! Now sync your X account to activate the autonomous drafting studio."
              : "Account created! Connect your X profile to start the AI studio."
          );
          onAuthenticated?.(user, token);
        }
      } else {
        // Local simulation when Firebase keys are not in .env
        setTimeout(() => {
          setIsSubmitting(false);
          setLocalMessage(
            mode === "signin"
              ? "Signed in! Now connect with X to link your workspace."
              : "Account created! Connect your X profile to start the AI studio."
          );
          onAuthenticated?.({ uid: `tenant_${Date.now()}`, email }, "demo_token");
        }, 500);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Authentication error";
      setLocalMessage(msg);
      setIsError(true);
    } finally {
      if (isFirebaseConfigured) setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#090D16] text-slate-900 dark:text-slate-100 flex flex-col justify-between selection:bg-slate-900 selection:text-white transition-colors duration-200">
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
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                Creator Studio 2.0
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">Autonomous X Growth & Voice Engine</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {onToggleTheme && (
            <button
              type="button"
              onClick={onToggleTheme}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              aria-label="Toggle theme"
            >
              {theme === "light" ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4 text-amber-400" />}
            </button>
          )}

          {onExploreDemo && (
            <button
              onClick={onExploreDemo}
              className="text-[13px] font-medium text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors flex items-center gap-1.5"
            >
              <span className="hidden sm:inline">Explore Studio in Demo Mode</span>
              <span className="sm:hidden">Demo Mode</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </header>

      {/* Main Hero & Auth Card */}
      <main className="flex-1 flex items-center justify-center p-4 sm:p-6 my-2 sm:my-4">
        <div className="w-full max-w-[460px] space-y-6">
          {/* Headline */}
          <div className="text-center space-y-2">
            <motion.h1
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-2xl sm:text-3xl font-semibold text-slate-900 dark:text-white tracking-tight"
            >
              Sign in to your Creator Studio
            </motion.h1>
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 }}
              className="text-sm text-slate-500 dark:text-slate-400 max-w-sm mx-auto"
            >
              Autonomous feed intelligence, few-shot voice cloning, and organic engagement for builders on X.
            </motion.p>
          </div>

          {/* Auth Card */}
          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.2 }}
            className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 sm:p-8 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.05)] dark:shadow-[0_4px_20px_-4px_rgba(0,0,0,0.4)] space-y-5"
          >
            {/* Primary OAuth Actions */}
            <div className="space-y-2.5">
              {/* Continue with X */}
              <button
                type="button"
                onClick={handleTwitterAuth}
                disabled={busyLogin || isSubmitting}
                className="w-full h-11 px-4 rounded-xl bg-black hover:bg-neutral-900 dark:bg-white dark:hover:bg-slate-200 dark:text-black active:scale-[0.99] text-white font-medium text-[13.5px] transition-all flex items-center justify-center gap-3 shadow-sm disabled:opacity-60"
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
                className="w-full h-11 px-4 rounded-xl bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700/80 active:scale-[0.99] text-slate-800 dark:text-slate-100 font-medium text-[13.5px] border border-slate-200 dark:border-slate-700 transition-all flex items-center justify-center gap-3 shadow-xs disabled:opacity-60"
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
            <div className="relative flex items-center justify-center">
              <div className="border-t border-slate-200 dark:border-slate-800 w-full" />
              <span className="bg-white dark:bg-slate-900 px-3 text-[11px] font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                or with email
              </span>
            </div>

            {/* Mode switch */}
            <div className="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-lg text-[12px] font-medium text-slate-600 dark:text-slate-400">
              <button
                type="button"
                onClick={() => setMode("signin")}
                className={`flex-1 py-1.5 rounded-md transition-all ${
                  mode === "signin"
                    ? "bg-white dark:bg-slate-900 text-slate-900 dark:text-white shadow-xs font-semibold"
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
                    ? "bg-white dark:bg-slate-900 text-slate-900 dark:text-white shadow-xs font-semibold"
                    : "hover:text-slate-900 dark:hover:text-white"
                }`}
              >
                Create Account
              </button>
            </div>

            {/* Email form */}
            <form onSubmit={handleEmailAuth} className="space-y-3.5">
              <div>
                <label className="block text-[12px] font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  Work or Creator Email
                </label>
                <input
                  type="email"
                  required
                  placeholder="alex@buildspace.so"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full h-10 px-3.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-[13px] text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:border-slate-900 dark:focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5 transition-all"
                />
              </div>

              <div>
                <label className="block text-[12px] font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  Password
                </label>
                <input
                  type="password"
                  required
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full h-10 px-3.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-[13px] text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:border-slate-900 dark:focus:border-slate-400 focus:ring-2 focus:ring-slate-900/5 transition-all"
                />
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full h-10 rounded-lg bg-slate-900 hover:bg-black dark:bg-white dark:hover:bg-slate-200 text-white dark:text-black text-[13px] font-medium transition-all flex items-center justify-center gap-2"
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
                    ? "bg-rose-50 dark:bg-rose-950/50 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200"
                    : "bg-emerald-50 dark:bg-emerald-950/50 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200"
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
            <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex items-start gap-2.5 text-left">
              <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
              <p className="text-[11.5px] leading-relaxed text-slate-500 dark:text-slate-400">
                <strong className="text-slate-700 dark:text-slate-200 font-medium">Direct X sync:</strong> your
                workspace and browser profile are isolated and 100% private. We never store or
                share your credentials.
              </p>
            </div>
          </motion.div>

          {/* Bottom Security / Feature badges */}
          <div className="flex items-center justify-center gap-4 text-[12px] text-slate-500 dark:text-slate-400 flex-wrap">
            <span className="flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
              Isolated Browser Sandbox
            </span>
            <span>·</span>
            <span className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" />
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

      {/* Footer */}
      <footer className="w-full max-w-6xl mx-auto px-6 py-4 text-center text-xs text-slate-400 dark:text-slate-500">
        X-VibeBot Studio · Built for Modern Founders and Creators on X
      </footer>
    </div>
  );
}
