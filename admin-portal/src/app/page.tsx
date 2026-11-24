"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  LogOut,
  Power,
  RefreshCw,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import {
  AdminApiError,
  AdminBrowsersResponse,
  AdminMeResponse,
  AdminOverviewResponse,
  AdminUserSummary,
  AdminUsersResponse,
  BrowserWorkerItem,
  PlatformSettings,
  adminFetch,
  clearAdminSession,
  formatCompactTokens,
  formatFullNumber,
  formatHour,
  formatIdleDuration,
  formatTaskLabel,
  formatUsd,
  getAdminToken,
  getStoredAdminEmail,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { ThemeToggle } from "@/components/ThemeToggle";
import { AdminSpendChart } from "@/components/AdminSpendChart";
import { UserConfigDrawer } from "@/components/UserConfigDrawer";
import { ConfirmDialog } from "@/components/ConfirmDialog";

type PortalTab = "overview" | "users" | "infrastructure";
type UserStatusFilter = "all" | "active" | "paused" | "suspended";

interface GuardrailDraft {
  default_daily_token_cap: number;
  web_radar_cache_hours: number;
  browser_idle_sleep_minutes: number;
  auto_sleep_browsers_enabled: boolean;
  global_pause_bots: boolean;
}

function toGuardrailDraft(s: PlatformSettings): GuardrailDraft {
  return {
    default_daily_token_cap: s.default_daily_token_cap,
    web_radar_cache_hours: Math.max(1, Math.round(s.web_radar_cache_seconds / 3600)),
    browser_idle_sleep_minutes: s.browser_idle_sleep_minutes,
    auto_sleep_browsers_enabled: s.auto_sleep_browsers_enabled,
    global_pause_bots: s.global_pause_bots,
  };
}

export default function SuperAdminPortalPage() {
  const router = useRouter();
  const [authReady, setAuthReady] = useState(false);
  const [adminEmail, setAdminEmail] = useState<string>("");

  const [tab, setTab] = useState<PortalTab>("overview");
  const [days, setDays] = useState<number>(7);

  const [overview, setOverview] = useState<AdminOverviewResponse | null>(null);
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [browsers, setBrowsers] = useState<AdminBrowsersResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Guardrails state
  const [guardrails, setGuardrails] = useState<GuardrailDraft>({
    default_daily_token_cap: 50000,
    web_radar_cache_hours: 2,
    browser_idle_sleep_minutes: 15,
    auto_sleep_browsers_enabled: true,
    global_pause_bots: false,
  });
  const [savingGuardrails, setSavingGuardrails] = useState(false);
  const [guardrailError, setGuardrailError] = useState<string | null>(null);
  const [guardrailNotice, setGuardrailNotice] = useState<string | null>(null);
  const [confirmPauseAllOpen, setConfirmPauseAllOpen] = useState(false);

  // Users filter & drawer state
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<UserStatusFilter>("all");
  const [selectedUser, setSelectedUser] = useState<AdminUserSummary | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Infrastructure actions state
  const [confirmSleepIdleOpen, setConfirmSleepIdleOpen] = useState(false);
  const [confirmSleepAllOpen, setConfirmSleepAllOpen] = useState(false);
  const [workerToStop, setWorkerToStop] = useState<BrowserWorkerItem | null>(null);
  const [infraBusy, setInfraBusy] = useState(false);
  const [infraNotice, setInfraNotice] = useState<string | null>(null);
  const [infraError, setInfraError] = useState<string | null>(null);

  const loadPortalData = useCallback(
    async (selectedDays: number, isManualRefresh = false) => {
      if (isManualRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setLoadError(null);

      try {
        const [ovRes, usrRes, brwRes] = await Promise.all([
          adminFetch<AdminOverviewResponse>(`/api/admin/overview?days=${selectedDays}`),
          adminFetch<AdminUsersResponse>("/api/admin/users"),
          adminFetch<AdminBrowsersResponse>("/api/admin/browsers"),
        ]);

        setOverview(ovRes);
        setGuardrails(toGuardrailDraft(ovRes.settings));
        setUsers(usrRes.users);
        setBrowsers(brwRes);
      } catch (err) {
        setLoadError(
          err instanceof AdminApiError ? err.message : "Failed to load platform telemetry."
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    []
  );

  // Verify session on mount
  useEffect(() => {
    const token = getAdminToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const storedEmail = getStoredAdminEmail();
    if (storedEmail) {
      setAdminEmail(storedEmail);
    }

    adminFetch<AdminMeResponse>("/api/admin/auth/me")
      .then((me) => {
        setAdminEmail(me.email);
        setAuthReady(true);
      })
      .catch(() => {
        clearAdminSession();
        router.replace("/login");
      });
  }, [router]);

  useEffect(() => {
    if (!authReady) return;
    void loadPortalData(days, false);
  }, [authReady, days, loadPortalData]);

  function handleSignOut() {
    clearAdminSession();
    router.replace("/login");
  }

  async function saveGuardrails(overridePause?: boolean) {
    setSavingGuardrails(true);
    setGuardrailError(null);
    setGuardrailNotice(null);

    const nextPause =
      typeof overridePause === "boolean" ? overridePause : guardrails.global_pause_bots;

    try {
      const res = await adminFetch<{ success: boolean; settings: PlatformSettings }>(
        "/api/admin/settings",
        {
          method: "PATCH",
          body: JSON.stringify({
            default_daily_token_cap: guardrails.default_daily_token_cap,
            web_radar_cache_seconds: Math.max(300, Math.round(guardrails.web_radar_cache_hours * 3600)),
            browser_idle_sleep_minutes: guardrails.browser_idle_sleep_minutes,
            auto_sleep_browsers_enabled: guardrails.auto_sleep_browsers_enabled,
            global_pause_bots: nextPause,
          }),
        }
      );

      setGuardrails(toGuardrailDraft(res.settings));
      setOverview((prev) => (prev ? { ...prev, settings: res.settings } : prev));
      setBrowsers((prev) => (prev ? { ...prev, settings: res.settings } : prev));
      setConfirmPauseAllOpen(false);
      setGuardrailNotice("Guardrails saved.");
    } catch (err) {
      setGuardrailError(
        err instanceof AdminApiError ? err.message : "Failed to save guardrails."
      );
    } finally {
      setSavingGuardrails(false);
    }
  }

  function handlePauseToggleClick() {
    const targetState = !guardrails.global_pause_bots;
    if (targetState) {
      setConfirmPauseAllOpen(true);
    } else {
      setGuardrails((prev) => ({ ...prev, global_pause_bots: false }));
      void saveGuardrails(false);
    }
  }

  async function handleSleepIdleBrowsers(force: boolean) {
    setInfraBusy(true);
    setInfraError(null);
    setInfraNotice(null);
    try {
      const res = await adminFetch<{
        success: boolean;
        stopped_count: number;
        estimated_ram_freed_mb: number;
      }>(`/api/admin/browsers/sleep-idle?force=${force ? "true" : "false"}`, {
        method: "POST",
      });
      setConfirmSleepIdleOpen(false);
      setConfirmSleepAllOpen(false);
      setInfraNotice(
        res.stopped_count > 0
          ? `Stopped ${res.stopped_count} browser worker${res.stopped_count === 1 ? "" : "s"} (~${res.estimated_ram_freed_mb} MB freed).`
          : "No eligible awake browsers needed to be stopped."
      );
      await loadPortalData(days, true);
    } catch (err) {
      setInfraError(
        err instanceof AdminApiError ? err.message : "Failed to sleep idle browsers."
      );
    } finally {
      setInfraBusy(false);
    }
  }

  async function handleStopSingleWorker() {
    if (!workerToStop) return;
    setInfraBusy(true);
    setInfraError(null);
    setInfraNotice(null);
    try {
      const res = await adminFetch<{
        success: boolean;
        already_asleep: boolean;
        estimated_ram_freed_mb: number;
      }>(`/api/admin/browsers/${encodeURIComponent(workerToStop.tenant_id)}/stop`, {
        method: "POST",
      });
      setWorkerToStop(null);
      setInfraNotice(
        res.already_asleep
          ? "Browser worker was already asleep."
          : `Stopped browser (~${res.estimated_ram_freed_mb} MB freed). Cookies preserved.`
      );
      await loadPortalData(days, true);
    } catch (err) {
      setInfraError(
        err instanceof AdminApiError ? err.message : "Failed to stop browser worker."
      );
    } finally {
      setInfraBusy(false);
    }
  }

  function handleUserUpdated(updated: AdminUserSummary) {
    setUsers((prev) => prev.map((u) => (u.tenant_id === updated.tenant_id ? updated : u)));
    setSelectedUser(updated);
  }

  function openUserDrawer(u: AdminUserSummary) {
    setSelectedUser(u);
    setDrawerOpen(true);
  }

  const normalizedSearch = searchQuery.trim().toLowerCase();
  const filteredUsers = users.filter((u) => {
    if (statusFilter === "active" && (!u.is_active || u.is_suspended)) return false;
    if (statusFilter === "paused" && (u.is_active || u.is_suspended)) return false;
    if (statusFilter === "suspended" && !u.is_suspended) return false;

    if (!normalizedSearch) return true;
    return [u.email, u.name || "", u.linked_username || "", u.tenant_id]
      .join(" ")
      .toLowerCase()
      .includes(normalizedSearch);
  });

  if (!authReady) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas px-4">
        <div className="w-full max-w-xs space-y-2 text-center">
          <div className="mx-auto h-4 w-32 rounded bg-line/70" />
          <div className="mx-auto h-3 w-48 rounded bg-line/50" />
        </div>
      </div>
    );
  }

  const summary = overview?.summary;
  const ram = overview?.ram || browsers?.ram;
  const isGloballyPaused = Boolean(overview?.settings.global_pause_bots);
  const ramHigh = Boolean(ram && ram.utilization_pct >= 80);

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      {/* Top Bar */}
      <header
        className="sticky top-0 z-20 border-b border-line bg-surface"
        style={{ paddingTop: "env(safe-area-inset-top)" }}
      >
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "size-2 rounded-full",
                  isGloballyPaused ? "bg-red-600" : "bg-emerald-600"
                )}
                aria-hidden="true"
              />
              <span className="text-sm font-semibold text-ink">X-VibeBot Control</span>
            </div>

            <nav aria-label="Portal sections" className="flex items-center gap-1">
              {(
                [
                  { id: "overview", label: "Overview" },
                  { id: "users", label: "Users" },
                  { id: "infrastructure", label: "Infrastructure" },
                ] as const
              ).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setTab(item.id)}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-sm font-medium",
                    tab === item.id
                      ? "bg-canvas text-ink border border-line"
                      : "text-muted hover:text-ink border border-transparent"
                  )}
                >
                  {item.label}
                </button>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            {adminEmail && (
              <span className="hidden max-w-[180px] truncate font-mono text-xs text-muted md:inline">
                {adminEmail}
              </span>
            )}
            <ThemeToggle />
            <button
              type="button"
              onClick={handleSignOut}
              aria-label="Sign out of Super Admin portal"
              className="inline-flex size-8 items-center justify-center rounded-md border border-line bg-surface text-muted hover:text-ink"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
        {isGloballyPaused && (
          <div
            role="status"
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-600/30 bg-red-600/10 px-4 py-3 text-sm"
          >
            <p className="text-red-700 dark:text-red-400 text-pretty">
              Global pause is active. All background creator scans and scheduled dispatches are halted.
            </p>
            <button
              type="button"
              disabled={savingGuardrails}
              onClick={() => void saveGuardrails(false)}
              className="inline-flex h-8 items-center rounded-md border border-red-600/40 bg-surface px-3 text-xs font-medium text-ink hover:bg-canvas"
            >
              Resume all bots
            </button>
          </div>
        )}

        {loadError && (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-600/30 bg-surface px-4 py-3 text-sm"
          >
            <span className="text-red-600 dark:text-red-400">{loadError}</span>
            <button
              type="button"
              onClick={() => void loadPortalData(days, true)}
              className="inline-flex h-8 items-center rounded-md border border-line bg-canvas px-3 text-xs font-medium text-ink hover:bg-surface"
            >
              Retry
            </button>
          </div>
        )}

        {/* OVERVIEW TAB */}
        {tab === "overview" && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold text-ink text-balance">
                  Platform overview
                </h1>
                <p className="mt-1 text-sm text-muted text-pretty">
                  Live AI token spend, prompt-cache efficiency, active creators, and browser memory.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <div
                  role="group"
                  aria-label="Date range"
                  className="inline-flex rounded-md border border-line bg-surface p-0.5 text-xs"
                >
                  {[7, 14, 30].map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setDays(d)}
                      className={cn(
                        "rounded px-2.5 py-1 font-mono tabular-nums",
                        days === d ? "bg-canvas font-medium text-ink" : "text-muted hover:text-ink"
                      )}
                    >
                      {d}d
                    </button>
                  ))}
                </div>

                <button
                  type="button"
                  disabled={refreshing}
                  onClick={() => void loadPortalData(days, true)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-xs font-medium text-ink hover:bg-canvas disabled:opacity-50"
                >
                  <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
                  Refresh
                </button>
              </div>
            </div>

            {/* Unified 4-Column Hairline Ledger Strip */}
            {loading ? (
              <div className="grid grid-cols-1 divide-y divide-line rounded-lg border border-line bg-surface sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
                {[0, 1, 2, 3].map((idx) => (
                  <div key={idx} className="space-y-2 p-5">
                    <div className="h-3.5 w-24 rounded bg-line/70" />
                    <div className="h-7 w-28 rounded bg-line/60" />
                    <div className="h-3 w-36 rounded bg-line/50" />
                  </div>
                ))}
              </div>
            ) : (
              <section
                aria-label="Key platform figures"
                className="grid grid-cols-1 divide-y divide-line rounded-lg border border-line bg-surface sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x"
              >
                <div className="p-5 sm:border-b sm:border-r lg:border-b-0 lg:border-r-0">
                  <div className="text-xs font-medium text-muted">Spend (24h)</div>
                  <div className="mt-1.5 font-mono text-2xl font-semibold tabular-nums text-ink">
                    {formatUsd(summary?.spend_24h_usd || 0)}
                  </div>
                  <div className="mt-1 font-mono text-xs tabular-nums text-muted">
                    {formatFullNumber(summary?.calls_24h || 0)} calls · {summary?.active_users_24h || 0} active
                  </div>
                </div>

                <div className="p-5 sm:border-b lg:border-b-0">
                  <div className="text-xs font-medium text-muted">Tokens (24h)</div>
                  <div className="mt-1.5 font-mono text-2xl font-semibold tabular-nums text-ink">
                    {formatFullNumber(summary?.tokens_24h || 0)}
                  </div>
                  <div className="mt-1 font-mono text-xs tabular-nums text-muted">
                    {formatCompactTokens(summary?.prompt_tokens_24h || 0)} in /{" "}
                    {formatCompactTokens(summary?.completion_tokens_24h || 0)} out
                  </div>
                </div>

                <div className="p-5 sm:border-r lg:border-r-0">
                  <div className="text-xs font-medium text-muted">Cache savings</div>
                  <div className="mt-1.5 font-mono text-2xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-500">
                    {(summary?.cache_hit_rate_pct || 0).toFixed(1)}%
                  </div>
                  <div className="mt-1 font-mono text-xs tabular-nums text-muted">
                    Saved {formatUsd(summary?.cache_savings_period_usd || 0)} ({days}d)
                  </div>
                </div>

                <div className="p-5">
                  <div className="text-xs font-medium text-muted">Server RAM</div>
                  <div
                    className={cn(
                      "mt-1.5 font-mono text-2xl font-semibold tabular-nums",
                      ramHigh ? "text-amber-600 dark:text-amber-500" : "text-ink"
                    )}
                  >
                    {Math.round(ram?.total_rss_mb || 0)}{" "}
                    <span className="text-sm font-normal text-muted">
                      / {Math.round(ram?.system_ram_limit_mb || 512)} MB
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-xs tabular-nums text-muted">
                    {ram?.awake_browsers_count || 0} awake · {summary?.active_bots || 0}/
                    {summary?.total_users || 0} bots active
                  </div>
                </div>
              </section>
            )}

            {/* Main 2-Column Workspace: Chart + Task Breakdown | Global Guardrails */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
              <div className="space-y-6 lg:col-span-8">
                <AdminSpendChart
                  series={overview?.daily_series || []}
                  days={days}
                  loading={loading}
                />

                {/* Feature Breakdown Ledger */}
                <div className="rounded-lg border border-line bg-surface">
                  <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
                    <h2 className="text-sm font-semibold text-ink">
                      Spend by task ({days} days)
                    </h2>
                    <span className="font-mono text-xs tabular-nums text-muted">
                      {formatFullNumber(summary?.published_24h || 0)} posts 24h ·{" "}
                      {formatFullNumber(summary?.pending_queue_total || 0)} queued
                    </span>
                  </div>

                  {loading ? (
                    <div className="space-y-2 p-5">
                      <div className="h-6 w-full rounded bg-line/50" />
                      <div className="h-6 w-full rounded bg-line/40" />
                    </div>
                  ) : !overview?.task_breakdown?.length ? (
                    <div className="px-5 py-6 text-sm text-muted">
                      No task-level AI calls logged in the selected {days}-day window.
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm">
                        <thead>
                          <tr className="border-b border-line text-xs text-muted">
                            <th className="px-5 py-2.5 font-medium">Task</th>
                            <th className="px-3 py-2.5 text-right font-medium">Calls</th>
                            <th className="px-3 py-2.5 text-right font-medium">Tokens</th>
                            <th className="px-3 py-2.5 text-right font-medium">Share</th>
                            <th className="px-5 py-2.5 text-right font-medium">Cost</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-line">
                          {overview.task_breakdown.map((row) => (
                            <tr key={row.task_type} className="hover:bg-canvas/70">
                              <td className="px-5 py-2.5 font-medium text-ink">
                                {formatTaskLabel(row.task_type)}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums text-muted">
                                {formatFullNumber(row.calls)}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums text-ink">
                                {formatCompactTokens(row.total_tokens)}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums text-muted">
                                {row.share_pct.toFixed(1)}%
                              </td>
                              <td className="px-5 py-2.5 text-right font-mono text-xs font-medium tabular-nums text-ink">
                                {formatUsd(row.cost_usd)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Column: Global Guardrails */}
              <div className="lg:col-span-4">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void saveGuardrails();
                  }}
                  className="rounded-lg border border-line bg-surface p-5"
                >
                  <div className="flex items-center gap-2">
                    <SlidersHorizontal className="size-4 text-muted" />
                    <h2 className="text-sm font-semibold text-ink">Global guardrails</h2>
                  </div>
                  <p className="mt-1 text-xs text-muted text-pretty">
                    Platform-wide defaults for token caps, Web Radar caching, and browser sleep rules.
                  </p>

                  <div className="mt-5 space-y-4">
                    <label className="block space-y-1">
                      <span className="block text-xs text-muted">Default daily token cap</span>
                      <input
                        type="number"
                        min={1000}
                        max={5000000}
                        step={5000}
                        value={guardrails.default_daily_token_cap}
                        onChange={(e) => {
                          const v = Number.parseInt(e.target.value, 10);
                          if (!Number.isNaN(v)) {
                            setGuardrails({ ...guardrails, default_daily_token_cap: v });
                          }
                        }}
                        className="h-9 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm tabular-nums text-ink focus:border-emerald-600 focus:outline-none"
                      />
                    </label>

                    <label className="block space-y-1">
                      <span className="block text-xs text-muted">Web Radar cache (hours)</span>
                      <input
                        type="number"
                        min={1}
                        max={24}
                        step={1}
                        value={guardrails.web_radar_cache_hours}
                        onChange={(e) => {
                          const v = Number.parseInt(e.target.value, 10);
                          if (!Number.isNaN(v)) {
                            setGuardrails({ ...guardrails, web_radar_cache_hours: v });
                          }
                        }}
                        className="h-9 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm tabular-nums text-ink focus:border-emerald-600 focus:outline-none"
                      />
                    </label>

                    <label className="block space-y-1">
                      <span className="block text-xs text-muted">Sleep idle browser (mins)</span>
                      <input
                        type="number"
                        min={1}
                        max={1440}
                        step={1}
                        value={guardrails.browser_idle_sleep_minutes}
                        onChange={(e) => {
                          const v = Number.parseInt(e.target.value, 10);
                          if (!Number.isNaN(v)) {
                            setGuardrails({ ...guardrails, browser_idle_sleep_minutes: v });
                          }
                        }}
                        className="h-9 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm tabular-nums text-ink focus:border-emerald-600 focus:outline-none"
                      />
                    </label>

                    <div className="divide-y divide-line rounded-md border border-line bg-canvas">
                      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
                        <div>
                          <div className="text-xs font-medium text-ink">Auto-sleep browsers</div>
                          <div className="text-xs text-muted">Sleep after idle timeout and off-hours</div>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={guardrails.auto_sleep_browsers_enabled}
                          aria-label="Auto-sleep browsers"
                          onClick={() =>
                            setGuardrails({
                              ...guardrails,
                              auto_sleep_browsers_enabled: !guardrails.auto_sleep_browsers_enabled,
                            })
                          }
                          className={cn(
                            "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-150",
                            guardrails.auto_sleep_browsers_enabled
                              ? "border-emerald-600 bg-emerald-600"
                              : "border-line bg-surface"
                          )}
                        >
                          <span
                            className={cn(
                              "inline-block size-3.5 rounded-full bg-white shadow-sm transition-transform duration-150",
                              guardrails.auto_sleep_browsers_enabled ? "translate-x-4" : "translate-x-0.5"
                            )}
                          />
                        </button>
                      </div>

                      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
                        <div>
                          <div className="text-xs font-medium text-ink">Pause all bots</div>
                          <div className="text-xs text-muted">Emergency global kill-switch</div>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={guardrails.global_pause_bots}
                          aria-label="Pause all bots"
                          onClick={handlePauseToggleClick}
                          className={cn(
                            "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-150",
                            guardrails.global_pause_bots
                              ? "border-red-600 bg-red-600"
                              : "border-line bg-surface"
                          )}
                        >
                          <span
                            className={cn(
                              "inline-block size-3.5 rounded-full bg-white shadow-sm transition-transform duration-150",
                              guardrails.global_pause_bots ? "translate-x-4" : "translate-x-0.5"
                            )}
                          />
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1 text-xs">
                      {guardrailError && (
                        <span className="text-red-600 dark:text-red-400">{guardrailError}</span>
                      )}
                      {!guardrailError && guardrailNotice && (
                        <span className="text-emerald-700 dark:text-emerald-400">
                          {guardrailNotice}
                        </span>
                      )}
                    </div>
                    <button
                      type="submit"
                      disabled={savingGuardrails}
                      className="inline-flex h-9 items-center justify-center rounded-md bg-ink px-4 text-sm font-medium text-canvas hover:opacity-90 disabled:opacity-50"
                    >
                      {savingGuardrails ? "Saving..." : "Save defaults"}
                    </button>
                  </div>
                </form>
              </div>
            </div>

            {/* Compact Creators Ledger right on Overview */}
            <CreatorsLedgerSection
              users={filteredUsers}
              totalCount={users.length}
              loading={loading}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              onSelectUser={openUserDrawer}
              onResetFilters={() => {
                setSearchQuery("");
                setStatusFilter("all");
              }}
            />
          </>
        )}

        {/* USERS TAB */}
        {tab === "users" && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold text-ink text-balance">Creators ledger</h1>
                <p className="mt-1 text-sm text-muted text-pretty">
                  Click any creator row to inspect quotas, set daily token caps, or suspend access.
                </p>
              </div>
              <button
                type="button"
                disabled={refreshing}
                onClick={() => void loadPortalData(days, true)}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-xs font-medium text-ink hover:bg-canvas disabled:opacity-50"
              >
                <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
                Refresh
              </button>
            </div>

            <CreatorsLedgerSection
              users={filteredUsers}
              totalCount={users.length}
              loading={loading}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              onSelectUser={openUserDrawer}
              onResetFilters={() => {
                setSearchQuery("");
                setStatusFilter("all");
              }}
            />
          </>
        )}

        {/* INFRASTRUCTURE TAB */}
        {tab === "infrastructure" && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="text-xl font-semibold text-ink text-balance">
                  Browser infrastructure
                </h1>
                <p className="mt-1 text-sm text-muted text-pretty">
                  Live Playwright Chromium workers, server memory footprint, and one-click RAM recovery.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={infraBusy || (ram?.awake_browsers_count || 0) === 0}
                  onClick={() => setConfirmSleepIdleOpen(true)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-xs font-medium text-ink hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Power className="size-3.5" />
                  Sleep idle browsers
                </button>
                <button
                  type="button"
                  disabled={infraBusy || (ram?.awake_browsers_count || 0) === 0}
                  onClick={() => setConfirmSleepAllOpen(true)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-600/30 bg-red-600/10 px-3 text-xs font-medium text-red-700 hover:bg-red-600/15 disabled:cursor-not-allowed disabled:opacity-50 dark:text-red-400"
                >
                  Stop all browsers
                </button>
                <button
                  type="button"
                  disabled={refreshing}
                  onClick={() => void loadPortalData(days, true)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-xs font-medium text-ink hover:bg-canvas disabled:opacity-50"
                >
                  <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
                  Refresh
                </button>
              </div>
            </div>

            {(infraNotice || infraError) && (
              <div
                role={infraError ? "alert" : "status"}
                className={cn(
                  "rounded-lg border px-4 py-2.5 text-xs",
                  infraError
                    ? "border-red-600/30 bg-red-600/10 text-red-700 dark:text-red-400"
                    : "border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
                )}
              >
                {infraError || infraNotice}
              </div>
            )}

            {/* Live Server RAM Summary Card */}
            <section className="rounded-lg border border-line bg-surface p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold text-ink">Server memory footprint</h2>
                  <p className="mt-0.5 text-xs text-muted">
                    Auto-sleep threshold: {browsers?.settings.browser_idle_sleep_minutes ?? 15} mins
                    {browsers?.settings.auto_sleep_browsers_enabled ? " (enabled)" : " (manual only)"}
                  </p>
                </div>
                <div className="font-mono text-sm font-semibold tabular-nums text-ink">
                  {Math.round(ram?.total_rss_mb || 0)} / {Math.round(ram?.system_ram_limit_mb || 512)} MB{" "}
                  <span className="font-normal text-muted">
                    ({(ram?.utilization_pct || 0).toFixed(1)}%)
                  </span>
                </div>
              </div>

              <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-canvas border border-line">
                <div
                  className={cn(
                    "h-full rounded-full",
                    (ram?.utilization_pct || 0) >= 85
                      ? "bg-red-600"
                      : (ram?.utilization_pct || 0) >= 65
                        ? "bg-amber-600"
                        : "bg-emerald-600"
                  )}
                  style={{ width: `${Math.min(100, ram?.utilization_pct || 0)}%` }}
                />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 sm:grid-cols-4">
                <div>
                  <div className="text-xs text-muted">Python backend RSS</div>
                  <div className="mt-0.5 font-mono text-sm font-medium tabular-nums text-ink">
                    {(ram?.process_rss_mb || 0).toFixed(1)} MB
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted">Chromium workers RSS</div>
                  <div className="mt-0.5 font-mono text-sm font-medium tabular-nums text-ink">
                    {(ram?.chromium_rss_mb || 0).toFixed(1)} MB
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted">Awake browsers</div>
                  <div className="mt-0.5 font-mono text-sm font-medium tabular-nums text-ink">
                    {ram?.awake_browsers_count || 0} / {ram?.total_browsers_count || 0}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted">Telemetry source</div>
                  <div className="mt-0.5 font-mono text-sm font-medium text-ink">
                    {ram?.psutil_available ? "psutil live" : "Estimated"}
                  </div>
                </div>
              </div>
            </section>

            {/* Browser Workers Table */}
            <section className="rounded-lg border border-line bg-surface">
              <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
                <h2 className="text-sm font-semibold text-ink">
                  Registered workers ({browsers?.workers.length || 0})
                </h2>
                <span className="text-xs text-muted">
                  Stopping a worker frees Chromium RAM while keeping X cookies intact
                </span>
              </div>

              {loading ? (
                <div className="space-y-2 p-5">
                  <div className="h-9 w-full rounded bg-line/50" />
                  <div className="h-9 w-full rounded bg-line/40" />
                </div>
              ) : !browsers?.workers.length ? (
                <div className="px-5 py-10 text-center">
                  <p className="text-sm font-medium text-ink">No browser workers registered</p>
                  <p className="mt-1 text-xs text-muted">
                    Workers are created automatically when a creator links X or runs a scan.
                  </p>
                  <button
                    type="button"
                    onClick={() => void loadPortalData(days, true)}
                    className="mt-4 inline-flex h-8 items-center rounded-md border border-line bg-canvas px-3 text-xs font-medium text-ink hover:bg-surface"
                  >
                    Check again
                  </button>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs text-muted">
                        <th className="px-5 py-2.5 font-medium">Tenant</th>
                        <th className="px-3 py-2.5 font-medium">State</th>
                        <th className="px-3 py-2.5 font-medium">Idle</th>
                        <th className="px-3 py-2.5 font-medium">Active hours</th>
                        <th className="px-3 py-2.5 font-medium">Session</th>
                        <th className="px-3 py-2.5 text-right font-medium">RAM</th>
                        <th className="px-5 py-2.5 text-right font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {browsers.workers.map((w) => (
                        <tr key={w.worker_key} className="hover:bg-canvas/70">
                          <td className="px-5 py-3">
                            <div className="font-medium text-ink">{w.email}</div>
                            <div className="font-mono text-xs text-muted">
                              {w.linked_username ? `@${w.linked_username.replace(/^@/, "")}` : w.tenant_id}
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <span
                              className={cn(
                                "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium",
                                w.is_running
                                  ? "border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
                                  : "border-line bg-canvas text-muted"
                              )}
                            >
                              <span
                                className={cn(
                                  "size-1.5 rounded-full",
                                  w.is_running ? "bg-emerald-600" : "bg-muted/50"
                                )}
                              />
                              {w.is_running ? "Awake" : "Asleep"}
                            </span>
                          </td>
                          <td className="px-3 py-3 font-mono text-xs tabular-nums text-muted">
                            {w.is_running ? formatIdleDuration(w.idle_seconds) : "—"}
                          </td>
                          <td className="px-3 py-3 font-mono text-xs tabular-nums text-muted">
                            {formatHour(w.active_hours_start)}–{formatHour(w.active_hours_end)}
                            {!w.within_active_hours && (
                              <span className="ml-1.5 text-amber-600 dark:text-amber-500">
                                (sleeping)
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-3 text-xs text-muted">
                            {w.has_cookies_backup ? "Cookies saved" : "Not linked"}
                          </td>
                          <td className="px-3 py-3 text-right font-mono text-xs font-medium tabular-nums text-ink">
                            {w.is_running ? `${w.estimated_ram_mb.toFixed(0)} MB` : "0 MB"}
                          </td>
                          <td className="px-5 py-3 text-right">
                            <button
                              type="button"
                              disabled={!w.is_running || infraBusy}
                              onClick={() => setWorkerToStop(w)}
                              className="inline-flex h-7 items-center rounded border border-line bg-surface px-2.5 text-xs font-medium text-ink hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              Stop browser
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>

      {/* Slide-Over User Drawer */}
      <UserConfigDrawer
        user={selectedUser}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onUserUpdated={handleUserUpdated}
        onBrowserStopped={() => void loadPortalData(days, true)}
      />

      {/* Destructive / High-Impact Confirmation Modals */}
      <ConfirmDialog
        open={confirmPauseAllOpen}
        onOpenChange={setConfirmPauseAllOpen}
        title="Pause all creator bots globally?"
        description="This immediately halts background feed scanning and scheduled post dispatches across every tenant until you turn global pause off."
        confirmLabel="Pause all bots"
        tone="danger"
        busy={savingGuardrails}
        onConfirm={() => saveGuardrails(true)}
      />

      <ConfirmDialog
        open={confirmSleepIdleOpen}
        onOpenChange={setConfirmSleepIdleOpen}
        title="Sleep idle and sleeping-hours browsers?"
        description="Closes Chromium for idle, paused, suspended, or sleeping-hours tenants to reclaim RAM. Active sessions and saved cookies remain intact."
        confirmLabel="Sleep idle browsers"
        tone="warning"
        busy={infraBusy}
        onConfirm={() => handleSleepIdleBrowsers(false)}
      />

      <ConfirmDialog
        open={confirmSleepAllOpen}
        onOpenChange={setConfirmSleepAllOpen}
        title="Stop all running Chromium browsers?"
        description="Gracefully closes every awake browser worker right now to free maximum server RAM. Workers will automatically wake up on their next scheduled scan using saved cookies."
        confirmLabel="Stop all browsers"
        tone="danger"
        busy={infraBusy}
        onConfirm={() => handleSleepIdleBrowsers(true)}
      />

      <ConfirmDialog
        open={workerToStop !== null}
        onOpenChange={(open) => {
          if (!open) setWorkerToStop(null);
        }}
        title={workerToStop ? `Stop browser for ${workerToStop.email}?` : "Stop browser?"}
        description="Closes this tenant's Chromium worker to reclaim RAM. Stored X cookies remain safely saved on disk."
        confirmLabel="Stop browser"
        tone="warning"
        busy={infraBusy}
        onConfirm={handleStopSingleWorker}
      />
    </div>
  );
}

interface CreatorsLedgerSectionProps {
  users: AdminUserSummary[];
  totalCount: number;
  loading: boolean;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  statusFilter: UserStatusFilter;
  onStatusFilterChange: (f: UserStatusFilter) => void;
  onSelectUser: (u: AdminUserSummary) => void;
  onResetFilters: () => void;
}

function CreatorsLedgerSection({
  users,
  totalCount,
  loading,
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  onSelectUser,
  onResetFilters,
}: CreatorsLedgerSectionProps) {
  return (
    <section className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-ink">
            Creators <span className="font-mono text-xs font-normal tabular-nums text-muted">({totalCount})</span>
          </h2>

          <div
            role="group"
            aria-label="Filter creators by status"
            className="inline-flex rounded-md border border-line bg-canvas p-0.5 text-xs"
          >
            {(["all", "active", "paused", "suspended"] as const).map((status) => (
              <button
                key={status}
                type="button"
                onClick={() => onStatusFilterChange(status)}
                className={cn(
                  "rounded px-2 py-0.5 capitalize",
                  statusFilter === status
                    ? "bg-surface font-medium text-ink shadow-sm"
                    : "text-muted hover:text-ink"
                )}
              >
                {status}
              </button>
            ))}
          </div>
        </div>

        <label className="relative block w-full sm:w-64">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted"
          />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search email or @handle"
            aria-label="Search creators by email or handle"
            className="h-8 w-full rounded-md border border-line bg-canvas pl-8 pr-3 text-xs text-ink placeholder:text-muted/80 focus:border-emerald-600 focus:bg-surface focus:outline-none"
          />
        </label>
      </div>

      {loading ? (
        <div className="space-y-2 p-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-11 w-full rounded bg-line/45" />
          ))}
        </div>
      ) : users.length === 0 ? (
        <div className="px-5 py-10 text-center">
          <p className="text-sm font-medium text-ink">
            {totalCount === 0 ? "No creator accounts found" : "No creators match your filter"}
          </p>
          <p className="mt-1 text-xs text-muted text-pretty">
            {totalCount === 0
              ? "Creators appear here as soon as they register on X-VibeBot."
              : "Adjust your search query or status filter to view all creators."}
          </p>
          {totalCount > 0 && (
            <button
              type="button"
              onClick={onResetFilters}
              className="mt-4 inline-flex h-8 items-center rounded-md border border-line bg-canvas px-3 text-xs font-medium text-ink hover:bg-surface"
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-muted">
                <th className="px-5 py-2.5 font-medium">Creator</th>
                <th className="px-3 py-2.5 font-medium">Bot</th>
                <th className="px-3 py-2.5 font-medium">Posts 24h</th>
                <th className="px-3 py-2.5 font-medium">Tokens 24h</th>
                <th className="px-5 py-2.5 text-right font-medium">Browser</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {users.map((u) => {
                const tokenPct =
                  u.daily_token_cap > 0
                    ? Math.min(100, Math.round((u.daily_tokens_used / u.daily_token_cap) * 100))
                    : 0;
                const overCap = tokenPct >= 100;
                const nearCap = tokenPct >= 80 && !overCap;

                return (
                  <tr
                    key={u.tenant_id}
                    tabIndex={0}
                    role="button"
                    onClick={() => onSelectUser(u)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelectUser(u);
                      }
                    }}
                    className="cursor-pointer hover:bg-canvas focus:bg-canvas focus:outline-none"
                  >
                    <td className="px-5 py-3">
                      <div className="max-w-[240px] truncate font-medium text-ink">{u.email}</div>
                      <div className="mt-0.5 flex items-center gap-1.5 font-mono text-xs text-muted">
                        <span>
                          {u.linked_username
                            ? `@${u.linked_username.replace(/^@/, "")}`
                            : u.tenant_id}
                        </span>
                        <span>·</span>
                        <span className="rounded border border-line bg-canvas px-1 py-0.5 text-[10px] uppercase font-medium text-ink">
                          {u.plan_tier || "trial"}
                        </span>
                      </div>
                    </td>

                    <td className="px-3 py-3">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium",
                          u.is_suspended
                            ? "border-red-600/30 bg-red-600/10 text-red-700 dark:text-red-400"
                            : u.is_active
                              ? "border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
                              : "border-line bg-canvas text-muted"
                        )}
                      >
                        <span
                          className={cn(
                            "size-1.5 rounded-full",
                            u.is_suspended
                              ? "bg-red-600"
                              : u.is_active
                                ? "bg-emerald-600"
                                : "bg-muted/50"
                          )}
                        />
                        {u.is_suspended ? "Suspended" : u.is_active ? "Active" : "Paused"}
                      </span>
                    </td>

                    <td className="px-3 py-3 font-mono text-xs tabular-nums text-ink">
                      {u.daily_actions_used}{" "}
                      <span className="text-muted">/ {u.daily_action_cap}</span>
                    </td>

                    <td className="px-3 py-3">
                      <div className="flex items-center justify-between gap-2 font-mono text-xs tabular-nums">
                        <span
                          className={cn(
                            overCap
                              ? "font-medium text-red-600 dark:text-red-400"
                              : nearCap
                                ? "font-medium text-amber-600 dark:text-amber-500"
                                : "text-ink"
                          )}
                        >
                          {formatCompactTokens(u.daily_tokens_used)}{" "}
                          <span className="text-muted">/ {formatCompactTokens(u.daily_token_cap)}</span>
                        </span>
                        <span className="text-muted">{formatUsd(u.daily_cost_usd)}</span>
                      </div>
                      <div className="mt-1.5 h-1.5 w-40 overflow-hidden rounded-full bg-canvas border border-line">
                        <div
                          className={cn(
                            "h-full rounded-full",
                            overCap
                              ? "bg-red-600"
                              : nearCap
                                ? "bg-amber-600"
                                : "bg-emerald-600"
                          )}
                          style={{ width: `${tokenPct}%` }}
                        />
                      </div>
                    </td>

                    <td className="px-5 py-3 text-right font-mono text-xs tabular-nums">
                      {u.browser_running ? (
                        <span className="text-emerald-700 dark:text-emerald-400">
                          Awake · {Math.round(u.browser_ram_mb)} MB
                        </span>
                      ) : (
                        <span className="text-muted">Asleep · 0 MB</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
