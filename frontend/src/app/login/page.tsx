"use client";

import React, { useEffect, useState } from "react";
import AuthView from "@/components/AuthView";

export default function LoginPage() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [initialMode, setInitialMode] = useState<"signin" | "signup" | "forgot">("signin");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const savedTheme = localStorage.getItem("xvibebot_theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const effectiveTheme = savedTheme === "dark" || (!savedTheme && prefersDark) ? "dark" : "light";
      setTheme(effectiveTheme);
      document.documentElement.classList.toggle("dark", effectiveTheme === "dark");

      // Check URL query parameters
      const params = new URLSearchParams(window.location.search);
      const modeParam = params.get("mode");
      if (modeParam === "signup") {
        setInitialMode("signup");
      } else if (modeParam === "forgot") {
        setInitialMode("forgot");
      } else {
        setInitialMode("signin");
      }

      // If user landed here with a reset token by mistake, redirect to dedicated reset page
      const token = params.get("token") || params.get("reset_token");
      if (token) {
        window.location.href = `/reset-password?token=${encodeURIComponent(token)}`;
        return;
      }

      setMounted(true);
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (typeof window !== "undefined") {
      localStorage.setItem("xvibebot_theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
    }
  };

  const handleAuthenticated = (
    user: { uid: string; email?: string | null; displayName?: string | null; tenant_id?: string },
    token: string
  ) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("xvibebot_auth_token", token);
      localStorage.setItem("xvibebot_tenant_id", user.tenant_id || user.uid);
      if (user.email) localStorage.setItem("xvibebot_user_email", user.email);
      if (user.displayName) localStorage.setItem("xvibebot_user_name", user.displayName);
      window.location.href = "/";
    }
  };

  if (!mounted) {
    return (
      <div className="min-h-screen bg-[#FBFBFA] dark:bg-[#0A0A0A] flex items-center justify-center">
        <div className="w-5 h-5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className={theme === "dark" ? "dark" : ""}>
      <AuthView
        theme={theme}
        onToggleTheme={toggleTheme}
        initialMode={initialMode}
        onBack={() => {
          window.location.href = "/";
        }}
        onAuthenticated={handleAuthenticated}
      />
    </div>
  );
}
