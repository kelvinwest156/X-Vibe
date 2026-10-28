"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  Inbox,
  History as HistoryIcon,
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
  Loader2,
  Sparkles,
  ShieldCheck,
  Brain,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  User,
  Heart,
  LogOut,
  Sun,
  Moon,
  Menu,
} from "lucide-react";
import AnalyticsView, { AnalyticsData } from "@/components/AnalyticsView";
import AuthView from "@/components/AuthView";
import ConnectAccountModal from "@/components/ConnectAccountModal";
import { isSupabaseConfigured, subscribeToAuth, signOutUser } from "@/lib/supabase";

const Spin = ({ className = "w-4 h-4" }: { className?: string }) => (
  <Loader2 className={`${className} animate-spin`} aria-label="Loading" />
);

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
  hourly_action_cap?: number;
  hourly_actions_used?: number;
  smart_query_enabled?: boolean;
  warmup_mode?: boolean;
  active_search_query?: string | null;
  learned_examples_count?: number;
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
  media_url?: string | null;
  generated_text?: string | null;
  variants_json?: string | null;
  tweet_metrics?: string | null;
  should_like?: boolean | null;
  urgency_score?: number | null;
  user_edited?: boolean | null;
  status: string;
  scheduled_for?: string | null;
  error_message?: string | null;
  timestamp: string;
}

type NavTab = "dashboard" | "queue" | "history" | "settings";

const NAV: Array<{ id: NavTab; label: string; icon: React.ElementType }> = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "queue", label: "Queue", icon: Inbox },
  { id: "history", label: "History", icon: HistoryIcon },
  { id: "settings", label: "Settings", icon: Sliders },
];

const STATUS_STYLE: Record<string, string> = {
  posted: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  scheduled: "bg-blue-50 text-blue-700 border border-blue-200",
  pending_approval: "bg-amber-50 text-amber-700 border border-amber-200",
  skipped: "bg-slate-100 text-slate-600 border border-slate-200",
  failed: "bg-rose-50 text-rose-700 border border-rose-200",
};

function cleanErrorMessage(raw: string): string {
  if (!raw) return "An unexpected error occurred.";
  const lower = raw.toLowerCase();
  if (raw.includes("429") || lower.includes("resource_exhausted") || lower.includes("quota")) {
    const match = raw.match(/retry in ([\d\w\.]+)/i);
    const delayInfo = match ? ` (resets in ${match[1]})` : "";
    return `Google Gemini Free Tier daily quota limit reached (20 requests/day limit)${delayInfo}. Please switch your API key or model in Settings, or configure DeepSeek API for higher capacity.`;
  }
  if (raw.includes("API_KEY_INVALID") || lower.includes("api key not valid") || lower.includes("invalid api key")) {
    return "Invalid Gemini API key. Please check or replace your key in Settings.";
  }
  if (raw.includes("PERMISSION_DENIED") || raw.includes("403")) {
    return "API permission denied. Ensure Generative Language API is enabled on your Google Cloud project.";
  }
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return "AI request timed out. Please try again or switch model in Settings.";
  }
  const cleaned = raw.replace(/\{.*?\}/g, "").replace(/\n/g, " ").trim();
  return cleaned.length > 0 ? (cleaned.length > 220 ? cleaned.slice(0, 220) + "..." : cleaned) : raw.slice(0, 220);
}

async function extractApiError(res: Response, fallback = "Action failed"): Promise<string> {
  try {
    const text = await res.text();
    try {
      const data = JSON.parse(text);
      if (data && typeof data === "object") {
        const detail = data.detail || data.message || data.error;
        if (typeof detail === "string") return cleanErrorMessage(detail);
        if (typeof detail === "object") return cleanErrorMessage(JSON.stringify(detail));
      }
    } catch {
      if (text && !text.trim().startsWith("<")) {
        return cleanErrorMessage(text);
      }
    }
  } catch {}
  if (res.status === 429) {
    return "API rate limit or daily quota reached (429). Please try again later or switch API keys in Settings.";
  }
  if (res.status === 401 || res.status === 403) {
    return "Authentication error (401/403). Please verify your API key or session.";
  }
  if (res.status >= 500) {
    return `Server encountered an error (${res.status}). Please try again shortly.`;
  }
  return fallback;
}

