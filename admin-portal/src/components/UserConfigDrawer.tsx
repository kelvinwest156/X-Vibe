"use client";

import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Power, ShieldAlert, ShieldCheck } from "lucide-react";
import {
  AdminApiError,
  AdminUserSummary,
  adminFetch,
  formatCompactTokens,
  formatFullNumber,
  formatHour,
  formatUsd,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { ConfirmDialog } from "@/components/ConfirmDialog";

interface UserConfigDrawerProps {
  user: AdminUserSummary | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUserUpdated: (updated: AdminUserSummary) => void;
  onBrowserStopped?: (tenantId: string) => void;
}

interface EditableFields {
  is_active: boolean;
  auto_pilot_mode: boolean;
  warmup_mode: boolean;
  auto_sleep_browser: boolean;
  plan_tier: string;
  daily_action_cap: number;
  hourly_action_cap: number;
  daily_token_cap: number;
  max_pending_queue: number;
  polling_interval_minutes: number;
  active_hours_start: number;
  active_hours_end: number;
}

function toEditable(u: AdminUserSummary): EditableFields {
  return {
    is_active: u.is_active,
    auto_pilot_mode: u.auto_pilot_mode,
    warmup_mode: u.warmup_mode,
    auto_sleep_browser: u.auto_sleep_browser,
    plan_tier: u.plan_tier || "trial",
    daily_action_cap: u.daily_action_cap,
    hourly_action_cap: u.hourly_action_cap,
    daily_token_cap: u.daily_token_cap,
    max_pending_queue: u.max_pending_queue,
    polling_interval_minutes: u.polling_interval_minutes,
    active_hours_start: u.active_hours_start,
    active_hours_end: u.active_hours_end,
  };
}

export function UserConfigDrawer({
  user,
  open,
  onOpenChange,
  onUserUpdated,
  onBrowserStopped,
}: UserConfigDrawerProps) {
  const [form, setForm] = useState<EditableFields | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmSuspendOpen, setConfirmSuspendOpen] = useState(false);
  const [confirmStopBrowserOpen, setConfirmStopBrowserOpen] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    if (user) {
      setForm(toEditable(user));
      setError(null);
      setNotice(null);
    }
  }, [user]);

  if (!user || !form) return null;

  const tokenPct =
    user.daily_token_cap > 0
      ? Math.min(100, Math.round((user.daily_tokens_used / user.daily_token_cap) * 100))
      : 0;

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!user || !form) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await adminFetch<{ success: boolean; user: AdminUserSummary }>(
        `/api/admin/users/${encodeURIComponent(user.tenant_id)}`,
        {
          method: "PATCH",
          body: JSON.stringify(form),
        }
      );
      onUserUpdated(res.user);
      setForm(toEditable(res.user));
      setNotice("Limits saved.");
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "Failed to save limits.");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleSuspend() {
    if (!user) return;
    setActionBusy(true);
    setError(null);
    setNotice(null);
    const nextSuspended = !user.is_suspended;
    try {
      const res = await adminFetch<{ success: boolean; user: AdminUserSummary }>(
        `/api/admin/users/${encodeURIComponent(user.tenant_id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            is_suspended: nextSuspended,
            ...(nextSuspended ? { is_active: false } : {}),
          }),
        }
      );
      onUserUpdated(res.user);
      setForm(toEditable(res.user));
      setConfirmSuspendOpen(false);
      setNotice(nextSuspended ? "Account suspended and automation halted." : "Account restored.");
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "Failed to update account status.");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleStopBrowser() {
    if (!user) return;
    setActionBusy(true);
    setError(null);
    setNotice(null);
    try {
      await adminFetch(`/api/admin/browsers/${encodeURIComponent(user.tenant_id)}/stop`, {
        method: "POST",
      });
      setConfirmStopBrowserOpen(false);
      onUserUpdated({ ...user, browser_running: false, browser_ram_mb: 0 });
      onBrowserStopped?.(user.tenant_id);
      setNotice("Browser put to sleep. Session cookies preserved.");
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "Failed to sleep browser.");
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <>
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/35" />
          <Dialog.Content
            className="fixed inset-y-0 right-0 z-40 flex h-dvh w-full max-w-lg flex-col border-l border-line bg-surface shadow-xl focus:outline-none"
            style={{
              paddingTop: "env(safe-area-inset-top)",
              paddingBottom: "env(safe-area-inset-bottom)",
            }}
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Dialog.Title className="truncate text-base font-semibold text-ink text-balance">
                    {user.email}
                  </Dialog.Title>
                  <span
                    className={cn(
                      "inline-flex shrink-0 items-center rounded border px-1.5 py-0.5 text-xs font-medium",
                      user.is_suspended
                        ? "border-red-600/30 bg-red-600/10 text-red-700 dark:text-red-400"
                        : user.is_active
                          ? "border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
                          : "border-line bg-canvas text-muted"
                    )}
                  >
                    {user.is_suspended ? "Suspended" : user.is_active ? "Active" : "Paused"}
                  </span>
                </div>
                <Dialog.Description className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-xs text-muted">
                  <span>{user.linked_username ? `@${user.linked_username.replace(/^@/, "")}` : "No X handle linked"}</span>
                  <span>·</span>
                  <span className="truncate">{user.tenant_id}</span>
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button
                  type="button"
                  aria-label="Close user settings drawer"
                  className="inline-flex size-8 shrink-0 items-center justify-center rounded-md border border-line bg-surface text-muted hover:text-ink"
                >
                  <X className="size-4" />
                </button>
              </Dialog.Close>
            </div>

            {/* Body */}
            <form onSubmit={handleSave} className="flex flex-1 flex-col overflow-hidden">
              <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
                {/* Compact Usage Snapshot Strip */}
                <div className="grid grid-cols-3 divide-x divide-line rounded-md border border-line bg-canvas">
                  <div className="p-3">
                    <div className="text-xs text-muted">Tokens 24h</div>
                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-ink">
                      {formatCompactTokens(user.daily_tokens_used)}
                    </div>
                    <div className="mt-0.5 font-mono text-xs tabular-nums text-muted">
                      {tokenPct}% of cap
                    </div>
                  </div>
                  <div className="p-3">
                    <div className="text-xs text-muted">Spend 24h</div>
                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-ink">
                      {formatUsd(user.daily_cost_usd)}
                    </div>
                    <div className="mt-0.5 font-mono text-xs tabular-nums text-muted">
                      {user.daily_actions_used} / {user.daily_action_cap} posts
                    </div>
                  </div>
                  <div className="p-3">
                    <div className="text-xs text-muted">Browser</div>
                    <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-ink">
                      {user.browser_running ? `${user.browser_ram_mb} MB` : "Asleep"}
                    </div>
                    <div className="mt-0.5 font-mono text-xs tabular-nums text-muted">
                      {user.pending_count} / {user.max_pending_queue} queue
                    </div>
                  </div>
                </div>

                {/* Subscription Plan Tier */}
                <section className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-medium text-ink">Subscription plan</h3>
                    <span className="text-xs font-mono text-muted">
                      {user.subscription_status === "expired" ? "Expired" : form.plan_tier}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { id: "trial", name: "7-Day Trial", price: "$0", tokens: "15,000/day", cap: 15000, actions: 10, queue: 6 },
                      { id: "starter", name: "Starter", price: "$9/mo", tokens: "50,000/day", cap: 50000, actions: 15, queue: 8 },
                      { id: "pro", name: "Creator Pro", price: "$24/mo", tokens: "150,000/day", cap: 150000, actions: 35, queue: 12 },
                      { id: "growth", name: "Growth", price: "$59/mo", tokens: "400,000/day", cap: 400000, actions: 50, queue: 20 },
                    ].map((p) => {
                      const selected = form.plan_tier === p.id;
                      return (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => {
                            setForm({
                              ...form,
                              plan_tier: p.id,
                              daily_token_cap: p.cap,
                              daily_action_cap: p.actions,
                              max_pending_queue: p.queue,
                            });
                          }}
                          className={cn(
                            "flex flex-col items-start rounded-md border p-2.5 text-left transition-colors",
                            selected
                              ? "border-emerald-500 bg-emerald-500/10 text-ink"
                              : "border-line bg-canvas hover:border-muted text-muted"
                          )}
                        >
                          <div className="flex w-full items-center justify-between">
                            <span className="text-xs font-semibold text-ink">{p.name}</span>
                            <span className="text-[11px] font-mono text-muted">{p.price}</span>
                          </div>
                          <span className="mt-1 text-[11px] font-mono text-muted">{p.tokens}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>

                {/* Automation Toggles */}
                <section className="space-y-3">
                  <h3 className="text-sm font-medium text-ink">Automation controls</h3>
                  <div className="divide-y divide-line rounded-md border border-line bg-surface">
                    <ToggleRow
                      label="Bot scanner active"
                      hint="Allow background scans and reply drafting for this creator."
                      checked={form.is_active}
                      disabled={user.is_suspended}
                      onChange={(val) => setForm({ ...form, is_active: val })}
                    />
                    <ToggleRow
                      label="Auto-pilot mode"
                      hint="Schedule approved-score drafts automatically without manual review."
                      checked={form.auto_pilot_mode}
                      onChange={(val) => setForm({ ...form, auto_pilot_mode: val })}
                    />
                    <ToggleRow
                      label="Account warmup mode"
                      hint="Caps output to 8 posts/day and widens cooldown intervals."
                      checked={form.warmup_mode}
                      onChange={(val) => setForm({ ...form, warmup_mode: val })}
                    />
                    <ToggleRow
                      label="Auto-sleep idle browser"
                      hint="Close Chromium after idle timeout or sleeping hours while keeping cookies."
                      checked={form.auto_sleep_browser}
                      onChange={(val) => setForm({ ...form, auto_sleep_browser: val })}
                    />
                  </div>
                </section>

                {/* Quotas & Token Caps */}
                <section className="space-y-3">
                  <h3 className="text-sm font-medium text-ink">Quotas and token limits</h3>
                  <div className="grid grid-cols-2 gap-3">
                    <NumberField
                      label="Daily token cap"
                      value={form.daily_token_cap}
                      min={1000}
                      max={5000000}
                      step={5000}
                      onChange={(v) => setForm({ ...form, daily_token_cap: v })}
                    />
                    <NumberField
                      label="Daily action cap"
                      value={form.daily_action_cap}
                      min={1}
                      max={200}
                      onChange={(v) => setForm({ ...form, daily_action_cap: v })}
                    />
                    <NumberField
                      label="Hourly action cap"
                      value={form.hourly_action_cap}
                      min={1}
                      max={60}
                      onChange={(v) => setForm({ ...form, hourly_action_cap: v })}
                    />
                    <NumberField
                      label="Max pending queue"
                      value={form.max_pending_queue}
                      min={1}
                      max={100}
                      onChange={(v) => setForm({ ...form, max_pending_queue: v })}
                    />
                    <NumberField
                      label="Scan interval (mins)"
                      value={form.polling_interval_minutes}
                      min={5}
                      max={240}
                      onChange={(v) => setForm({ ...form, polling_interval_minutes: v })}
                    />
                    <div className="rounded-md border border-line bg-canvas px-3 py-2">
                      <div className="text-xs text-muted">Active window</div>
                      <div className="mt-1 font-mono text-sm tabular-nums text-ink">
                        {formatHour(form.active_hours_start)} – {formatHour(form.active_hours_end)}
                      </div>
                    </div>
                    <NumberField
                      label="Active hours start (0-23)"
                      value={form.active_hours_start}
                      min={0}
                      max={23}
                      onChange={(v) => setForm({ ...form, active_hours_start: v })}
                    />
                    <NumberField
                      label="Active hours end (0-23)"
                      value={form.active_hours_end}
                      min={0}
                      max={23}
                      onChange={(v) => setForm({ ...form, active_hours_end: v })}
                    />
                  </div>
                </section>

                {/* Operational & Account Actions */}
                <section className="space-y-3 border-t border-line pt-5">
                  <h3 className="text-sm font-medium text-ink">Account actions</h3>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      disabled={!user.browser_running || actionBusy}
                      onClick={() => setConfirmStopBrowserOpen(true)}
                      className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-surface px-3 text-sm font-medium text-ink hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Power className="size-3.5" />
                      Sleep browser
                    </button>

                    <button
                      type="button"
                      disabled={actionBusy}
                      onClick={() => setConfirmSuspendOpen(true)}
                      className={cn(
                        "inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-medium disabled:opacity-50",
                        user.is_suspended
                          ? "border-emerald-600/40 bg-emerald-600/10 text-emerald-700 hover:bg-emerald-600/15 dark:text-emerald-400"
                          : "border-red-600/30 bg-red-600/10 text-red-700 hover:bg-red-600/15 dark:text-red-400"
                      )}
                    >
                      {user.is_suspended ? (
                        <>
                          <ShieldCheck className="size-3.5" />
                          Restore account
                        </>
                      ) : (
                        <>
                          <ShieldAlert className="size-3.5" />
                          Suspend account
                        </>
                      )}
                    </button>
                  </div>
                </section>
              </div>

              {/* Sticky Footer with inline feedback next to Save button */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-canvas px-6 py-3.5">
                <div className="min-w-0 flex-1 text-xs">
                  {error && <p className="text-red-600 dark:text-red-400">{error}</p>}
                  {!error && notice && (
                    <p className="text-emerald-700 dark:text-emerald-400">{notice}</p>
                  )}
                  {!error && !notice && (
                    <p className="font-mono tabular-nums text-muted">
                      Cap: {formatFullNumber(form.daily_token_cap)} tok/day
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Dialog.Close asChild>
                    <button
                      type="button"
                      className="inline-flex h-9 items-center justify-center rounded-md border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-canvas"
                    >
                      Close
                    </button>
                  </Dialog.Close>
                  <button
                    type="submit"
                    disabled={saving}
                    className="inline-flex h-9 items-center justify-center rounded-md bg-ink px-4 text-sm font-medium text-canvas hover:opacity-90 disabled:opacity-50"
                  >
                    {saving ? "Saving..." : "Save limits"}
                  </button>
                </div>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConfirmDialog
        open={confirmSuspendOpen}
        onOpenChange={setConfirmSuspendOpen}
        title={user.is_suspended ? `Restore ${user.email}?` : `Suspend ${user.email}?`}
        description={
          user.is_suspended
            ? "Restoring this creator lets them re-enable automation and use AI generation within their configured daily token cap."
            : "Suspending immediately pauses this creator's bot, blocks AI token usage, and stops their running Chromium browser."
        }
        confirmLabel={user.is_suspended ? "Restore account" : "Suspend account"}
        tone={user.is_suspended ? "default" : "danger"}
        busy={actionBusy}
        onConfirm={handleToggleSuspend}
      />

      <ConfirmDialog
        open={confirmStopBrowserOpen}
        onOpenChange={setConfirmStopBrowserOpen}
        title={`Sleep browser for ${user.email}?`}
        description="This closes the tenant's Chromium process to free server RAM immediately. Stored X session cookies remain intact for the next active scan."
        confirmLabel="Sleep browser"
        tone="warning"
        busy={actionBusy}
        onConfirm={handleStopBrowser}
      />
    </>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  disabled = false,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label
      className={cn(
        "flex items-center justify-between gap-4 px-3.5 py-3",
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"
      )}
    >
      <div className="min-w-0">
        <div className="text-sm font-medium text-ink">{label}</div>
        <div className="text-xs text-muted text-pretty">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/40",
          checked
            ? "border-emerald-600 bg-emerald-600"
            : "border-line bg-canvas"
        )}
      >
        <span
          className={cn(
            "inline-block size-3.5 rounded-full bg-white shadow-sm transition-transform duration-150",
            checked ? "translate-x-4" : "translate-x-0.5"
          )}
        />
      </button>
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (val: number) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="block text-xs text-muted">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const parsed = Number.parseInt(e.target.value, 10);
          if (!Number.isNaN(parsed)) {
            onChange(parsed);
          }
        }}
        className="h-9 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm tabular-nums text-ink focus:border-emerald-600 focus:outline-none"
      />
    </label>
  );
}
