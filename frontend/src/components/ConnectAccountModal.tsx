"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Check,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  LogOut,
  Globe,
  Key,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

interface ConnectAccountModalProps {
  isOpen: boolean;
  onClose: () => void;
  isLoggedIn: boolean;
  linkedUsername?: string | null;
  onSessionUpdated: () => void;
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>;
  notify: (msg: string, isError?: boolean) => void;
}

export default function ConnectAccountModal({
  isOpen,
  onClose,
  isLoggedIn,
  linkedUsername,
  onSessionUpdated,
  apiFetch,
  notify,
}: ConnectAccountModalProps) {
  const [activeTab, setActiveTab] = useState<"browser" | "token">("browser");
  const [windowOpened, setWindowOpened] = useState(false);
  const [authToken, setAuthToken] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);
  const [isConnectingToken, setIsConnectingToken] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; isError: boolean } | null>(null);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Automatic session check loop while login window is opened
  useEffect(() => {
    if (!isOpen || !windowOpened || isLoggedIn) return;

    let isCancelled = false;
    const interval = setInterval(async () => {
      try {
        const res = await apiFetch("/api/browser/check-session", { method: "POST" });
        const data = await res.json();
        if (!isCancelled && res.ok && data.is_logged_in) {
          clearInterval(interval);
          setWindowOpened(false);
          const handle = data.linked_username ? (data.linked_username.startsWith("@") ? data.linked_username : `@${data.linked_username}`) : "your account";
          notify(`Verified active session for ${handle}!`);
          setFeedback({
            text: `Connected ${handle}! The sign-in window has been verified and closed automatically.`,
            isError: false,
          });
          onSessionUpdated();
          setTimeout(() => {
            if (!isCancelled) onClose();
          }, 1400);
        }
      } catch {
        // Continue polling silently
      }
    }, 1800);

    return () => {
      isCancelled = true;
      clearInterval(interval);
    };
  }, [isOpen, windowOpened, isLoggedIn, apiFetch, notify, onSessionUpdated, onClose]);

  if (!isOpen) return null;

  const displayHandle = (() => {
    if (!linkedUsername) return "Connected account";
    return linkedUsername.startsWith("@") ? linkedUsername : `@${linkedUsername}`;
  })();

  const handleLaunchBrowser = async () => {
    setFeedback(null);
    setWindowOpened(true);
    try {
      const res = await apiFetch("/api/browser/launch-login", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to open browser.");
      setFeedback({
        text: "Dedicated Chromium window opened on your screen. Sign in to X — X-VibeBot will automatically verify your account and close the window for you.",
        isError: false,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not launch browser.";
      setFeedback({ text: msg, isError: true });
    }
  };

  const handleVerify = async () => {
    setIsVerifying(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/browser/check-session", { method: "POST" });
      const data = await res.json();
      if (res.ok && data.is_logged_in) {
        notify(`Verified active session for ${data.linked_username || "your account"}.`);
        onSessionUpdated();
        onClose();
      } else {
        setFeedback({
          text: "No active X session detected yet. Complete sign-in in the Chromium window, then click verify.",
          isError: true,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Verification check failed.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsVerifying(false);
    }
  };

  const handleConnectToken = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanToken = authToken.trim();
    if (!cleanToken) {
      setFeedback({ text: "Please enter your X auth_token cookie or session JSON.", isError: true });
      return;
    }
    setIsConnectingToken(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/browser/connect-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auth_token: cleanToken }),
      });
      const data = await res.json();
      if (res.ok && data.is_logged_in) {
        notify(data.message || `Connected as ${data.linked_username || "your account"}!`);
        onSessionUpdated();
        setAuthToken("");
        onClose();
      } else {
        setFeedback({
          text: data.message || "X rejected or expired this session token. Please copy a fresh auth_token.",
          isError: true,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to connect token.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsConnectingToken(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/api/browser/disconnect", { method: "POST" });
      if (res.ok) {
        notify("X account disconnected.");
        onSessionUpdated();
        onClose();
      } else {
        setFeedback({ text: "Could not disconnect X session.", isError: true });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not disconnect X session.";
      setFeedback({ text: msg, isError: true });
    } finally {
      setIsDisconnecting(false);
    }
  };

  return (
    <AnimatePresence>
      <div
        className="fixed inset-0 z-50 bg-black/65 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto"
        onClick={onClose}
      >
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby="connect-account-title"
          initial={{ opacity: 0, scale: 0.97, y: 6 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.97, y: 6 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
          onClick={(e) => e.stopPropagation()}
          className="bg-white dark:bg-[#171717] border border-[#E4E4E7] dark:border-[#262626] rounded-2xl w-full max-w-[460px] p-6 sm:p-7 shadow-[0_16px_40px_rgba(0,0,0,0.14)] dark:shadow-[0_20px_50px_rgba(0,0,0,0.75)] text-[#111111] dark:text-[#F5F5F5] space-y-5 my-8"
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-lg bg-[#111111] dark:bg-[#F5F5F5] text-white dark:text-[#111111] flex items-center justify-center shrink-0">
                <svg className="size-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                </svg>
              </div>
              <div>
                <h3 id="connect-account-title" className="font-display text-[16px] font-semibold tracking-[-0.02em] text-[#111111] dark:text-[#F5F5F5] flex items-center gap-2 text-balance">
                  <span>{isLoggedIn ? "X account connection" : "Connect your X account"}</span>
                  {isLoggedIn && (
                    <span className="text-[11px] font-sans font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                      Live
                    </span>
                  )}
                </h3>
                <p className="text-[12.5px] text-[#71717A] dark:text-[#9E9E9E] text-pretty">
                  Isolated browser session dedicated to your workspace
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="size-8 rounded-lg flex items-center justify-center text-[#71717A] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#222222] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-colors"
              aria-label="Close modal"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>

          {isLoggedIn ? (
            /* Connected Account Management */
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-[#FAFAFA] dark:bg-[#121212] border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <CheckCircle2 className="size-5 text-emerald-600 dark:text-emerald-400 shrink-0" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="font-mono text-[13.5px] font-medium text-[#111111] dark:text-[#F5F5F5] truncate">
                      {displayHandle}
                    </p>
                    <p className="text-[12px] text-[#71717A] dark:text-[#8E8E8E]">
                      Session verified and active
                    </p>
                  </div>
                </div>
              </div>

              {feedback && (
                <div
                  role="alert"
                  aria-live="polite"
                  className={`p-3 rounded-lg text-[12.5px] leading-relaxed flex items-start gap-2 border ${
                    feedback.isError
                      ? "bg-rose-50/80 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/50 text-rose-800 dark:text-rose-200"
                      : "bg-emerald-50/80 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/50 text-emerald-800 dark:text-emerald-200"
                  }`}
                >
                  <AlertCircle className="size-4 shrink-0 mt-0.5" aria-hidden="true" />
                  <span className="text-pretty">{feedback.text}</span>
                </div>
              )}

              <div className="flex items-center justify-between gap-3 pt-1">
                <button
                  type="button"
                  onClick={handleVerify}
                  disabled={isVerifying}
                  className="h-9 px-3.5 rounded-lg text-[12.5px] font-medium border border-[#E4E4E7] dark:border-[#2E2E2E] bg-white dark:bg-[#1E1E1E] text-[#111111] dark:text-[#E5E5E5] hover:bg-[#FAFAFA] dark:hover:bg-[#262626] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-colors inline-flex items-center gap-1.5"
                >
                  <RefreshCw className={`size-3.5 ${isVerifying ? "animate-spin" : ""}`} aria-hidden="true" />
                  <span>{isVerifying ? "Checking..." : "Re-check session"}</span>
                </button>

                <button
                  type="button"
                  onClick={handleDisconnect}
                  disabled={isDisconnecting}
                  className="h-9 px-3.5 rounded-lg text-[12.5px] font-medium text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 border border-rose-200 dark:border-rose-900/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 transition-colors inline-flex items-center gap-1.5"
                >
                  <LogOut className="size-3.5" aria-hidden="true" />
                  <span>{isDisconnecting ? "Disconnecting..." : "Disconnect account"}</span>
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Mode Segment Switch */}
              <div className="grid grid-cols-2 p-1 rounded-xl bg-[#F4F4F5] dark:bg-[#1C1C1C] border border-[#E4E4E7] dark:border-[#2A2A2A] text-[12.5px] font-medium">
                <button
                  type="button"
                  onClick={() => {
                    setActiveTab("browser");
                    setFeedback(null);
                  }}
                  className={`py-1.5 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeTab === "browser"
                      ? "bg-white dark:bg-[#2A2A2A] text-[#111111] dark:text-[#F5F5F5] shadow-xs"
                      : "text-[#71717A] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5]"
                  }`}
                >
                  <Globe className="size-3.5" aria-hidden="true" />
                  <span>Interactive Browser</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setActiveTab("token");
                    setFeedback(null);
                  }}
                  className={`py-1.5 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeTab === "token"
                      ? "bg-white dark:bg-[#2A2A2A] text-[#111111] dark:text-[#F5F5F5] shadow-xs"
                      : "text-[#71717A] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5]"
                  }`}
                >
                  <Key className="size-3.5" aria-hidden="true" />
                  <span>Session Token (Cloud)</span>
                </button>
              </div>

              {/* Tab 1: Interactive Browser Mode */}
              {activeTab === "browser" && (
                <div className="space-y-4">
                  <div className="p-3.5 rounded-xl bg-[#FAFAFA] dark:bg-[#121212] border border-[#E4E4E7] dark:border-[#242424] text-[12.5px] leading-relaxed text-[#52525B] dark:text-[#9E9E9E] space-y-1">
                    <p className="font-medium text-[#111111] dark:text-[#E5E5E5]">
                      Local Desktop Sign-in
                    </p>
                    <p className="text-pretty">
                      Click below to open the dedicated Chromium window and sign in. X-VibeBot will automatically detect your sign-in, verify your session, and close the window for you!
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <button
                      type="button"
                      onClick={handleLaunchBrowser}
                      className={`w-full h-10 px-4 rounded-lg text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-all flex items-center justify-center gap-2 ${
                        !windowOpened
                          ? "bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] text-white dark:text-[#111111]"
                          : "bg-white dark:bg-[#1E1E1E] hover:bg-[#FAFAFA] dark:hover:bg-[#262626] text-[#111111] dark:text-[#F5F5F5] border border-[#E4E4E7] dark:border-[#2E2E2E]"
                      }`}
                    >
                      {windowOpened ? (
                        <>
                          <Check className="size-4 text-emerald-500" aria-hidden="true" />
                          <span>Chromium window opened — open again</span>
                        </>
                      ) : (
                        <>
                          <Globe className="size-4" aria-hidden="true" />
                          <span>Open X Chromium browser</span>
                        </>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={handleVerify}
                      disabled={isVerifying}
                      className={`w-full h-10 px-4 rounded-lg text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 dark:focus-visible:ring-white transition-all flex items-center justify-center gap-2 disabled:opacity-60 ${
                        windowOpened
                          ? "bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] text-white dark:text-[#111111]"
                          : "bg-white dark:bg-[#1E1E1E] hover:bg-[#FAFAFA] dark:hover:bg-[#262626] text-[#111111] dark:text-[#F5F5F5] border border-[#E4E4E7] dark:border-[#2E2E2E]"
                      }`}
                    >
                      <RefreshCw className={`size-4 ${isVerifying ? "animate-spin" : ""}`} aria-hidden="true" />
                      <span>{isVerifying ? "Checking X session..." : "Verify X connection"}</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Tab 2: Direct Token Mode (Perfect for Cloud & Production) */}
              {activeTab === "token" && (
                <form onSubmit={handleConnectToken} className="space-y-3.5">
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <label
                        htmlFor="modal-auth-token"
                        className="text-[12.5px] font-medium text-[#111111] dark:text-[#E5E5E5]"
                      >
                        X auth_token cookie
                      </label>
                      <button
                        type="button"
                        onClick={() => setShowGuide(!showGuide)}
                        className="text-[11.5px] font-medium text-[#EA580C] hover:underline flex items-center gap-1"
                      >
                        <span>Where do I find this?</span>
                        {showGuide ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
                      </button>
                    </div>

                    <input
                      id="modal-auth-token"
                      type="password"
                      autoComplete="off"
                      placeholder="Paste your 40-character auth_token value"
                      value={authToken}
                      onChange={(e) => setAuthToken(e.target.value)}
                      className="w-full h-10 px-3.5 rounded-lg border border-[#E4E4E7] dark:border-[#2A2A2A] bg-white dark:bg-[#141414] text-[13px] text-[#111111] dark:text-[#F5F5F5] placeholder:text-[#A1A1AA] dark:placeholder:text-[#5E5E5E] focus:outline-none focus:border-[#111111] dark:focus:border-[#666666] focus:ring-2 focus:ring-[#111111]/5 dark:focus:ring-white/5 font-mono"
                    />

                    {showGuide && (
                      <div className="p-3 rounded-lg bg-[#F4F4F5] dark:bg-[#181818] border border-[#E4E4E7] dark:border-[#262626] text-[11.5px] leading-relaxed text-[#52525B] dark:text-[#A3A3A3] space-y-1">
                        <p>1. Open <strong className="text-[#111111] dark:text-white">x.com</strong> in your browser where you are logged in.</p>
                        <p>2. Press <kbd className="px-1 py-0.5 rounded bg-white dark:bg-[#222] border border-[#D4D4D8] dark:border-[#333] font-mono">F12</kbd> (Inspect) → <strong>Application</strong> tab → <strong>Cookies</strong> → <strong>https://x.com</strong>.</p>
                        <p>3. Double-click the <strong>auth_token</strong> cookie value, copy it, and paste it here.</p>
                      </div>
                    )}
                  </div>

                  <button
                    type="submit"
                    disabled={isConnectingToken}
                    className="w-full h-10 px-4 rounded-lg bg-[#111111] hover:bg-[#27272A] dark:bg-[#F5F5F5] dark:hover:bg-[#E4E4E7] active:scale-[0.995] text-white dark:text-[#111111] text-[13px] font-medium transition-all flex items-center justify-center gap-2 disabled:opacity-60"
                  >
                    {isConnectingToken ? (
                      <>
                        <RefreshCw className="size-4 animate-spin" aria-hidden="true" />
                        <span>Connecting & Verifying with X...</span>
                      </>
                    ) : (
                      <span>Connect with Token</span>
                    )}
                  </button>
                </form>
              )}

              {/* Feedback Alert */}
              {feedback && (
                <div
                  role="alert"
                  aria-live="polite"
                  className={`p-3 rounded-lg text-[12px] leading-relaxed flex items-start gap-2 border ${
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
            </div>
          )}

          {/* Privacy Note */}
          <div className="pt-3 border-t border-[#F4F4F5] dark:border-[#222222] text-[11.5px] text-[#71717A] dark:text-[#737373]">
            Your X password is never stored. Sessions run inside an isolated workspace container.
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
