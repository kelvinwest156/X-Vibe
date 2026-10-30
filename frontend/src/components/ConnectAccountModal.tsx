"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  ExternalLink,
  Check,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  LogOut,
  Globe,
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
  const [windowOpened, setWindowOpened] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
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

  if (!isOpen) return null;

  const displayHandle = (() => {
    if (!linkedUsername) return "Connected account";
    return linkedUsername.startsWith("@") ? linkedUsername : `@${linkedUsername}`;
  })();

  const handleLaunchBrowser = async () => {
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
          text: "No active X session detected yet. Complete sign-in in the X browser window, then click verify.",
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
          className="bg-white dark:bg-[#171717] border border-[#E4E4E7] dark:border-[#262626] rounded-2xl w-full max-w-[440px] p-6 sm:p-7 shadow-[0_16px_40px_rgba(0,0,0,0.14)] dark:shadow-[0_20px_50px_rgba(0,0,0,0.75)] text-[#111111] dark:text-[#F5F5F5] space-y-5 my-8"
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
                      Session verified and isolated
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
            /* Single Browser Window Action Form */
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-[#FAFAFA] dark:bg-[#121212] border border-[#E4E4E7] dark:border-[#242424] text-[12.5px] leading-relaxed text-[#52525B] dark:text-[#9E9E9E] space-y-1.5">
                <p className="font-medium text-[#111111] dark:text-[#E5E5E5]">
                  Interactive browser sign-in
                </p>
                <p className="text-pretty">
                  Open the X sign-in window, sign in to your profile, then click <strong>Verify X connection</strong> to sync your workspace.
                </p>
              </div>

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

          {/* Privacy Note */}
          <div className="pt-3 border-t border-[#F4F4F5] dark:border-[#222222] text-[11.5px] text-[#71717A] dark:text-[#737373]">
            Your X password is never stored. Sessions run inside an isolated workspace container.
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
