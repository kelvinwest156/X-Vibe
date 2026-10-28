"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  ExternalLink,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  LogOut,
  Key,
  Globe,
  Sparkles,
  Info,
  ShieldCheck,
  ChevronDown,
  ChevronUp
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
  const [activeTab, setActiveTab] = useState<"token" | "desktop">("token");
  const [authToken, setAuthToken] = useState("");
  const [ct0, setCt0] = useState("");
  const [rawCookies, setRawCookies] = useState("");
  const [useRaw, setUseRaw] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showGuide, setShowGuide] = useState(false);

  if (!isOpen) return null;

  const handleConnectToken = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!useRaw && !authToken.trim()) {
      notify("Please provide your X auth_token", true);
      return;
    }
    if (useRaw && !rawCookies.trim()) {
      notify("Please paste your session cookies", true);
      return;
    }

    setIsConnecting(true);
    try {
      const payload = useRaw
        ? { raw_cookies: rawCookies.trim() }
        : { auth_token: authToken.trim(), ct0: ct0.trim() || undefined };

      const res = await apiFetch("/api/browser/connect-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (res.ok && data.is_logged_in) {
        notify(data.message || `Connected as ${data.linked_username || "your X account"}!`);
        onSessionUpdated();
        setAuthToken("");
        setCt0("");
        setRawCookies("");
      } else {
        notify(data.message || data.detail || "Could not connect account. Please verify token.", true);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Connection failed";
      notify(msg, true);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleLaunchDesktop = async () => {
    // 1. Open interactive popup in user's browser immediately so it is 100% visible
    if (typeof window !== "undefined") {
      window.open(
        "https://x.com/login",
        "XLoginPopup",
        "width=650,height=750,left=200,top=100,menubar=no,toolbar=no"
      );
    }

    // 2. Also notify backend to prep worker
    try {
      await apiFetch("/api/browser/launch-login", { method: "POST" });
    } catch {}
    notify("Login window opened. Sign into X, then click 'Verify Connection' below.");
  };

  const handleVerify = async () => {
    setIsVerifying(true);
    try {
      const res = await apiFetch("/api/browser/check-session", { method: "POST" });
      const data = await res.json();
      if (res.ok && data.is_logged_in) {
        notify(`Verified active session for ${data.linked_username || "your account"}!`);
        onSessionUpdated();
      } else {
        notify("No active logged-in session detected on X. Please sign in first.", true);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Verification check failed";
      notify(msg, true);
    } finally {
      setIsVerifying(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDisconnecting(true);
    try {
      const res = await apiFetch("/api/browser/disconnect", { method: "POST" });
      if (res.ok) {
        notify("X account disconnected.");
        onSessionUpdated();
      } else {
        notify("Failed to disconnect", true);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error disconnecting";
      notify(msg, true);
    } finally {
      setIsDisconnecting(false);
    }
  };

  return (
    <AnimatePresence>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 8 }}
          transition={{ duration: 0.18 }}
          onClick={(e) => e.stopPropagation()}
          className="bg-white dark:bg-[#181818] border border-slate-200 dark:border-[#262626] rounded-2xl w-full max-w-lg p-5 sm:p-7 shadow-[0_8px_30px_rgb(0,0,0,0.12)] dark:shadow-[0_8px_30px_rgb(0,0,0,0.7)] text-slate-900 dark:text-[#F3F3F3] space-y-5 my-8"
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-black text-white flex items-center justify-center shrink-0 shadow-xs">
                <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
                  <span>Connect X Account</span>
                  {isLoggedIn && (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                      Live
                    </span>
                  )}
                </h3>
                <p className="text-xs text-slate-500 dark:text-[#A3A3A3]">
                  Autonomous sandbox container for your creator workspace
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-[#222222] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Connected State Banner */}
          {isLoggedIn ? (
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800/30 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <div>
                    <p className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">
                      Synchronized as {linkedUsername || "@your_account"}
                    </p>
                    <p className="text-xs text-emerald-700 dark:text-emerald-400/80">
                      Isolated multi-tenant browser sandbox active and healthy.
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2">
                <button
                  type="button"
                  onClick={handleVerify}
                  disabled={isVerifying}
                  className="px-3.5 py-2 rounded-lg text-xs font-medium border border-slate-200 dark:border-[#2E2E2E] bg-white dark:bg-[#202020] text-slate-700 dark:text-[#D4D4D4] hover:bg-slate-50 dark:hover:bg-[#262626] transition-colors flex items-center gap-1.5"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isVerifying ? "animate-spin" : ""}`} />
                  <span>{isVerifying ? "Verifying..." : "Re-check Session"}</span>
                </button>

                <button
                  type="button"
                  onClick={handleDisconnect}
                  disabled={isDisconnecting}
                  className="px-3.5 py-2 rounded-lg text-xs font-medium text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 border border-rose-200 dark:border-rose-900/40 transition-colors flex items-center gap-1.5"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>{isDisconnecting ? "Disconnecting..." : "Disconnect Account"}</span>
                </button>
              </div>
            </div>
          ) : (
            /* Connection Options */
            <div className="space-y-4">
              {/* Tab Selector */}
              <div className="grid grid-cols-2 p-1 rounded-xl bg-slate-100 dark:bg-[#202020] border border-slate-200 dark:border-[#2A2A2A] text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setActiveTab("token")}
                  className={`py-1.5 px-3 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeTab === "token"
                      ? "bg-white dark:bg-[#121212] text-slate-900 dark:text-white shadow-2xs font-semibold"
                      : "text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white"
                  }`}
                >
                  <Key className="w-3.5 h-3.5 text-amber-500" />
                  <span>Instant Session Sync</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("desktop")}
                  className={`py-1.5 px-3 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeTab === "desktop"
                      ? "bg-white dark:bg-[#121212] text-slate-900 dark:text-white shadow-2xs font-semibold"
                      : "text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white"
                  }`}
                >
                  <Globe className="w-3.5 h-3.5 text-blue-500" />
                  <span>Browser Window</span>
                </button>
              </div>

              {/* Tab 1: Token Sync */}
              {activeTab === "token" && (
                <form onSubmit={handleConnectToken} className="space-y-3.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-500 dark:text-[#A3A3A3]">
                      Recommended for SaaS & 24/7 cloud automation
                    </span>
                    <button
                      type="button"
                      onClick={() => setUseRaw(!useRaw)}
                      className="text-neutral-900 dark:text-white font-medium hover:underline text-[11px]"
                    >
                      {useRaw ? "Use token inputs" : "Paste full cookie / JSON"}
                    </button>
                  </div>

                  {!useRaw ? (
                    <div className="space-y-2.5">
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-[#D4D4D4] mb-1">
                          X Session Token (auth_token) <span className="text-rose-500">*</span>
                        </label>
                        <input
                          type="password"
                          value={authToken}
                          onChange={(e) => setAuthToken(e.target.value)}
                          placeholder="e.g. 847d02e07bf35d1f953fa98e2..."
                          className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-slate-50 dark:bg-[#121212] border border-slate-200 dark:border-[#2E2E2E] text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-hidden focus:border-neutral-900 dark:focus:border-white transition-colors"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-[#D4D4D4] mb-1">
                          CSRF Token (ct0 - optional)
                        </label>
                        <input
                          type="text"
                          value={ct0}
                          onChange={(e) => setCt0(e.target.value)}
                          placeholder="Optional ct0 token"
                          className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-slate-50 dark:bg-[#121212] border border-slate-200 dark:border-[#2E2E2E] text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-hidden focus:border-neutral-900 dark:focus:border-white transition-colors"
                        />
                      </div>
                    </div>
                  ) : (
                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-[#D4D4D4] mb-1">
                        Raw Cookie String or JSON
                      </label>
                      <textarea
                        rows={4}
                        value={rawCookies}
                        onChange={(e) => setRawCookies(e.target.value)}
                        placeholder='auth_token=847d...; ct0=192e... or [{"name":"auth_token","value":"..."}]'
                        className="w-full p-2.5 text-[11px] font-mono rounded-lg bg-slate-50 dark:bg-[#121212] border border-slate-200 dark:border-[#2E2E2E] text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-hidden focus:border-neutral-900 dark:focus:border-white transition-colors"
                      />
                    </div>
                  )}

                  {/* Expandable How-To Guide */}
                  <div className="rounded-xl border border-slate-200 dark:border-[#262626] bg-slate-50/60 dark:bg-[#141414] overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setShowGuide(!showGuide)}
                      className="w-full px-3.5 py-2.5 flex items-center justify-between text-xs font-medium text-slate-700 dark:text-[#D4D4D4] hover:bg-slate-100 dark:hover:bg-[#1A1A1A] transition-colors"
                    >
                      <span className="flex items-center gap-1.5">
                        <Info className="w-3.5 h-3.5 text-blue-500" />
                        <span>How to get your X auth_token in 10 seconds</span>
                      </span>
                      {showGuide ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    </button>
                    {showGuide && (
                      <div className="px-3.5 pb-3.5 pt-1 text-[11px] text-slate-600 dark:text-[#A3A3A3] space-y-1.5 border-t border-slate-200 dark:border-[#262626]">
                        <p>1. Open <a href="https://x.com" target="_blank" rel="noreferrer" className="text-blue-500 underline font-medium">x.com</a> in your browser and sign in.</p>
                        <p>2. Press <kbd className="px-1.5 py-0.5 rounded bg-slate-200 dark:bg-[#222] font-mono">F12</kbd> (or Right Click → <strong>Inspect</strong>).</p>
                        <p>3. Go to <strong>Application</strong> (or Storage) → <strong>Cookies</strong> → <code className="font-mono">https://x.com</code>.</p>
                        <p>4. Double click the value of <code className="text-amber-500 font-mono font-semibold">auth_token</code>, copy, and paste it above!</p>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-3 pt-2">
                    <button
                      type="button"
                      onClick={() => window.open("https://x.com/login", "_blank")}
                      className="text-xs text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white flex items-center gap-1 transition-colors"
                    >
                      <span>Open X in new tab</span>
                      <ExternalLink className="w-3 h-3" />
                    </button>

                    <button
                      type="submit"
                      disabled={isConnecting}
                      className="btn btn-primary !h-9 text-xs px-4"
                    >
                      {isConnecting ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Connecting & Verifying...</span>
                        </>
                      ) : (
                        <span>Connect & Sync Account</span>
                      )}
                    </button>
                  </div>
                </form>
              )}

              {/* Tab 2: Desktop Window */}
              {activeTab === "desktop" && (
                <div className="space-y-4 py-1">
                  <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-[#141414] border border-slate-200 dark:border-[#262626] text-xs text-slate-600 dark:text-[#A3A3A3] space-y-2">
                    <p className="font-medium text-slate-800 dark:text-[#E5E5E5]">
                      Interactive Browser Connection
                    </p>
                    <p>
                      Click the button below to launch a dedicated X sign-in window right in front of you. Once you complete sign-in, return here and click <strong>Verify Connection</strong>.
                    </p>
                  </div>

                  <div className="space-y-2.5">
                    <button
                      type="button"
                      onClick={handleLaunchDesktop}
                      className="w-full btn !h-10 text-xs font-semibold bg-neutral-900 hover:bg-neutral-800 text-white dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100 flex items-center justify-center gap-2"
                    >
                      <Globe className="w-4 h-4" />
                      <span>Launch X Sign-in Window</span>
                      <ExternalLink className="w-3.5 h-3.5 opacity-70" />
                    </button>

                    <button
                      type="button"
                      onClick={handleVerify}
                      disabled={isVerifying}
                      className="w-full btn !h-9 text-xs border border-slate-200 dark:border-[#2E2E2E] bg-white dark:bg-[#202020] text-slate-800 dark:text-white hover:bg-slate-50 dark:hover:bg-[#262626] flex items-center justify-center gap-2"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isVerifying ? "animate-spin" : ""}`} />
                      <span>{isVerifying ? "Checking X Session..." : "I Have Signed In · Verify Connection"}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Privacy & Sandbox Footer */}
          <div className="pt-3 border-t border-slate-100 dark:border-[#222222] flex items-center justify-between text-[11px] text-slate-400 dark:text-[#737373]">
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
              <span>Multi-Tenant Sandbox: 100% Isolated Profile</span>
            </span>
            <span>Zero Third-Party Sharing</span>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
