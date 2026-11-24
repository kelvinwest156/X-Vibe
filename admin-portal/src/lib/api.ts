export const ADMIN_TOKEN_KEY = "xvibebot_super_admin_token";
export const ADMIN_EMAIL_KEY = "xvibebot_super_admin_email";

const DEFAULT_API_BASE = "http://localhost:8000";

export function getApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE;
  return raw.replace(/\/+$/, "");
}

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAdminSession(token: string, email: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
    window.localStorage.setItem(ADMIN_EMAIL_KEY, email);
  } catch {
    // Ignore storage quota errors
  }
}

export function clearAdminSession(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ADMIN_TOKEN_KEY);
    window.localStorage.removeItem(ADMIN_EMAIL_KEY);
  } catch {
    // Ignore storage errors
  }
}

export function getStoredAdminEmail(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ADMIN_EMAIL_KEY);
  } catch {
    return null;
  }
}

export class AdminApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
  }
}

export async function adminFetch<T>(
  path: string,
  options: RequestInit & { skipAuthRedirect?: boolean } = {}
): Promise<T> {
  const { skipAuthRedirect = false, headers, ...rest } = options;
  const token = getAdminToken();

  const mergedHeaders = new Headers(headers || {});
  if (!mergedHeaders.has("Content-Type") && rest.body) {
    mergedHeaders.set("Content-Type", "application/json");
  }
  if (token) {
    mergedHeaders.set("Authorization", `Bearer ${token}`);
    mergedHeaders.set("X-Admin-Token", token);
  }

  const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: mergedHeaders,
    });
  } catch {
    throw new AdminApiError(
      "Could not reach the backend API. Confirm the server is running and NEXT_PUBLIC_API_URL is configured.",
      0
    );
  }

  let data: unknown = null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? String((data as { detail?: unknown }).detail || "Request failed")
        : `Request failed with status ${response.status}`;

    if ((response.status === 401 || response.status === 403) && !skipAuthRedirect) {
      clearAdminSession();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.replace("/login");
      }
    }
    throw new AdminApiError(detail, response.status);
  }

  return data as T;
}

// ==============================================================================
// Typed API Contracts
// ==============================================================================

export interface AdminLoginResponse {
  token: string;
  email: string;
  role: string;
}

export interface AdminMeResponse {
  authenticated: boolean;
  email: string;
  role: string;
}

export interface PlatformSettings {
  default_daily_token_cap: number;
  web_radar_cache_seconds: number;
  browser_idle_sleep_minutes: number;
  auto_sleep_browsers_enabled: boolean;
  global_pause_bots: boolean;
  updated_at: string | null;
}

export interface ServerRamStats {
  process_rss_mb: number;
  chromium_rss_mb: number;
  total_rss_mb: number;
  system_ram_limit_mb: number;
  utilization_pct: number;
  awake_browsers_count: number;
  total_browsers_count: number;
  psutil_available: boolean;
}

export interface DailySeriesPoint {
  date: string;
  label: string;
  prompt_tokens: number;
  completion_tokens: number;
  cache_hit_tokens: number;
  cache_miss_tokens: number;
  total_tokens: number;
  cost_usd: number;
  calls: number;
}

export interface TaskBreakdownItem {
  task_type: string;
  calls: number;
  total_tokens: number;
  cost_usd: number;
  share_pct: number;
}

export interface OverviewSummary {
  spend_24h_usd: number;
  spend_period_usd: number;
  tokens_24h: number;
  prompt_tokens_24h: number;
  completion_tokens_24h: number;
  tokens_period: number;
  calls_24h: number;
  calls_period: number;
  active_users_24h: number;
  cache_hit_rate_pct: number;
  cache_savings_24h_usd: number;
  cache_savings_period_usd: number;
  total_users: number;
  active_bots: number;
  suspended_users: number;
  published_24h: number;
  pending_queue_total: number;
}

export interface AdminOverviewResponse {
  days: number;
  summary: OverviewSummary;
  daily_series: DailySeriesPoint[];
  task_breakdown: TaskBreakdownItem[];
  ram: ServerRamStats;
  settings: PlatformSettings;
}

export interface AdminUserSummary {
  tenant_id: string;
  email: string;
  name: string | null;
  linked_username: string | null;
  is_active: boolean;
  is_suspended: boolean;
  auto_pilot_mode: boolean;
  warmup_mode: boolean;
  daily_action_cap: number;
  hourly_action_cap: number;
  daily_actions_used: number;
  daily_token_cap: number;
  daily_tokens_used: number;
  daily_cost_usd: number;
  max_pending_queue: number;
  pending_count: number;
  polling_interval_minutes: number;
  active_hours_start: number;
  active_hours_end: number;
  auto_sleep_browser: boolean;
  browser_running: boolean;
  browser_ram_mb: number;
  plan_tier?: string;
  subscription_status?: string;
  trial_days_remaining?: number | null;
  daily_original_post_cap?: number;
  created_at: string | null;
}

export interface AdminUsersResponse {
  total: number;
  users: AdminUserSummary[];
}

export interface BrowserWorkerItem {
  tenant_id: string;
  worker_key: string;
  email: string;
  linked_username: string | null;
  is_running: boolean;
  idle_seconds: number;
  estimated_ram_mb: number;
  is_active: boolean;
  is_suspended: boolean;
  auto_sleep_browser: boolean;
  active_hours_start: number;
  active_hours_end: number;
  within_active_hours: boolean;
  has_cookies_backup: boolean;
}

export interface AdminBrowsersResponse {
  workers: BrowserWorkerItem[];
  ram: ServerRamStats;
  settings: PlatformSettings;
}

// ==============================================================================
// Formatting Helpers (Deterministic, Tabular-Safe)
// ==============================================================================

export function formatUsd(amount: number): string {
  if (!Number.isFinite(amount) || amount <= 0) return "$0.00";
  if (amount < 0.01) return `$${amount.toFixed(4)}`;
  if (amount < 1) return `$${amount.toFixed(3)}`;
  return `$${amount.toFixed(2)}`;
}

export function formatCompactTokens(tokens: number): string {
  if (!Number.isFinite(tokens) || tokens <= 0) return "0";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(2)}M`;
  if (tokens >= 10_000) return `${(tokens / 1_000).toFixed(1)}k`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(2)}k`;
  return tokens.toLocaleString("en-US");
}

export function formatFullNumber(val: number): string {
  if (!Number.isFinite(val)) return "0";
  return Math.round(val).toLocaleString("en-US");
}

export function formatIdleDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Active now";
  if (seconds < 60) return `${Math.round(seconds)}s idle`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m idle`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hrs}h ${remMins}m idle` : `${hrs}h idle`;
}

export function formatHour(hour: number): string {
  const h = ((hour % 24) + 24) % 24;
  return `${String(h).padStart(2, "0")}:00`;
}

export function formatTaskLabel(taskType: string): string {
  const map: Record<string, string> = {
    evaluate_batch: "Batch evaluation",
    original_post: "Original posts",
    web_scout: "Web Radar scout",
    web_draft: "Web Radar drafts",
    smart_query: "Smart query",
    strategy_brief: "Strategy brief",
    variants: "Reply variants",
    other: "Other tasks",
  };
  return map[taskType] || taskType.replace(/_/g, " ");
}
