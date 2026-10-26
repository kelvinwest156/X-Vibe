"use client";

import React, { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BarChart3,
  Inbox,
  History,
  Sliders,
  Play,
  Pause,
  Radar,
  RefreshCw,
  Clock,
  Send,
  X,
  ExternalLink,
  Cookie,
  Terminal,
  Feather,
  Layers,
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
  daily_action_cap: number;
  daily_actions_used: number;
  cooldown_active: boolean;
  cooldown_seconds_remaining: number;
  within_active_hours: boolean;
  scheduled_count: number;
  is_logged_in: boolean;
  linked_username?: string | null;
  pending_approvals_count: number;
  total_processed_count: number;
  selected_model: string;
  recent_logs: SystemLog[];
}

interface AgentConfig {
  masked_api_key?: string | null;
  [k: string]: unknown;
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

const NAV: Array<{ id: NavTab; label: string; icon: typeof BarChart3 }> = [
  { id: "dashboard", label: "Analytics", icon: BarChart3 },
  { id: "queue", label: "Queue", icon: Inbox },
  { id: "history", label: "History", icon: History },
  { id: "settings", label: "Settings", icon: Sliders },
];

const STATUS_STYLE: Record<string, string> = {
  posted: "bg-[#dff6dd] text-[#107c10]",
  scheduled: "bg-[#deecf9] text-[#0f548c]",
  pending_approval: "bg-[#fff4ce] text-[#8a6d00]",
  skipped: "bg-[#f3f2f1] text-[#605e5c]",
  failed: "bg-[#fde7e9] text-[#a4262c]",
};

export default function HomePage() {
  const [tab, setTab] = useState<NavTab>("dashboard");
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [pending, setPending] = useState<TweetItem[]>([]);
  const [history, setHistory] = useState<TweetItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [variantSel, setVariantSel] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [scanning, setScanning] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [cookieOpen, setCookieOpen] = useState(false);
  const [cookieJson, setCookieJson] = useState("");
  const [histFilter, setHistFilter] = useState("all");

  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gemini-3.8-flash");
  const [query, setQuery] = useState("");
  const [persona, setPersona] = useState("");
  const [cap, setCap] = useState(15);
  const [interval, setIntervalMin] = useState(20);
  const [minDelay, setMinDelay] = useState(10);
  const [maxDelay, setMaxDelay] = useState(45);
  const [wake, setWake] = useState(8);
  const [sleep, setSleep] = useState(23);
  const [autopilot, setAutopilot] = useState(false);
  const [models, setModels] = useState<string[]>([
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
  ]);

  const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);
  const notify = useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    setTimeout(() => setToast(null), 3400);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, a, p] = await Promise.all([
        fetch("/api/status"),
        fetch("/api/analytics"),
        fetch("/api/pending"),
      ]);
      if (s.ok) setStatus(await s.json());
      if (a.ok) setAnalytics(await a.json());
      if (p.ok) {
        const list: TweetItem[] = await p.json();
        setPending(list);
        setDrafts((prev) => {
          const next = { ...prev };
          list.forEach((i) => {
            if (next[i.tweet_id] === undefined) next[i.tweet_id] = i.generated_text || "";
          });
          return next;
        });
      }
    } catch {}
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const res = await fetch("/api/config");
      if (!res.ok) return;
      const c = await res.json();
      setConfig(c);
      setModel(c.selected_model || "gemini-3.8-flash");
      setQuery(c.search_query || "");
      setPersona(c.persona_prompt || "");
      setCap(c.daily_action_cap || 15);
      setIntervalMin(c.polling_interval_minutes || 20);
      setMinDelay(c.min_cooldown_minutes || 10);
      setMaxDelay(c.max_cooldown_minutes || 45);
      setWake(c.active_hours_start ?? 8);
      setSleep(c.active_hours_end ?? 23);
      setAutopilot(Boolean(c.auto_pilot_mode));
    } catch {}
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/history?limit=60");
      if (res.ok) setHistory(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    loadConfig();
    refresh();
    loadHistory();
    const t = setInterval(refresh, 6000);
    return () => clearInterval(t);
  }, [loadConfig, refresh, loadHistory]);

  const toggleAgent = async () => {
    if (!status) return;
    const next = !status.is_active;
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: next }),
    });
    if (res.ok) {
      notify(next ? "Agent started" : "Agent paused");
      refresh();
    }
  };

  const saveSettings = async (silent = false) => {
    const payload: Record<string, unknown> = {
      auto_pilot_mode: autopilot,
      polling_interval_minutes: Number(interval) || 20,
      daily_action_cap: Number(cap) || 15,
      min_cooldown_minutes: Number(minDelay) || 10,
      max_cooldown_minutes: Number(maxDelay) || 45,
      active_hours_start: Number(wake) || 0,
      active_hours_end: Number(sleep) || 23,
      search_query: query.trim(),
      persona_prompt: persona.trim(),
      selected_model: model,
    };
    if (apiKey.trim()) payload.api_key = apiKey.trim();
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      setConfig(await res.json());
      setApiKey("");
      if (!silent) notify("Settings saved");
      refresh();
    } else if (!silent) notify("Could not save settings", true);
  };

  const verifyKey = async () => {
    setBusy((p) => ({ ...p, key: true }));
    try {
      const res = await fetch("/api/ai/test-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim() || null }),
      });
      const d = await res.json();
      if (d.success) {
        if (d.models?.length) setModels(d.models.map((m: { id: string }) => m.id));
        setApiKey("");
        notify("API key verified");
        loadConfig();
      } else notify(d.hint || d.error || "Key not accepted", true);
    } finally {
      setBusy((p) => ({ ...p, key: false }));
    }
  };

  const scan = async () => {
    setScanning(true);
    await saveSettings(true);
    try {
      const res = await fetch("/api/trigger-scrape", { method: "POST" });
      const d = await res.json();
      if (!res.ok || d.status === "not_logged_in" || d.status === "missing_api_key") {
        notify(d.message || "Check your X login and API key", true);
      } else {
        notify("Scanning your feed");
        [3000, 8000, 15000, 25000].forEach((ms) => setTimeout(refresh, ms));
      }
    } finally {
      setTimeout(() => setScanning(false), 1500);
    }
  };

  const createOriginal = async (mode: "post" | "thread") => {
    setCreating(mode);
    try {
      const res = await fetch("/api/generate-original", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, custom_topic: query.trim() || null }),
      });
      if (res.ok) {
        const c: TweetItem = await res.json();
        setDrafts((p) => ({ ...p, [c.tweet_id]: c.generated_text || "" }));
        notify(`New ${mode} added to the queue`);
        setTab("queue");
        await refresh();
      } else {
        const e = await res.json();
        notify(e.detail || `Could not create ${mode}`, true);
      }
    } finally {
      setCreating(null);
    }
  };

  const regenerate = async (id: string) => {
    setBusy((p) => ({ ...p, [`r_${id}`]: true }));
    try {
      const res = await fetch(`/api/regenerate/${id}`, { method: "POST" });
      if (res.ok) {
        const d = await res.json();
        setDrafts((p) => ({ ...p, [id]: d.generated_text || "" }));
        notify("New angles ready");
        refresh();
      } else notify("Could not regenerate", true);
    } finally {
      setBusy((p) => ({ ...p, [`r_${id}`]: false }));
    }
  };

  const approve = async (id: string, random: boolean) => {
    const key = `${random ? "s" : "p"}_${id}`;
    setBusy((p) => ({ ...p, [key]: true }));
    try {
      const res = await fetch(`/api/approve/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ custom_text: (drafts[id] || "").trim(), schedule_random: random }),
      });
      const d = await res.json();
      if (res.ok) {
        notify(random ? `Scheduled in about ${d.minutes_from_now} min` : "Posted to X");
        refresh();
        loadHistory();
      } else notify(d.detail || "Action failed", true);
    } finally {
      setBusy((p) => ({ ...p, [key]: false }));
    }
  };

  const skip = async (id: string) => {
    await fetch(`/api/reject/${id}`, { method: "POST" });
    setPending((p) => p.filter((i) => i.tweet_id !== id));
    refresh();
    loadHistory();
  };

  const login = async () => {
    const res = await fetch("/api/browser/launch-login", { method: "POST" });
    const d = await res.json();
    notify(d.message || "Browser opened");
    setTimeout(refresh, 4000);
  };

  const checkSession = async () => {
    const res = await fetch("/api/browser/check-session", { method: "POST" });
    const d = await res.json();
    if (d.is_logged_in) notify(`Connected as ${d.linked_username || "your account"}`);
    else notify("Not logged in", true);
    refresh();
  };

  const exportCookies = async () => {
    const res = await fetch("/api/browser/cookies");
    const d = await res.json();
    setCookieJson(JSON.stringify(d.cookies || [], null, 2));
    notify(`Exported ${d.count || 0} cookies`);
  };

  const importCookies = async () => {
    try {
      const res = await fetch("/api/browser/cookies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies: JSON.parse(cookieJson.trim()) }),
      });
      const d = await res.json();
      if (d.is_logged_in) {
        notify(`Connected as ${d.linked_username || "your account"}`);
        setCookieOpen(false);
        refresh();
      } else notify("Imported, but the session is not signed in", true);
    } catch {
      notify("That is not valid JSON", true);
    }
  };

  const schedLabel = (iso?: string | null) => {
    if (!iso) return "";
    const dt = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    const m = Math.max(1, Math.round((dt.getTime() - Date.now()) / 60000));
    return `${dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (in ${m} min)`;
  };

  const shownHistory = history.filter((h) => histFilter === "all" || h.status === histFilter);
  const pageTitle = NAV.find((n) => n.id === tab)?.label;
  const awake = status?.within_active_hours;

  return (
    <div className="min-h-screen flex">
      {/* Navigation rail */}
      <aside className="w-[208px] shrink-0 bg-[#252423] text-white flex flex-col sticky top-0 h-screen">
        <div className="px-5 h-14 flex items-center gap-2.5 border-b border-white/10">
          <span className="w-6 h-6 bg-[#f2c811] text-[#252423] font-extrabold text-[13px] grid place-items-center rounded-[2px]">
            V
          </span>
          <span className="font-semibold text-[15px] tracking-tight">VibeBot</span>
        </div>

        <nav className="flex-1 py-3">
          {NAV.map((n) => {
            const Icon = n.icon;
            const active = tab === n.id;
            const count =
              n.id === "queue" ? status?.pending_approvals_count : undefined;
            return (
              <button
                key={n.id}
                onClick={() => {
                  setTab(n.id);
                  if (n.id === "history") loadHistory();
                }}
                className={`relative w-full h-10 px-5 flex items-center gap-3 text-[13px] text-left transition-colors ${
                  active
                    ? "bg-white/10 text-white font-semibold"
                    : "text-white/65 hover:bg-white/5 hover:text-white font-normal"
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="rail"
                    className="absolute left-0 top-0 bottom-0 w-[3px] bg-[#f2c811]"
                  />
                )}
                <Icon className="w-4 h-4" strokeWidth={1.75} />
                <span className="flex-1">{n.label}</span>
                {count ? (
                  <span className="min-w-[20px] h-5 px-1.5 rounded-full bg-[#f2c811] text-[#252423] text-[11px] font-bold grid place-items-center">
                    {count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className="p-4 border-t border-white/10 space-y-2.5 text-[12px]">
          <div className="flex items-center gap-2 text-white/70">
            <span
              className={`w-2 h-2 rounded-full ${
                status?.is_active ? (awake ? "bg-[#01b8aa]" : "bg-[#f2c811]") : "bg-white/30"
              }`}
            />
            {status?.is_active ? (awake ? "Running" : "Sleeping") : "Paused"}
          </div>
          <button
            onClick={() => setShowLogs((s) => !s)}
            className="flex items-center gap-2 text-white/60 hover:text-white transition-colors"
          >
            <Terminal className="w-3.5 h-3.5" />
            {showLogs ? "Hide activity log" : "Activity log"}
          </button>
        </div>
      </aside>

      {/* Report area */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 bg-white border-b border-line px-6 flex items-center justify-between gap-4 sticky top-0 z-20">
          <div className="flex items-center gap-4 min-w-0">
            <h1 className="text-[18px] font-semibold text-ink">{pageTitle}</h1>
            <span className="hidden md:inline caption">
              {status ? `${status.daily_actions_used} of ${status.daily_action_cap} actions today` : ""}
              {status && status.scheduled_count ? `, ${status.scheduled_count} scheduled` : ""}
              {status?.cooldown_active
                ? `, cooldown ${Math.ceil((status.cooldown_seconds_remaining || 0) / 60)} min`
                : ""}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {status?.is_logged_in ? (
              <span className="chip gap-1.5 !h-8 !px-3 !text-[12px] !bg-white">
                <i className="w-2 h-2 rounded-full bg-[#01b8aa] inline-block" />
                <span className="font-semibold text-ink">{status.linked_username || "Linked"}</span>
                <button onClick={checkSession} title="Re-check session" className="text-ink-3 hover:text-ink">
                  <RefreshCw className="w-3 h-3" />
                </button>
              </span>
            ) : (
              status && (
                <button onClick={login} className="btn btn-accent">
                  Log in to X
                </button>
              )
            )}
            <button onClick={() => setCookieOpen(true)} className="btn btn-quiet" title="Session cookies">
              <Cookie className="w-4 h-4" />
            </button>
            <button onClick={scan} disabled={scanning} className="btn">
              <Radar className={`w-4 h-4 ${scanning ? "animate-spin" : ""}`} />
              {scanning ? "Scanning" : "Scan feed"}
            </button>
            <button onClick={toggleAgent} className={`btn ${status?.is_active ? "" : "btn-primary"}`}>
              {status?.is_active ? (
                <>
                  <Pause className="w-4 h-4" /> Pause
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" /> Start
                </>
              )}
            </button>
          </div>
        </header>

        <main className="flex-1 p-6 space-y-3 max-w-[1280px] w-full">
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              {tab === "dashboard" && <AnalyticsView data={analytics} />}

              {tab === "queue" && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="caption">
                      Edit a draft, then post it now or let it go out at a random time.
                    </p>
                    <div className="flex gap-2">
                      <button onClick={() => createOriginal("post")} disabled={creating !== null} className="btn">
                        <Feather className="w-4 h-4" />
                        {creating === "post" ? "Writing" : "New post"}
                      </button>
                      <button onClick={() => createOriginal("thread")} disabled={creating !== null} className="btn">
                        <Layers className="w-4 h-4" />
                        {creating === "thread" ? "Writing" : "New thread"}
                      </button>
                    </div>
                  </div>

                  {pending.length === 0 ? (
                    <div className="tile py-16 text-center">
                      <p className="text-[15px] font-semibold text-ink">Nothing waiting for review</p>
                      <p className="caption mt-1">
                        Scan your feed for replies, or write a new post or thread.
                      </p>
                    </div>
                  ) : (
                    pending.map((item, idx) => {
                      let variants: Record<string, string> = {};
                      try {
                        if (item.variants_json) variants = JSON.parse(item.variants_json);
                      } catch {}
                      const keys = Object.keys(variants);
                      const type = item.action_type || "reply";
                      const text = drafts[item.tweet_id] ?? item.generated_text ?? "";
                      const parts = text.split("---").filter((p) => p.trim()).length;
                      const typeColor =
                        type === "thread" ? "#f2c811" : type === "post" ? "#01b8aa" : "#374649";
                      const typeLabel =
                        type === "thread" ? `Thread, ${parts} posts` : type === "post" ? "Original post" : "Reply";

                      return (
                        <motion.article
                          key={item.tweet_id}
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.25, delay: Math.min(idx, 6) * 0.04 }}
                          className="tile relative p-4"
                        >
                          <span
                            className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-[4px]"
                            style={{ background: typeColor }}
                          />
                          <div className="flex items-center justify-between gap-3 mb-2.5">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-[13px] font-semibold text-ink">{typeLabel}</span>
                              <span className="caption">@{item.tweet_author || "user"}</span>
                              {item.tweet_metrics && <span className="chip">{item.tweet_metrics}</span>}
                              {item.status === "scheduled" && (
                                <span className="chip !bg-[#deecf9] !text-[#0f548c] !border-transparent gap-1">
                                  <Clock className="w-3 h-3" /> {schedLabel(item.scheduled_for)}
                                </span>
                              )}
                            </div>
                            {type === "reply" && item.tweet_url && (
                              <a
                                href={item.tweet_url}
                                target="_blank"
                                rel="noreferrer"
                                className="caption inline-flex items-center gap-1 hover:text-ink"
                              >
                                Original <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                          </div>

                          {item.tweet_text && (
                            <p className="text-[13px] font-light text-ink-2 bg-[#faf9f8] border border-line-soft rounded-[2px] px-3 py-2 mb-3 whitespace-pre-line">
                              {item.tweet_text}
                            </p>
                          )}

                          <div className="flex items-center justify-between mb-1.5">
                            <div className="flex items-center gap-1">
                              {keys.map((k) => {
                                const sel = (variantSel[item.tweet_id] || keys[0]) === k;
                                return (
                                  <button
                                    key={k}
                                    onClick={() => {
                                      setVariantSel((p) => ({ ...p, [item.tweet_id]: k }));
                                      setDrafts((p) => ({ ...p, [item.tweet_id]: variants[k] }));
                                    }}
                                    className={`h-7 px-2.5 text-[12px] capitalize rounded-[2px] border transition-colors ${
                                      sel
                                        ? "bg-[#252423] border-[#252423] text-white font-semibold"
                                        : "bg-white border-[#c8c6c4] text-ink-2 hover:bg-[#f3f2f1]"
                                    }`}
                                  >
                                    {k}
                                  </button>
                                );
                              })}
                              {type === "thread" && (
                                <span className="caption ml-2">Split posts with ---</span>
                              )}
                            </div>
                            <button
                              onClick={() => regenerate(item.tweet_id)}
                              disabled={busy[`r_${item.tweet_id}`]}
                              className="btn btn-quiet !h-7 !px-2"
                            >
                              <RefreshCw
                                className={`w-3.5 h-3.5 ${busy[`r_${item.tweet_id}`] ? "animate-spin" : ""}`}
                              />
                              Rewrite
                            </button>
                          </div>

                          <textarea
                            rows={type === "thread" ? 6 : 3}
                            value={text}
                            onChange={(e) => setDrafts((p) => ({ ...p, [item.tweet_id]: e.target.value }))}
                            className="field leading-relaxed resize-y"
                          />

                          <div className="flex items-center justify-between mt-3">
                            <span className="caption">{text.length} characters</span>
                            <div className="flex items-center gap-2">
                              <button onClick={() => skip(item.tweet_id)} className="btn btn-quiet">
                                <X className="w-4 h-4" /> Skip
                              </button>
                              <button
                                onClick={() => approve(item.tweet_id, true)}
                                disabled={busy[`s_${item.tweet_id}`]}
                                className="btn"
                              >
                                <Clock className="w-4 h-4" />
                                {busy[`s_${item.tweet_id}`] ? "Scheduling" : "Schedule randomly"}
                              </button>
                              <button
                                onClick={() => approve(item.tweet_id, false)}
                                disabled={busy[`p_${item.tweet_id}`]}
                                className="btn btn-accent"
                              >
                                <Send className="w-4 h-4" />
                                {busy[`p_${item.tweet_id}`] ? "Posting" : "Post now"}
                              </button>
                            </div>
                          </div>
                        </motion.article>
                      );
                    })
                  )}
                </div>
              )}

              {tab === "history" && (
                <section className="tile overflow-hidden">
                  <div className="px-4 py-3 border-b border-line flex items-center justify-between">
                    <h3 className="tile-title">All activity</h3>
                    <div className="flex gap-1">
                      {["all", "posted", "scheduled", "pending_approval", "skipped", "failed"].map((f) => (
                        <button
                          key={f}
                          onClick={() => setHistFilter(f)}
                          className={`h-7 px-2.5 text-[12px] rounded-[2px] border transition-colors capitalize ${
                            histFilter === f
                              ? "bg-[#252423] border-[#252423] text-white font-semibold"
                              : "bg-white border-[#c8c6c4] text-ink-2 hover:bg-[#f3f2f1]"
                          }`}
                        >
                          {f === "pending_approval" ? "Pending" : f}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[13px] text-left">
                      <thead>
                        <tr className="bg-[#faf9f8] caption border-b border-line">
                          <th className="py-2 px-4 font-medium">Status</th>
                          <th className="py-2 px-4 font-medium">Type</th>
                          <th className="py-2 px-4 font-medium">Source</th>
                          <th className="py-2 px-4 font-medium">Draft or reason</th>
                          <th className="py-2 px-4 font-medium text-right">Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shownHistory.length === 0 && (
                          <tr>
                            <td colSpan={5} className="py-10 text-center caption">
                              Nothing here yet.
                            </td>
                          </tr>
                        )}
                        {shownHistory.map((h) => (
                          <tr key={h.tweet_id} className="border-b border-line-soft last:border-0 hover:bg-[#faf9f8]">
                            <td className="py-2.5 px-4">
                              <span
                                className={`inline-block px-2 py-0.5 rounded-[2px] text-[11px] font-semibold ${
                                  STATUS_STYLE[h.status] || STATUS_STYLE.skipped
                                }`}
                              >
                                {h.status === "pending_approval" ? "pending" : h.status}
                              </span>
                            </td>
                            <td className="py-2.5 px-4 capitalize text-ink-2">{h.action_type || "reply"}</td>
                            <td className="py-2.5 px-4 max-w-[260px]">
                              <span className="font-semibold text-ink block">@{h.tweet_author || "user"}</span>
                              <span className="text-ink-2 font-light block truncate">{h.tweet_text}</span>
                            </td>
                            <td className="py-2.5 px-4 max-w-[320px] text-ink-2 truncate">
                              {h.generated_text || h.error_message || "-"}
                            </td>
                            <td className="py-2.5 px-4 text-right text-ink-3 whitespace-nowrap">
                              {new Date(h.timestamp).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {tab === "settings" && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
                  <section className="tile p-5 space-y-4">
                    <h3 className="tile-title">Voice and topic</h3>
                    <div>
                      <label className="label">Search topic on X</label>
                      <input
                        className="field"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="#elclassico OR buildinpublic"
                      />
                    </div>
                    <div>
                      <label className="label">How you write</label>
                      <textarea
                        rows={3}
                        className="field"
                        value={persona}
                        onChange={(e) => setPersona(e.target.value)}
                        placeholder="Casual, dry humor, short sentences"
                      />
                    </div>
                    <div>
                      <label className="label">
                        Gemini API key{" "}
                        <span className="text-ink-3 font-normal">
                          {config?.masked_api_key ? `(saved: ${config.masked_api_key})` : "(not set)"}
                        </span>
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          className="field"
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="Paste a new key"
                        />
                        <button onClick={verifyKey} disabled={busy.key} className="btn">
                          {busy.key ? "Checking" : "Verify"}
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="label">Model</label>
                      <select className="field" value={model} onChange={(e) => setModel(e.target.value)}>
                        {models.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
                  </section>

                  <section className="tile p-5 space-y-4">
                    <h3 className="tile-title">Timing and limits</h3>
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        ["Daily action limit", cap, setCap],
                        ["Scan every (min)", interval, setIntervalMin],
                        ["Shortest random delay (min)", minDelay, setMinDelay],
                        ["Longest random delay (min)", maxDelay, setMaxDelay],
                        ["Wakes up at (hour)", wake, setWake],
                        ["Goes to sleep at (hour)", sleep, setSleep],
                      ].map(([label, val, set]) => (
                        <div key={label as string}>
                          <label className="label">{label as string}</label>
                          <input
                            type="number"
                            className="field"
                            value={val as number}
                            onChange={(e) => (set as (n: number) => void)(Number(e.target.value))}
                          />
                        </div>
                      ))}
                    </div>
                    <label className="flex items-start gap-3 p-3 border border-line rounded-[2px] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={autopilot}
                        onChange={(e) => setAutopilot(e.target.checked)}
                        className="mt-0.5 w-4 h-4 accent-[#252423]"
                      />
                      <span>
                        <span className="block text-[13px] font-semibold text-ink">Autopilot</span>
                        <span className="caption">
                          Schedule new drafts at random times without waiting for approval.
                        </span>
                      </span>
                    </label>
                    <button onClick={() => saveSettings(false)} className="btn btn-primary w-full justify-center">
                      Save settings
                    </button>
                  </section>
                </div>
              )}
            </motion.div>
          </AnimatePresence>

          <AnimatePresence>
            {showLogs && (
              <motion.section
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="tile overflow-hidden"
              >
                <div className="px-4 py-2 border-b border-line flex justify-between caption">
                  <span className="font-semibold text-ink">Activity log</span>
                  <span>{status?.selected_model}</span>
                </div>
                <div className="p-3 h-36 overflow-y-auto font-mono text-[11px] space-y-0.5 bg-[#faf9f8]">
                  {status?.recent_logs?.length ? (
                    status.recent_logs.map((l, i) => (
                      <div
                        key={i}
                        className={
                          l.level === "ERROR"
                            ? "text-[#a4262c]"
                            : l.level === "WARNING"
                            ? "text-[#8a6d00]"
                            : "text-ink-2"
                        }
                      >
                        <span className="text-ink-3 mr-2">{l.timestamp}</span>
                        {l.message}
                      </div>
                    ))
                  ) : (
                    <span className="text-ink-3">No activity yet.</span>
                  )}
                </div>
              </motion.section>
            )}
          </AnimatePresence>
        </main>
      </div>

      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className={`fixed bottom-5 right-5 z-50 px-4 py-2.5 text-[13px] shadow-lg rounded-[2px] ${
              toast.error ? "bg-[#a4262c] text-white" : "bg-[#252423] text-white"
            }`}
          >
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Cookie dialog */}
      <AnimatePresence>
        {cookieOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4"
            onClick={() => setCookieOpen(false)}
          >
            <motion.div
              initial={{ y: 10 }}
              animate={{ y: 0 }}
              exit={{ y: 10 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-white rounded-[4px] w-full max-w-lg p-5 space-y-3 shadow-2xl"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-[15px] font-semibold text-ink">Session cookies</h3>
                <button onClick={() => setCookieOpen(false)} className="text-ink-3 hover:text-ink">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="caption">
                Export your X session here, then paste it on your Render deployment so it stays logged in.
              </p>
              <textarea
                rows={7}
                className="field font-mono text-[11px]"
                value={cookieJson}
                onChange={(e) => setCookieJson(e.target.value)}
                placeholder='[{"name": "auth_token", ...}]'
              />
              <div className="flex justify-end gap-2">
                <button onClick={exportCookies} className="btn">
                  Export current
                </button>
                <button onClick={importCookies} className="btn btn-primary">
                  Import and verify
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
