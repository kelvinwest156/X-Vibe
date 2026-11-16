"use client";

import React, { useEffect, useState, useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Key,
  ShieldCheck,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertCircle,
  ArrowLeft,
  Loader2,
  Sun,
  Moon,
  Sparkles,
  Mail,
  Send,
} from "lucide-react";

function getPasswordStrength(pw: string): { score: number; label: string } {
  if (!pw) return { score: 0, label: "Minimum 6 characters" };
  if (pw.length < 6) return { score: 1, label: `${6 - pw.length} more characters needed` };
  let score = 2;
  if (pw.length >= 10) score += 1;
  if (/[A-Z]/.test(pw) && /[0-9!@#$%^&*(),.?":{}|<>]/.test(pw)) score += 1;
  const labels = ["", "Too short", "Fair", "Good", "Strong"];
  return { score: Math.min(score, 4), label: labels[Math.min(score, 4)] };
}

export default function ResetPasswordPage() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [mounted, setMounted] = useState(false);

  // Reset password states
  const [resetToken, setResetToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);
  const [isResetSuccess, setIsResetSuccess] = useState(false);

  // Fallback request states (if user arrives without token)
  const [fallbackEmail, setFallbackEmail] = useState("");
  const [isRequestingNewLink, setIsRequestingNewLink] = useState(false);
  const [requestFeedback, setRequestFeedback] = useState<{ text: string; isError: boolean } | null>(null);

  const strength = useMemo(() => getPasswordStrength(newPassword), [newPassword]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedTheme = localStorage.getItem("xvibebot_theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const effectiveTheme = savedTheme === "dark" || (!savedTheme && prefersDark) ? "dark" : "light";
      setTheme(effectiveTheme);
      document.documentElement.classList.toggle("dark", effectiveTheme === "dark");

      // Extract reset token from URL
      const params = new URLSearchParams(window.location.search);
      const token = params.get("token") || params.get("reset_token");
      if (token) {
        setResetToken(token.trim());
      }
      setMounted(true);
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (typeof window !== "undefined") {
      localStorage.setItem("xvibebot_theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
    }
  };

  const handleResetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);

    if (!resetToken.trim()) {
      setFeedback({
        text: "Missing or invalid reset token. Please request a new password reset link below.",
        isError: true,
      });
      return;
    }

    if (newPassword.length < 6) {
      setFeedback({ text: "Password must be at least 6 characters long.", isError: true });
      return;
    }

    if (newPassword !== confirmPassword) {
      setFeedback({ text: "Passwords do not match. Please re-enter.", isError: true });
      return;
    }

    setIsSubmitting(true);

    try {
      const res = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: resetToken.trim(),
          new_password: newPassword,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || "Failed to reset password. The link may have expired.");
      }

      // Store authenticated credentials for automatic session restoration
      if (typeof window !== "undefined") {
        if (data.token) localStorage.setItem("xvibebot_auth_token", data.token);
        if (data.tenant_id) localStorage.setItem("xvibebot_tenant_id", data.tenant_id);
        if (data.user?.email) localStorage.setItem("xvibebot_user_email", data.user.email);
        if (data.user?.name) localStorage.setItem("xvibebot_user_name", data.user.name);
      }

      setIsResetSuccess(true);
      setFeedback({
        text: "Password updated successfully! Welcome back to X-VibeBot.",
        isError: false,
      });

      // Redirect to workspace after a brief delay
      setTimeout(() => {
        window.location.href = "/";
      }, 1800);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to reset password.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRequestNewLink = async (e: React.FormEvent) => {
    e.preventDefault();
    setRequestFeedback(null);

    const cleanEmail = fallbackEmail.trim().toLowerCase();
    if (!cleanEmail || !cleanEmail.includes("@")) {
      setRequestFeedback({ text: "Please enter a valid email address.", isError: true });
      return;
    }

    setIsRequestingNewLink(true);

    try {
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
        throw new Error(data.detail || data.message || "Failed to send reset email.");
      }

      if (data.reset_token) {
        // Local developer fallback when SMTP is not enabled
        setResetToken(data.reset_token);
        setRequestFeedback({
          text: "Reset token generated! Enter your new password above.",
          isError: false,
        });
      } else {
        setRequestFeedback({
          text: data.message || "A password reset link has been sent to your email inbox.",
          isError: false,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to send reset link.";
      setRequestFeedback({ text: msg, isError: true });
    } finally {
      setIsRequestingNewLink(false);
    }
  };

  if (!mounted) {
    return (
      <div className="min-h-screen bg-[#FBFBFA] dark:bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${theme === "dark" ? "dark bg-[#0A0A0A] text-[#EDEDED]" : "bg-[#FBFBFA] text-[#18181B]"} flex flex-col justify-between selection:bg-indigo-500/20`}>
      {/* Top Navigation */}
      <header className="w-full max-w-6xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link
          href="/"
          className="flex items-center gap-2.5 group cursor-pointer"
          aria-label="X-VibeBot Home"
        >
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center shadow-sm shadow-indigo-500/20 text-white font-bold text-sm tracking-tight overflow-hidden">
            <Image
              src="/logos/logo_chibi_bot.png"
              alt="X-VibeBot"
              width={36}
              height={36}
              className="object-cover"
              onError={(e) => {
                (e.target as HTMLElement).style.display = "none";
              }}
            />
            <span className="hidden">X</span>
          </div>
          <div className="flex flex-col">
            <span className="text-[15px] font-semibold tracking-tight leading-none text-[#09090B] dark:text-[#F4F4F5] group-hover:text-indigo-600 transition-colors">
              X-VibeBot
            </span>
            <span className="text-[11px] font-medium text-[#71717A] dark:text-[#A1A1AA] tracking-wide uppercase mt-0.5">
              Creator Studio
            </span>
          </div>
        </Link>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            className="w-9 h-9 rounded-lg border border-[#E4E4E7] dark:border-[#27272A] flex items-center justify-center text-[#71717A] dark:text-[#A1A1AA] hover:text-[#09090B] dark:hover:text-[#FAFAFA] hover:bg-[#F4F4F5] dark:hover:bg-[#18181B] transition-colors"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <Link
            href="/login"
            className="px-3.5 py-1.5 text-[13px] font-medium text-[#52525B] dark:text-[#A1A1AA] hover:text-[#09090B] dark:hover:text-white rounded-lg hover:bg-[#F4F4F5] dark:hover:bg-[#18181B] transition-colors flex items-center gap-1.5"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Sign In
          </Link>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-[440px]">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="bg-white dark:bg-[#121212] border border-[#E4E4E7] dark:border-[#27272A] rounded-2xl shadow-xl shadow-black/5 dark:shadow-black/20 p-7 sm:p-8"
          >
            {/* Header Icon & Title */}
            <div className="flex flex-col items-center text-center mb-6">
              <div className="w-12 h-12 rounded-2xl bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900/60 flex items-center justify-center text-indigo-600 dark:text-indigo-400 mb-4 shadow-sm">
                <Key className="w-6 h-6" />
              </div>

              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[#09090B] dark:text-[#FAFAFA]">
                {resetToken ? "Create New Password" : "Reset Password"}
              </h1>

              <p className="text-[13.5px] text-[#71717A] dark:text-[#A1A1AA] mt-1.5 max-w-xs">
                {resetToken
                  ? "Choose a strong, memorable password to secure your workspace."
                  : "Enter your email address to receive a verified password reset link."}
              </p>
            </div>

            {/* Notification Feedback */}
            <AnimatePresence mode="wait">
              {feedback && (
                <motion.div
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  className={`mb-5 p-3.5 rounded-xl text-[13px] font-medium flex items-start gap-2.5 ${
                    feedback.isError
                      ? "bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50"
                      : "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/50"
                  }`}
                >
                  {feedback.isError ? (
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-500" />
                  )}
                  <span className="leading-snug">{feedback.text}</span>
                </motion.div>
              )}
            </AnimatePresence>

            {/* FORM A: Set New Password (When Token is Present) */}
            {resetToken ? (
              <form onSubmit={handleResetSubmit} className="space-y-4">
                <div>
                  <label
                    htmlFor="new-password"
                    className="block text-[12.5px] font-medium text-[#3F3F46] dark:text-[#D4D4D8] mb-1.5"
                  >
                    New Password
                  </label>
                  <div className="relative">
                    <input
                      id="new-password"
                      type={showPassword ? "text" : "password"}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      placeholder="At least 6 characters"
                      disabled={isSubmitting || isResetSuccess}
                      required
                      className="w-full h-11 px-3.5 pr-10 text-[14px] bg-[#FAFAFA] dark:bg-[#18181B] border border-[#E4E4E7] dark:border-[#27272A] rounded-xl text-[#09090B] dark:text-[#FAFAFA] placeholder:text-[#A1A1AA] dark:placeholder:text-[#71717A] focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all disabled:opacity-60"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      tabIndex={-1}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-[#52525B] dark:hover:text-[#D4D4D8] transition-colors"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>

                  {/* Password Strength Indicator */}
                  {newPassword.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="flex gap-1 h-1.5 w-full">
                        {[1, 2, 3, 4].map((step) => (
                          <div
                            key={step}
                            className={`h-full flex-1 rounded-full transition-all duration-300 ${
                              strength.score >= step
                                ? step === 1
                                  ? "bg-rose-500"
                                  : step === 2
                                  ? "bg-amber-500"
                                  : step === 3
                                  ? "bg-blue-500"
                                  : "bg-emerald-500"
                                : "bg-[#E4E4E7] dark:bg-[#27272A]"
                            }`}
                          />
                        ))}
                      </div>
                      <div className="flex justify-between items-center text-[11px] text-[#71717A] dark:text-[#A1A1AA]">
                        <span>Strength: {strength.label}</span>
                        {strength.score >= 3 && (
                          <span className="text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                            <ShieldCheck className="w-3 h-3" /> Secure
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <div>
                  <label
                    htmlFor="confirm-password"
                    className="block text-[12.5px] font-medium text-[#3F3F46] dark:text-[#D4D4D8] mb-1.5"
                  >
                    Confirm New Password
                  </label>
                  <div className="relative">
                    <input
                      id="confirm-password"
                      type={showConfirmPassword ? "text" : "password"}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      placeholder="Repeat your new password"
                      disabled={isSubmitting || isResetSuccess}
                      required
                      className="w-full h-11 px-3.5 pr-10 text-[14px] bg-[#FAFAFA] dark:bg-[#18181B] border border-[#E4E4E7] dark:border-[#27272A] rounded-xl text-[#09090B] dark:text-[#FAFAFA] placeholder:text-[#A1A1AA] dark:placeholder:text-[#71717A] focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all disabled:opacity-60"
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                      tabIndex={-1}
                      aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A1A1AA] hover:text-[#52525B] dark:hover:text-[#D4D4D8] transition-colors"
                    >
                      {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting || isResetSuccess}
                  className="w-full h-11 mt-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-[14px] rounded-xl shadow-sm shadow-indigo-600/30 flex items-center justify-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Updating Password...
                    </>
                  ) : isResetSuccess ? (
                    <>
                      <CheckCircle2 className="w-4 h-4 text-emerald-300" />
                      Password Updated!
                    </>
                  ) : (
                    <>
                      <Key className="w-4 h-4" />
                      Set New Password
                    </>
                  )}
                </button>

                {isResetSuccess && (
                  <div className="pt-2 text-center">
                    <Link
                      href="/"
                      className="text-[13px] font-semibold text-indigo-600 dark:text-indigo-400 hover:underline"
                    >
                      Click here to enter your workspace now &rarr;
                    </Link>
                  </div>
                )}
              </form>
            ) : (
              /* FORM B: Request Reset Link (When arrived without Token) */
              <div className="space-y-4">
                <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50 text-[12.5px] text-amber-800 dark:text-amber-300 flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-amber-600" />
                  <span>
                    No reset token was found in this link. If your link expired or you arrived directly, enter your email below to receive a fresh password reset link.
                  </span>
                </div>

                {requestFeedback && (
                  <div
                    className={`p-3 rounded-xl text-[13px] font-medium flex items-start gap-2.5 ${
                      requestFeedback.isError
                        ? "bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border border-rose-200"
                        : "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200"
                    }`}
                  >
                    {requestFeedback.isError ? (
                      <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                    ) : (
                      <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-emerald-500" />
                    )}
                    <span>{requestFeedback.text}</span>
                  </div>
                )}

                <form onSubmit={handleRequestNewLink} className="space-y-3">
                  <div>
                    <label
                      htmlFor="fallback-email"
                      className="block text-[12.5px] font-medium text-[#3F3F46] dark:text-[#D4D4D8] mb-1.5"
                    >
                      Email Address
                    </label>
                    <div className="relative">
                      <input
                        id="fallback-email"
                        type="email"
                        value={fallbackEmail}
                        onChange={(e) => setFallbackEmail(e.target.value)}
                        placeholder="you@domain.com"
                        disabled={isRequestingNewLink}
                        required
                        className="w-full h-11 px-3.5 pl-10 text-[14px] bg-[#FAFAFA] dark:bg-[#18181B] border border-[#E4E4E7] dark:border-[#27272A] rounded-xl text-[#09090B] dark:text-[#FAFAFA] placeholder:text-[#A1A1AA] focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all"
                      />
                      <Mail className="w-4 h-4 text-[#A1A1AA] absolute left-3.5 top-1/2 -translate-y-1/2" />
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={isRequestingNewLink}
                    className="w-full h-11 bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-[14px] rounded-xl shadow-sm shadow-indigo-600/30 flex items-center justify-center gap-2 transition-all disabled:opacity-50 cursor-pointer"
                  >
                    {isRequestingNewLink ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Sending Reset Link...
                      </>
                    ) : (
                      <>
                        <Send className="w-4 h-4" />
                        Send Password Reset Link
                      </>
                    )}
                  </button>
                </form>
              </div>
            )}

            {/* Bottom Navigation Link */}
            <div className="mt-6 pt-5 border-t border-[#F4F4F5] dark:border-[#1F1F23] flex items-center justify-center">
              <Link
                href="/login"
                className="text-[13px] font-medium text-[#71717A] dark:text-[#A1A1AA] hover:text-[#09090B] dark:hover:text-[#FAFAFA] transition-colors flex items-center gap-1.5"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Return to Sign In
              </Link>
            </div>
          </motion.div>
        </div>
      </main>

      {/* Subtle Footer */}
      <footer className="w-full max-w-6xl mx-auto px-6 py-4 flex items-center justify-between text-[11.5px] text-[#A1A1AA] dark:text-[#52525B]">
        <span>&copy; {new Date().getFullYear()} X-VibeBot. All rights reserved.</span>
        <div className="flex items-center gap-4">
          <Link href="/" className="hover:text-[#71717A] dark:hover:text-[#A1A1AA] transition-colors">
            Home
          </Link>
          <Link href="/login" className="hover:text-[#71717A] dark:hover:text-[#A1A1AA] transition-colors">
            Login
          </Link>
        </div>
      </footer>
    </div>
  );
}
