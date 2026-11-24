"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/cn";

interface ThemeToggleProps {
  className?: string;
}

export function ThemeToggle({ className }: ThemeToggleProps) {
  const [isDark, setIsDark] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function handleToggle() {
    const nextDark = !isDark;
    setIsDark(nextDark);
    document.documentElement.classList.toggle("dark", nextDark);
    try {
      window.localStorage.setItem("xvibebot_admin_theme", nextDark ? "dark" : "light");
    } catch {
      // Ignore storage failures
    }
  }

  return (
    <button
      type="button"
      onClick={handleToggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-md border border-line bg-surface text-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/40",
        className
      )}
    >
      {mounted && isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}
