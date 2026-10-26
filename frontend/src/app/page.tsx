"use client";

import React, { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BarChart3,
  Inbox,
  History,
  Sliders,
  Sparkles,
  Play,
  Pause,
  Radar,
  RefreshCw,
  Clock,
  Send,
  Trash2,
  ExternalLink,
  Terminal,
  Cookie,
  CheckCircle2,
  AlertCircle,
  Layers,
  Feather,
  Moon,
  Sun,
  ShieldCheck,
} from "lucide-react";
import AnalyticsView, { AnalyticsData } from "@/components/AnalyticsView";

interface SystemLog {
  timestamp: string;
  level: string;
  message: string;
}

interface AgentStatus {
  is_active: boolean;
  auto_pilot_mode: boolean;
  polling_interval_minutes: number;
  daily_action_cap: number;
  daily_actions_used: number;
  cooldown_active: boolean;
  cooldown_seconds_remaining: number;
  within_active_hours: boolean;
  scheduled_count: number;
  browser_connected: boolean;
  is_logged_in: boolean;
  linked_username?: string | null;
  pending_approvals_count: number;
  total_processed_count: number;
  selected_model: string;
  recent_logs: SystemLog[];
}

interface AgentConfig {
  id: number;
  is_active: boolean;
  auto_pilot_mode: boolean;
  polling_interval_minutes: number;
  daily_action_cap: number;
  min_cooldown_minutes: number;
  max_cooldown_minutes: number;
  active_hours_start: number;
  active_hours_end: number;
  search_query: string;
  persona_prompt: string;
  selected_model: string;
  linked_username?: string | null;
  masked_api_key?: string | null;
}

interface TweetItem {
  tweet_id: string;
  action_type: string;
  tweet_text?: string | null;
  tweet_author?: string | null;
  tweet_url?: string | null;
  generated_text?: string | null;
  variants_json?: string | null;
  tweet_metrics?: string | null;
  status: string;
  scheduled_for?: string | null;
  error_message?: string | null;
  timestamp: string;
}

