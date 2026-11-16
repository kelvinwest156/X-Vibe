"use client";

import React, { useState, useMemo, useEffect } from "react";
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
  ArrowLeft,
  Sparkles,
  ShieldCheck,
  Brain,
  Lock,
  KeyRound,
  ChevronDown,
  X as CloseIcon,
  Check,
} from "lucide-react";
import {
  isSupabaseConfigured,
  signInWithEmail,
  signUpWithEmail,
  signInWithTwitter,
  resetPasswordForEmail,
  updateUserPassword,
} from "@/lib/supabase";

interface AuthViewProps {
  onAuthenticated?: (
    user: { uid: string; email?: string | null; displayName?: string | null; tenant_id?: string },
    token: string,
    isNewSignup?: boolean
  ) => void;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
  initialMode?: "signin" | "signup" | "forgot" | "reset";
  onBack?: () => void;
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

const FAQS = [
  {
    q: "Will my X account get shadowbanned?",
    a: "No. X-VibeBot uses randomized 45–180s delays, daily action caps, and circadian sleep so activity stays well within natural human browsing limits.",
  },
  {
    q: "How does it avoid sounding like an AI bot?",
    a: "It hard-bans 100+ overused AI phrases ('delve', 'game-changer', 'spot on') and continuously tunes its tone from your manual edits.",
  },
  {
    q: "Are my passwords safe?",
    a: "We never ask for your password. Sessions sync directly through AES-256 encrypted browser cookies in sandboxed containers.",
  },
  {
    q: "Can I approve replies before posting?",
    a: "Yes. The Smart Queue lets you review, edit, or reject drafts with 1 click before anything is scheduled.",
  },
  {
    q: "How much time will this save me?",
    a: "Review and approve 15–20 high-signal replies in under 10 minutes a day, without doomscrolling the feed.",
  },
];

export default function AuthView({
  onAuthenticated,
  theme = "light",
  onToggleTheme,
  initialMode = "signin",
  onBack,
}: AuthViewProps) {
  const [mode, setMode] = useState<"signin" | "signup" | "forgot" | "reset">(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isXBusy, setIsXBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);
  const [showFeaturesModal, setShowFeaturesModal] = useState(false);
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(null);

  const strength = useMemo(() => getPasswordStrength(password), [password]);

  // Inspect URL parameters for password reset tokens or recovery links
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const hash = window.location.hash || "";
      const tokenParam = params.get("token") || params.get("reset_token");
      const modeParam = params.get("mode");

      if (tokenParam) {
        setResetToken(tokenParam);
        setMode("reset");
      } else if (modeParam === "reset" || hash.includes("type=recovery")) {
        setMode("reset");
      }
    }
  }, []);

  const switchMode = (nextMode: "signin" | "signup" | "forgot" | "reset") => {
    setMode(nextMode);
    setFeedback(null);
  };

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setFeedback(null);

    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail || !cleanEmail.includes("@")) {
      setFeedback({ text: "Please provide a valid email address.", isError: true });
      setIsSubmitting(false);
      return;
    }

    try {
      // 1. Prioritize FastAPI backend SMTP service (delivers via your configured Gmail SMTP)
      const clientOrigin = typeof window !== "undefined" ? window.location.origin : undefined;
      const res = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: cleanEmail,
          app_url: clientOrigin,
        }),
      });
      const data = await res.json();

      if (!res.ok) {
        // Fallback to Supabase password recovery if backend user was not found
        if (isSupabaseConfigured) {
          const { error } = await resetPasswordForEmail(cleanEmail);
          if (!error) {
            setFeedback({
              text: "Password reset instructions sent! Please check your email inbox.",
              isError: false,
            });
            return;
          }
        }
        throw new Error(data.detail || data.message || "Failed to initiate password reset.");
      }

      if (data.reset_token) {
        setResetToken(data.reset_token);
        setMode("reset");
        setFeedback({
          text: "Reset token ready! Enter your new password below.",
          isError: false,
        });
      } else {
        setFeedback({
          text: data.message || "A password reset link has been sent to your email inbox. Please check your inbox.",
          isError: false,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to request password reset.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setFeedback(null);

    if (password.length < 6) {
      setFeedback({ text: "Password must be at least 6 characters long.", isError: true });
      setIsSubmitting(false);
      return;
    }

    if (password !== confirmPassword) {
      setFeedback({ text: "Passwords do not match. Please re-enter.", isError: true });
      setIsSubmitting(false);
      return;
    }

    try {
      // If we have a backend resetToken (from email link param or local fallback)
      if (resetToken && resetToken.trim()) {
        const res = await fetch("/api/auth/reset-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: resetToken.trim(),
            new_password: password,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || data.message || "Failed to reset password.");
        }

        if (typeof window !== "undefined") {
          localStorage.setItem("xvibebot_auth_token", data.token);
          localStorage.setItem("xvibebot_tenant_id", data.tenant_id);
          localStorage.setItem("xvibebot_user_email", data.user.email);
          if (data.user.name) {
            localStorage.setItem("xvibebot_user_name", data.user.name);
          }
        }

        setFeedback({
          text: "Password updated successfully! Welcome back.",
          isError: false,
        });

        onAuthenticated?.(
          {
            uid: data.user.uid,
            email: data.user.email,
            displayName: data.user.name || data.user.email.split("@")[0],
            tenant_id: data.tenant_id,
          },
          data.token,
          false
        );
        return;
      }

      // Supabase recovery session fallback if no token was passed
      if (isSupabaseConfigured) {
        const { error } = await updateUserPassword(password);
        if (error) throw error;
        setFeedback({
          text: "Password updated successfully! Redirecting to sign in...",
          isError: false,
        });
        setTimeout(() => {
          setMode("signin");
          setPassword("");
          setConfirmPassword("");
        }, 1500);
        return;
      }

      throw new Error("Missing reset token. Please request a new password reset link from your email.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to reset password.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleXAuth = async () => {
    setIsXBusy(true);
    setFeedback(null);
    try {
      if (isSupabaseConfigured) {
        const { error } = await signInWithTwitter();
        if (error) {
          const lower = error.message?.toLowerCase() || "";
          if (lower.includes("not enabled") || lower.includes("unsupported provider") || lower.includes("validation_failed")) {
            setFeedback({
              text: "X OAuth is not yet enabled in your Supabase dashboard (Authentication > Providers > Twitter). Please sign in with your email & password below.",
              isError: true,
            });
            return;
          }
          throw error;
        }
      } else {
        setFeedback({
          text: "Supabase authentication is not configured. Continue with your email and password below.",
          isError: true,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "X authentication could not be started.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsXBusy(false);
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
        <div className="flex items-center justify-between relative z-10">
          <div className="flex items-center gap-2.5">
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

          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Home</span>
            </button>
          )}
        </div>

        {/* Center Editorial Value + Live Calibration Artifact */}
        <div className="max-w-[440px] space-y-6 my-auto py-8 relative z-10">
          <div className="space-y-2">
            <h2 className="font-display text-[26px] xl:text-[30px] font-semibold leading-[1.2] tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              Show up in the right conversations.
            </h2>
            <p className="text-[14px] leading-relaxed text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Autonomous X studio calibrated to your authentic voice.
            </p>
          </div>

          {/* Authentic Product Preview Surface */}
          <div className="rounded-xl bg-white dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] p-4 xl:p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] dark:shadow-[0_8px_24px_rgba(0,0,0,0.45)] space-y-3.5">
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
                <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
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

              <div className="rounded-lg bg-[#FAFAFA] dark:bg-[#131313] border border-[#E4E4E7] dark:border-[#262626] p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11.5px] font-medium text-[#111111] dark:text-[#F5F5F5]">
                    Drafted in your voice
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] text-[#EA580C] font-medium">
                    <Clock className="w-3 h-3" />
                    Scheduled in 14m
                  </span>
                </div>
                <p className="text-[12px] leading-[1.55] text-[#111111] dark:text-[#E5E5E5]">
                  Give a 72-hour in-app banner before sending a single billing email. Most failed renewals are expired virtual cards, not churn.
                </p>
                <div className="pt-2 border-t border-[#E4E4E7]/80 dark:border-[#222222] flex items-center justify-between text-[11px] text-[#71717A] dark:text-[#787878]">
                  <span>Calibrated from 24 approved edits</span>
                  <span>Zero clichés</span>
                </div>
              </div>
            </div>
          </div>

          {/* Clean 3 Feature Tags */}
          <div className="flex items-center gap-4 text-[12px] text-[#71717A] dark:text-[#8E8E8E] pt-1">
            <span>✓ Human pacing</span>
            <span>•</span>
            <span>✓ Zero AI clichés</span>
            <span>•</span>
            <span>✓ Cookie sync</span>
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
            {onBack && (
              <button
                type="button"
                onClick={onBack}
                aria-label="Back to home"
                className="w-8 h-8 rounded-lg border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-center text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
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
          <div className="flex items-center gap-2 sm:gap-2.5">
            <button
              type="button"
              onClick={() => setShowFeaturesModal(true)}
              className="h-8 px-2.5 sm:px-3 rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[12px] font-medium text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] inline-flex items-center gap-1.5 transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5 text-[#EA580C]" />
              <span className="hidden sm:inline">Why X-VibeBot & FAQ</span>
              <span className="sm:hidden">FAQ</span>
            </button>

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
                {mode === "forgot" && (
                  <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[#EA580C] mb-1">
                    <KeyRound className="w-3.5 h-3.5" />
                    <span>Account Recovery</span>
                  </div>
                )}
                {mode === "reset" && (
                  <div className="inline-flex items-center gap-1.5 text-[12px] font-medium text-emerald-600 dark:text-emerald-400 mb-1">
                    <Lock className="w-3.5 h-3.5" />
                    <span>Choose New Password</span>
                  </div>
                )}
                <h1 className="font-display text-[24px] sm:text-[26px] font-semibold tracking-[-0.025em] text-[#111111] dark:text-[#F5F5F5]">
                  {mode === "signin"
                    ? "Sign in to X-VibeBot"
                    : mode === "signup"
                    ? "Create your workspace"
                    : mode === "forgot"
                    ? "Reset your password"
                    : "Set new password"}
                </h1>
                <p className="text-[13.5px] leading-relaxed text-[#52525B] dark:text-[#9E9E9E]">
                  {mode === "signin"
                    ? "Enter your email and password to access your studio."
                    : mode === "signup"
                    ? "Set up your account, then connect your X profile in the next step."
                    : mode === "forgot"
                    ? "Enter your account email and we'll send you instructions to reset your password."
                    : "Enter and confirm your new secure password below."}
                </p>
              </div>

              {/* Secondary X SSO (only for sign in & sign up) */}
              {(mode === "signin" || mode === "signup") && (
                <>
                  <button
                    type="button"
                    onClick={handleXAuth}
                    disabled={isXBusy || isSubmitting}
                    className="w-full h-10 px-4 rounded-lg bg-white dark:bg-[#161616] hover:bg-[#FAFAFA] dark:hover:bg-[#1E1E1E] active:scale-[0.995] text-[#111111] dark:text-[#F5F5F5] font-medium text-[13.5px] border border-[#E4E4E7] dark:border-[#2A2A2A] transition-all flex items-center justify-center gap-2.5 disabled:opacity-60"
                  >
                    {isXBusy ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <svg className="w-4 h-4 shrink-0 fill-current" viewBox="0 0 24 24">
                        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                      </svg>
                    )}
                    <span>{mode === "signin" ? "Sign in with X" : "Sign up with X"}</span>
                  </button>

                  {/* Hairline Divider */}
                  <div className="relative flex items-center justify-center">
                    <div className="absolute inset-x-0 top-1/2 border-t border-[#E4E4E7] dark:border-[#242424]" />
                    <span className="relative bg-white dark:bg-[#0E0E0E] px-3 text-[12px] text-[#A1A1AA] dark:text-[#666666]">
                      or
                    </span>
                  </div>
                </>
              )}

              {/* Email & Password Form (Sign In / Sign Up) */}
              {(mode === "signin" || mode === "signup") && (
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
                    <div className="flex items-center justify-between mb-1.5">
                      <label
                        htmlFor="auth-password"
                        className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5]"
                      >
                        Password
                      </label>
                      {mode === "signin" && (
                        <button
                          type="button"
                          onClick={() => switchMode("forgot")}
                          className="text-[12px] font-medium text-[#EA580C] hover:text-[#C2410C] dark:hover:text-[#F97316] transition-colors focus-visible:outline-none focus-visible:underline"
                        >
                          Forgot password?
                        </button>
                      )}
                    </div>
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
                    disabled={isSubmitting || isXBusy}
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
              )}

              {/* Forgot Password Mode Form */}
              {mode === "forgot" && (
                <form onSubmit={handleForgotPassword} className="space-y-4">
                  <div>
                    <label
                      htmlFor="forgot-email"
                      className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5] mb-1.5"
                    >
                      Account email
                    </label>
                    <input
                      id="forgot-email"
                      type="email"
                      required
                      autoComplete="email"
                      placeholder="you@domain.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full h-10 px-3.5 rounded-lg border border-[#E4E4E7] dark:border-[#2A2A2A] bg-white dark:bg-[#141414] text-[13.5px] text-[#111111] dark:text-[#F5F5F5] placeholder:text-[#A1A1AA] dark:placeholder:text-[#5E5E5E] focus:outline-none focus:border-[#111111] dark:focus:border-[#666666] focus:ring-2 focus:ring-[#111111]/5 dark:focus:ring-white/5 transition-all"
                    />
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

                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="w-full h-10 rounded-lg bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] active:scale-[0.995] text-white dark:text-[#111111] text-[13.5px] font-medium transition-all flex items-center justify-center gap-2 disabled:opacity-60"
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Sending reset link...</span>
                      </>
                    ) : (
                      <span>Send reset link</span>
                    )}
                  </button>

                  <div className="text-center pt-2">
                    <button
                      type="button"
                      onClick={() => switchMode("signin")}
                      className="text-[12.5px] font-medium text-[#71717A] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
                    >
                      Remember your password?{" "}
                      <span className="text-[#EA580C] underline font-semibold">Sign in</span>
                    </button>
                  </div>
                </form>
              )}

              {/* Reset Password Form */}
              {mode === "reset" && (
                <form onSubmit={handleResetPassword} className="space-y-4">
                  <div>
                    <label
                      htmlFor="reset-password"
                      className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5] mb-1.5"
                    >
                      New password
                    </label>
                    <div className="relative">
                      <input
                        id="reset-password"
                        type={showPassword ? "text" : "password"}
                        required
                        minLength={6}
                        autoComplete="new-password"
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

                    {/* Password Strength Meter */}
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
                  </div>

                  <div>
                    <label
                      htmlFor="reset-confirm-password"
                      className="block text-[13px] font-medium text-[#18181B] dark:text-[#E5E5E5] mb-1.5"
                    >
                      Confirm new password
                    </label>
                    <div className="relative">
                      <input
                        id="reset-confirm-password"
                        type={showConfirmPassword ? "text" : "password"}
                        required
                        minLength={6}
                        autoComplete="new-password"
                        placeholder="••••••••"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        className="w-full h-10 pl-3.5 pr-10 rounded-lg border border-[#E4E4E7] dark:border-[#2A2A2A] bg-white dark:bg-[#141414] text-[13.5px] text-[#111111] dark:text-[#F5F5F5] placeholder:text-[#A1A1AA] dark:placeholder:text-[#5E5E5E] focus:outline-none focus:border-[#111111] dark:focus:border-[#666666] focus:ring-2 focus:ring-[#111111]/5 dark:focus:ring-white/5 transition-all"
                      />
                      <button
                        type="button"
                        onClick={() => setShowConfirmPassword((s) => !s)}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-[#71717A] dark:text-[#787878] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
                        aria-label={showConfirmPassword ? "Hide confirm password" : "Show confirm password"}
                      >
                        {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
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

                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="w-full h-10 rounded-lg bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] active:scale-[0.995] text-white dark:text-[#111111] text-[13.5px] font-medium transition-all flex items-center justify-center gap-2 disabled:opacity-60"
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Updating password...</span>
                      </>
                    ) : (
                      <span>Update password</span>
                    )}
                  </button>

                  <div className="text-center pt-2">
                    <button
                      type="button"
                      onClick={() => switchMode("signin")}
                      className="text-[12.5px] font-medium text-[#71717A] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
                    >
                      Cancel and return to{" "}
                      <span className="text-[#EA580C] underline font-semibold">Sign in</span>
                    </button>
                  </div>
                </form>
              )}
            </motion.div>
          </AnimatePresence>
        </main>

        {/* Minimal Footer */}
        <footer className="text-center lg:text-left text-[12px] text-[#A1A1AA] dark:text-[#666666]">
          <span className="lg:hidden">Dedicated browser container per workspace.</span>
        </footer>
      </div>

      {/* Features & Architecture Showcase Modal */}
      <AnimatePresence>
        {showFeaturesModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6 overflow-y-auto"
            onClick={() => setShowFeaturesModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 10 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 10 }}
              transition={{ duration: 0.18 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-white dark:bg-[#141414] border border-[#E4E4E7] dark:border-[#262626] rounded-2xl p-6 sm:p-8 shadow-2xl space-y-6 text-[#111111] dark:text-[#F5F5F5]"
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1.5">
                  <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 text-[11px] font-medium">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>BUILT FOR FOUNDERS, BUILDERS & CREATORS</span>
                  </div>
                  <h3 className="font-display text-[22px] sm:text-[24px] font-bold tracking-tight">
                    Scale on X without sounding like an AI bot.
                  </h3>
                  <p className="text-[13px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                    Generic automation ruins your brand reputation. X-VibeBot uses proprietary anti-bot circadian pacing and voice-calibration so every interaction builds authentic trust.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowFeaturesModal(false)}
                  className="p-1.5 rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[#71717A] dark:text-[#8E8E8E] hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors shrink-0"
                  aria-label="Close modal"
                >
                  <CloseIcon className="w-4 h-4" />
                </button>
              </div>

              {/* 4 Feature Pillars Grid */}
              <div className="grid sm:grid-cols-2 gap-3 pt-2">
                <div className="p-4 rounded-xl bg-[#F8F8F9] dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] space-y-2">
                  <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                    <ShieldCheck className="w-4 h-4" />
                  </div>
                  <h4 className="text-[14px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                    Anti-Bot Human Pacing
                  </h4>
                  <p className="text-[12px] text-[#52525B] dark:text-[#9E9E9E] leading-relaxed">
                    Never fires on rigid intervals. Randomized 45–180s human jitter delays and daily action ceilings prevent algorithmic flags.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-[#F8F8F9] dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] space-y-2">
                  <div className="w-8 h-8 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                    <Brain className="w-4 h-4" />
                  </div>
                  <h4 className="text-[14px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                    Zero-Cliché Voice Engine
                  </h4>
                  <p className="text-[12px] text-[#52525B] dark:text-[#9E9E9E] leading-relaxed">
                    Hard-bans 100+ AI giveaways (&quot;game-changer&quot;, &quot;spot on&quot;, &quot;delve&quot;). Continuously calibrates against your accepted edits.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-[#F8F8F9] dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] space-y-2">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 flex items-center justify-center">
                    <Clock className="w-4 h-4" />
                  </div>
                  <h4 className="text-[14px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                    Circadian Sleep Scheduling
                  </h4>
                  <p className="text-[12px] text-[#52525B] dark:text-[#9E9E9E] leading-relaxed">
                    Respects natural human rest windows. Enforces quiet hours and realistic work pauses so your account behavior matches real humans.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-[#F8F8F9] dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] space-y-2">
                  <div className="w-8 h-8 rounded-lg bg-purple-500/10 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                    <Lock className="w-4 h-4" />
                  </div>
                  <h4 className="text-[14px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                    Isolated Cloud Cookie Sync
                  </h4>
                  <p className="text-[12px] text-[#52525B] dark:text-[#9E9E9E] leading-relaxed">
                    Multi-tenant AES-256 encrypted browser containers keep sessions persistent without risking password leakage or cross-account contamination.
                  </p>
                </div>
              </div>

              {/* Head-to-Head Comparison Table */}
              <div className="p-4 rounded-xl bg-[#FAFAFA] dark:bg-[#161616] border border-[#E4E4E7] dark:border-[#262626] space-y-3">
                <h4 className="text-[12.5px] font-semibold uppercase tracking-wider text-[#71717A] dark:text-[#8E8E8E]">
                  How X-VibeBot Compares to Typical Bots
                </h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[12px]">
                    <thead>
                      <tr className="border-b border-[#E4E4E7] dark:border-[#262626] text-[#71717A] dark:text-[#787878]">
                        <th className="pb-2 font-medium">Dimension</th>
                        <th className="pb-2 font-medium text-rose-600 dark:text-rose-400">Typical ChatGPT Bot</th>
                        <th className="pb-2 font-medium text-emerald-600 dark:text-emerald-400">X-VibeBot Studio</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E4E4E7]/60 dark:divide-[#242424]">
                      <tr>
                        <td className="py-2 font-medium text-[#111111] dark:text-[#E5E5E5]">Reply Quality</td>
                        <td className="py-2 text-[#71717A] dark:text-[#8E8E8E]">Generic sycophancy (&quot;Spot on!&quot;)</td>
                        <td className="py-2 text-emerald-700 dark:text-emerald-300 font-medium">Sharp, opinionated, contextual</td>
                      </tr>
                      <tr>
                        <td className="py-2 font-medium text-[#111111] dark:text-[#E5E5E5]">Execution Pacing</td>
                        <td className="py-2 text-[#71717A] dark:text-[#8E8E8E]">Fixed cron loops (High shadowban risk)</td>
                        <td className="py-2 text-emerald-700 dark:text-emerald-300 font-medium">45-180s randomized jitter + sleep</td>
                      </tr>
                      <tr>
                        <td className="py-2 font-medium text-[#111111] dark:text-[#E5E5E5]">Voice Training</td>
                        <td className="py-2 text-[#71717A] dark:text-[#8E8E8E]">Static prompts that sound fake</td>
                        <td className="py-2 text-emerald-700 dark:text-emerald-300 font-medium">Adaptive delta learning from your edits</td>
                      </tr>
                      <tr>
                        <td className="py-2 font-medium text-[#111111] dark:text-[#E5E5E5]">Account Control</td>
                        <td className="py-2 text-[#71717A] dark:text-[#8E8E8E]">Uncontrolled auto-spam</td>
                        <td className="py-2 text-emerald-700 dark:text-emerald-300 font-medium">Smart Queue + Semi-Autonomous review</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Interactive Accordion FAQ */}
              <div className="space-y-2">
                <h4 className="text-[13px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                  Frequently Asked Questions
                </h4>
                <div className="space-y-1.5">
                  {FAQS.map((faq, idx) => {
                    const isOpen = openFaqIndex === idx;
                    return (
                      <div
                        key={idx}
                        className="rounded-lg border border-[#E4E4E7] dark:border-[#262626] overflow-hidden bg-[#FAFAFA] dark:bg-[#161616]"
                      >
                        <button
                          type="button"
                          onClick={() => setOpenFaqIndex(isOpen ? null : idx)}
                          className="w-full p-3 text-left text-[12.5px] font-medium flex items-center justify-between gap-3 text-[#111111] dark:text-[#E5E5E5] hover:bg-[#F4F4F5] dark:hover:bg-[#1E1E1E] transition-colors"
                        >
                          <span>{faq.q}</span>
                          <ChevronDown
                            className={`w-3.5 h-3.5 text-[#71717A] shrink-0 transition-transform duration-200 ${
                              isOpen ? "rotate-180" : ""
                            }`}
                          />
                        </button>
                        {isOpen && (
                          <div className="px-3 pb-3 pt-1 text-[12px] leading-relaxed text-[#52525B] dark:text-[#9E9E9E] border-t border-[#E4E4E7]/60 dark:border-[#262626]">
                            {faq.a}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Modal CTA */}
              <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-[#E4E4E7] dark:border-[#262626]">
                <div className="text-[12px] text-[#71717A] dark:text-[#8E8E8E] text-center sm:text-left">
                  Ready to show up in niche conversations effortlessly?
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setShowFeaturesModal(false);
                    switchMode("signup");
                  }}
                  className="w-full sm:w-auto h-9 px-5 rounded-lg bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] text-white dark:text-[#111111] font-medium text-[13px] transition-all flex items-center justify-center gap-2 shrink-0"
                >
                  <Sparkles className="w-3.5 h-3.5 text-amber-400 dark:text-[#EA580C]" />
                  <span>Start Free Workspace</span>
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
