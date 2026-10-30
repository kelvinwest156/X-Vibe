"use client";

import React, { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2,
  Loader2,
  AlertCircle,
  Sun,
  Moon,
  Eye,
  EyeOff,
  Clock,
} from "lucide-react";
import {
  isSupabaseConfigured,
  signInWithEmail,
  signUpWithEmail,
  signInWithGoogle,
} from "@/lib/supabase";

interface AuthViewProps {
  onAuthenticated?: (
    user: { uid: string; email?: string | null; displayName?: string | null; tenant_id?: string },
    token: string,
    isNewSignup?: boolean
  ) => void;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
}

function getPasswordStrength(pw: string): { score: number; label: string } {
  if (!pw) return { score: 0, label: "Minimum 6 characters" };
  if (pw.length < 6) return { score: 1, label: `${6 - pw.length} more characters needed` };
  let score = 2;
  if (pw.length >= 10) score += 1;
  if (/[A-Z]/.test(pw) && /[0-9!@#$%^&*(),.?":{}|<>]/.test(pw)) score += 1;
  const labels = ["", "Too short", "Fair", "Good", "Strong"];
  return { score: Math.min(score, 4), label: labels[Math.min(score, 4)] };
}

export default function AuthView({
  onAuthenticated,
  theme = "light",
  onToggleTheme,
}: AuthViewProps) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleBusy, setIsGoogleBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);

  const strength = useMemo(() => getPasswordStrength(password), [password]);

  const switchMode = (nextMode: "signin" | "signup") => {
    setMode(nextMode);
    setFeedback(null);
  };

  const handleGoogleAuth = async () => {
    setIsGoogleBusy(true);
    setFeedback(null);
    try {
      if (isSupabaseConfigured) {
        const { error } = await signInWithGoogle();
        if (error) throw error;
      } else {
        setFeedback({
          text: "Google SSO requires NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local. Continue with your email below.",
          isError: true,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Google sign-in could not be started.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsGoogleBusy(false);
    }
  };

  const handleEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setFeedback(null);

    const cleanEmail = email.trim().toLowerCase();
    const cleanName = name.trim() || cleanEmail.split("@")[0];

    try {
      if (isSupabaseConfigured) {
        if (mode === "signin") {
          const { user, session, error } = await signInWithEmail(cleanEmail, password);
          if (error) throw error;
          if (user && session) {
            onAuthenticated?.(
              {
                uid: user.id,
                email: user.email,
                displayName: user.user_metadata?.name || cleanEmail.split("@")[0],
                tenant_id: user.id,
              },
              session.access_token,
              false
            );
            return;
          }
        } else {
          const { user, session, error } = await signUpWithEmail(cleanEmail, password, cleanName);
          if (error) throw error;
          if (user) {
            if (session) {
              onAuthenticated?.(
                {
                  uid: user.id,
                  email: user.email,
                  displayName: user.user_metadata?.name || cleanName,
                  tenant_id: user.id,
                },
                session.access_token,
                true
              );
            } else {
              setFeedback({
                text: "Check your inbox for the verification link to activate your workspace.",
                isError: false,
              });
            }
            return;
          }
        }
      }

      // Direct backend workspace authentication
      const endpoint = mode === "signin" ? "/api/auth/signin" : "/api/auth/signup";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: cleanEmail,
          password,
          name: mode === "signup" ? cleanName : undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || "Could not verify your credentials.");
      }

      if (typeof window !== "undefined") {
        localStorage.setItem("xvibebot_auth_token", data.token);
        localStorage.setItem("xvibebot_tenant_id", data.tenant_id);
        localStorage.setItem("xvibebot_user_email", data.user.email);
        if (data.user.name) {
          localStorage.setItem("xvibebot_user_name", data.user.name);
        }
      }

      onAuthenticated?.(
        {
          uid: data.user.uid,
          email: data.user.email,
          displayName: data.user.name || cleanName,
          tenant_id: data.tenant_id,
        },
        data.token,
        mode === "signup"
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Authentication failed. Check your connection and try again.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-dvh bg-white dark:bg-[#0E0E0E] text-[#111111] dark:text-[#F5F5F5] grid lg:grid-cols-[46%_54%] xl:grid-cols-[44%_56%] selection:bg-[#111111] selection:text-white dark:selection:bg-white dark:selection:text-[#111111] transition-colors duration-200">
      {/* Left Editorial Product Stage (Desktop) */}
      <aside className="hidden lg:flex flex-col justify-between bg-[#F4F4F5] dark:bg-[#131313] border-r border-[#E4E4E7] dark:border-[#222222] p-10 xl:p-14 relative overflow-hidden">
        {/* Top Brand Lockup */}
        <div className="flex items-center gap-2.5 relative z-10">
          <div className="w-8 h-8 rounded-lg bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
            <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
          </div>
          <span className="font-display font-semibold text-[15px] tracking-[-0.02em] text-[#111111] dark:text-[#F5F5F5]">
            X-VibeBot
          </span>
          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-white dark:bg-[#1E1E1E] text-[#52525B] dark:text-[#9E9E9E] border border-[#E4E4E7] dark:border-[#2C2C2C]">
            v2.0
          </span>
        </div>

        {/* Center Editorial Value + Live Calibration Artifact */}
        <div className="max-w-[440px] space-y-8 my-auto py-8 relative z-10">
          <div className="space-y-3.5">
            <h2 className="font-display text-[28px] xl:text-[32px] font-semibold leading-[1.18] tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5]">
              Show up in the right X conversations, in your own voice.
            </h2>
            <p className="text-[14px] leading-[1.65] text-[#52525B] dark:text-[#9E9E9E]">
              Monitor high-signal threads in your niche, train replies directly from your own edits, and publish on natural human intervals.
            </p>
          </div>

          {/* Authentic Product Preview Surface */}
          <div className="rounded-xl bg-white dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] dark:shadow-[0_8px_24px_rgba(0,0,0,0.45)] space-y-4">
            {/* Incoming Thread Context */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-[12px]">
                <div className="flex items-center gap-2">
                  <div className="w-5 h-5 rounded-full bg-[#E4E4E7] dark:bg-[#2A2A2A] flex items-center justify-center text-[10px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                    M
                  </div>
                  <span className="font-medium text-[#111111] dark:text-[#E5E5E5]">@marclou_dev</span>
                  <span className="text-[#A1A1AA] dark:text-[#6E6E6E]">12m ago</span>
                </div>
                <span className="text-[11px] font-medium text-[#52525B] dark:text-[#9E9E9E]">
                  High relevance
                </span>
              </div>
              <p className="text-[12.5px] leading-[1.55] text-[#52525B] dark:text-[#A3A3A3] pl-7">
                Anyone running usage-based billing in production—how do you handle card expirations without hurting retention?
              </p>
            </div>

            {/* Calibrated Voice Reply */}
            <div className="relative pl-7 pt-1">
              <div className="absolute left-[9px] -top-2 bottom-3 w-[1.5px] bg-[#E4E4E7] dark:bg-[#2A2A2A]" />
              <div className="absolute left-[6px] top-3.5 w-[7.5px] h-[7.5px] rounded-full bg-[#EA580C]" />

              <div className="rounded-lg bg-[#FAFAFA] dark:bg-[#131313] border border-[#E4E4E7] dark:border-[#262626] p-3.5 space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11.5px] font-medium text-[#111111] dark:text-[#F5F5F5]">
                    Drafted in your voice
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] text-[#EA580C] font-medium">
                    <Clock className="w-3 h-3" />
                    Scheduled in 14m
                  </span>
                </div>
                <p className="text-[12.5px] leading-[1.55] text-[#111111] dark:text-[#E5E5E5]">
                  Give a 72-hour in-app banner before sending a single billing email. Most failed renewals are expired virtual cards, not churn.
                </p>
                <div className="pt-2 border-t border-[#E4E4E7]/80 dark:border-[#222222] flex items-center justify-between text-[11px] text-[#71717A] dark:text-[#787878]">
                  <span>Shaped from 24 approved edits</span>
                  <span>131 chars</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Quiet Security Architecture Line */}
        <div className="text-[12px] text-[#71717A] dark:text-[#737373] relative z-10">
          Dedicated browser container per workspace. Credentials remain encrypted and isolated.
        </div>
      </aside>

      {/* Right Interactive Form Stage */}
      <div className="flex flex-col justify-between min-h-dvh px-5 py-5 sm:px-10 sm:py-7">
        {/* Top Utility Header */}
        <header className="flex items-center justify-between gap-4">
          {/* Mobile Brand Lockup */}
          <div className="flex lg:hidden items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
              <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
              </svg>
            </div>
            <span className="font-display font-semibold text-[15px] tracking-[-0.02em]">
              X-VibeBot
            </span>
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-[#F4F4F5] dark:bg-[#1A1A1A] text-[#52525B] dark:text-[#9E9E9E] border border-[#E4E4E7] dark:border-[#262626]">
              v2.0
            </span>
          </div>

          <div className="hidden lg:block" />

          {/* Right Controls: Quick Mode Switch + Theme Toggle */}
          <div className="flex items-center gap-2.5">
            {mode === "signin" ? (
              <button
                type="button"
                onClick={() => switchMode("signup")}
                className="h-8 px-3 rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[12px] font-medium text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-colors"
              >
                Create account
              </button>
            ) : (
              <button
                type="button"
                onClick={() => switchMode("signin")}
                className="h-8 px-3 rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[12px] font-medium text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-colors"
              >
                Sign in
              </button>
            )}

            {onToggleTheme && (
              <button
                type="button"
                onClick={onToggleTheme}
                className="w-8 h-8 rounded-lg border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-center text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] transition-colors"
                title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
                aria-label="Toggle theme"
              >
                {theme === "light" ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4 text-amber-400" />}
              </button>
            )}
          </div>
        </header>

        {/* Centered Form Container */}
        <main className="w-full max-w-[380px] mx-auto my-auto py-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={mode}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
              className="space-y-6"
            >
              {/* Form Heading */}
              <div className="space-y-1.5">
                {mode === "signup" && (
                  <div className="inline-flex items-center gap-2 text-[12px] font-medium text-[#EA580C] mb-1">
                    <span>Step 1 of 2</span>
                    <span className="text-[#D4D4D8] dark:text-[#333333]">/</span>
                    <span className="text-[#71717A] dark:text-[#8E8E8E]">Create workspace</span>
                  </div>
                )}
                <h1 className="font-display text-[24px] sm:text-[26px] font-semibold tracking-[-0.025em] text-[#111111] dark:text-[#F5F5F5]">
                  {mode === "signin" ? "Sign in to X-VibeBot" : "Create your workspace"}
                </h1>
                <p className="text-[13.5px] leading-relaxed text-[#52525B] dark:text-[#9E9E9E]">
                  {mode === "signin"
                    ? "Enter your email and password to access your studio."
                    : "Set up your account, then connect your X profile in the next step."}
                </p>
              </div>

              {/* Secondary Google SSO */}
              <button
                type="button"
                onClick={handleGoogleAuth}
                disabled={isGoogleBusy || isSubmitting}
                className="w-full h-10 px-4 rounded-lg bg-white dark:bg-[#161616] hover:bg-[#FAFAFA] dark:hover:bg-[#1E1E1E] active:scale-[0.995] text-[#111111] dark:text-[#F5F5F5] font-medium text-[13.5px] border border-[#E4E4E7] dark:border-[#2A2A2A] transition-all flex items-center justify-center gap-2.5 disabled:opacity-60"
              >
                {isGoogleBusy ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24">
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
                )}
                <span>Continue with Google</span>
              </button>

              {/* Hairline Divider */}
              <div className="relative flex items-center justify-center">
                <div className="absolute inset-x-0 top-1/2 border-t border-[#E4E4E7] dark:border-[#242424]" />
                <span className="relative bg-white dark:bg-[#0E0E0E] px-3 text-[12px] text-[#A1A1AA] dark:text-[#666666]">
                  or
                </span>
              </div>

              {/* Email & Password Form */}
              <form onSubmit={handleEmailAuth} className="space-y-4">
                {mode === "signup" && (
                  <div>
                    <label
                      htmlFor="auth-name"
                      className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5] mb-1.5"
                    >
                      Full name
                    </label>
                    <input
                      id="auth-name"
                      type="text"
                      required
                      autoComplete="name"
                      placeholder="Alex Rivera"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full h-10 px-3.5 rounded-lg border border-[#E4E4E7] dark:border-[#2A2A2A] bg-white dark:bg-[#141414] text-[13.5px] text-[#111111] dark:text-[#F5F5F5] placeholder:text-[#A1A1AA] dark:placeholder:text-[#5E5E5E] focus:outline-none focus:border-[#111111] dark:focus:border-[#666666] focus:ring-2 focus:ring-[#111111]/5 dark:focus:ring-white/5 transition-all"
                    />
                  </div>
                )}

                <div>
                  <label
                    htmlFor="auth-email"
                    className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5] mb-1.5"
                  >
                    Email
                  </label>
                  <input
                    id="auth-email"
                    type="email"
                    required
                    autoComplete="email"
                    placeholder="you@domain.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full h-10 px-3.5 rounded-lg border border-[#E4E4E7] dark:border-[#2A2A2A] bg-white dark:bg-[#141414] text-[13.5px] text-[#111111] dark:text-[#F5F5F5] placeholder:text-[#A1A1AA] dark:placeholder:text-[#5E5E5E] focus:outline-none focus:border-[#111111] dark:focus:border-[#666666] focus:ring-2 focus:ring-[#111111]/5 dark:focus:ring-white/5 transition-all"
                  />
                </div>

                <div>
                  <label
                    htmlFor="auth-password"
                    className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5] mb-1.5"
                  >
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="auth-password"
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={6}
                      autoComplete={mode === "signin" ? "current-password" : "new-password"}
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full h-10 pl-3.5 pr-10 rounded-lg border border-[#E4E4E7] dark:border-[#2A2A2A] bg-white dark:bg-[#141414] text-[13.5px] text-[#111111] dark:text-[#F5F5F5] placeholder:text-[#A1A1AA] dark:placeholder:text-[#5E5E5E] focus:outline-none focus:border-[#111111] dark:focus:border-[#666666] focus:ring-2 focus:ring-[#111111]/5 dark:focus:ring-white/5 transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((s) => !s)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-[#71717A] dark:text-[#787878] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>

                  {/* Password Strength Meter on Sign Up */}
                  {mode === "signup" && (
                    <div className="mt-2 space-y-1.5">
                      <div className="grid grid-cols-4 gap-1.5">
                        {[1, 2, 3, 4].map((segment) => {
                          const active = strength.score >= segment;
                          const barColor =
                            !active
                              ? "bg-[#E4E4E7] dark:bg-[#242424]"
                              : strength.score === 1
                              ? "bg-rose-500"
                              : strength.score === 2
                              ? "bg-amber-500"
                              : "bg-emerald-500";
                          return (
                            <div
                              key={segment}
                              className={`h-1 rounded-full transition-colors duration-200 ${barColor}`}
                            />
                          );
                        })}
                      </div>
                      <p className="text-[11.5px] text-[#71717A] dark:text-[#8E8E8E]">
                        {strength.label}
                      </p>
                    </div>
                  )}
                </div>

                {/* Inline Feedback Banner */}
                {feedback && (
                  <motion.div
                    initial={{ opacity: 0, y: 3 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`p-3 rounded-lg text-[12.5px] leading-relaxed flex items-start gap-2.5 border ${
                      feedback.isError
                        ? "bg-rose-50/80 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/50 text-rose-800 dark:text-rose-200"
                        : "bg-emerald-50/80 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/50 text-emerald-800 dark:text-emerald-200"
                    }`}
                  >
                    {feedback.isError ? (
                      <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                    )}
                    <span>{feedback.text}</span>
                  </motion.div>
                )}

                {/* Single Primary Action */}
                <button
                  type="submit"
                  disabled={isSubmitting || isGoogleBusy}
                  className="w-full h-10 rounded-lg bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] active:scale-[0.995] text-white dark:text-[#111111] text-[13.5px] font-medium transition-all flex items-center justify-center gap-2 disabled:opacity-60"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>{mode === "signin" ? "Signing in..." : "Creating workspace..."}</span>
                    </>
                  ) : (
                    <span>{mode === "signin" ? "Sign in" : "Create account"}</span>
                  )}
                </button>
              </form>
            </motion.div>
          </AnimatePresence>
        </main>

        {/* Minimal Footer */}
        <footer className="text-center lg:text-left text-[12px] text-[#A1A1AA] dark:text-[#666666]">
          <span className="lg:hidden">Dedicated browser container per workspace.</span>
        </footer>
      </div>
    </div>
  );
}
