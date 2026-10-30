"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Globe,
  RefreshCw,
  LogOut,
  Sun,
  Moon,
} from "lucide-react";

interface OnboardingConnectViewProps {
  userEmail?: string | null;
  userName?: string | null;
  isLoggedIn: boolean;
  linkedUsername?: string | null;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
  onSignOut: () => void;
  onSessionConnected: () => Promise<void> | void;
  onContinueToStudio: () => void;
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

export default function OnboardingConnectView({
  userEmail,
  isLoggedIn,
  linkedUsername,
  theme = "light",
  onToggleTheme,
  onSignOut,
  onSessionConnected,
  onContinueToStudio,
  apiFetch,
}: OnboardingConnectViewProps) {
  const [windowOpened, setWindowOpened] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [connectedHandle, setConnectedHandle] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);

  const isConnected = isLoggedIn || Boolean(connectedHandle);
  const displayHandle = (() => {
    const raw = connectedHandle || linkedUsername;
    if (!raw) return "Connected account";
    return raw.startsWith("@") ? raw : `@${raw}`;
  })();

  const handleOpenBrowserWindow = async () => {
    setFeedback(null);
    if (typeof window !== "undefined") {
      window.open(
        "https://x.com/login",
        "XLoginPopup",
        "width=660,height=760,left=220,top=90,menubar=no,toolbar=no"
      );
    }
    setWindowOpened(true);
    try {
      await apiFetch("/api/browser/launch-login", { method: "POST" });
    } catch {}
    setFeedback({
      text: "Sign-in window opened. Complete sign-in on X, then click Verify X connection below.",
      isError: false,
    });
  };