type NavTab = "dashboard" | "queue" | "history" | "settings";

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<NavTab>("dashboard");
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [pendingItems, setPendingItems] = useState<TweetItem[]>([]);
  const [historyItems, setHistoryItems] = useState<TweetItem[]>([]);
  const [draftEdits, setDraftEdits] = useState<Record<string, string>>({});
  const [activeVariantKey, setActiveVariantKey] = useState<Record<string, string>>({});
  const [busyMap, setBusyMap] = useState<Record<string, boolean>>({});
  const [scanning, setScanning] = useState(false);
  const [draftingMode, setDraftingMode] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(true);
  const [cookieModalOpen, setCookieModalOpen] = useState(false);
  const [cookieJson, setCookieJson] = useState("");
  const [historyFilter, setHistoryFilter] = useState<string>("all");

  // Editable config fields
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [modelInput, setModelInput] = useState("gemini-3.8-flash");
  const [queryInput, setQueryInput] = useState("");
  const [personaInput, setPersonaInput] = useState("");
  const [capInput, setCapInput] = useState(15);
  const [intervalInput, setIntervalInput] = useState(20);
  const [minDelayInput, setMinDelayInput] = useState(10);
  const [maxDelayInput, setMaxDelayInput] = useState(45);
  const [startHourInput, setStartHourInput] = useState(8);
  const [endHourInput, setEndHourInput] = useState(23);
  const [autopilotInput, setAutopilotInput] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
  ]);

  // Toast state
  const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);
  const notify = useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    setTimeout(() => setToast(null), 3600);
  }, []);

  const fetchAllData = useCallback(async () => {
    try {
      const [stRes, anRes, pdRes] = await Promise.all([
        fetch("/api/status"),
        fetch("/api/analytics"),
        fetch("/api/pending"),
      ]);
      if (stRes.ok) setStatus(await stRes.json());
      if (anRes.ok) setAnalytics(await anRes.json());
      if (pdRes.ok) {
        const list: TweetItem[] = await pdRes.json();
        setPendingItems(list);
        setDraftEdits((prev) => {
          const next = { ...prev };
          list.forEach((item) => {
            if (next[item.tweet_id] === undefined) {
              next[item.tweet_id] = item.generated_text || "";
            }
          });
          return next;
        });
      }
    } catch {}
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch("/api/config");
      if (!res.ok) return;
      const cfg: AgentConfig = await res.json();
      setConfig(cfg);
      setModelInput(cfg.selected_model || "gemini-3.8-flash");
      setQueryInput(cfg.search_query || "");
      setPersonaInput(cfg.persona_prompt || "");
      setCapInput(cfg.daily_action_cap || 15);
      setIntervalInput(cfg.polling_interval_minutes || 20);
      setMinDelayInput(cfg.min_cooldown_minutes || 10);
      setMaxDelayInput(cfg.max_cooldown_minutes || 45);
      setStartHourInput(cfg.active_hours_start ?? 8);
      setEndHourInput(cfg.active_hours_end ?? 23);
      setAutopilotInput(Boolean(cfg.auto_pilot_mode));
    } catch {}
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/history?limit=60");
      if (res.ok) setHistoryItems(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    fetchConfig();
    fetchAllData();
    fetchHistory();
    const timer = setInterval(fetchAllData, 5000);
    return () => clearInterval(timer);
  }, [fetchConfig, fetchAllData, fetchHistory]);

  // Actions
  const handleToggleAgent = async () => {
    if (!status) return;
    const nextState = !status.is_active;
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: nextState }),
    });
    if (res.ok) {
      notify(nextState ? "Autonomous Agent started" : "Agent paused");
      fetchAllData();
    }
  };

  const handleSaveSettings = async (silent = false) => {
    const payload: Record<string, unknown> = {
      auto_pilot_mode: autopilotInput,
      polling_interval_minutes: Number(intervalInput) || 20,
      daily_action_cap: Number(capInput) || 15,
      min_cooldown_minutes: Number(minDelayInput) || 10,
      max_cooldown_minutes: Number(maxDelayInput) || 45,
      active_hours_start: Number(startHourInput) || 0,
      active_hours_end: Number(endHourInput) || 23,
      search_query: queryInput.trim(),
      persona_prompt: personaInput.trim(),
      selected_model: modelInput,
    };
    if (apiKeyInput.trim()) payload.api_key = apiKeyInput.trim();

    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const updated = await res.json();
      setConfig(updated);
      setApiKeyInput("");
      if (!silent) notify("Configuration saved");
      fetchAllData();
    } else if (!silent) {
      notify("Failed to save configuration", true);
    }
  };

  const handleVerifyKey = async () => {
    setBusyMap((p) => ({ ...p, verifyKey: true }));
    try {
      const res = await fetch("/api/ai/test-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKeyInput.trim() || null }),
      });
      const data = await res.json();
      if (data.success) {
        if (data.models?.length) {
          setAvailableModels(data.models.map((m: { id: string }) => m.id));
        }
        setApiKeyInput("");
        notify("Gemini API key verified & active");
        fetchConfig();
      } else {
        notify(data.hint || data.error || "API key verification failed", true);
      }
    } finally {
      setBusyMap((p) => ({ ...p, verifyKey: false }));
    }
  };

  const handleScanNow = async () => {
    setScanning(true);
    await handleSaveSettings(true);
    try {
      const res = await fetch("/api/trigger-scrape", { method: "POST" });
      const data = await res.json();
      if (!res.ok || data.status === "not_logged_in" || data.status === "missing_api_key") {
        notify(data.message || "Check X login & Gemini API key", true);
      } else {
        notify("Scanning live X feed & synthesizing drafts...");
        [3000, 7000, 13000, 22000].forEach((ms) => setTimeout(fetchAllData, ms));
      }
    } finally {
      setTimeout(() => setScanning(false), 1800);
    }
  };

  const handleGenerateOriginal = async (mode: "post" | "thread") => {
    setDraftingMode(mode);
    notify(`Synthesizing original ${mode} from live pulse...`);
    try {
      const res = await fetch("/api/generate-original", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          custom_topic: queryInput.trim() || null,
        }),
      });
      if (res.ok) {
        const created: TweetItem = await res.json();
        setDraftEdits((p) => ({
          ...p,
          [created.tweet_id]: created.generated_text || "",
        }));
        notify(`New ${mode} added to Action Queue!`);
        setActiveTab("queue");
        await fetchAllData();
      } else {
        const err = await res.json();
        notify(err.detail || `Failed to generate ${mode}`, true);
      }
    } finally {
      setDraftingMode(null);
    }
  };

  const handleRegenerate = async (tweetId: string) => {
    setBusyMap((p) => ({ ...p, [`regen_${tweetId}`]: true }));
    try {
      const res = await fetch(`/api/regenerate/${tweetId}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setDraftEdits((p) => ({ ...p, [tweetId]: data.generated_text || "" }));
        notify("Fresh angles synthesized");
        await fetchAllData();
      } else {
        notify("Could not regenerate right now", true);
      }
    } finally {
      setBusyMap((p) => ({ ...p, [`regen_${tweetId}`]: false }));
    }
  };

  const handleApprove = async (tweetId: string, scheduleRandom: boolean) => {
    const busyKey = `${scheduleRandom ? "sched" : "post"}_${tweetId}`;
    setBusyMap((p) => ({ ...p, [busyKey]: true }));
    try {
      const customText = (draftEdits[tweetId] || "").trim();
      const res = await fetch(`/api/approve/${tweetId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          custom_text: customText,
          schedule_random: scheduleRandom,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        if (scheduleRandom) {
          notify(`Scheduled for random organic window (~${data.minutes_from_now}m)`);
        } else {
          notify("Published to X!");
        }
        await fetchAllData();
        await fetchHistory();
      } else {
        notify(data.detail || "Action failed", true);
      }
    } finally {
      setBusyMap((p) => ({ ...p, [busyKey]: false }));
    }
  };

  const handleReject = async (tweetId: string) => {
    await fetch(`/api/reject/${tweetId}`, { method: "POST" });
    setPendingItems((prev) => prev.filter((i) => i.tweet_id !== tweetId));
    fetchAllData();
    fetchHistory();
  };

  const handleLaunchLogin = async () => {
    notify("Launching browser window for X login...");
    const res = await fetch("/api/browser/launch-login", { method: "POST" });
    const data = await res.json();
    notify(data.message || "Browser opened");
    setTimeout(fetchAllData, 4000);
  };

  const handleCheckSession = async () => {
    notify("Verifying X session...");
    const res = await fetch("/api/browser/check-session", { method: "POST" });
    const data = await res.json();
    if (data.is_logged_in) {
      notify(`Connected as ${data.linked_username || "active user"}`);
    } else {
      notify("Not logged in yet", true);
    }
    fetchAllData();
  };

  const handleExportCookies = async () => {
    const res = await fetch("/api/browser/cookies");
    const data = await res.json();
    setCookieJson(JSON.stringify(data.cookies || [], null, 2));
    notify(`Exported ${data.count || 0} cookies`);
  };

  const handleImportCookies = async () => {
    try {
      const parsed = JSON.parse(cookieJson.trim());
      const res = await fetch("/api/browser/cookies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies: parsed }),
      });
      const data = await res.json();
      if (data.is_logged_in) {
        notify(`Connected as ${data.linked_username || "active user"}!`);
        setCookieModalOpen(false);
        fetchAllData();
      } else {
        notify("Cookies imported, but session not authenticated", true);
      }
    } catch {
      notify("Invalid JSON format", true);
    }
  };

  const formatScheduledBadge = (iso?: string | null) => {
    if (!iso) return "";
    const dt = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    const mins = Math.max(1, Math.round((dt.getTime() - Date.now()) / 60000));
    const timeStr = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `Scheduled ${timeStr} (~${mins}m)`;
  };

  const filteredHistory = historyItems.filter((item) =>
    historyFilter === "all" ? true : item.status === historyFilter
  );

  return (
    <div className="min-h-screen flex flex-col lg:flex-row">
      {/* Toast Notification */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.95 }}
            className="fixed bottom-5 right-5 z-50 bi-card rounded-xl px-4 py-3 flex items-center gap-2.5 shadow-2xl border border-sky-500/30"
          >
            {toast.error ? (
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            ) : (
              <CheckCircle2 className="w-4 h-4 text-sky-400 shrink-0" />
            )}
            <span className="text-xs font-light text-slate-100">{toast.msg}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Cloud Cookie Sync Modal */}
      <AnimatePresence>
        {cookieModalOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95, y: 10 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.95, y: 10 }}
              className="bi-card rounded-2xl max-w-lg w-full p-5 space-y-4"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cookie className="w-4 h-4 text-sky-400" />
                  <h3 className="text-sm font-semibold text-white">
                    X Session Cookies (Cloud Sync)
                  </h3>
                </div>
                <button
                  onClick={() => setCookieModalOpen(false)}
                  className="text-slate-400 hover:text-white text-xs"
                >
                  ✕
                </button>
              </div>
              <p className="text-xs font-extralight text-slate-400">
                Export your local X session cookies or paste them here when running on Render.
              </p>
              <textarea
                rows={6}
                value={cookieJson}
                onChange={(e) => setCookieJson(e.target.value)}
                placeholder='[{"name": "auth_token", ...}]'
                className="w-full bg-[#0A0F1D] border border-white/10 rounded-xl p-3 text-xs font-mono font-light text-slate-200 focus:outline-none focus:border-sky-400"
              />
              <div className="flex items-center justify-end gap-2">
                <button
                  onClick={handleExportCookies}
                  className="px-3.5 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 text-xs font-light text-slate-200 transition"
                >
                  Export Current
                </button>
                <button
                  onClick={handleImportCookies}
                  className="px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs transition"
                >
                  Import & Verify
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Left Power BI Navigation Sidebar */}
      <aside className="w-full lg:w-64 bg-[#0D1322]/90 backdrop-blur-xl border-b lg:border-b-0 lg:border-r border-white/[0.07] flex flex-col justify-between p-4 shrink-0">
        <div className="space-y-6">
          {/* Brand Logo */}
          <div className="flex items-center justify-between px-2 pt-1">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-sky-400/20 to-purple-500/20 border border-sky-400/40 flex items-center justify-center text-sky-300 font-mono font-semibold text-base shadow-lg shadow-sky-500/10">
                X
              </div>
              <div>
                <div className="text-base tracking-tight text-white">
                  <strong className="font-semibold">Vibe</strong>
                  <span className="font-extralight text-slate-300">Bot</span>
                </div>
                <span className="text-[10px] font-mono font-extralight text-sky-400/90 block">
                  BI & Creator Suite
                </span>
              </div>
            </div>

            {/* Live Status Dot */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] text-[11px]">
              <span
                className={`w-2 h-2 rounded-full ${
                  status?.is_active
                    ? status.within_active_hours
                      ? "bg-emerald-400 animate-pulse"
                      : "bg-amber-400"
                    : "bg-slate-500"
                }`}
              />
              <span className="font-light text-slate-300">
                {status?.is_active
                  ? status.within_active_hours
                    ? "Active"
                    : "Sleeping"
                  : "Paused"}
              </span>
            </div>
          </div>

          {/* Navigation Menu */}
          <nav className="space-y-1.5">
            {[
              {
                id: "dashboard" as NavTab,
                label: "Analytics BI",
                sub: "Metrics & Velocity",
                icon: BarChart3,
                badge: null,
              },
              {
                id: "queue" as NavTab,
                label: "Action Queue",
                sub: "Replies, Posts & Threads",
                icon: Inbox,
                badge: status?.pending_approvals_count ?? 0,
              },
              {
                id: "history" as NavTab,
                label: "Activity Audit",
                sub: "Published & Filtered",
                icon: History,
                badge: status?.total_processed_count ?? null,
              },
              {
                id: "settings" as NavTab,
                label: "Agent Studio",
                sub: "Voice, Timing & Keys",
                icon: Sliders,
                badge: null,
              },
            ].map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveTab(item.id);
                    if (item.id === "history") fetchHistory();
                  }}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-left transition relative overflow-hidden ${
                    isActive
                      ? "bg-gradient-to-r from-sky-500/15 to-purple-500/10 text-white border border-sky-400/30 shadow-lg shadow-sky-500/5"
                      : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.03] border border-transparent"
                  }`}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeRail"
                      className="absolute left-0 top-2 bottom-2 w-1 rounded-r-full bg-sky-400"
                    />
                  )}
                  <div className="flex items-center gap-3">
                    <Icon
                      className={`w-4 h-4 ${
                        isActive ? "text-sky-400" : "text-slate-400"
                      }`}
                      strokeWidth={1.6}
                    />
                    <div>
                      <span
                        className={`text-xs block ${
                          isActive ? "font-semibold text-white" : "font-light"
                        }`}
                      >
                        {item.label}
                      </span>
                      <span className="text-[10px] font-extralight text-slate-500 hidden sm:block">
                        {item.sub}
                      </span>
                    </div>
                  </div>
                  {item.badge !== null && (
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono ${
                        isActive
                          ? "bg-sky-400/20 text-sky-300 font-semibold"
                          : "bg-white/[0.05] text-slate-400 font-light"
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Quick Live Target Card inside Sidebar */}
          <div className="bi-card rounded-2xl p-3.5 space-y-2.5">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-extralight text-slate-400">Active Topic</span>
              <span className="font-mono text-[10px] text-sky-400">Live Pulse</span>
            </div>
            <input
              type="text"
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              onBlur={() => handleSaveSettings(true)}
              placeholder="#elclassico OR buildinpublic"
              className="w-full bg-[#090D18] border border-white/[0.08] rounded-xl px-2.5 py-1.5 text-xs font-light text-white focus:outline-none focus:border-sky-400"
            />
            <div className="grid grid-cols-2 gap-1.5 pt-1">
              <button
                onClick={() => handleGenerateOriginal("post")}
                disabled={draftingMode !== null}
                className="py-1.5 px-2 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/25 text-[11px] font-light text-emerald-300 transition flex items-center justify-center gap-1"
              >
                <Feather className="w-3 h-3" />
                {draftingMode === "post" ? "..." : "+ Post"}
              </button>
              <button
                onClick={() => handleGenerateOriginal("thread")}
                disabled={draftingMode !== null}
                className="py-1.5 px-2 rounded-lg bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/25 text-[11px] font-light text-purple-300 transition flex items-center justify-center gap-1"
              >
                <Layers className="w-3 h-3" />
                {draftingMode === "thread" ? "..." : "+ Thread"}
              </button>
            </div>
          </div>
        </div>

        {/* Bottom Sidebar Info: Awake Schedule & Logs Toggle */}
        <div className="space-y-2 pt-4 border-t border-white/[0.06] mt-4">
          <div className="flex items-center justify-between px-2 py-1.5 rounded-xl bg-white/[0.02] text-xs">
            <div className="flex items-center gap-2">
              {status?.within_active_hours ? (
                <Sun className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <Moon className="w-3.5 h-3.5 text-amber-400" />
              )}
              <span className="font-extralight text-slate-300 text-[11px]">
                {status?.within_active_hours ? "Awake Window" : "Sleep Window"}
              </span>
            </div>
            <span className="font-mono text-[10px] text-slate-400">
              {startHourInput}:00–{endHourInput}:00
            </span>
          </div>

          <button
            onClick={() => setShowLogs((s) => !s)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] text-xs font-light text-slate-300 transition"
          >
            <span className="flex items-center gap-2">
              <Terminal className="w-3.5 h-3.5 text-sky-400" />
              Live Telemetry Logs
            </span>
            <span className="text-[10px] font-mono text-slate-500">
              {showLogs ? "Hide" : "Show"}
            </span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Power BI Glass Header */}
        <header className="sticky top-0 z-30 bg-[#0B0F19]/80 backdrop-blur-xl border-b border-white/[0.07] px-5 py-3 flex flex-wrap items-center justify-between gap-3">
          {/* Left: Linked Account + Quick Metrics */}
          <div className="flex items-center gap-3 flex-wrap">
            {/* Linked X Account Pill */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/[0.04] border border-white/[0.08] text-xs">
              <span
                className={`w-2 h-2 rounded-full ${
                  status?.is_logged_in ? "bg-emerald-400" : "bg-rose-400"
                }`}
              />
              <span
                className={`font-mono ${
                  status?.is_logged_in
                    ? "font-semibold text-emerald-300"
                    : "font-light text-slate-400"
                }`}
              >
                {status?.is_logged_in
                  ? status.linked_username || "Linked"
                  : "Not Linked"}
              </span>
              <button
                onClick={handleCheckSession}
                title="Verify X Session"
                className="text-slate-400 hover:text-white transition ml-0.5"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>

            {/* Hide Login Button when already logged in */}
            {status && !status.is_logged_in && (
              <button
                onClick={handleLaunchLogin}
                className="px-3 py-1.5 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/30 text-xs font-semibold text-sky-300 transition"
              >
                Login to X
              </button>
            )}

            <div className="hidden md:flex items-center gap-4 pl-2 text-xs font-mono font-light text-slate-400">
              <span>
                Today:{" "}
                <strong className="font-semibold text-white">
                  {status?.daily_actions_used ?? 0}/{status?.daily_action_cap ?? 15}
                </strong>
              </span>
              <span>
                Scheduled:{" "}
                <strong className="font-semibold text-sky-400">
                  {status?.scheduled_count ?? 0}
                </strong>
              </span>
              <span
                className={
                  status?.cooldown_active ? "text-amber-400" : "text-emerald-400"
                }
              >
                {status?.cooldown_active
                  ? `Cooldown ${Math.floor(
                      (status.cooldown_seconds_remaining || 0) / 60
                    )}m`
                  : "Ready"}
              </span>
            </div>
          </div>

          {/* Right: Action Buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCookieModalOpen(true)}
              className="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-xs font-light text-slate-300 flex items-center gap-1.5 transition"
            >
              <Cookie className="w-3.5 h-3.5 text-slate-400" />
              <span className="hidden sm:inline">Cookies</span>
            </button>

            <button
              onClick={handleScanNow}
              disabled={scanning}
              className="px-3.5 py-1.5 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/35 text-xs font-light text-sky-300 flex items-center gap-1.5 transition"
            >
              <Radar
                className={`w-3.5 h-3.5 ${scanning ? "animate-spin" : ""}`}
              />
              <span>{scanning ? "Scanning..." : "Scan Feed"}</span>
            </button>

            <button
              onClick={handleToggleAgent}
              className={`px-4 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition ${
                status?.is_active
                  ? "bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/35"
                  : "bg-emerald-500 hover:bg-emerald-400 text-slate-950 shadow-lg shadow-emerald-500/15"
              }`}
            >
              {status?.is_active ? (
                <>
                  <Pause className="w-3.5 h-3.5" />
                  <span>Pause</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" />
                  <span>Start Agent</span>
                </>
              )}
            </button>
          </div>
        </header>

        {/* Main Animated View Container */}
        <main className="flex-1 p-5 lg:p-6 max-w-7xl w-full mx-auto space-y-5">
          <AnimatePresence mode="wait">
            {/* TAB 1: POWER BI ANALYTICS DASHBOARD */}
            {activeTab === "dashboard" && (
              <motion.div
                key="dashboard"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
              >
                <AnalyticsView
                  data={analytics}
                  onGenerateOriginal={handleGenerateOriginal}
                />
              </motion.div>
            )}

            {/* TAB 2: ACTION QUEUE (REPLIES, ORIGINAL POSTS & THREADS) */}
            {activeTab === "queue" && (
              <motion.div
                key="queue"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
                className="space-y-4"
              >
                {/* Queue Header Bar */}
                <div className="bi-card rounded-2xl p-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-white tracking-tight">
                      Action Queue & Content Synthesizer
                    </h2>
                    <p className="text-xs font-extralight text-slate-400">
                      Review, tweak angles, schedule at random human timestamps, or publish immediately
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleGenerateOriginal("post")}
                      disabled={draftingMode !== null}
                      className="px-3.5 py-2 rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-xs font-light text-emerald-300 flex items-center gap-1.5 transition"
                    >
                      <Feather className="w-3.5 h-3.5" />
                      <span>
                        {draftingMode === "post" ? "Drafting..." : "+ New Post"}
                      </span>
                    </button>
                    <button
                      onClick={() => handleGenerateOriginal("thread")}
                      disabled={draftingMode !== null}
                      className="px-3.5 py-2 rounded-xl bg-purple-500/15 hover:bg-purple-500/25 border border-purple-500/30 text-xs font-light text-purple-300 flex items-center gap-1.5 transition"
                    >
                      <Layers className="w-3.5 h-3.5" />
                      <span>
                        {draftingMode === "thread" ? "Drafting..." : "+ New Thread"}
                      </span>
                    </button>
                  </div>
                </div>

                {pendingItems.length === 0 ? (
                  <div className="bi-card rounded-2xl p-12 text-center space-y-3">
                    <Sparkles className="w-8 h-8 text-sky-400 mx-auto opacity-80" strokeWidth={1.4} />
                    <p className="text-sm font-light text-slate-300">
                      Your Action Queue is clear.
                    </p>
                    <p className="text-xs font-extralight text-slate-500">
                      Click <strong className="font-semibold text-slate-300">Scan Feed</strong> to discover conversations or{" "}
                      <strong className="font-semibold text-purple-300">+ New Thread</strong> to synthesize an original thread.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4">
                    {pendingItems.map((item, idx) => {
                      let variants: Record<string, string> = {};
                      try {
                        if (item.variants_json) variants = JSON.parse(item.variants_json);
                      } catch {}
                      const variantKeys = Object.keys(variants);
                      const isScheduled = item.status === "scheduled";
                      const actType = item.action_type || "reply";
                      const isThread = actType === "thread";
                      const isPost = actType === "post";
                      const currentText =
                        draftEdits[item.tweet_id] ?? item.generated_text ?? "";
                      const threadPartsCount = currentText
                        .split("---")
                        .filter((p) => p.trim()).length;

                      return (
                        <motion.div
                          key={item.tweet_id}
                          initial={{ opacity: 0, y: 14 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.3, delay: idx * 0.04 }}
                          className={`bi-card bi-card-interactive rounded-2xl p-5 space-y-3.5 ${
                            isScheduled ? "border-sky-400/40" : ""
                          }`}
                        >
                          {/* Card Top Metadata */}
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap">
                              {isThread ? (
                                <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30">
                                  THREAD ({threadPartsCount} posts)
                                </span>
                              ) : isPost ? (
                                <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                                  ORIGINAL POST
                                </span>
                              ) : (
                                <span className="text-[10px] font-mono font-light px-2.5 py-0.5 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/30">
                                  SMART REPLY
                                </span>
                              )}

                              <span className="text-xs font-semibold text-white tracking-tight">
                                @{item.tweet_author || "user"}
                              </span>

                              {item.tweet_metrics && (
                                <span className="text-[10px] font-mono font-light px-2 py-0.5 rounded-full bg-white/[0.04] text-slate-400 border border-white/[0.06]">
                                  {item.tweet_metrics}
                                </span>
                              )}

                              {isScheduled && (
                                <span className="text-[10px] font-mono font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-400/35 flex items-center gap-1">
                                  <Clock className="w-2.5 h-2.5" />
                                  {formatScheduledBadge(item.scheduled_for)}
                                </span>
                              )}
                            </div>

                            {actType === "reply" && item.tweet_url && (
                              <a
                                href={item.tweet_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-[11px] font-mono font-light text-slate-400 hover:text-sky-400 flex items-center gap-1 transition"
                              >
                                <span>Source</span>
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                          </div>

                          {/* Context / Original Scraped Tweet */}
                          <div className="text-xs font-extralight leading-relaxed text-slate-300 bg-[#0A0F1D]/90 p-3 rounded-xl border border-white/[0.06] whitespace-pre-line">
                            {item.tweet_text}
                          </div>

                          {/* Vibe Variant Switcher + Regenerate */}
                          <div className="space-y-2">
                            <div className="flex items-center justify-between flex-wrap gap-2">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                {variantKeys.map((k) => {
                                  const selected =
                                    (activeVariantKey[item.tweet_id] || "witty") === k;
                                  return (
                                    <button
                                      key={k}
                                      onClick={() => {
                                        setActiveVariantKey((p) => ({
                                          ...p,
                                          [item.tweet_id]: k,
                                        }));
                                        setDraftEdits((p) => ({
                                          ...p,
                                          [item.tweet_id]: variants[k],
                                        }));
                                      }}
                                      className={`px-2.5 py-1 rounded-lg text-[10px] font-mono capitalize transition border ${
                                        selected
                                          ? "bg-sky-500/20 text-sky-300 border-sky-400/40 font-semibold"
                                          : "bg-white/[0.03] hover:bg-white/[0.07] text-slate-400 border-white/[0.06] font-light"
                                      }`}
                                    >
                                      {k}
                                    </button>
                                  );
                                })}
                                {isThread && (
                                  <span className="text-[10px] font-mono font-extralight text-slate-500 ml-1">
                                    Separate tweets with ---
                                  </span>
                                )}
                              </div>

                              <button
                                onClick={() => handleRegenerate(item.tweet_id)}
                                disabled={busyMap[`regen_${item.tweet_id}`]}
                                className="px-2.5 py-1 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-xs font-mono font-light text-slate-300 flex items-center gap-1 transition"
                              >
                                <RefreshCw
                                  className={`w-3 h-3 ${
                                    busyMap[`regen_${item.tweet_id}`]
                                      ? "animate-spin text-sky-400"
                                      : ""
                                  }`}
                                />
                                <span className="text-[10px]">Regenerate</span>
                              </button>
                            </div>

                            <textarea
                              rows={isThread ? 6 : 2}
                              value={currentText}
                              onChange={(e) =>
                                setDraftEdits((p) => ({
                                  ...p,
                                  [item.tweet_id]: e.target.value,
                                }))
                              }
                              className="w-full bg-[#090D18] border border-white/[0.09] rounded-xl p-3 text-xs font-light leading-relaxed text-white focus:outline-none focus:border-sky-400"
                            />
                          </div>

                          {/* Action Buttons */}
                          <div className="flex items-center justify-between pt-1">
                            <span className="text-[10px] font-mono font-extralight text-slate-500">
                              {currentText.length} chars
                            </span>
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => handleReject(item.tweet_id)}
                                className="px-3 py-1.5 rounded-xl text-xs font-light text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 flex items-center gap-1 transition"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                                <span>Skip</span>
                              </button>
                              <button
                                onClick={() => handleApprove(item.tweet_id, true)}
                                disabled={busyMap[`sched_${item.tweet_id}`]}
                                className="px-3.5 py-1.5 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-400/30 font-light text-xs flex items-center gap-1.5 transition"
                              >
                                <Clock className="w-3.5 h-3.5" />
                                <span>
                                  {busyMap[`sched_${item.tweet_id}`]
                                    ? "Scheduling..."
                                    : "Queue Random Time"}
                                </span>
                              </button>
                              <button
                                onClick={() => handleApprove(item.tweet_id, false)}
                                disabled={busyMap[`post_${item.tweet_id}`]}
                                className="px-4 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-xs flex items-center gap-1.5 transition shadow-md shadow-emerald-500/10"
                              >
                                <Send className="w-3.5 h-3.5" />
                                <span>
                                  {busyMap[`post_${item.tweet_id}`]
                                    ? "Posting..."
                                    : "Post Now"}
                                </span>
                              </button>
                            </div>
                          </div>
                        </motion.div>
                      );
                    })}
                  </div>
                )}
              </motion.div>
            )}

            {/* TAB 3: ACTIVITY AUDIT HISTORY */}
            {activeTab === "history" && (
              <motion.div
                key="history"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
                className="bi-card rounded-2xl overflow-hidden"
              >
                <div className="p-4 border-b border-white/[0.07] flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-white tracking-tight">
                      Interaction & Content Audit Log
                    </h2>
                    <p className="text-xs font-extralight text-slate-400">
                      Complete record of published posts, scheduled items, and AI-filtered noise
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {["all", "posted", "scheduled", "pending_approval", "skipped"].map(
                      (flt) => (
                        <button
                          key={flt}
                          onClick={() => setHistoryFilter(flt)}
                          className={`px-2.5 py-1 rounded-lg text-[10px] font-mono uppercase transition ${
                            historyFilter === flt
                              ? "bg-sky-500/20 text-sky-300 border border-sky-400/35 font-semibold"
                              : "bg-white/[0.03] text-slate-400 hover:text-white font-light"
                          }`}
                        >
                          {flt.replace("_", " ")}
                        </button>
                      )
                    )}
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-[10px] font-mono font-light uppercase text-slate-400 bg-[#090D18]/60">
                        <th className="py-3 px-4">Status</th>
                        <th className="py-3 px-4">Type</th>
                        <th className="py-3 px-4">Source / Topic</th>
                        <th className="py-3 px-4">Draft / Reason</th>
                        <th className="py-3 px-4 text-right">Time</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.05] text-xs font-light">
                      {filteredHistory.map((item) => {
                        const statusColors: Record<string, string> = {
                          posted: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
                          scheduled: "text-sky-400 bg-sky-500/10 border-sky-500/30",
                          pending_approval:
                            "text-amber-300 bg-amber-500/10 border-amber-500/30",
                          skipped: "text-slate-400 bg-white/[0.03] border-white/10",
                          failed: "text-rose-400 bg-rose-500/10 border-rose-500/30",
                        };
                        const badgeCls =
                          statusColors[item.status] ||
                          "text-slate-400 bg-white/[0.03] border-white/10";

                        return (
                          <tr
                            key={item.tweet_id}
                            className="hover:bg-white/[0.02] transition"
                          >
                            <td className="py-3 px-4">
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold border ${badgeCls}`}
                              >
                                {item.status.replace("_", " ")}
                              </span>
                            </td>
                            <td className="py-3 px-4 font-mono text-[11px] text-slate-400 uppercase">
                              {item.action_type || "reply"}
                            </td>
                            <td className="py-3 px-4 max-w-xs">
                              <span className="font-semibold text-white block">
                                @{item.tweet_author || "user"}
                              </span>
                              <p className="font-extralight text-slate-400 truncate">
                                {item.tweet_text}
                              </p>
                            </td>
                            <td className="py-3 px-4 max-w-sm text-slate-300 truncate">
                              {item.generated_text || item.error_message || "-"}
                            </td>
                            <td className="py-3 px-4 text-right font-mono text-[11px] text-slate-500">
                              {new Date(item.timestamp).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </motion.div>
            )}

            {/* TAB 4: AGENT STUDIO & PERSONA CONFIGURATION */}
            {activeTab === "settings" && (
              <motion.div
                key="settings"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
                className="grid grid-cols-1 lg:grid-cols-12 gap-5"
              >
                {/* Left Column: AI Brain & Persona Voice (7 cols) */}
                <div className="lg:col-span-7 bi-card rounded-2xl p-5 space-y-4">
                  <div className="flex items-center gap-2 border-b border-white/[0.07] pb-3">
                    <Sparkles className="w-4 h-4 text-sky-400" />
                    <h2 className="text-sm font-semibold text-white tracking-tight">
                      AI Engine & Persona Voice Studio
                    </h2>
                  </div>

                  {/* Gemini API Key */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <label className="font-light text-slate-300">
                        Google Gemini API Key
                      </label>
                      <span className="font-mono text-[11px] text-emerald-400">
                        {config?.masked_api_key || "Not Configured"}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="password"
                        value={apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        placeholder="Paste new key from aistudio.google.com"
                        className="flex-1 bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white focus:outline-none focus:border-sky-400"
                      />
                      <button
                        onClick={handleVerifyKey}
                        disabled={busyMap.verifyKey}
                        className="px-4 py-2 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/35 text-xs font-semibold text-sky-300 transition"
                      >
                        {busyMap.verifyKey ? "..." : "Verify Key"}
                      </button>
                    </div>
                  </div>

                  {/* Model Selection */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-light text-slate-300 block">
                      Active Gemini Model (Auto-Failover Enabled)
                    </label>
                    <select
                      value={modelInput}
                      onChange={(e) => setModelInput(e.target.value)}
                      className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white focus:outline-none focus:border-sky-400"
                    >
                      {availableModels.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Target Feed Query */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-light text-slate-300 block">
                      Target Feed / X Search Topic
                    </label>
                    <input
                      type="text"
                      value={queryInput}
                      onChange={(e) => setQueryInput(e.target.value)}
                      placeholder="#elclassico OR buildinpublic"
                      className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-light text-white focus:outline-none focus:border-sky-400"
                    />
                  </div>

                  {/* Persona Voice Prompt */}
                  <div className="space-y-1.5">
                    <label className="text-xs font-light text-slate-300 block">
                      Creator Persona & Anti-Robotic Style Rules
                    </label>
                    <textarea
                      rows={3}
                      value={personaInput}
                      onChange={(e) => setPersonaInput(e.target.value)}
                      placeholder="Casual, sharp, dry humor, lowercase okay, short punchy sentences, zero corporate buzzwords"
                      className="w-full bg-[#090D18] border border-white/10 rounded-xl p-3 text-xs font-light text-white focus:outline-none focus:border-sky-400"
                    />
                  </div>
                </div>

                {/* Right Column: Random Cadence & Active Hours (5 cols) */}
                <div className="lg:col-span-5 bi-card rounded-2xl p-5 flex flex-col justify-between space-y-4">
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 border-b border-white/[0.07] pb-3">
                      <ShieldCheck className="w-4 h-4 text-emerald-400" />
                      <h2 className="text-sm font-semibold text-white tracking-tight">
                        Human Cadence & Random Scheduling
                      </h2>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[11px] font-extralight text-slate-400 block mb-1">
                          Daily Action Cap
                        </label>
                        <input
                          type="number"
                          value={capInput}
                          onChange={(e) => setCapInput(Number(e.target.value))}
                          className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-extralight text-slate-400 block mb-1">
                          Scan Interval (mins)
                        </label>
                        <input
                          type="number"
                          value={intervalInput}
                          onChange={(e) => setIntervalInput(Number(e.target.value))}
                          className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-extralight text-slate-400 block mb-1">
                          Min Random Delay (m)
                        </label>
                        <input
                          type="number"
                          value={minDelayInput}
                          onChange={(e) => setMinDelayInput(Number(e.target.value))}
                          className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-extralight text-slate-400 block mb-1">
                          Max Random Delay (m)
                        </label>
                        <input
                          type="number"
                          value={maxDelayInput}
                          onChange={(e) => setMaxDelayInput(Number(e.target.value))}
                          className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-extralight text-slate-400 block mb-1">
                          Wake Hour (0–23)
                        </label>
                        <input
                          type="number"
                          value={startHourInput}
                          onChange={(e) => setStartHourInput(Number(e.target.value))}
                          className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-extralight text-slate-400 block mb-1">
                          Sleep Hour (0–23)
                        </label>
                        <input
                          type="number"
                          value={endHourInput}
                          onChange={(e) => setEndHourInput(Number(e.target.value))}
                          className="w-full bg-[#090D18] border border-white/10 rounded-xl px-3 py-2 text-xs font-mono font-light text-white"
                        />
                      </div>
                    </div>

                    {/* Autopilot Switch */}
                    <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.07] flex items-center justify-between">
                      <div>
                        <span className="text-xs font-semibold text-white block">
                          Autopilot Random Scheduling
                        </span>
                        <span className="text-[11px] font-extralight text-slate-400">
                          Automatically stagger approved drafts across random timestamps
                        </span>
                      </div>
                      <input
                        type="checkbox"
                        checked={autopilotInput}
                        onChange={(e) => setAutopilotInput(e.target.checked)}
                        className="w-4 h-4 accent-sky-400 cursor-pointer"
                      />
                    </div>
                  </div>

                  <button
                    onClick={() => handleSaveSettings(false)}
                    className="w-full py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs transition shadow-lg shadow-sky-500/15"
                  >
                    Save All Studio Settings
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Collapsible Live Telemetry Console */}
          <AnimatePresence>
            {showLogs && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="bi-card rounded-2xl overflow-hidden"
              >
                <div className="px-4 py-2 border-b border-white/[0.06] flex items-center justify-between bg-[#090D18]/70">
                  <div className="flex items-center gap-2">
                    <Terminal className="w-3.5 h-3.5 text-sky-400" />
                    <span className="text-[11px] font-mono font-light text-slate-300">
                      Live Agent Telemetry
                    </span>
                  </div>
                  <span className="text-[10px] font-mono font-extralight text-slate-500">
                    {status?.selected_model || "gemini-3.8-flash"}
                  </span>
                </div>
                <div className="p-3.5 h-32 overflow-y-auto font-mono font-light text-[11px] space-y-1 bg-[#070A12]/90">
                  {status?.recent_logs?.length ? (
                    status.recent_logs.map((l, i) => (
                      <div
                        key={i}
                        className={
                          l.level === "ERROR"
                            ? "text-rose-400"
                            : l.level === "WARNING"
                            ? "text-amber-300"
                            : "text-slate-300"
                        }
                      >
                        <span className="text-slate-600 mr-2">[{l.timestamp}]</span>
                        {l.message}
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-600">Waiting for telemetry events...</div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
