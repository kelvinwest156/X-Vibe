"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import {
  AdminApiError,
  AdminLoginResponse,
  AdminMeResponse,
  adminFetch,
  getAdminToken,
  setAdminSession,
} from "@/lib/api";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const existing = getAdminToken();
    if (!existing) {
      setCheckingSession(false);
      return;
    }
    adminFetch<AdminMeResponse>("/api/admin/auth/me", { skipAuthRedirect: true })
      .then(() => {
        router.replace("/");
      })
      .catch(() => {
        setCheckingSession(false);
      });
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("Enter both admin email and password.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await adminFetch<AdminLoginResponse>("/api/admin/auth/login", {
        method: "POST",
        skipAuthRedirect: true,
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      });
      setAdminSession(res.token, res.email);
      router.replace("/");
    } catch (err) {
      if (err instanceof AdminApiError) {
        setError(err.message);
      } else {
        setError("Unable to sign in right now. Verify the backend is reachable.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header
        className="flex items-center justify-end px-6 py-4"
        style={{ paddingTop: "max(1rem, env(safe-area-inset-top))" }}
      >
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-sm rounded-lg border border-line bg-surface p-7 shadow-sm">
          <div className="flex items-center gap-2">
            <span className="size-2 rounded-full bg-emerald-600" aria-hidden="true" />
            <h1 className="text-base font-semibold text-ink text-balance">
              X-VibeBot Control
            </h1>
          </div>
          <p className="mt-1.5 text-sm text-muted text-pretty">
            Sign in to manage platform spend, creators, and server memory.
          </p>

          {checkingSession ? (
            <div className="mt-6 space-y-4">
              <div className="space-y-1.5">
                <div className="h-3.5 w-24 rounded bg-line/70" />
                <div className="h-9 w-full rounded bg-line/50" />
              </div>
              <div className="space-y-1.5">
                <div className="h-3.5 w-20 rounded bg-line/70" />
                <div className="h-9 w-full rounded bg-line/50" />
              </div>
              <div className="h-9 w-full rounded bg-line/70" />
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
              <label className="block space-y-1.5">
                <span className="block text-xs font-medium text-ink">Admin email</span>
                <input
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@xbot.org"
                  className="h-9 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink placeholder:text-muted/70 focus:border-emerald-600 focus:outline-none"
                />
              </label>

              <label className="block space-y-1.5">
                <span className="block text-xs font-medium text-ink">Password</span>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter password"
                    className="h-9 w-full rounded-md border border-line bg-surface pl-3 pr-9 text-sm text-ink placeholder:text-muted/70 focus:border-emerald-600 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    className="absolute right-1 top-1/2 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded text-muted hover:text-ink"
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </label>

              <div className="space-y-2.5 pt-1">
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex h-9 w-full items-center justify-center rounded-md bg-ink px-4 text-sm font-medium text-canvas hover:opacity-90 disabled:opacity-50"
                >
                  {submitting ? "Signing in..." : "Sign in to portal"}
                </button>

                {error && (
                  <p role="alert" className="text-xs leading-relaxed text-red-600 dark:text-red-400">
                    {error}
                  </p>
                )}
              </div>
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