export default function HomePage() {
  const [tab, setTab] = useState<NavTab>("dashboard");
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [pending, setPending] = useState<TweetItem[]>([]);
  const [history, setHistory] = useState<TweetItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [variantSel, setVariantSel] = useState<Record<string, string>>({});
  const [likeOverrides, setLikeOverrides] = useState<Record<string, boolean>>({});
  const [queueSort, setQueueSort] = useState<"urgency" | "newest">("urgency");
  const [customTopic, setCustomTopic] = useState("");
  const [refreshingBrief, setRefreshingBrief] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [scanning, setScanning] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [cookieOpen, setCookieOpen] = useState(false);
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  const [cookieJson, setCookieJson] = useState("");
  const [histFilter, setHistFilter] = useState("all");
  const [ready, setReady] = useState(false);
  const [histReady, setHistReady] = useState(false);

  // Demo mode toggle allows previewing the full studio even if X session is not linked yet
  const [demoMode, setDemoMode] = useState(false);
  const [tenantId, setTenantId] = useState<string>("default");
  const [userProfile, setUserProfile] = useState<{ email?: string | null; name?: string | null; uid?: string | null } | null>(null);

  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [authToken, setAuthToken] = useState<string>("");
  const [authInitialized, setAuthInitialized] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedToken = localStorage.getItem("xvibebot_auth_token");
      const savedTenant = localStorage.getItem("xvibebot_tenant_id");
      const savedEmail = localStorage.getItem("xvibebot_user_email");
      const savedDemo = localStorage.getItem("xvibebot_demo_mode");

      if (savedDemo === "true") {
        setDemoMode(true);
      }
      if (savedToken) {
        setAuthToken(savedToken);
      }
      if (savedTenant) {
        setTenantId(savedTenant);
      }
      if (savedEmail) {
        setUserProfile({ email: savedEmail, name: savedEmail.split("@")[0] });
      }
      setAuthInitialized(true);

      // Verify token with backend
      if (savedToken) {
        fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${savedToken}` },
        })
          .then((r) => {
            if (r.ok) return r.json();
            if (r.status === 401) {
              localStorage.removeItem("xvibebot_auth_token");
              localStorage.removeItem("xvibebot_tenant_id");
              localStorage.removeItem("xvibebot_user_email");
              setAuthToken("");
              setUserProfile(null);
            }
            return null;
          })
          .then((d) => {
            if (d && d.email) {
              setUserProfile({ email: d.email, name: d.name, uid: d.uid });
              if (d.tenant_id) setTenantId(d.tenant_id);
            }
          })
          .catch(() => {})
          .finally(() => {
            setAuthInitialized(true);
          });
      } else {
        setAuthInitialized(true);
      }

      const savedTheme = localStorage.getItem("xvibebot_theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const initialTheme = savedTheme === "dark" || (!savedTheme && prefersDark) ? "dark" : "light";
      setTheme(initialTheme);
      if (initialTheme === "dark") {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "light" ? "dark" : "light";
      if (typeof document !== "undefined") {
        if (next === "dark") {
          document.documentElement.classList.add("dark");
        } else {
          document.documentElement.classList.remove("dark");
        }
      }
      if (typeof window !== "undefined") {
        localStorage.setItem("xvibebot_theme", next);
      }
      return next;
    });
  }, []);


  const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);
  const toastTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const notify = useCallback((msg: string, error = false) => {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    const cleanMsg = error ? cleanErrorMessage(msg) : msg;
    setToast({ msg: cleanMsg, error });
    const duration = error ? 7500 : 3800;
    toastTimeoutRef.current = setTimeout(() => setToast(null), duration);
  }, []);

  const handleSignOut = useCallback(async () => {
    try {
      if (isSupabaseConfigured) {
        await signOutUser();
      }
      await fetch("/api/auth/signout", { method: "POST" });
    } catch {}
    if (typeof window !== "undefined") {
      localStorage.removeItem("xvibebot_auth_token");
      localStorage.removeItem("xvibebot_tenant_id");
      localStorage.removeItem("xvibebot_user_email");
      localStorage.removeItem("xvibebot_demo_mode");
    }
    setAuthToken("");
    setUserProfile(null);
    setTenantId("default");
    setDemoMode(false);
    notify("Signed out of Creator Studio.");
  }, [notify]);

  const enterDemoMode = useCallback(() => {
    setDemoMode(true);
    if (typeof window !== "undefined") {
      localStorage.setItem("xvibebot_demo_mode", "true");
    }
  }, []);

  const apiFetch = useCallback(
    (url: string, options: RequestInit = {}) => {
      const headers = new Headers(options.headers || {});
      headers.set("X-Tenant-Id", tenantId);
      if (authToken) {
        headers.set("Authorization", `Bearer ${authToken}`);
      }
      return fetch(url, { ...options, headers });
    },
    [tenantId, authToken]
  );

  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gemini-3.8-flash");
  const [query, setQuery] = useState("");
  const [persona, setPersona] = useState("");
  const [cap, setCap] = useState(15);
  const [hourlyCap, setHourlyCap] = useState(6);
  const [smartQuery, setSmartQuery] = useState(true);
  const [warmupMode, setWarmupMode] = useState(false);
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

  const refresh = useCallback(async () => {
    try {
      const [s, a, p] = await Promise.all([
        apiFetch("/api/status"),
        apiFetch("/api/analytics"),
        apiFetch("/api/pending"),
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
    } catch {
    } finally {
      setReady(true);
    }
  }, [apiFetch]);

  const loadConfig = useCallback(async () => {
    try {
      const res = await apiFetch("/api/config");
      if (!res.ok) return;
      const c = await res.json();
      setConfig(c);
      setModel(c.selected_model || "gemini-3.8-flash");
      setQuery(c.search_query || "");
      setPersona(c.persona_prompt || "");
      setCap(c.daily_action_cap || 15);
      setHourlyCap(c.hourly_action_cap || 6);
      setSmartQuery(c.smart_query_enabled ?? true);
      setWarmupMode(Boolean(c.warmup_mode));
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
      const res = await apiFetch("/api/history?limit=60");
      if (res.ok) setHistory(await res.json());
    } catch {
    } finally {
      setHistReady(true);
    }
  }, [apiFetch]);

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
    setBusy((p) => ({ ...p, toggle: true }));
    try {
      const res = await apiFetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: next }),
      });
      if (res.ok) {
        notify(next ? "Studio agent active" : "Studio agent paused");
        await refresh();
      } else {
        const err = await extractApiError(res, "Could not toggle agent");
        notify(err, true);
      }
    } catch (err: any) {
      notify(err?.message || "Connection error toggling agent", true);
    } finally {
      setBusy((p) => ({ ...p, toggle: false }));
    }
  };

  const saveSettings = async (silent = false) => {
    if (!silent) setBusy((p) => ({ ...p, save: true }));
    try {
      const payload: Record<string, unknown> = {
        auto_pilot_mode: autopilot,
        polling_interval_minutes: Number(interval) || 20,
        daily_action_cap: Number(cap) || 15,
        hourly_action_cap: Number(hourlyCap) || 6,
        smart_query_enabled: smartQuery,
        warmup_mode: warmupMode,
        min_cooldown_minutes: Number(minDelay) || 10,
        max_cooldown_minutes: Number(maxDelay) || 45,
        active_hours_start: Number(wake) || 0,
        active_hours_end: Number(sleep) || 23,
        search_query: query.trim(),
        persona_prompt: persona.trim(),
        selected_model: model,
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      const res = await apiFetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setConfig(await res.json());
        setApiKey("");
        if (!silent) notify("Studio settings saved");
        refresh();
      } else if (!silent) {
        const err = await extractApiError(res, "Could not save settings");
        notify(err, true);
      }
    } catch (err: any) {
      if (!silent) notify(err?.message || "Failed to save settings", true);
    } finally {
      if (!silent) setBusy((p) => ({ ...p, save: false }));
    }
  };

  const verifyKey = async () => {
    setBusy((p) => ({ ...p, key: true }));
    try {
      const res = await apiFetch("/api/ai/test-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim() || null }),
      });
      if (res.ok) {
        const d = await res.json();
        if (d.success) {
          if (d.models?.length) setModels(d.models.map((m: { id: string }) => m.id));
          setApiKey("");
          notify("Gemini API key verified successfully");
          loadConfig();
        } else {
          notify(d.hint || d.error || "Key not accepted", true);
        }
      } else {
        const err = await extractApiError(res, "API key verification failed");
        notify(err, true);
      }
    } catch (err: any) {
      notify(err?.message || "Failed to verify API key", true);
    } finally {
      setBusy((p) => ({ ...p, key: false }));
    }
  };

  const scan = async () => {
    setScanning(true);
    try {
      await saveSettings(true);
      const res = await apiFetch("/api/trigger-scrape", { method: "POST" });
      if (res.ok) {
        const d = await res.json();
        if (d.status === "not_logged_in" || d.status === "missing_api_key") {
          notify(d.message || "Please check your X connection and API key", true);
        } else {
          notify("Scanning your feed for high-resonance posts");
          [3000, 8000, 15000, 25000].forEach((ms) => setTimeout(refresh, ms));
        }
      } else {
        const err = await extractApiError(res, "Feed scan failed");
        notify(err, true);
      }
    } catch (err: any) {
      notify(err?.message || "Failed to trigger feed scan", true);
    } finally {
      setTimeout(() => setScanning(false), 1500);
    }
  };

  const refreshBrief = async () => {
    setRefreshingBrief(true);
    try {
      const res = await apiFetch("/api/analytics?refresh_brief=true");
      if (res.ok) {
        setAnalytics(await res.json());
        notify("AI Strategy Brief refreshed");
      } else {
        const err = await extractApiError(res, "Could not refresh brief");
        notify(err, true);
      }
    } catch (err: any) {
      notify(err?.message || "Could not refresh strategy brief", true);
    } finally {
      setRefreshingBrief(false);
    }
  };

  const applySuggestedQuery = async (suggested: string) => {
    setQuery(suggested);
    try {
      const res = await apiFetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ search_query: suggested }),
      });
      if (res.ok) {
        setConfig(await res.json());
        notify(`Applied search pulse: "${suggested}"`);
        refresh();
      } else {
        const err = await extractApiError(res, "Could not apply query");
        notify(err, true);
      }
    } catch (err: any) {
      notify(err?.message || "Could not apply search query", true);
    }
  };

  const createOriginal = async (mode: "auto" | "post" | "thread") => {
    setCreating(mode);
    try {
      const topicSeed = customTopic.trim() || query.trim() || null;
      const res = await apiFetch("/api/generate-original", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, custom_topic: topicSeed }),
      });
      if (res.ok) {
        const c = await res.json();
        setCustomTopic("");
        notify(`New ${c.action_type || mode} added to the drafting queue`);
        setTab("queue");
        await refresh();
      } else {
        const errMsg = await extractApiError(res, `Could not create ${mode}`);
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message || `Could not create ${mode}`, true);
    } finally {
      setCreating(null);
    }
  };

  const regenerate = async (id: string) => {
    setBusy((p) => ({ ...p, [`r_${id}`]: true }));
    try {
      const res = await apiFetch(`/api/regenerate/${id}`, { method: "POST" });
      if (res.ok) {
        const d = await res.json();
        setDrafts((p) => ({ ...p, [id]: d.generated_text || "" }));
        notify("New creative angles generated");
        refresh();
      } else {
        const errMsg = await extractApiError(res, "Could not rewrite draft");
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message || "Failed to regenerate draft", true);
    } finally {
      setBusy((p) => ({ ...p, [`r_${id}`]: false }));
    }
  };

  const approve = async (id: string, random: boolean, defaultLike?: boolean) => {
    const key = `${random ? "s" : "p"}_${id}`;
    setBusy((p) => ({ ...p, [key]: true }));
    const shouldLikeVal =
      likeOverrides[id] !== undefined ? likeOverrides[id] : Boolean(defaultLike);
    try {
      const fallbackText = pending.find((p) => p.tweet_id === id)?.generated_text || "";
      const textToSend = (drafts[id] !== undefined ? drafts[id] : fallbackText).trim();
      const res = await apiFetch(`/api/approve/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          custom_text: textToSend,
          schedule_random: random,
          should_like: shouldLikeVal,
        }),
      });
      if (res.ok) {
        const d = await res.json();
        notify(random ? `Scheduled in about ${d.minutes_from_now} min` : "Posted to X");
        refresh();
        loadHistory();
      } else {
        const errMsg = await extractApiError(res, "Action failed");
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message || "Publish action failed", true);
    } finally {
      setBusy((p) => ({ ...p, [key]: false }));
    }
  };

  const skip = async (id: string) => {
    try {
      const res = await apiFetch(`/api/reject/${id}`, { method: "POST" });
      if (!res.ok) {
        const errMsg = await extractApiError(res, "Could not reject draft");
        notify(errMsg, true);
      } else {
        setPending((p) => p.filter((i) => i.tweet_id !== id));
        notify("Post skipped & added to anti-pattern memory");
        refresh();
        loadHistory();
      }
    } catch (err: any) {
      notify(err?.message || "Could not skip post", true);
    }
  };

  const login = () => {
    setConnectModalOpen(true);
  };

  const checkSession = async () => {
    setBusy((p) => ({ ...p, session: true }));
    try {
      const res = await apiFetch("/api/browser/check-session", { method: "POST" });
      if (res.ok) {
        const d = await res.json();
        if (d.is_logged_in) notify(`Connected as ${d.linked_username || "your account"}`);
        else notify("Not logged in to X", true);
        refresh();
      } else {
        const errMsg = await extractApiError(res, "Failed to check session");
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message || "Error checking session", true);
    } finally {
      setBusy((p) => ({ ...p, session: false }));
    }
  };

  const exportCookies = async () => {
    setBusy((p) => ({ ...p, cexp: true }));
    try {
      const res = await apiFetch("/api/browser/cookies");
      if (res.ok) {
        const d = await res.json();
        setCookieJson(JSON.stringify(d.cookies || [], null, 2));
        notify(`Exported ${d.count || 0} cookies`);
      } else {
        const errMsg = await extractApiError(res, "Failed to export cookies");
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message || "Cookie export failed", true);
    } finally {
      setBusy((p) => ({ ...p, cexp: false }));
    }
  };

  const importCookies = async () => {
    setBusy((p) => ({ ...p, cimp: true }));
    try {
      const parsedCookies = JSON.parse(cookieJson.trim());
      const res = await apiFetch("/api/browser/cookies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies: parsedCookies }),
      });
      if (res.ok) {
        const d = await res.json();
        if (d.is_logged_in) {
          notify(`Connected as ${d.linked_username || "your account"}`);
          setCookieOpen(false);
          refresh();
        } else notify("Imported, but the session is not signed in", true);
      } else {
        const errMsg = await extractApiError(res, "Failed to import cookies");
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message?.includes("JSON") ? "Invalid cookie JSON format" : (err?.message || "Failed to import cookies"), true);
    } finally {
      setBusy((p) => ({ ...p, cimp: false }));
    }
  };

  const schedLabel = (iso?: string | null) => {
    if (!iso) return "";
    const dt = new Date(iso.endsWith("Z") ? iso : iso + "Z");
    const m = Math.max(1, Math.round((dt.getTime() - Date.now()) / 60000));
    return `${dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (in ${m}m)`;
  };

  const shownHistory = history.filter((h) => histFilter === "all" || h.status === histFilter);
  const awake = status?.within_active_hours;
  const isUserAuthenticated = Boolean(userProfile?.email || authToken || demoMode);

  // Smooth loading splash while initializing stored authentication
  if (!authInitialized && !isUserAuthenticated) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#121212] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-slate-500 dark:text-[#A3A3A3]">
          <Loader2 className="w-6 h-6 animate-spin text-neutral-900 dark:text-white" />
          <span className="text-xs font-medium">Loading Creator Studio...</span>
        </div>
      </div>
    );
  }

  // If user is not authenticated and hasn't toggled demo mode, show AuthView!
  if (!isUserAuthenticated) {
    return (
      <AuthView
        theme={theme}
        onToggleTheme={toggleTheme}
        onLoginWithX={() => {
          enterDemoMode();
          setConnectModalOpen(true);
        }}
        onExploreDemo={enterDemoMode}
        busyLogin={busy.login}
        onAuthenticated={(user, token) => {
          const tId = user.uid || (user as any).tenant_id || "default";
          setTenantId(tId);
          setAuthToken(token);
          setUserProfile({ email: user.email || undefined, name: user.displayName || user.email?.split("@")[0], uid: user.uid });
          if (typeof window !== "undefined") {
            localStorage.setItem("xvibebot_auth_token", token);
            localStorage.setItem("xvibebot_tenant_id", tId);
            if (user.email) localStorage.setItem("xvibebot_user_email", user.email);
            localStorage.removeItem("xvibebot_demo_mode");
          }
          refresh();
        }}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#121212] text-slate-900 dark:text-[#F3F3F3] flex flex-col selection:bg-neutral-900 selection:text-white transition-colors duration-200">
      {/* Top Modern Studio Rail / Navigation Header */}
      <header className="sticky top-0 z-30 bg-white/95 dark:bg-[#181818]/95 backdrop-blur-md border-b border-slate-200/80 dark:border-[#262626] px-4 sm:px-6 py-2.5 sm:py-3 transition-colors duration-200">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-3 sm:gap-4">
          {/* Brand & Identity */}
          <div className="flex items-center gap-2.5 sm:gap-3 shrink-0">
            <div className="w-8 h-8 rounded-lg bg-black text-white flex items-center justify-center font-bold text-sm shadow-xs shrink-0">
              <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
                <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-[14.5px] text-slate-900 dark:text-white tracking-tight">
                  X-VibeBot
                </span>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-[#222222] text-slate-600 dark:text-[#A3A3A3] border border-slate-200/80 dark:border-[#2E2E2E]">
                  Studio
                </span>
              </div>
            </div>
          </div>

          {/* Clean Pill-Based Navigation Tabs (Desktop Rail) */}
          <nav className="hidden md:flex items-center p-1 bg-slate-100 dark:bg-[#202020] rounded-xl border border-slate-200/60 dark:border-[#2E2E2E] shadow-xs">
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
                  className={`relative px-3.5 py-1.5 rounded-lg text-[13px] font-medium transition-all flex items-center gap-2 ${
                    active
                      ? "text-slate-900 dark:text-white shadow-xs font-semibold"
                      : "text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white"
                  }`}
                >
                  {active && (
                    <motion.div
                      layoutId="navPill"
                      className="absolute inset-0 bg-white dark:bg-[#141414] rounded-lg border border-slate-200/70 dark:border-[#2E2E2E]"
                      transition={{ type: "spring", stiffness: 450, damping: 35 }}
                    />
                  )}
                  <Icon className="w-4 h-4 relative z-10" />
                  <span className="relative z-10">{n.label}</span>
                  {Boolean(count && count > 0) && (
                    <span className="relative z-10 min-w-[18px] h-[18px] px-1 rounded-full bg-slate-900 dark:bg-white text-white dark:text-black text-[10.5px] font-semibold flex items-center justify-center">
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Right Action Rail */}
          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
            {/* Theme Toggle Button (Sun / Moon) */}
            <button
              type="button"
              onClick={toggleTheme}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-[#222222] transition-colors"
              title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              aria-label="Toggle theme"
            >
              {theme === "light" ? (
                <Moon className="w-4 h-4" />
              ) : (
                <Sun className="w-4 h-4 text-amber-400" />
              )}
            </button>

            {/* Multi-Tenant / User Profile pill */}
            {userProfile ? (
              <div className="flex items-center gap-2 px-2.5 h-8 rounded-lg bg-slate-100 dark:bg-[#202020] border border-slate-200/80 dark:border-[#2E2E2E] text-xs text-slate-700 dark:text-[#D4D4D4] shadow-2xs">
                <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                <span className="hidden sm:inline font-medium max-w-[120px] truncate" title={userProfile.email || tenantId}>
                  {userProfile.name || userProfile.email || "Creator"}
                </span>
              </div>
            ) : (
              <div className="hidden sm:flex items-center gap-1.5 px-2.5 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-600 dark:text-amber-400 font-medium">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Demo Mode</span>
              </div>
            )}

            {/* Dedicated Prominent Log Out Button (Always Available) */}
            <button
              type="button"
              onClick={handleSignOut}
              title="Log out of Creator Studio"
              className="flex items-center gap-1.5 px-2.5 h-8 rounded-lg text-xs font-medium text-slate-600 dark:text-[#A3A3A3] hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/20 border border-slate-200 dark:border-[#2E2E2E] transition-all cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5 text-rose-500" />
              <span className="hidden sm:inline">Log Out</span>
            </button>

            {/* Account pill */}
            {status?.is_logged_in ? (
              <button
                type="button"
                onClick={() => setConnectModalOpen(true)}
                title="Manage connected X account"
                className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white dark:bg-[#202020] border border-slate-200 dark:border-[#2E2E2E] text-xs shadow-2xs hover:border-slate-300 dark:hover:border-[#383838] transition-colors cursor-pointer text-left"
              >
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="font-semibold text-slate-800 dark:text-[#E5E5E5] max-w-[80px] sm:max-w-[120px] truncate">
                  {status.linked_username || "Linked"}
                </span>
              </button>
            ) : (
              <button
                onClick={login}
                disabled={busy.login}
                className="btn btn-primary !h-8 !px-3 text-xs hidden md:inline-flex"
              >
                {busy.login ? <Spin /> : <User className="w-3.5 h-3.5" />}
                <span>{busy.login ? "Connecting..." : "Connect X Account"}</span>
              </button>
            )}

            {/* Session cookies modal trigger */}
            <button
              onClick={() => setCookieOpen(true)}
              className="btn btn-quiet !h-8 !w-8 !p-0 hidden md:inline-flex"
              title="Session cookies"
            >
              <Cookie className="w-4 h-4" />
            </button>

            {/* Scan feed */}
            <button
              onClick={scan}
              disabled={scanning}
              className="btn !h-8 !px-3 text-xs hidden md:inline-flex"
              title="Scan feed for relevant niche tweets"
            >
              {scanning ? <Spin /> : <Radar className="w-3.5 h-3.5" />}
              <span className="hidden sm:inline">{scanning ? "Scanning..." : "Scan Feed"}</span>
            </button>

            {/* Agent Play/Pause Toggle */}
            <button
              onClick={toggleAgent}
              disabled={busy.toggle || !status}
              className={`btn !h-8 !px-3 text-xs transition-all hidden md:inline-flex ${
                status?.is_active
                  ? "bg-slate-100 dark:bg-[#222222] hover:bg-slate-200 dark:hover:bg-[#2A2A2A] text-slate-800 dark:text-[#E5E5E5] border-slate-200 dark:border-[#2E2E2E]"
                  : "btn-primary"
              }`}
            >
              {busy.toggle ? (
                <>
                  <Spin /> <span className="hidden sm:inline">Updating...</span>
                </>
              ) : status?.is_active ? (
                <>
                  <Pause className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Pause</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Start Agent</span>
                </>
              )}
            </button>

            {/* Terminal activity stream toggle */}
            <button
              onClick={() => setShowLogs((s) => !s)}
              className={`btn btn-quiet !h-8 !w-8 !p-0 transition-colors hidden md:inline-flex ${
                showLogs ? "bg-slate-200 dark:bg-[#2A2A2A] text-slate-900 dark:text-white" : ""
              }`}
              title="Toggle Live Activity Log"
            >
              <Terminal className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Studio Viewport */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-5 sm:p-6 pb-28 md:pb-8 space-y-5">
        {/* Mobile action strip */}
        <div className="md:hidden grid grid-cols-3 gap-2">
          {status?.is_logged_in ? (
            <button type="button" onClick={() => setConnectModalOpen(true)} className="btn !h-10 text-xs justify-center">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="truncate">{status.linked_username || "Linked"}</span>
            </button>
          ) : (
            <button onClick={login} disabled={busy.login} className="btn btn-primary !h-10 text-xs justify-center">
              {busy.login ? <Spin /> : <User className="w-3.5 h-3.5" />}
              <span>Connect</span>
            </button>
          )}
          <button onClick={scan} disabled={scanning} className="btn !h-10 text-xs justify-center">
            {scanning ? <Spin /> : <Radar className="w-3.5 h-3.5" />}
            <span>{scanning ? "Scanning" : "Scan"}</span>
          </button>
          <button
            onClick={toggleAgent}
            disabled={busy.toggle || !status}
            className={`btn !h-10 text-xs justify-center ${status?.is_active ? "" : "btn-primary"}`}
          >
            {busy.toggle ? <Spin /> : status?.is_active ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            <span>{status?.is_active ? "Pause" : "Start"}</span>
          </button>
        </div>

        {/* Status Strip if Paused or Sleeping */}
        {status && !status.is_active && (
          <div className="bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200/70 dark:border-amber-900/50 rounded-xl px-4 py-3 text-xs text-amber-800 dark:text-amber-200 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-amber-600 shrink-0" />
              <span>
                <strong>Studio Agent Paused:</strong> Background scanning and auto-reply scheduling are paused.
              </span>
            </div>
            <button
              onClick={toggleAgent}
              className="text-amber-900 dark:text-amber-100 font-semibold underline hover:text-amber-700 text-left"
            >
              Resume Agent
            </button>
          </div>
        )}

        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            {/* Dashboard View */}
            {tab === "dashboard" && (
              <AnalyticsView
                data={analytics}
                onApplySuggestedQuery={applySuggestedQuery}
                onRefreshBrief={refreshBrief}
                refreshingBrief={refreshingBrief}
              />
            )}

            {/* Queue View - Focus on Drafting Craft */}
            {tab === "queue" && (
              <div className="space-y-4">
                {/* Queue Control Toolbar */}
                <div className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl p-3 sm:p-3.5 shadow-xs flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <input
                      className="field !h-9 flex-1 sm:max-w-[320px]"
                      value={customTopic}
                      onChange={(e) => setCustomTopic(e.target.value)}
                      placeholder={`Target angle / topic (default: ${query || "your niche"})`}
                    />
                    <button
                      onClick={() =>
                        setQueueSort((s) => (s === "urgency" ? "newest" : "urgency"))
                      }
                      className="btn !h-9 !px-3 text-xs shrink-0"
                      title="Toggle Queue Sort Order"
                    >
                      Sort: {queueSort === "urgency" ? "Urgency" : "Newest"}
                    </button>
                  </div>

                  <div className="grid grid-cols-3 sm:flex items-center gap-2">
                    <button
                      onClick={() => createOriginal("auto")}
                      disabled={creating !== null}
                      className="btn btn-primary !h-9 !px-2.5 sm:!px-3.5 text-xs truncate"
                      title="Let Gemini pick the best post or thread format"
                    >
                      {creating === "auto" ? <Spin /> : <Sparkles className="w-3.5 h-3.5" />}
                      <span>{creating === "auto" ? "Synthesizing..." : "Smart Auto"}</span>
                    </button>
                    <button
                      onClick={() => createOriginal("post")}
                      disabled={creating !== null}
                      className="btn !h-9 !px-2.5 sm:!px-3 text-xs truncate"
                    >
                      {creating === "post" ? <Spin /> : <Feather className="w-3.5 h-3.5" />}
                      <span>{creating === "post" ? "Drafting..." : "Post"}</span>
                    </button>
                    <button
                      onClick={() => createOriginal("thread")}
                      disabled={creating !== null}
                      className="btn !h-9 !px-2.5 sm:!px-3 text-xs truncate"
                    >
                      {creating === "thread" ? <Spin /> : <Layers className="w-3.5 h-3.5" />}
                      <span>{creating === "thread" ? "Drafting..." : "Thread"}</span>
                    </button>
                  </div>
                </div>

                {/* Queue Cards or Empty State */}
                {!ready ? (
                  <div className="bg-white dark:bg-[#181818] border border-slate-200 dark:border-[#262626] rounded-xl py-20 flex flex-col items-center justify-center gap-3 text-slate-400">
                    <Spin className="w-6 h-6 text-slate-600 dark:text-[#A3A3A3]" />
                    <span className="text-xs font-medium">Loading drafting queue...</span>
                  </div>
                ) : pending.length === 0 ? (
                  <div className="bg-white dark:bg-[#181818] border border-slate-200 dark:border-[#262626] rounded-xl py-16 sm:py-20 text-center space-y-2 p-6">
                    <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-[#222222] text-slate-400 dark:text-[#737373] flex items-center justify-center mx-auto mb-3">
                      <Inbox className="w-6 h-6" />
                    </div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                      Drafting queue is empty
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-[#A3A3A3] max-w-md mx-auto leading-relaxed">
                      Scan your feed to discover live niche conversations, or trigger{" "}
                      <strong className="text-slate-700 dark:text-[#E5E5E5]">Smart Auto-Draft</strong> above to let
                      Gemini compose an original post or multi-part thread.
                    </p>
                    <div className="pt-2">
                      <button onClick={scan} disabled={scanning} className="btn btn-primary text-xs">
                        {scanning ? <Spin /> : <Radar className="w-3.5 h-3.5" />}
                        <span>Scan Feed Now</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {[...pending]
                      .sort((a, b) =>
                        queueSort === "urgency"
                          ? (b.urgency_score ?? 5) - (a.urgency_score ?? 5)
                          : new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
                      )
                      .map((item, idx) => {
                        let variants: Record<string, string> = {};
                        try {
                          if (item.variants_json) variants = JSON.parse(item.variants_json);
                        } catch {}
                        const keys = Object.keys(variants);
                        const type = item.action_type || "reply";
                        const text = drafts[item.tweet_id] ?? item.generated_text ?? "";
                        const isEdited =
                          text.trim() !== "" &&
                          text.trim() !== (item.generated_text || "").trim();
                        const effectiveLike =
                          likeOverrides[item.tweet_id] !== undefined
                            ? likeOverrides[item.tweet_id]
                            : Boolean(item.should_like);
                        const parts = text.split("---").filter((p) => p.trim()).length;

                        // Type colors
                        const typeBadgeStyle =
                          type === "thread"
                            ? "bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-800"
                            : type === "post"
                            ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800"
                            : "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800";

                        const typeLabel =
                          type === "thread"
                            ? `Thread · ${parts} posts`
                            : type === "post"
                            ? "Original Post"
                            : "Reply";
                        const urgency = item.urgency_score ?? 5;

                        return (
                          <motion.article
                            key={item.tweet_id}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.2, delay: Math.min(idx, 5) * 0.03 }}
                            className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl p-4 sm:p-5 shadow-xs transition-shadow hover:shadow-sm space-y-4 relative overflow-hidden"
                          >
                            {/* Accent stripe */}
                            <div
                              className={`absolute left-0 top-0 bottom-0 w-1 ${
                                type === "thread"
                                  ? "bg-[#EA580C]"
                                  : type === "post"
                                  ? "bg-emerald-500"
                                  : "bg-blue-500"
                              }`}
                            />

                            {/* Header row */}
                            <div className="flex items-center justify-between gap-3 flex-wrap">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span
                                  className={`text-[11.5px] font-semibold px-2.5 py-0.5 rounded-md border ${typeBadgeStyle}`}
                                >
                                  {typeLabel}
                                </span>
                                <span className="text-xs font-medium text-slate-700 dark:text-[#D4D4D4]">
                                  @{item.tweet_author || "creator"}
                                </span>
                                {item.tweet_metrics && (
                                  <span className="hidden sm:inline text-[11px] text-slate-500 dark:text-[#A3A3A3] bg-slate-100 dark:bg-[#222222] px-2 py-0.5 rounded-md border border-slate-200/60 dark:border-[#2E2E2E]">
                                    {item.tweet_metrics}
                                  </span>
                                )}
                                <span
                                  className={`text-[11px] font-medium px-2 py-0.5 rounded-md ${
                                    urgency >= 7
                                      ? "bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
                                      : "bg-slate-100 dark:bg-[#222222] text-slate-600 dark:text-[#D4D4D4]"
                                  }`}
                                >
                                  Urgency {urgency}/10
                                </span>

                                {/* Auto-Like Toggle */}
                                {type === "reply" && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setLikeOverrides((p) => ({
                                        ...p,
                                        [item.tweet_id]: !effectiveLike,
                                      }))
                                    }
                                    className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-md border transition-colors ${
                                      effectiveLike
                                        ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800 font-semibold"
                                        : "bg-slate-50 dark:bg-[#222222]/60 text-slate-500 dark:text-[#A3A3A3] border-slate-200 dark:border-[#2E2E2E] hover:text-slate-800 dark:hover:text-[#E5E5E5]"
                                    }`}
                                  >
                                    <Heart
                                      className={`w-3 h-3 ${
                                        effectiveLike ? "fill-emerald-600 text-emerald-600 dark:fill-emerald-400 dark:text-emerald-400" : ""
                                      }`}
                                    />
                                    <span>{effectiveLike ? "Auto-Like ON" : "Auto-Like OFF"}</span>
                                  </button>
                                )}

                                {item.media_url && (
                                  <span className="hidden sm:inline text-[11px] font-medium px-2 py-0.5 rounded-md bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                                    Vision Analyzed
                                  </span>
                                )}

                                {item.status === "scheduled" && (
                                  <span className="text-[11px] font-medium px-2 py-0.5 rounded-md bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 flex items-center gap-1">
                                    <Clock className="w-3 h-3" /> {schedLabel(item.scheduled_for)}
                                  </span>
                                )}
                              </div>

                              {type === "reply" && item.tweet_url && (
                                <a
                                  href={item.tweet_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-xs text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white inline-flex items-center gap-1 transition-colors"
                                >
                                  <span>View Original</span>
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              )}
                            </div>

                            {/* Source Tweet Context Box */}
                            {item.tweet_text && (
                              <div className="bg-slate-50 dark:bg-[#222222]/60 border border-slate-200/70 dark:border-[#2E2E2E]/60 rounded-lg p-3 sm:p-3.5 flex items-start gap-3.5">
                                <div className="flex-1 min-w-0">
                                  <p className="text-xs font-normal text-slate-700 dark:text-[#D4D4D4] leading-relaxed whitespace-pre-line">
                                    {item.tweet_text}
                                  </p>
                                  {item.error_message && (
                                    <p className="text-[11.5px] text-blue-700 dark:text-blue-300 mt-2 pt-2 border-t border-slate-200/60 dark:border-[#2E2E2E]/60 flex items-center gap-1.5">
                                      <Sparkles className="w-3 h-3 text-blue-600 dark:text-blue-400 shrink-0" />
                                      <span>
                                        <strong className="font-semibold">Context Insight:</strong>{" "}
                                        {item.error_message}
                                      </span>
                                    </p>
                                  )}
                                </div>
                                {item.media_url && (
                                  <a
                                    href={item.media_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="shrink-0 block"
                                    title="Attached tweet image analyzed by Gemini Vision"
                                  >
                                    <img
                                      src={item.media_url}
                                      alt="Tweet media"
                                      className="w-16 h-16 object-cover rounded-md border border-slate-200 dark:border-[#2E2E2E] hover:opacity-90 transition-opacity"
                                    />
                                  </a>
                                )}
                              </div>
                            )}

                            {/* Creative Angle Chips & Rewrite */}
                            <div className="flex items-center justify-between flex-wrap gap-2 pt-1">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                {keys.map((k) => {
                                  const sel = (variantSel[item.tweet_id] || keys[0]) === k;
                                  return (
                                    <button
                                      key={k}
                                      type="button"
                                      onClick={() => {
                                        setVariantSel((p) => ({ ...p, [item.tweet_id]: k }));
                                        setDrafts((p) => ({ ...p, [item.tweet_id]: variants[k] }));
                                      }}
                                      className={`h-7 px-3 rounded-md text-[12px] font-medium transition-all ${
                                        sel
                                          ? "bg-slate-900 dark:bg-white text-white dark:text-black shadow-xs font-semibold"
                                          : "bg-slate-100 dark:bg-[#222222] hover:bg-slate-200 dark:hover:bg-[#2C2C2C] text-slate-700 dark:text-[#D4D4D4] border border-slate-200/60 dark:border-[#2E2E2E]"
                                      }`}
                                    >
                                      {k}
                                    </button>
                                  );
                                })}
                                {type === "thread" && (
                                  <span className="text-[11px] text-slate-400 dark:text-[#737373] ml-1">
                                    (Posts separated with ---)
                                  </span>
                                )}
                              </div>

                              <button
                                onClick={() => regenerate(item.tweet_id)}
                                disabled={busy[`r_${item.tweet_id}`]}
                                className="text-xs text-slate-500 dark:text-[#A3A3A3] hover:text-slate-900 dark:hover:text-white font-medium inline-flex items-center gap-1 px-2.5 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-[#222222] transition-colors"
                              >
                                {busy[`r_${item.tweet_id}`] ? (
                                  <Spin className="w-3.5 h-3.5" />
                                ) : (
                                  <RefreshCw className="w-3.5 h-3.5" />
                                )}
                                <span>{busy[`r_${item.tweet_id}`] ? "Rewriting..." : "Rewrite"}</span>
                              </button>
                            </div>

                            {/* Live Editable Textarea */}
                            <div>
                              <textarea
                                rows={type === "thread" ? 6 : 3}
                                value={text}
                                onChange={(e) =>
                                  setDrafts((p) => ({ ...p, [item.tweet_id]: e.target.value }))
                                }
                                className={`field leading-relaxed resize-y ${
                                  busy[`r_${item.tweet_id}`] ? "opacity-50" : ""
                                }`}
                              />
                            </div>

                            {/* Bottom Action Footer */}
                            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-[#262626]">
                              <div className="flex items-center gap-2.5 text-xs text-slate-500 dark:text-[#A3A3A3]">
                                <span className="tabular-nums">{text.length} characters</span>
                                {isEdited && (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 text-[11px] font-semibold border border-amber-200 dark:border-amber-800">
                                    <Brain className="w-3 h-3 text-amber-600 dark:text-amber-400" />
                                    <span>Edited · Voice Memory will learn</span>
                                  </span>
                                )}
                              </div>

                              <div className="grid grid-cols-2 sm:flex items-center gap-2">
                                <button
                                  onClick={() => skip(item.tweet_id)}
                                  className="btn btn-quiet text-xs !h-10 sm:!h-9 justify-center"
                                >
                                  <X className="w-3.5 h-3.5" />
                                  <span>Skip</span>
                                </button>

                                <button
                                  onClick={() => approve(item.tweet_id, true, item.should_like)}
                                  disabled={busy[`s_${item.tweet_id}`] || busy[`p_${item.tweet_id}`]}
                                  className="btn text-xs !h-10 sm:!h-9 justify-center"
                                >
                                  {busy[`s_${item.tweet_id}`] ? <Spin /> : <Clock className="w-3.5 h-3.5" />}
                                  <span>{busy[`s_${item.tweet_id}`] ? "Scheduling..." : "Schedule"}</span>
                                </button>

                                <button
                                  onClick={() => approve(item.tweet_id, false, item.should_like)}
                                  disabled={busy[`p_${item.tweet_id}`] || busy[`s_${item.tweet_id}`]}
                                  className="btn btn-primary text-xs !h-10 sm:!h-9 !px-3 sm:!px-4 col-span-2 order-first sm:order-none sm:col-span-1 justify-center"
                                >
                                  {busy[`p_${item.tweet_id}`] ? <Spin /> : <Send className="w-3.5 h-3.5" />}
                                  <span>{busy[`p_${item.tweet_id}`] ? "Posting..." : "Post Now"}</span>
                                </button>
                              </div>
                            </div>
                          </motion.article>
                        );
                      })}
                  </div>
                )}
              </div>
            )}

            {/* History View */}
            {tab === "history" && (
              <section className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl overflow-hidden shadow-xs">
                {/* Header & Filter Pills */}
                <div className="p-4 border-b border-slate-200 dark:border-[#262626] flex items-center justify-between flex-wrap gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Activity History</h3>
                    <p className="text-xs text-slate-500 dark:text-[#A3A3A3]">Every evaluated tweet, published reply, and schedule event</p>
                  </div>
                  <div className="flex items-center gap-1.5 overflow-x-auto pb-1 max-w-full">
                    {["all", "posted", "scheduled", "pending_approval", "skipped", "failed"].map((f) => (
                      <button
                        key={f}
                        onClick={() => setHistFilter(f)}
                        className={`h-7 px-3 text-xs rounded-lg transition-all capitalize font-medium shrink-0 ${
                          histFilter === f
                            ? "bg-slate-900 dark:bg-white text-white dark:text-black shadow-xs font-semibold"
                            : "bg-slate-100 dark:bg-[#222222] hover:bg-slate-200 dark:hover:bg-[#2C2C2C] text-slate-600 dark:text-[#D4D4D4]"
                        }`}
                      >
                        {f === "pending_approval" ? "Pending" : f}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="bg-slate-50/80 dark:bg-[#222222]/60 text-slate-500 dark:text-[#A3A3A3] font-medium border-b border-slate-200 dark:border-[#262626]">
                        <th className="py-2.5 px-4">Status</th>
                        <th className="py-2.5 px-4 hidden md:table-cell">Type & Signals</th>
                        <th className="py-2.5 px-4 hidden md:table-cell">Source Conversation</th>
                        <th className="py-2.5 px-4">Draft / Resolution</th>
                        <th className="py-2.5 px-4 text-right">Time</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-[#262626]">
                      {!histReady && (
                        <tr>
                          <td colSpan={5} className="py-12 text-center text-slate-400 dark:text-[#737373]">
                            <div className="flex items-center justify-center gap-2">
                              <Spin /> Loading history...
                            </div>
                          </td>
                        </tr>
                      )}
                      {histReady && shownHistory.length === 0 && (
                        <tr>
                          <td colSpan={5} className="py-12 text-center text-slate-400 dark:text-[#737373]">
                            No activity found matching this filter.
                          </td>
                        </tr>
                      )}
                      {shownHistory.map((h) => (
                        <tr key={h.tweet_id} className="hover:bg-slate-50/70 dark:hover:bg-[#202020] transition-colors">
                          <td className="py-3 px-4">
                            <span
                              className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wider ${
                                STATUS_STYLE[h.status] || STATUS_STYLE.skipped
                              }`}
                            >
                              {h.status === "pending_approval" ? "pending" : h.status}
                            </span>
                          </td>
                          <td className="py-3 px-4 hidden md:table-cell">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="capitalize font-semibold text-slate-800 dark:text-[#E5E5E5]">
                                {h.action_type || "reply"}
                              </span>
                              {h.urgency_score !== undefined && (
                                <span className="text-[10px] font-medium bg-slate-100 dark:bg-[#222222] text-slate-600 dark:text-[#D4D4D4] px-1.5 py-0.5 rounded">
                                  U{h.urgency_score}/10
                                </span>
                              )}
                              {h.should_like && (
                                <span className="text-[10px] font-medium bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 px-1.5 py-0.5 rounded border border-emerald-200 dark:border-emerald-800">
                                  ♥ Liked
                                </span>
                              )}
                              {h.user_edited && (
                                <span className="text-[10px] font-medium bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-800">
                                  Voice Learned
                                </span>
                              )}
                              {h.media_url && (
                                <span className="text-[10px] font-medium bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded border border-blue-200 dark:border-blue-800">
                                  Vision
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-4 max-w-[260px] hidden md:table-cell">
                            <span className="font-semibold text-slate-900 dark:text-white block truncate">
                              @{h.tweet_author || "creator"}
                            </span>
                            <span className="text-slate-500 dark:text-[#A3A3A3] font-normal block truncate">
                              {h.tweet_text}
                            </span>
                          </td>
                          <td className="py-3 px-4 max-w-[200px] md:max-w-[320px] text-slate-600 dark:text-[#D4D4D4] truncate">
                            {h.generated_text || h.error_message || "—"}
                          </td>
                          <td className="py-3 px-4 text-right text-slate-400 dark:text-[#737373] whitespace-nowrap">
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

            {/* Settings View */}
            {tab === "settings" && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 lg:gap-6 items-start">
                {/* Column 1: Voice & AI Intelligence */}
                <section className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl p-5 sm:p-7 space-y-7 shadow-xs">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                      Voice, Persona & Discovery
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-[#A3A3A3] mt-0.5">
                      Tune Gemini&apos;s writing persona and autonomous niche exploration
                    </p>
                  </div>

                  <div>
                    <label className="label">Target Niche / Topic Seed</label>
                    <input
                      className="field"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="AI agents, SaaS builders, TypeScript, Next.js"
                    />
                  </div>

                  {/* Smart Search Toggle */}
                  <label className="flex items-start gap-3 p-3.5 border border-slate-200 dark:border-[#262626] rounded-xl bg-slate-50/70 dark:bg-[#202020] cursor-pointer hover:bg-slate-50 dark:hover:bg-[#242424] transition-colors">
                    <input
                      type="checkbox"
                      checked={smartQuery}
                      onChange={(e) => setSmartQuery(e.target.checked)}
                      className="mt-0.5 w-4 h-4 accent-slate-900 dark:accent-sky-400"
                    />
                    <div className="space-y-0.5">
                      <span className="block text-xs font-semibold text-slate-900 dark:text-white">
                        Smart AI Search Discovery
                      </span>
                      <span className="text-xs text-slate-500 dark:text-[#A3A3A3] leading-normal block">
                        Allows Gemini to formulate dynamic 2–4 word search pulses for every scan, preventing query stagnation and discovering fresh conversational threads.
                      </span>
                    </div>
                  </label>

                  <div>
                    <label className="label">Base Persona & Tone Rules</label>
                    <textarea
                      rows={3}
                      className="field"
                      value={persona}
                      onChange={(e) => setPersona(e.target.value)}
                      placeholder="Direct, dry wit, authentic practitioner, no buzzwords, short punchy sentences."
                    />
                  </div>

                  {/* Active Few-Shot Memory Card */}
                  <div className="p-4 bg-slate-50 dark:bg-[#202020] border border-slate-200 dark:border-[#262626] rounded-xl space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-800 dark:text-[#E5E5E5] flex items-center gap-1.5">
                        <Brain className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                        Few-Shot Self-Learning Voice Memory
                      </span>
                      <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/50 px-2 py-0.5 rounded-md border border-emerald-200 dark:border-emerald-800">
                        {analytics?.learning_memory?.total_learned ?? status?.learned_examples_count ?? 0} samples active
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-[#A3A3A3] leading-relaxed">
                      Every reply you edit or approve in the Queue is automatically injected as a high-signal few-shot reference, while skipped posts refine the negative filter.
                    </p>
                  </div>

                  {/* AI Model & Key Verification */}
                  <div className="space-y-4 pt-6 border-t border-slate-100 dark:border-[#262626]">
                    <div>
                      <label className="label">Active Model</label>
                      <select
                        className="field"
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                      >
                        {models.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="label">
                        Gemini API Key{" "}
                        <span className="text-slate-400 font-normal">
                          (leave blank to keep {config?.masked_api_key ? "configured" : "default"})
                        </span>
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          className="field flex-1"
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="AIzaSy..."
                        />
                        <button
                          type="button"
                          onClick={verifyKey}
                          disabled={busy.key || !apiKey.trim()}
                          className="btn text-xs shrink-0"
                        >
                          {busy.key ? <Spin /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                          <span>{busy.key ? "Verifying..." : "Verify Key"}</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </section>

                {/* Column 2: Safety & Anti-Detection Automation */}
                <section className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl p-5 sm:p-7 space-y-7 shadow-xs">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                      Safety, Throttling & Velocity
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-[#A3A3A3] mt-0.5">
                      Configure biological pacing and anti-detection boundaries
                    </p>
                  </div>

                  {/* Velocity Limit Sliders */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-5">
                    <div>
                      <label className="label">Daily Action Cap</label>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        className="field"
                        value={cap}
                        onChange={(e) => setCap(Number(e.target.value))}
                      />
                    </div>
                    <div>
                      <label className="label">Rolling 60-min Cap</label>
                      <input
                        type="number"
                        min={1}
                        max={15}
                        className="field"
                        value={hourlyCap}
                        onChange={(e) => setHourlyCap(Number(e.target.value))}
                      />
                    </div>
                  </div>

                  {/* Cooldown Delays */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                      <label className="label">Scan Interval (m)</label>
                      <input
                        type="number"
                        min={5}
                        max={180}
                        className="field"
                        value={interval}
                        onChange={(e) => setIntervalMin(Number(e.target.value))}
                      />
                    </div>
                    <div>
                      <label className="label">Min Delay (m)</label>
                      <input
                        type="number"
                        min={1}
                        max={60}
                        className="field"
                        value={minDelay}
                        onChange={(e) => setMinDelay(Number(e.target.value))}
                      />
                    </div>
                    <div>
                      <label className="label">Max Delay (m)</label>
                      <input
                        type="number"
                        min={2}
                        max={120}
                        className="field"
                        value={maxDelay}
                        onChange={(e) => setMaxDelay(Number(e.target.value))}
                      />
                    </div>
                  </div>

                  {/* Active Hours */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-5">
                    <div>
                      <label className="label">Wake Hour (0–23)</label>
                      <input
                        type="number"
                        min={0}
                        max={23}
                        className="field"
                        value={wake}
                        onChange={(e) => setWake(Number(e.target.value))}
                      />
                    </div>
                    <div>
                      <label className="label">Sleep Hour (0–23)</label>
                      <input
                        type="number"
                        min={0}
                        max={23}
                        className="field"
                        value={sleep}
                        onChange={(e) => setSleep(Number(e.target.value))}
                      />
                    </div>
                  </div>

                  {/* Account Warmup Shield */}
                  <label className="flex items-start gap-3 p-3.5 border border-slate-200 dark:border-[#262626] rounded-xl bg-slate-50/70 dark:bg-[#202020] cursor-pointer hover:bg-slate-50 dark:hover:bg-[#242424] transition-colors">
                    <input
                      type="checkbox"
                      checked={warmupMode}
                      onChange={(e) => setWarmupMode(e.target.checked)}
                      className="mt-0.5 w-4 h-4 accent-slate-900 dark:accent-sky-400"
                    />
                    <div className="space-y-0.5">
                      <span className="block text-xs font-semibold text-slate-900 dark:text-white">
                        Account Warmup Shield
                      </span>
                      <span className="text-xs text-slate-500 dark:text-[#A3A3A3] leading-normal block">
                        Recommended for new or cautious profiles: limits velocity to 3 actions/hr and 8/day with extended dwell and randomized reading intervals.
                      </span>
                    </div>
                  </label>

                  {/* Autopilot Mode */}
                  <label className="flex items-start gap-3 p-3.5 border border-slate-200 dark:border-[#262626] rounded-xl bg-slate-50/70 dark:bg-[#202020] cursor-pointer hover:bg-slate-50 dark:hover:bg-[#242424] transition-colors">
                    <input
                      type="checkbox"
                      checked={autopilot}
                      onChange={(e) => setAutopilot(e.target.checked)}
                      className="mt-0.5 w-4 h-4 accent-slate-900 dark:accent-sky-400"
                    />
                    <div className="space-y-0.5">
                      <span className="block text-xs font-semibold text-slate-900 dark:text-white">
                        Autonomous Autopilot
                      </span>
                      <span className="text-xs text-slate-500 dark:text-[#A3A3A3] leading-normal block">
                        Automatically schedules high-urgency drafts into natural jittered intervals without waiting for manual queue approval.
                      </span>
                    </div>
                  </label>

                  {/* Account & Session Security Section */}
                  <div className="p-4 rounded-xl border border-slate-200 dark:border-[#262626] bg-slate-50/70 dark:bg-[#202020] space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="space-y-0.5">
                        <span className="block text-xs font-semibold text-slate-900 dark:text-white">
                          Creator Account & Session
                        </span>
                        <span className="text-[11px] text-slate-500 dark:text-[#A3A3A3]">
                          {userProfile?.email ? `Signed in as ${userProfile.email}` : "Currently in Sneak Peek / Demo Mode"} · 365-day persistent session
                        </span>
                      </div>
                      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                        Active
                      </span>
                    </div>
                    <div className="pt-1 flex items-center justify-between">
                      <span className="text-[11px] text-slate-400 font-mono">
                        Tenant ID: {tenantId}
                      </span>
                      <button
                        type="button"
                        onClick={handleSignOut}
                        className="btn !h-8 !px-3 text-xs text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/40 hover:bg-rose-50 dark:hover:bg-rose-950/30 flex items-center gap-1.5"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        <span>Sign Out of Studio</span>
                      </button>
                    </div>
                  </div>

                  {/* Save button */}
                  <button
                    onClick={() => saveSettings(false)}
                    disabled={busy.save}
                    className="btn btn-primary w-full justify-center !h-10 text-xs"
                  >
                    {busy.save ? <Spin /> : <CheckCircle2 className="w-4 h-4" />}
                    <span>{busy.save ? "Saving Settings..." : "Save Studio Configuration"}</span>
                  </button>
                </section>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        {/* Live System Activity Log Section */}
        <AnimatePresence>
          {showLogs && (
            <motion.section
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="bg-[#141414] text-[#E5E5E5] rounded-xl overflow-hidden border border-[#262626] shadow-md"
            >
              <div className="px-4 py-2.5 bg-[#101010] border-b border-[#262626] flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <Terminal className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="font-semibold text-white">Live Activity Stream</span>
                </div>
                <span className="text-[#A3A3A3] font-mono text-[11px]">{status?.selected_model}</span>
              </div>
              <div className="p-3.5 h-44 overflow-y-auto font-mono text-[11px] space-y-1 bg-[#141414]">
                {status?.recent_logs?.length ? (
                  status.recent_logs.map((l, i) => (
                    <div
                      key={i}
                      className={
                        l.level === "ERROR"
                          ? "text-rose-400"
                          : l.level === "WARNING"
                          ? "text-amber-400"
                          : "text-[#D4D4D4]"
                      }
                    >
                      <span className="text-[#737373] mr-2">{l.timestamp}</span>
                      <span className="text-[10px] font-bold uppercase mr-2 text-[#A3A3A3]">
                        [{l.level}]
                      </span>
                      <span>{l.message}</span>
                    </div>
                  ))
                ) : (
                  <span className="text-[#737373]">No activity logged yet.</span>
                )}
              </div>
            </motion.section>
          )}
        </AnimatePresence>
      </main>

      {/* Floating Toast Notification */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.95 }}
            className={`fixed bottom-20 md:bottom-6 right-4 left-4 sm:left-auto sm:right-6 z-50 px-4 py-3 text-xs font-medium shadow-dropdown rounded-xl flex items-center gap-2.5 max-w-md ${
              toast.error
                ? "bg-rose-950 text-rose-100 border border-rose-800"
                : "bg-[#181818] text-[#F3F3F3] border border-[#262626]"
            }`}
          >
            {toast.error ? (
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            ) : (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            )}
            <span className="flex-1 leading-relaxed break-words">{toast.msg}</span>
            <button
              onClick={() => setToast(null)}
              className="p-1 hover:opacity-80 shrink-0 text-slate-400 hover:text-white transition-colors"
              title="Dismiss notification"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Mobile Bottom Navigation Thumb Bar */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 bg-white/95 dark:bg-[#181818]/95 backdrop-blur-md border-t border-slate-200 dark:border-[#262626] px-3 py-1.5 flex items-center justify-around md:hidden shadow-lg">
        {NAV.map((n) => {
          const Icon = n.icon;
          const active = tab === n.id;
          const count = n.id === "queue" ? status?.pending_approvals_count : undefined;
          return (
            <button
              key={n.id}
              onClick={() => {
                setTab(n.id);
                if (n.id === "history") loadHistory();
              }}
              className={`relative flex flex-col items-center justify-center py-1 px-3 rounded-lg text-[11px] font-medium transition-all ${
                active
                  ? "text-slate-900 dark:text-white font-semibold"
                  : "text-slate-400 dark:text-[#737373] hover:text-slate-700 dark:hover:text-[#D4D4D4]"
              }`}
            >
              <div className="relative">
                <Icon className={`w-5 h-5 ${active ? "stroke-[2.2px]" : "stroke-[1.8px]"}`} />
                {Boolean(count && count > 0) && (
                  <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-full bg-slate-900 dark:bg-white text-white dark:text-black text-[10px] font-bold flex items-center justify-center">
                    {count}
                  </span>
                )}
              </div>
              <span className="mt-0.5 tracking-tight">{n.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Session Cookies Dialog */}
      <AnimatePresence>
        {cookieOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs grid place-items-center p-4"
            onClick={() => setCookieOpen(false)}
          >
            <motion.div
              initial={{ y: 8, scale: 0.98 }}
              animate={{ y: 0, scale: 1 }}
              exit={{ y: 8, scale: 0.98 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-white dark:bg-[#181818] rounded-2xl w-full max-w-lg p-5 sm:p-6 space-y-4 shadow-dropdown border border-slate-200 dark:border-[#262626]"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cookie className="w-4 h-4 text-slate-700 dark:text-[#D4D4D4]" />
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Session Cookie Sync</h3>
                </div>
                <button
                  onClick={() => setCookieOpen(false)}
                  className="text-slate-400 hover:text-slate-700 dark:hover:text-[#F3F3F3] transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-xs text-slate-500 dark:text-[#A3A3A3] leading-relaxed">
                Export your active X session cookies to transfer your logged-in session to cloud deployments (like Render or Docker) without re-authenticating.
              </p>
              <textarea
                rows={8}
                className="field font-mono text-[11px]"
                value={cookieJson}
                onChange={(e) => setCookieJson(e.target.value)}
                placeholder='[{"name": "auth_token", "value": "..."}, ...]'
              />
              <div className="flex justify-end gap-2.5">
                <button onClick={exportCookies} disabled={busy.cexp} className="btn text-xs">
                  {busy.cexp && <Spin />}
                  <span>Export Local Session</span>
                </button>
                <button
                  onClick={importCookies}
                  disabled={busy.cimp}
                  className="btn btn-primary text-xs"
                >
                  {busy.cimp && <Spin />}
                  <span>{busy.cimp ? "Verifying..." : "Import & Sync"}</span>
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      {/* Connect Account Modal */}
      <ConnectAccountModal
        isOpen={connectModalOpen}
        onClose={() => setConnectModalOpen(false)}
        isLoggedIn={Boolean(status?.is_logged_in)}
        linkedUsername={status?.linked_username}
        onSessionUpdated={() => {
          refresh();
          loadHistory();
        }}
        apiFetch={apiFetch}
        notify={notify}
      />
    </div>
  );
}