  const handleVerifyBrowser = async () => {
    setIsVerifying(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/browser/check-session", { method: "POST" });
      const data = await res.json();
      if (res.ok && data.is_logged_in) {
        setConnectedHandle(data.linked_username || "your_account");
        await onSessionConnected();
      } else {
        setFeedback({
          text: "No active X session detected yet. Complete sign-in in the X browser window, then click verify.",
          isError: true,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not check X session.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsVerifying(false);
    }
  };

  return (
    <div className="min-h-dvh bg-white dark:bg-[#0E0E0E] text-[#111111] dark:text-[#F5F5F5] grid lg:grid-cols-[46%_54%] xl:grid-cols-[44%_56%] selection:bg-[#111111] selection:text-white dark:selection:bg-white dark:selection:text-[#111111] transition-colors duration-200">
      {/* Left Workspace Provisioning Stage (Desktop) */}
      <aside className="hidden lg:flex flex-col justify-between bg-[#F4F4F5] dark:bg-[#131313] border-r border-[#E4E4E7] dark:border-[#222222] p-10 xl:p-14">
        {/* Brand Lockup */}
        <div className="flex items-center gap-2.5">
          <div className="size-8 rounded-lg bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
            <svg className="size-3.5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
          </div>
          <span className="font-display font-semibold text-[15px] tracking-[-0.02em] text-[#111111] dark:text-[#F5F5F5]">
            X-VibeBot
          </span>
          <span className="text-[11px] font-medium tabular-nums px-2 py-0.5 rounded-full bg-white dark:bg-[#1E1E1E] text-[#52525B] dark:text-[#9E9E9E] border border-[#E4E4E7] dark:border-[#2C2C2C]">
            v2.0
          </span>
        </div>

        {/* Center Live Setup Checklist */}
        <div className="max-w-[430px] space-y-8 my-auto py-8">
          <div className="space-y-3">
            <h2 className="font-display text-[28px] xl:text-[31px] font-semibold leading-[1.2] tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              {isConnected
                ? "Your workspace is linked and ready."
                : "Connect the X profile you want to grow."}
            </h2>
            <p className="text-[14px] leading-[1.65] text-[#52525B] dark:text-[#9E9E9E] text-pretty">
              X-VibeBot runs your X session inside a private browser profile dedicated to your workspace. Nothing is published without your rules or approval.
            </p>
          </div>

          {/* 3-Step Live Provisioning Ledger */}
          <div className="rounded-xl bg-white dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] divide-y divide-[#E4E4E7] dark:divide-[#242424] shadow-[0_1px_2px_rgba(0,0,0,0.03)] dark:shadow-[0_8px_24px_rgba(0,0,0,0.45)]">
            {/* Step 1: Account */}
            <div className="p-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <div className="size-6 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
                  <Check className="size-3.5 stroke-[2.5]" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-[#111111] dark:text-[#F5F5F5]">
                    Workspace account
                  </p>
                  <p className="text-[12px] text-[#71717A] dark:text-[#8E8E8E] truncate">
                    {userEmail || "Authenticated"}
                  </p>
                </div>
              </div>
              <span className="text-[11.5px] font-medium text-emerald-600 dark:text-emerald-400 shrink-0">
                Verified
              </span>
            </div>

            {/* Step 2: Isolated Container */}
            <div className="p-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="size-6 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
                  <Check className="size-3.5 stroke-[2.5]" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-[13px] font-medium text-[#111111] dark:text-[#F5F5F5]">
                    Isolated browser profile
                  </p>
                  <p className="text-[12px] text-[#71717A] dark:text-[#8E8E8E]">
                    Dedicated container provisioned
                  </p>
                </div>
              </div>
              <span className="text-[11.5px] font-medium text-emerald-600 dark:text-emerald-400 shrink-0">
                Ready
              </span>
            </div>

            {/* Step 3: X Link */}
            <div className="p-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                {isConnected ? (
                  <div className="size-6 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
                    <Check className="size-3.5 stroke-[2.5]" aria-hidden="true" />
                  </div>
                ) : (
                  <div className="size-6 rounded-full bg-[#EA580C]/15 border border-[#EA580C]/40 flex items-center justify-center shrink-0">
                    <span className="size-2 rounded-full bg-[#EA580C]" />
                  </div>
                )}
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-[#111111] dark:text-[#F5F5F5]">
                    X profile session
                  </p>
                  <p className="text-[12px] text-[#71717A] dark:text-[#8E8E8E] truncate">
                    {isConnected ? `Linked to ${displayHandle}` : "Awaiting session authorization"}
                  </p>
                </div>
              </div>
              <span
                className={`text-[11.5px] font-medium shrink-0 ${
                  isConnected
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-[#EA580C]"
                }`}
              >
                {isConnected ? "Connected" : "In progress"}
              </span>
            </div>
          </div>
        </div>

        {/* Bottom Guarantee */}
        <div className="text-[12px] text-[#71717A] dark:text-[#737373]">
          Your X password is never stored. Disconnect or replace your session anytime in Settings.
        </div>
      </aside>

      {/* Right Interactive Onboarding Stage */}
      <div className="flex flex-col justify-between min-h-dvh px-5 py-5 sm:px-10 sm:py-7">
        {/* Top Utility Header */}
        <header className="flex items-center justify-between gap-3">
          {/* Mobile Brand Lockup */}
          <div className="flex lg:hidden items-center gap-2">
            <div className="size-8 rounded-lg bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
              <svg className="size-3.5 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
              </svg>
            </div>
            <span className="font-display font-semibold text-[15px] tracking-[-0.02em]">
              X-VibeBot
            </span>
          </div>

          {/* Desktop Step Sequence */}
          <div className="hidden lg:flex items-center gap-2 text-[12.5px]">
            <span className="inline-flex items-center gap-1.5 text-[#71717A] dark:text-[#8E8E8E]">
              <Check className="size-3.5 text-emerald-500" aria-hidden="true" />
              Workspace
            </span>
            <span className="text-[#D4D4D8] dark:text-[#333333]">/</span>
            <span className="font-medium text-[#111111] dark:text-[#F5F5F5]">
              Connect X account
            </span>
          </div>

          {/* Right Controls: User Email + Theme + Sign out */}
          <div className="flex items-center gap-2">
            {userEmail && (
              <span className="hidden sm:inline-block text-[12px] text-[#71717A] dark:text-[#8E8E8E] max-w-[180px] truncate mr-1">
                {userEmail}
              </span>
            )}

            {onToggleTheme && (
              <button
                type="button"
                onClick={onToggleTheme}
                className="size-8 rounded-lg border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-center text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-colors"
                title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
                aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              >
                {theme === "light" ? <Moon className="size-4" aria-hidden="true" /> : <Sun className="size-4 text-amber-400" aria-hidden="true" />}
              </button>
            )}

            <button
              type="button"
              onClick={onSignOut}
              className="h-8 px-2.5 rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[12px] font-medium text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-colors inline-flex items-center gap-1.5"
              aria-label="Sign out of workspace"
            >
              <LogOut className="size-3.5" aria-hidden="true" />
              <span>Sign out</span>
            </button>
          </div>
        </header>

        {/* Main Onboarding Card */}
        <main className="w-full max-w-[420px] mx-auto my-auto py-8">
          <AnimatePresence mode="wait">
            {isConnected ? (
              /* Connected Confirmation Milestone */
              <motion.div
                key="connected"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
                className="space-y-6"
              >
                <div className="size-11 rounded-xl bg-emerald-500/15 border border-emerald-500/25 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                  <CheckCircle2 className="size-5" aria-hidden="true" />
                </div>

                <div className="space-y-1.5">
                  <h1 className="font-display text-[24px] sm:text-[26px] font-semibold tracking-[-0.025em] text-[#111111] dark:text-[#F5F5F5] text-balance">
                    X account connected
                  </h1>
                  <p className="text-[13.5px] leading-relaxed text-[#52525B] dark:text-[#9E9E9E] text-pretty">
                    Your isolated browser session is verified and ready to scan conversations and draft in your voice.
                  </p>
                </div>

                {/* Linked Profile Summary Card */}
                <div className="p-4 rounded-xl bg-[#FAFAFA] dark:bg-[#161616] border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="size-9 rounded-lg bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
                      <svg className="size-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                      </svg>
                    </div>
                    <div className="min-w-0">
                      <p className="font-mono text-[13.5px] font-medium text-[#111111] dark:text-[#F5F5F5] truncate">
                        {displayHandle}
                      </p>
                      <p className="text-[12px] text-[#71717A] dark:text-[#8E8E8E]">
                        Isolated browser session active
                      </p>
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 shrink-0">
                    <span className="size-1.5 rounded-full bg-emerald-500" />
                    Live
                  </span>
                </div>

                <button
                  type="button"
                  onClick={onContinueToStudio}
                  className="w-full h-10 rounded-lg bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] active:scale-[0.995] text-white dark:text-[#111111] text-[13.5px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-all flex items-center justify-center"
                >
                  Enter Studio
                </button>
              </motion.div>
            ) : (
              /* Clean Single Browser Window Connection Form (No Tabs, No Tokens) */
              <motion.div
                key="connect-form"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.16, ease: "easeOut" }}
                className="space-y-6"
              >
                <div className="space-y-1.5">
                  <div className="inline-flex lg:hidden items-center gap-2 text-[12px] font-medium text-[#EA580C] mb-1">
                    <span className="tabular-nums">Step 2 of 2</span>
                    <span className="text-[#D4D4D8] dark:text-[#333333]">/</span>
                    <span className="text-[#71717A] dark:text-[#8E8E8E]">Connect X account</span>
                  </div>
                  <h1 className="font-display text-[24px] sm:text-[26px] font-semibold tracking-[-0.025em] text-[#111111] dark:text-[#F5F5F5] text-balance">
                    Connect your X account
                  </h1>
                </div>

                {/* Direct Browser Window Card */}
                <div className="rounded-xl bg-[#FAFAFA] dark:bg-[#141414] border border-[#E4E4E7] dark:border-[#242424] p-5 space-y-4">
                  <div className="flex items-start gap-3.5">
                    <div className="size-10 rounded-xl bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
                      <svg className="size-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                      </svg>
                    </div>
                    <div className="space-y-1 min-w-0">
                      <p className="text-[13.5px] font-medium text-[#111111] dark:text-[#F5F5F5]">
                        Interactive sign-in window
                      </p>
                      <p className="text-[12.5px] text-[#71717A] dark:text-[#8E8E8E] leading-relaxed text-pretty">
                        Open the X sign-in window, sign in to your profile, then click verify to sync your workspace.
                      </p>
                    </div>
                  </div>

                  <div className="space-y-2.5 pt-1">
                    <button
                      type="button"
                      onClick={handleOpenBrowserWindow}
                      className={`w-full h-10 px-4 rounded-lg text-[13.5px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-all flex items-center justify-center gap-2 ${
                        !windowOpened
                          ? "bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] text-white dark:text-[#111111]"
                          : "bg-white dark:bg-[#1A1A1A] hover:bg-[#FAFAFA] dark:hover:bg-[#222222] text-[#111111] dark:text-[#F5F5F5] border border-[#E4E4E7] dark:border-[#2E2E2E]"
                      }`}
                    >
                      {windowOpened ? (
                        <>
                          <Check className="size-4 text-emerald-500" aria-hidden="true" />
                          <span>Sign-in window opened — open again</span>
                        </>
                      ) : (
                        <>
                          <Globe className="size-4" aria-hidden="true" />
                          <span>Open X sign-in window</span>
                          <ExternalLink className="size-3.5 opacity-70" aria-hidden="true" />
                        </>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={handleVerifyBrowser}
                      disabled={isVerifying}
                      className={`w-full h-10 px-4 rounded-lg text-[13.5px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-all flex items-center justify-center gap-2 disabled:opacity-60 ${
                        windowOpened
                          ? "bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] text-white dark:text-[#111111]"
                          : "bg-white dark:bg-[#1A1A1A] hover:bg-[#FAFAFA] dark:hover:bg-[#222222] text-[#111111] dark:text-[#F5F5F5] border border-[#E4E4E7] dark:border-[#2E2E2E]"
                      }`}
                    >
                      <RefreshCw className={`size-4 ${isVerifying ? "animate-spin" : ""}`} aria-hidden="true" />
                      <span>{isVerifying ? "Verifying connection..." : "Verify X connection"}</span>
                    </button>
                  </div>
                </div>

                {feedback && (
                  <div
                    role="alert"
                    aria-live="polite"
                    className={`p-3 rounded-lg text-[12.5px] leading-relaxed flex items-start gap-2.5 border ${
                      feedback.isError
                        ? "bg-rose-50/80 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/50 text-rose-800 dark:text-rose-200"
                        : "bg-emerald-50/80 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/50 text-emerald-800 dark:text-emerald-200"
                    }`}
                  >
                    {feedback.isError ? (
                      <AlertCircle className="size-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" aria-hidden="true" />
                    ) : (
                      <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" aria-hidden="true" />
                    )}
                    <span className="text-pretty">{feedback.text}</span>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* Minimal Footer */}
        <footer className="text-center lg:text-left text-[12px] text-[#A1A1AA] dark:text-[#666666]">
          <span>Your X password is never stored. Sessions run inside an isolated workspace container.</span>
        </footer>
      </div>
    </div>
  );
}
