"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles,
  Bot,
  Zap,
  ShieldCheck,
  Moon,
  Sun,
  ArrowRight,
  CheckCircle2,
  Clock,
  Key,
  Layers,
  ChevronRight,
  ChevronDown,
  Copy,
  Check,
  Terminal,
  MousePointer,
  Cpu,
  Fingerprint,
  Sliders,
  Send,
  Eye,
  Menu,
  X,
  ExternalLink,
  MessageSquare,
  Flame,
  HelpCircle,
  TrendingUp,
  UserCheck,
  RefreshCw,
  Lock,
  Compass,
} from "lucide-react";

interface LandingViewProps {
  onLaunchStudio: (mode?: "signin" | "signup") => void;
  theme?: "light" | "dark";
  onToggleTheme?: () => void;
}

// Preset tweets for the interactive vibe simulator
interface PresetTweet {
  id: string;
  category: string;
  icon: string;
  authorName: string;
  authorHandle: string;
  authorAvatar: string;
  verified: boolean;
  timeAgo: string;
  content: string;
  metrics: { replies: string; reposts: string; likes: string };
  vibes: {
    witty: { text: string; rationale: string; engagementScore: number };
    question: { text: string; rationale: string; engagementScore: number };
    punchy: { text: string; rationale: string; engagementScore: number };
  };
}

const PRESET_TWEETS: PresetTweet[] = [
  {
    id: "tech",
    category: "Tech Hot Take",
    icon: "🔥",
    authorName: "Pieter Levels",
    authorHandle: "levelsio",
    authorAvatar: "PL",
    verified: true,
    timeAgo: "22m",
    content:
      "Most SaaS products could be built in a single weekend with SQLite, plain HTML, and vanilla JS. Framework fatigue is reaching comical levels in 2026.",
    metrics: { replies: "148", reposts: "512", likes: "3.4K" },
    vibes: {
      witty: {
        text: "The ultimate full-stack framework is whatever keeps your server bill under $5/mo while the enterprise rewrites their microservices for the 4th time.",
        rationale: "Sharp indie-hacker humor that validates minimalist builders and drives quote-tweets.",
        engagementScore: 94,
      },
      question: {
        text: "What is the exact tipping point where you actually regretted skipping a framework? For me it's always real-time optimistic UI or multi-tenant RBAC.",
        rationale: "Constructive curiosity inviting high-status technical debate.",
        engagementScore: 91,
      },
      punchy: {
        text: "Complexity is sold by engineers who enjoy solving problems they invented for themselves.",
        rationale: "High-conviction aphorism designed for algorithmic bookmarking.",
        engagementScore: 96,
      },
    },
  },
  {
    id: "founder",
    category: "Founder Milestone",
    icon: "🚀",
    authorName: "Sahil Lavingia",
    authorHandle: "shl",
    authorAvatar: "SL",
    verified: true,
    timeAgo: "1h",
    content:
      "Just crossed $10k MRR after 9 months of near-zero traction. What changed? We killed automated blast DMs and started commenting on genuine creator discussions.",
    metrics: { replies: "89", reposts: "230", likes: "1.8K" },
    vibes: {
      witty: {
        text: "Turns out humans can smell generic 'Love what you're building!' bot comments from across the internet. Who would have guessed?",
        rationale: "Playfully calls out robotic behavior while praising the author's shift.",
        engagementScore: 95,
      },
      question: {
        text: "Did you target a strict list of 20 high-signal accounts daily, or was it purely organic timeline discovery?",
        rationale: "Tactical question founders love answering to showcase their playbook.",
        engagementScore: 89,
      },
      punchy: {
        text: "Authenticity doesn't scale on a spreadsheet, but its compounding returns crush any automated spam campaign.",
        rationale: "Resonant truth bomb that gets retweeted by creators.",
        engagementScore: 97,
      },
    },
  },
  {
    id: "ai",
    category: "AI Frontier",
    icon: "⚡",
    authorName: "Sam Altman",
    authorHandle: "sama",
    authorAvatar: "SA",
    verified: true,
    timeAgo: "3h",
    content:
      "The compute curve is unrelenting. A model capable of autonomous multi-repo code refactoring will be considered baseline table-stakes by the end of this year.",
    metrics: { replies: "612", reposts: "1.9K", likes: "9.2K" },
    vibes: {
      witty: {
        text: "Can't wait to explain to a 100B parameter neural net why my CSS flexbox is still refusing to center a div.",
        rationale: "Self-deprecating developer humor that breaks through corporate AI hype.",
        engagementScore: 98,
      },
      question: {
        text: "How do you foresee developer economics shifting once autonomous code audit agents run 24/7 without human review gates?",
        rationale: "Probing future-of-work query that invites technical executives to weigh in.",
        engagementScore: 93,
      },
      punchy: {
        text: "The winners won't be prompt engineers. They will be system architects who understand domain constraints.",
        rationale: "Authoritative contrarian perspective.",
        engagementScore: 95,
      },
    },
  },
];

const LANDING_FAQS = [
  {
    q: "Will my X account get shadowbanned?",
    a: "No. X-VibeBot uses randomized 45–180s delays, daily action caps, and circadian sleep so activity stays well within natural human browsing limits.",
  },
  {
    q: "How does it avoid sounding like an AI bot?",
    a: "It hard-bans 100+ overused AI phrases ('delve', 'game-changer', 'spot on') and continuously tunes its tone from your manual edits.",
  },
  {
    q: "Are my passwords safe?",
    a: "We never ask for your password. Sessions sync directly through AES-256 encrypted browser cookies in sandboxed containers.",
  },
  {
    q: "Can I approve replies before posting?",
    a: "Yes. The Smart Queue lets you review, edit, or reject drafts with 1 click before anything is scheduled.",
  },
  {
    q: "How much time will this save me?",
    a: "Review and approve 15–20 high-signal replies in under 10 minutes a day, without doomscrolling the feed.",
  },
];

export default function LandingView({
  onLaunchStudio,
  theme = "dark",
  onToggleTheme,
}: LandingViewProps) {
  // Mobile navigation state
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [openLandingFaq, setOpenLandingFaq] = useState<number | null>(0);

  // Simulator state
  const [selectedPresetId, setSelectedPresetId] = useState<string>("tech");
  const [customInputMode, setCustomInputMode] = useState(false);
  const [customTweetText, setCustomTweetText] = useState("");
  const [customVibes, setCustomVibes] = useState<{
    witty: { text: string; rationale: string; engagementScore: number };
    question: { text: string; rationale: string; engagementScore: number };
    punchy: { text: string; rationale: string; engagementScore: number };
  } | null>(null);
  const [selectedVibe, setSelectedVibe] = useState<"witty" | "question" | "punchy">("witty");
  const [isSimulatingGen, setIsSimulatingGen] = useState(false);
  const [copiedVibe, setCopiedVibe] = useState(false);
  const [simulatedQueueCount, setSimulatedQueueCount] = useState(4);
  const [showQueueToast, setShowQueueToast] = useState(false);

  // Active tweet data
  const activePreset = PRESET_TWEETS.find((t) => t.id === selectedPresetId) || PRESET_TWEETS[0];
  const activeVibes = customInputMode && customVibes ? customVibes : activePreset.vibes;
  const currentReply = activeVibes[selectedVibe];

  // Handle preset switch
  const handleSelectPreset = (id: string) => {
    setCustomInputMode(false);
    setSelectedPresetId(id);
    setIsSimulatingGen(true);
    setTimeout(() => {
      setIsSimulatingGen(false);
    }, 380);
  };

  // Generate for custom input
  const handleGenerateCustom = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customTweetText.trim()) return;

    setIsSimulatingGen(true);
    setCustomInputMode(true);

    setTimeout(() => {
      const trimmed = customTweetText.trim();
      const firstFew = trimmed.split(" ").slice(0, 4).join(" ");
      setCustomVibes({
        witty: {
          text: `The hot take isn't wrong, but wait until you see how the industry over-engineers the fix next quarter. Classic cycle.`,
          rationale: `Sharp industry perspective stripped of corporate AI clichés.`,
          engagementScore: 92,
        },
        question: {
          text: `Curious what the first signal was that made you realize this? Would love to hear the before/after metrics.`,
          rationale: `High-leverage conversational hook encouraging thread replies.`,
          engagementScore: 90,
        },
        punchy: {
          text: `Most people debate theory. The builders who actually ship and test ${firstFew}... are already five steps ahead.`,
          rationale: `Direct conviction statement built for retweets and bookmarks.`,
          engagementScore: 96,
        },
      });
      setIsSimulatingGen(false);
    }, 450);
  };

  const handleCopyReply = () => {
    if (!currentReply) return;
    navigator.clipboard.writeText(currentReply.text);
    setCopiedVibe(true);
    setTimeout(() => setCopiedVibe(false), 2000);
  };

  const handleSimulateQueue = () => {
    setSimulatedQueueCount((prev) => prev + 1);
    setShowQueueToast(true);
    setTimeout(() => setShowQueueToast(false), 3000);
  };

  return (
    <div className="min-h-dvh bg-[#FAFAFA] dark:bg-[#0E0E0E] text-[#111111] dark:text-[#F5F5F5] selection:bg-[#EA580C] selection:text-white transition-colors duration-200 overflow-x-hidden font-sans">
      {/* ─────────────────────────────────────────────────────────────
          1. STICKY GLASSMORPHISM HEADER
      ─────────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-white/85 dark:bg-[#0E0E0E]/85 border-b border-[#E4E4E7]/80 dark:border-[#262626]/80 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Brand Lockup */}
          <div className="flex items-center gap-3">
            <div className="relative group cursor-pointer flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-[#111111] dark:bg-[#18181A] border border-[#27272A] p-0.5 flex items-center justify-center shadow-[0_0_15px_rgba(234,88,12,0.25)] group-hover:shadow-[0_0_20px_rgba(234,88,12,0.45)] transition-all overflow-hidden">
                <img
                  src="/logos/logo_enhanced_chibi_bot.png"
                  alt="X-VibeBot Mascot"
                  className="w-full h-full object-cover rounded-lg group-hover:scale-110 transition-transform duration-300"
                />
              </div>
              <div className="flex flex-col">
                <div className="flex items-center gap-1.5">
                  <span className="font-display font-bold text-[16px] tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5]">
                    X-VibeBot
                  </span>
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-[#EA580C]/10 text-[#EA580C] border border-[#EA580C]/25">
                    v2.0
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-[10.5px] font-medium text-[#71717A] dark:text-[#8E8E8E]">
                    AI Agent Active
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Desktop Nav Links */}
          <nav className="hidden md:flex items-center gap-7 text-[13px] font-medium text-[#52525B] dark:text-[#A1A1AA]">
            <a
              href="#simulator"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Live Simulator
            </a>
            <a
              href="#bento"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Anti-Bot Engine
            </a>
            <a
              href="#comparison"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Why We're Different
            </a>
            <a
              href="#workflow"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              How It Works
            </a>
            <a
              href="#pricing"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors font-medium text-[#EA580C]"
            >
              Pricing
            </a>
            <a
              href="#faq"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              FAQ
            </a>
          </nav>

          {/* Right Action Buttons */}
          <div className="flex items-center gap-2.5">
            {/* Theme Toggle Button */}
            {onToggleTheme && (
              <button
                type="button"
                onClick={onToggleTheme}
                aria-label="Toggle dark/light theme"
                className="w-9 h-9 rounded-lg border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-center text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] transition-colors"
              >
                {theme === "light" ? (
                  <Moon className="w-4 h-4" />
                ) : (
                  <Sun className="w-4 h-4 text-amber-400" />
                )}
              </button>
            )}

            {/* Sign In Button */}
            <button
              type="button"
              onClick={() => onLaunchStudio("signin")}
              className="hidden sm:inline-flex h-9 px-3.5 items-center justify-center rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[13px] font-medium text-[#111111] dark:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1A1A1A] transition-colors"
            >
              Sign In
            </button>

            {/* Launch Studio CTA */}
            <button
              type="button"
              onClick={() => onLaunchStudio("signup")}
              className="h-9 px-4 rounded-lg bg-[#EA580C] hover:bg-[#D94F06] active:scale-[0.98] text-white text-[13px] font-semibold shadow-[0_2px_12px_rgba(234,88,12,0.35)] flex items-center gap-1.5 transition-all"
            >
              <span>Launch Studio</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>

            {/* Mobile Hamburger Toggle */}
            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden w-9 h-9 rounded-lg border border-[#E4E4E7] dark:border-[#262626] flex items-center justify-center text-[#52525B] dark:text-[#9E9E9E]"
              aria-label="Toggle navigation menu"
            >
              {mobileMenuOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown Menu */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="md:hidden border-b border-[#E4E4E7] dark:border-[#262626] bg-white dark:bg-[#121212] px-4 py-4 space-y-3"
            >
              <a
                href="#simulator"
                onClick={() => setMobileMenuOpen(false)}
                className="block text-[14px] font-medium text-[#52525B] dark:text-[#A1A1AA] hover:text-[#EA580C] py-1"
              >
                Live Simulator
              </a>
              <a
                href="#bento"
                onClick={() => setMobileMenuOpen(false)}
                className="block text-[14px] font-medium text-[#52525B] dark:text-[#A1A1AA] hover:text-[#EA580C] py-1"
              >
                Anti-Bot Engine
              </a>
              <a
                href="#comparison"
                onClick={() => setMobileMenuOpen(false)}
                className="block text-[14px] font-medium text-[#52525B] dark:text-[#A1A1AA] hover:text-[#EA580C] py-1"
              >
                Why We're Different
              </a>
              <a
                href="#workflow"
                onClick={() => setMobileMenuOpen(false)}
                className="block text-[14px] font-medium text-[#52525B] dark:text-[#A1A1AA] hover:text-[#EA580C] py-1"
              >
                How It Works
              </a>
              <a
                href="#pricing"
                onClick={() => setMobileMenuOpen(false)}
                className="block text-[14px] font-medium text-[#EA580C] py-1"
              >
                Pricing
              </a>
              <a
                href="#faq"
                onClick={() => setMobileMenuOpen(false)}
                className="block text-[14px] font-medium text-[#52525B] dark:text-[#A1A1AA] hover:text-[#EA580C] py-1"
              >
                FAQ
              </a>
              <div className="pt-2 border-t border-[#E4E4E7] dark:border-[#262626] flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    onLaunchStudio("signin");
                  }}
                  className="w-1/2 py-2 rounded-lg border border-[#E4E4E7] dark:border-[#262626] text-[13px] font-medium text-center"
                >
                  Sign In
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMobileMenuOpen(false);
                    onLaunchStudio("signup");
                  }}
                  className="w-1/2 py-2 rounded-lg bg-[#EA580C] text-white text-[13px] font-medium text-center"
                >
                  Get Started
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      {/* ─────────────────────────────────────────────────────────────
          2. MASCOT HERO SECTION
      ─────────────────────────────────────────────────────────────── */}
      <section className="relative pt-12 pb-20 md:pt-20 md:pb-32 overflow-hidden">
        {/* Subtle Background Radial Gradients */}
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] md:w-[840px] md:h-[840px] bg-gradient-to-tr from-[#EA580C]/12 via-[#06B6D4]/5 to-transparent rounded-full blur-3xl pointer-events-none" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
          <div className="grid lg:grid-cols-12 gap-12 lg:gap-8 items-center">
            {/* Left Column: Headline, Value Proposition, Action CTAs */}
            <div className="lg:col-span-7 space-y-6 text-center lg:text-left">
              {/* Badge: Autonomous Studio */}
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#EA580C]/10 dark:bg-[#EA580C]/15 border border-[#EA580C]/30 text-[#EA580C] text-[12px] font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-[#EA580C] animate-pulse" />
                <span>Autonomous X Growth Studio</span>
              </div>

              {/* Main Headline */}
              <h1 className="font-display text-[40px] sm:text-[52px] lg:text-[60px] font-extrabold leading-[1.06] tracking-[-0.035em] text-[#111111] dark:text-[#F5F5F5] text-balance">
                Grow on X without sounding like a{" "}
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#EA580C] via-[#F97316] to-[#06B6D4]">
                  bot.
                </span>
              </h1>

              {/* Subheadline: 1 crisp sentence */}
              <p className="text-[17px] sm:text-[19px] leading-[1.5] text-[#52525B] dark:text-[#A1A1AA] max-w-xl mx-auto lg:mx-0 text-pretty">
                Monitor niche conversations, draft in your authentic tone, and publish with human pacing.
              </p>

              {/* 3 High-Signal Feature Badges */}
              <div className="flex flex-wrap items-center justify-center lg:justify-start gap-2.5 pt-1 text-[12.5px] font-medium text-[#52525B] dark:text-[#A1A1AA]">
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white dark:bg-[#161619] border border-[#E4E4E7] dark:border-[#26262B]">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981] shrink-0" />
                  <span>45–180s human jitter</span>
                </div>
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white dark:bg-[#161619] border border-[#E4E4E7] dark:border-[#26262B]">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981] shrink-0" />
                  <span>Zero AI clichés</span>
                </div>
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white dark:bg-[#161619] border border-[#E4E4E7] dark:border-[#26262B]">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981] shrink-0" />
                  <span>Encrypted session sync</span>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-3.5 pt-2">
                <button
                  type="button"
                  onClick={() => onLaunchStudio("signup")}
                  className="w-full sm:w-auto h-11 px-6 rounded-xl bg-[#EA580C] hover:bg-[#D94F06] active:scale-[0.98] text-white font-semibold text-[14px] shadow-[0_4px_20px_rgba(234,88,12,0.35)] flex items-center justify-center gap-2 transition-all group"
                >
                  <span>Launch Studio Free</span>
                  <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                </button>

                <a
                  href="#simulator"
                  className="w-full sm:w-auto h-11 px-5 rounded-xl border border-[#E4E4E7] dark:border-[#262626] bg-white dark:bg-[#141416] hover:bg-[#F4F4F5] dark:hover:bg-[#1E1E22] text-[#111111] dark:text-[#F5F5F5] font-semibold text-[13.5px] flex items-center justify-center gap-2 transition-colors"
                >
                  <Sparkles className="w-3.5 h-3.5 text-[#EA580C]" />
                  <span>Live Simulator</span>
                </a>
              </div>

              {/* Micro Trust Note */}
              <div className="text-[12px] text-[#71717A] dark:text-[#787878] flex items-center justify-center lg:justify-start gap-3 pt-1">
                <span>No passwords stored</span>
                <span>•</span>
                <span>Sandboxed browser containers</span>
              </div>
            </div>

            {/* Right Column: Floating Mascot Centerpiece */}
            <div className="lg:col-span-5 relative flex items-center justify-center">
              {/* Backlight Ambient Glow */}
              <div className="absolute w-[280px] h-[280px] sm:w-[340px] sm:h-[340px] rounded-full bg-gradient-to-tr from-[#EA580C]/25 via-[#F97316]/20 to-[#06B6D4]/15 blur-2xl pointer-events-none animate-pulse" />

              {/* Framer-Motion Floating Container */}
              <motion.div
                animate={{
                  y: [-10, 10, -10],
                  rotate: [-1, 1, -1],
                }}
                transition={{
                  duration: 5,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
                className="relative z-10"
              >
                {/* Mascot Outer Ring Card */}
                <div className="relative p-3 rounded-3xl bg-white/70 dark:bg-[#161618]/80 border border-[#E4E4E7] dark:border-[#2C2C30] shadow-[0_12px_40px_rgba(0,0,0,0.12)] dark:shadow-[0_20px_60px_rgba(0,0,0,0.65)] backdrop-blur-md">
                  {/* Mascot Image */}
                  <div className="relative w-64 h-64 sm:w-72 sm:h-72 md:w-80 md:h-80 rounded-2xl overflow-hidden bg-gradient-to-b from-[#1C1C1F] to-[#0D0D0E] border border-[#2B2B30] flex items-center justify-center group">
                    <img
                      src="/logos/logo_enhanced_chibi_bot.png"
                      alt="X-VibeBot Mascot Character"
                      className="w-full h-full object-cover select-none drop-shadow-2xl group-hover:scale-105 transition-transform duration-500"
                    />

                    {/* Gradient Overlay Shine */}
                    <div className="absolute inset-0 bg-gradient-to-t from-[#0E0E0E]/80 via-transparent to-transparent pointer-events-none" />

                    {/* Internal Bottom Status Pill */}
                    <div className="absolute bottom-3 left-3 right-3 py-1.5 px-3 rounded-xl bg-[#0E0E0E]/90 border border-[#2E2E33] backdrop-blur-md flex items-center justify-between text-[11px]">
                      <div className="flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-ping" />
                        <span className="font-semibold text-white">Active</span>
                      </div>
                      <span className="font-mono text-[#A1A1AA]">42 queued</span>
                    </div>
                  </div>
                </div>

                {/* Satellite Floating Badge 1 (Top Left): Reading Delay */}
                <motion.div
                  animate={{ y: [6, -6, 6] }}
                  transition={{ duration: 4, repeat: Infinity, ease: "easeInOut", delay: 0.5 }}
                  className="absolute -top-4 -left-4 sm:-left-6 rounded-xl bg-white dark:bg-[#1C1C20] border border-[#E4E4E7] dark:border-[#2D2D35] px-3 py-2 shadow-lg backdrop-blur-md flex items-center gap-2 text-[12px]"
                >
                  <Clock className="w-3.5 h-3.5 text-[#10B981] shrink-0" />
                  <span className="font-medium text-[#111111] dark:text-[#F5F5F5]">Human jitter • 45s delay</span>
                </motion.div>

                {/* Satellite Floating Badge 2 (Bottom Right): Anti-Bot Persona */}
                <motion.div
                  animate={{ y: [-6, 6, -6] }}
                  transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut", delay: 1 }}
                  className="absolute -bottom-4 -right-4 sm:-right-6 rounded-xl bg-white dark:bg-[#1C1C20] border border-[#E4E4E7] dark:border-[#2D2D35] px-3 py-2 shadow-lg backdrop-blur-md flex items-center gap-2 text-[12px]"
                >
                  <Fingerprint className="w-3.5 h-3.5 text-[#EA580C] shrink-0" />
                  <span className="font-medium text-[#111111] dark:text-[#F5F5F5]">Zero clichés • Blocked</span>
                </motion.div>
              </motion.div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          3. INTERACTIVE LIVE VIBE SIMULATOR
      ─────────────────────────────────────────────────────────────── */}
      <section
        id="simulator"
        className="py-16 md:py-24 bg-white dark:bg-[#111113] border-y border-[#E4E4E7] dark:border-[#222225] relative scroll-mt-20"
      >
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Section Heading */}
          <div className="text-center max-w-2xl mx-auto space-y-2.5 mb-8">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#EA580C]/10 text-[#EA580C] text-[12px] font-semibold">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Live Simulator</span>
            </div>
            <h2 className="font-display text-[28px] sm:text-[36px] font-bold tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              See how it drafts in real time
            </h2>
            <p className="text-[15px] text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Select a conversation to preview replies without robotic filler.
            </p>
          </div>

          {/* Preset Picker Tabs */}
          <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3 mb-8">
            {PRESET_TWEETS.map((preset) => {
              const isSelected = !customInputMode && selectedPresetId === preset.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => handleSelectPreset(preset.id)}
                  className={`px-4 py-2 rounded-xl text-[13px] font-medium transition-all flex items-center gap-2 border ${
                    isSelected
                      ? "bg-[#111111] dark:bg-[#222226] text-white border-[#111111] dark:border-[#383840] shadow-sm"
                      : "bg-[#FAFAFA] dark:bg-[#18181A] text-[#52525B] dark:text-[#9E9E9E] border-[#E4E4E7] dark:border-[#26262A] hover:border-[#CBD5E1] dark:hover:border-[#333338]"
                  }`}
                >
                  <span>{preset.icon}</span>
                  <span>{preset.category}</span>
                </button>
              );
            })}

            <button
              type="button"
              onClick={() => {
                setCustomInputMode(true);
                if (!customTweetText) {
                  setCustomTweetText(
                    "Building in public is exhausting when every launch feels like shouting into the void. What is the one thing that actually drove early traction for you?"
                  );
                }
              }}
              className={`px-4 py-2 rounded-xl text-[13px] font-medium transition-all flex items-center gap-2 border ${
                customInputMode
                  ? "bg-[#111111] dark:bg-[#222226] text-white border-[#111111] dark:border-[#383840] shadow-sm"
                  : "bg-[#FAFAFA] dark:bg-[#18181A] text-[#52525B] dark:text-[#9E9E9E] border-[#E4E4E7] dark:border-[#26262A] hover:border-[#CBD5E1] dark:hover:border-[#333338]"
              }`}
            >
              <span>✍️</span>
              <span>Test Custom Tweet</span>
            </button>
          </div>

          {/* Custom Input Drawer (if open) */}
          <AnimatePresence>
            {customInputMode && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="max-w-2xl mx-auto mb-8 overflow-hidden"
              >
                <form
                  onSubmit={handleGenerateCustom}
                  className="rounded-2xl border border-[#EA580C]/40 bg-[#FAFAFA] dark:bg-[#161619] p-4 shadow-sm space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-semibold text-[#EA580C] flex items-center gap-1.5">
                      <Terminal className="w-3.5 h-3.5" />
                      <span>Paste Any Tweet Context</span>
                    </span>
                    <span className="text-[11px] text-[#71717A] dark:text-[#8E8E8E]">
                      Client-side simulation
                    </span>
                  </div>
                  <textarea
                    value={customTweetText}
                    onChange={(e) => setCustomTweetText(e.target.value)}
                    rows={2}
                    placeholder="Paste a tweet from your niche..."
                    className="w-full text-[13px] rounded-lg border border-[#E4E4E7] dark:border-[#2B2B30] bg-white dark:bg-[#0E0E0E] p-3 text-[#111111] dark:text-[#F5F5F5] focus:outline-none focus:ring-2 focus:ring-[#EA580C]"
                  />
                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isSimulatingGen || !customTweetText.trim()}
                      className="px-4 py-2 rounded-lg bg-[#EA580C] hover:bg-[#D94F06] disabled:opacity-50 text-white text-[12.5px] font-semibold flex items-center gap-1.5 transition-all"
                    >
                      {isSimulatingGen ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          <span>Drafting 3 Angles...</span>
                        </>
                      ) : (
                        <>
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>Generate 3 Vibe Angles</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Interactive Dual-Panel Demo Container */}
          <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-[#FAFAFA] dark:bg-[#16161A] p-5 sm:p-7 shadow-[0_12px_36px_rgba(0,0,0,0.06)] dark:shadow-[0_20px_50px_rgba(0,0,0,0.5)] grid lg:grid-cols-12 gap-7 items-start">
            {/* Left Side: Tweet Post Being Monitored */}
            <div className="lg:col-span-5 space-y-4">
              <div className="flex items-center justify-between text-[12px]">
                <div className="flex items-center gap-1.5 font-semibold text-[#71717A] dark:text-[#8E8E8E]">
                  <MessageSquare className="w-3.5 h-3.5 text-[#EA580C]" />
                  <span>Incoming Thread Signal</span>
                </div>
                <span className="px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-[#10B981]/15 text-[#10B981] border border-[#10B981]/30">
                  Radar Match 98%
                </span>
              </div>

              {/* Simulated Tweet Card */}
              <div className="rounded-xl bg-white dark:bg-[#1E1E23] border border-[#E4E4E7] dark:border-[#2D2D34] p-4 space-y-3 shadow-xs">
                {/* Tweet Author Lockup */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-[#EA580C] to-[#F97316] text-white font-bold text-[12px] flex items-center justify-center shadow-xs">
                      {customInputMode ? "YOU" : activePreset.authorAvatar}
                    </div>
                    <div>
                      <div className="flex items-center gap-1">
                        <span className="font-bold text-[13.5px] text-[#111111] dark:text-[#F5F5F5]">
                          {customInputMode ? "Demo Author" : activePreset.authorName}
                        </span>
                        {!customInputMode && activePreset.verified && (
                          <svg
                            className="w-3.5 h-3.5 text-[#1D9BF0] fill-current"
                            viewBox="0 0 24 24"
                          >
                            <path d="M22.5 12.5c0-1.58-.875-2.95-2.148-3.6.154-.435.238-.905.238-1.4 0-2.21-1.79-4-4-4-.495 0-.965.084-1.4.238C14.55 2.475 13.18 1.6 11.6 1.6c-1.58 0-2.95.875-3.6 2.148-.435-.154-.905-.238-1.4-.238-2.21 0-4 1.79-4 4 0 .495.084.965.238 1.4C1.575 9.55.7 10.92.7 12.5c0 1.58.875 2.95 2.148 3.6-.154.435-.238.905-.238 1.4 0 2.21 1.79 4 4 4 .495 0 .965-.084 1.4-.238C8.65 22.525 10.02 23.4 11.6 23.4c1.58 0 2.95-.875 3.6-2.148.435.154.905.238 1.4.238 2.21 0 4-1.79 4-4 0-.495-.084-.965-.238-1.4 1.273-.65 2.148-2.02 2.148-3.6zm-12.71 4.29l-3.58-3.58a.996.996 0 1 1 1.41-1.41l2.17 2.17 6.17-6.17a.996.996 0 1 1 1.41 1.41l-7.58 7.58z" />
                          </svg>
                        )}
                      </div>
                      <span className="text-[11.5px] text-[#71717A] dark:text-[#8E8E8E]">
                        @{customInputMode ? "creator_signal" : activePreset.authorHandle} •{" "}
                        {customInputMode ? "now" : activePreset.timeAgo}
                      </span>
                    </div>
                  </div>
                  <span className="text-[11px] font-mono text-[#71717A] dark:text-[#8E8E8E]">
                    12.4K views
                  </span>
                </div>

                {/* Tweet Body */}
                <p className="text-[13px] leading-[1.6] text-[#27272A] dark:text-[#D4D4D8]">
                  {customInputMode ? customTweetText : activePreset.content}
                </p>

                {/* Tweet Metrics Bar */}
                <div className="flex items-center gap-6 pt-2 border-t border-[#F4F4F5] dark:border-[#28282E] text-[11.5px] text-[#71717A] dark:text-[#8E8E8E]">
                  <span>💬 {customInputMode ? "32" : activePreset.metrics.replies}</span>
                  <span>🔄 {customInputMode ? "14" : activePreset.metrics.reposts}</span>
                  <span>❤️ {customInputMode ? "198" : activePreset.metrics.likes}</span>
                </div>
              </div>

              {/* Bot Pre-Flight Inspection */}
              <div className="rounded-xl border border-[#E4E4E7] dark:border-[#26262B] bg-white/70 dark:bg-[#141416]/70 p-3 space-y-2 text-[11.5px]">
                <div className="flex items-center justify-between text-[#71717A] dark:text-[#8E8E8E]">
                  <span className="flex items-center gap-1.5 font-medium">
                    <MousePointer className="w-3.5 h-3.5 text-[#06B6D4]" />
                    <span>Mouse Drift Simulation</span>
                  </span>
                  <span className="text-emerald-500 font-semibold font-mono">3.4s Bezier</span>
                </div>
                <div className="flex items-center justify-between text-[#71717A] dark:text-[#8E8E8E]">
                  <span className="flex items-center gap-1.5 font-medium">
                    <Clock className="w-3.5 h-3.5 text-amber-500" />
                    <span>Calculated Reading Delay</span>
                  </span>
                  <span className="text-[#111111] dark:text-white font-mono">28 seconds</span>
                </div>
                <div className="flex items-center justify-between text-[#71717A] dark:text-[#8E8E8E]">
                  <span className="flex items-center gap-1.5 font-medium">
                    <ShieldCheck className="w-3.5 h-3.5 text-[#10B981]" />
                    <span>Cliché Word Filter</span>
                  </span>
                  <span className="text-emerald-500 font-semibold">0% AI giveaway</span>
                </div>
              </div>
            </div>

            {/* Right Side: Vibe Angle Selector & Live Draft Output */}
            <div className="lg:col-span-7 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#EA580C] animate-pulse" />
                  <span className="text-[12.5px] font-semibold text-[#111111] dark:text-[#F5F5F5]">
                    Generated Vibe Angles
                  </span>
                </div>
                <span className="text-[11px] font-mono text-[#71717A] dark:text-[#8E8E8E]">
                  Model: Gemini Flash 3.8
                </span>
              </div>

              {/* 3 Vibe Angle Pill Selector */}
              <div className="grid grid-cols-3 gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedVibe("witty")}
                  className={`py-2 px-2.5 rounded-xl border text-center transition-all ${
                    selectedVibe === "witty"
                      ? "bg-[#EA580C]/15 border-[#EA580C] text-[#EA580C] font-semibold shadow-xs"
                      : "bg-white dark:bg-[#1E1E23] border-[#E4E4E7] dark:border-[#2C2C32] text-[#52525B] dark:text-[#9E9E9E] hover:border-[#CBD5E1]"
                  }`}
                >
                  <div className="text-[12px] flex items-center justify-center gap-1">
                    <span>⚡</span>
                    <span>Witty & Cynical</span>
                  </div>
                  <div className="text-[10px] opacity-75 mt-0.5">High virality</div>
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedVibe("question")}
                  className={`py-2 px-2.5 rounded-xl border text-center transition-all ${
                    selectedVibe === "question"
                      ? "bg-[#06B6D4]/15 border-[#06B6D4] text-[#06B6D4] font-semibold shadow-xs"
                      : "bg-white dark:bg-[#1E1E23] border-[#E4E4E7] dark:border-[#2C2C32] text-[#52525B] dark:text-[#9E9E9E] hover:border-[#CBD5E1]"
                  }`}
                >
                  <div className="text-[12px] flex items-center justify-center gap-1">
                    <span>💡</span>
                    <span>Deep Question</span>
                  </div>
                  <div className="text-[10px] opacity-75 mt-0.5">Sparks replies</div>
                </button>

                <button
                  type="button"
                  onClick={() => setSelectedVibe("punchy")}
                  className={`py-2 px-2.5 rounded-xl border text-center transition-all ${
                    selectedVibe === "punchy"
                      ? "bg-[#10B981]/15 border-[#10B981] text-[#10B981] font-semibold shadow-xs"
                      : "bg-white dark:bg-[#1E1E23] border-[#E4E4E7] dark:border-[#2C2C32] text-[#52525B] dark:text-[#9E9E9E] hover:border-[#CBD5E1]"
                  }`}
                >
                  <div className="text-[12px] flex items-center justify-center gap-1">
                    <span>🎯</span>
                    <span>Actionable Take</span>
                  </div>
                  <div className="text-[10px] opacity-75 mt-0.5">Bookmarks</div>
                </button>
              </div>

              {/* Active Vibe Output Preview Card */}
              <div className="rounded-xl bg-white dark:bg-[#19191D] border border-[#E4E4E7] dark:border-[#2D2D35] p-5 space-y-4 shadow-xs relative">
                {isSimulatingGen ? (
                  <div className="py-12 flex flex-col items-center justify-center gap-3 text-[#71717A] dark:text-[#8E8E8E]">
                    <RefreshCw className="w-6 h-6 animate-spin text-[#EA580C]" />
                    <span className="text-[13px] font-medium">Calibrating voice angles...</span>
                  </div>
                ) : (
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={`${selectedPresetId}-${selectedVibe}-${customInputMode}`}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.2 }}
                      className="space-y-3.5"
                    >
                      <div className="flex items-center justify-between text-[11.5px]">
                        <span className="font-semibold text-[#111111] dark:text-[#F5F5F5] flex items-center gap-1.5">
                          <Bot className="w-4 h-4 text-[#EA580C]" />
                          <span>Generated Reply Draft</span>
                        </span>
                        <span className="text-emerald-500 font-medium">
                          Engagement Index: {currentReply.engagementScore}/100
                        </span>
                      </div>

                      {/* Reply Text */}
                      <p className="text-[14px] leading-[1.65] font-medium text-[#111111] dark:text-[#F5F5F5] bg-[#FAFAFA] dark:bg-[#131315] p-4 rounded-lg border border-[#E4E4E7] dark:border-[#26262B]">
                        "{currentReply.text}"
                      </p>

                      {/* Editorial Rationale Note */}
                      <div className="flex items-start gap-2 text-[12px] text-[#52525B] dark:text-[#9E9E9E] pt-1">
                        <Flame className="w-4 h-4 text-[#EA580C] shrink-0 mt-0.5" />
                        <span>
                          <strong className="text-[#111111] dark:text-[#D4D4D8]">Angle Rationale:</strong>{" "}
                          {currentReply.rationale}
                        </span>
                      </div>
                    </motion.div>
                  </AnimatePresence>
                )}

                {/* Action Bar Under Reply */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[#F4F4F5] dark:border-[#26262B]">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleCopyReply}
                      className="h-8 px-3 rounded-lg border border-[#E4E4E7] dark:border-[#2B2B30] text-[12px] font-medium text-[#52525B] dark:text-[#9E9E9E] hover:text-[#111111] dark:hover:text-[#F5F5F5] hover:bg-[#F4F4F5] dark:hover:bg-[#1E1E22] flex items-center gap-1.5 transition-colors"
                    >
                      {copiedVibe ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-500" />
                          <span className="text-emerald-500 font-semibold">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>Copy Reply</span>
                        </>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={handleSimulateQueue}
                      className="h-8 px-3 rounded-lg bg-[#111111] dark:bg-[#27272C] text-white text-[12px] font-medium hover:bg-[#222226] flex items-center gap-1.5 transition-colors"
                    >
                      <Send className="w-3.5 h-3.5 text-[#EA580C]" />
                      <span>Simulate Post to Queue</span>
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => onLaunchStudio("signup")}
                    className="text-[12px] font-semibold text-[#EA580C] hover:underline flex items-center gap-1"
                  >
                    <span>Run this on your timeline →</span>
                  </button>
                </div>

                {/* Queue Toast Confirmation */}
                <AnimatePresence>
                  {showQueueToast && (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -5 }}
                      className="absolute -top-3 right-4 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-[11.5px] font-medium shadow-lg flex items-center gap-2"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Queued! Approval queue now has {simulatedQueueCount} items</span>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          4. MODERN ASYMMETRICAL BENTO GRID
      ─────────────────────────────────────────────────────────────── */}
      <section id="bento" className="py-20 md:py-28 relative scroll-mt-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Bento Header */}
          <div className="text-center max-w-2xl mx-auto space-y-2.5 mb-12">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#EA580C]/10 text-[#EA580C] text-[12px] font-semibold">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Zero Detection</span>
            </div>
            <h2 className="font-display text-[30px] sm:text-[38px] font-bold tracking-[-0.035em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              Engineered to stay undetected
            </h2>
            <p className="text-[15px] text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Real browser automation with human-speed delays, circadian sleep, and encrypted session containers.
            </p>
          </div>

          {/* Bento Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {/* Card 1: Anti-Bot Natural Browsing & Ghost Typing (Span 2 cols on lg) */}
            <div className="lg:col-span-2 rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 sm:p-7 shadow-xs hover:border-[#EA580C]/40 transition-colors space-y-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3.5">
                  <div className="w-9 h-9 rounded-xl bg-[#EA580C]/10 text-[#EA580C] flex items-center justify-center">
                    <MousePointer className="w-4 h-4" />
                  </div>
                  <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-[#F4F4F5] dark:bg-[#1E1E22] text-[#71717A] dark:text-[#A1A1AA] border border-[#E4E4E7] dark:border-[#2D2D33]">
                    Human Pacing
                  </span>
                </div>
                <h3 className="font-display text-[20px] sm:text-[22px] font-bold text-[#111111] dark:text-[#F5F5F5] mb-1.5">
                  Natural Browsing, Drift & Keystroke Jitter
                </h3>
                <p className="text-[14px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  Real Chromium instances execute micro-scrolls, calculate natural reading durations (18s–45s), and type character-by-character.
                </p>
              </div>

              {/* Visualized Timeline Strip */}
              <div className="rounded-xl bg-[#FAFAFA] dark:bg-[#1B1B1F] border border-[#E4E4E7] dark:border-[#27272D] p-3.5 space-y-2.5">
                <div className="text-[11px] font-semibold text-[#71717A] dark:text-[#8E8E8E] flex items-center justify-between">
                  <span>Simulated Session Timeline</span>
                  <span className="text-emerald-500 font-mono">46.2s total</span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-[11px] text-center">
                  <div className="p-2 rounded-lg bg-white dark:bg-[#24242A] border border-[#E4E4E7] dark:border-[#303038]">
                    <div className="font-semibold text-[#111111] dark:text-[#F5F5F5]">Read</div>
                    <div className="text-[10px] text-[#EA580C] mt-0.5">22s wait</div>
                  </div>
                  <div className="p-2 rounded-lg bg-white dark:bg-[#24242A] border border-[#E4E4E7] dark:border-[#303038]">
                    <div className="font-semibold text-[#111111] dark:text-[#F5F5F5]">Scroll</div>
                    <div className="text-[10px] text-[#06B6D4] mt-0.5">Mouse drift</div>
                  </div>
                  <div className="p-2 rounded-lg bg-white dark:bg-[#24242A] border border-[#E4E4E7] dark:border-[#303038]">
                    <div className="font-semibold text-[#111111] dark:text-[#F5F5F5]">Like?</div>
                    <div className="text-[10px] text-emerald-500 mt-0.5">40% ratio</div>
                  </div>
                  <div className="p-2 rounded-lg bg-white dark:bg-[#24242A] border border-[#E4E4E7] dark:border-[#303038]">
                    <div className="font-semibold text-[#111111] dark:text-[#F5F5F5]">Type</div>
                    <div className="text-[10px] text-purple-400 mt-0.5">48 wpm</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Card 2: Randomized Sleep & Waking Hours (Span 1 col) */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 sm:p-7 shadow-xs hover:border-[#EA580C]/40 transition-colors space-y-4 flex flex-col justify-between">
              <div>
                <div className="w-9 h-9 rounded-xl bg-[#06B6D4]/10 text-[#06B6D4] flex items-center justify-center mb-3.5">
                  <Moon className="w-4 h-4" />
                </div>
                <h3 className="font-display text-[19px] sm:text-[20px] font-bold text-[#111111] dark:text-[#F5F5F5] mb-1.5">
                  Circadian Sleep Hours
                </h3>
                <p className="text-[13.5px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  Humans don't tweet at 3:42 AM. Configure active hours with randomized wake-time jitter to match real biology.
                </p>
              </div>

              {/* Visualized Circadian Dial */}
              <div className="rounded-xl bg-[#FAFAFA] dark:bg-[#1B1B1F] border border-[#E4E4E7] dark:border-[#27272D] p-3 space-y-2">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-[#71717A] dark:text-[#8E8E8E]">Quiet Window</span>
                  <span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 font-mono text-[10px]">
                    23:00 → 07:45
                  </span>
                </div>
                <div className="w-full bg-[#E4E4E7] dark:bg-[#2A2A30] h-2 rounded-full overflow-hidden flex">
                  <div className="w-1/3 bg-blue-500/60" />
                  <div className="w-2/3 bg-gradient-to-r from-amber-500 to-[#EA580C]" />
                </div>
                <div className="flex justify-between text-[10px] text-[#71717A] dark:text-[#8E8E8E] font-mono">
                  <span>Sleep</span>
                  <span>Active Window</span>
                </div>
              </div>
            </div>

            {/* Card 3: 1-Click Cookie Cloud Sync (Span 1 col) */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 sm:p-7 shadow-xs hover:border-[#EA580C]/40 transition-colors space-y-4 flex flex-col justify-between">
              <div>
                <div className="w-9 h-9 rounded-xl bg-[#10B981]/10 text-[#10B981] flex items-center justify-center mb-3.5">
                  <Lock className="w-4 h-4" />
                </div>
                <h3 className="font-display text-[19px] sm:text-[20px] font-bold text-[#111111] dark:text-[#F5F5F5] mb-1.5">
                  Cloud Cookie Sync
                </h3>
                <p className="text-[13.5px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  Export session cookies directly from your browser. Zero master passwords stored or transmitted.
                </p>
              </div>

              {/* Visualized Cookie Sync Graphic */}
              <div className="rounded-xl bg-[#FAFAFA] dark:bg-[#1B1B1F] border border-[#E4E4E7] dark:border-[#27272D] p-3 flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-2">
                  <Key className="w-4 h-4 text-emerald-500" />
                  <div>
                    <div className="font-semibold text-[#111111] dark:text-[#F5F5F5]">
                      Isolated Container
                    </div>
                    <div className="text-[10px] text-[#71717A]">AES-256 Encrypted</div>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-medium text-[10px]">
                  Connected
                </span>
              </div>
            </div>

            {/* Card 4: Multi-Angle AI Persona & Cliché Stripping (Span 2 cols on lg) */}
            <div className="lg:col-span-2 rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 sm:p-7 shadow-xs hover:border-[#EA580C]/40 transition-colors space-y-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3.5">
                  <div className="w-9 h-9 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center">
                    <Fingerprint className="w-4 h-4" />
                  </div>
                  <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">
                    Voice Calibration
                  </span>
                </div>
                <h3 className="font-display text-[20px] sm:text-[22px] font-bold text-[#111111] dark:text-[#F5F5F5] mb-1.5">
                  Zero Clichés • Tunes to Your Edits
                </h3>
                <p className="text-[14px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  Hard-bans 100+ AI buzzwords. Whenever you edit a draft in the studio queue, it mirrors your vocabulary.
                </p>
              </div>

              {/* Stripped Words Tag Cloud */}
              <div className="rounded-xl bg-[#FAFAFA] dark:bg-[#1B1B1F] border border-[#E4E4E7] dark:border-[#27272D] p-3 space-y-2">
                <div className="text-[10.5px] font-semibold text-[#71717A] dark:text-[#8E8E8E]">
                  Blocked Buzzwords:
                </div>
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  <span className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 line-through">
                    &quot;Delve into&quot;
                  </span>
                  <span className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 line-through">
                    &quot;Indeed!&quot;
                  </span>
                  <span className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 line-through">
                    &quot;Game-changer&quot;
                  </span>
                  <span className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 line-through">
                    &quot;Kudos to the team&quot;
                  </span>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-medium">
                    ✓ High-signal opinion
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          5. COMPARISON TABLE: Generic Bots vs X-VibeBot
      ─────────────────────────────────────────────────────────────── */}
      <section
        id="comparison"
        className="py-16 md:py-24 bg-white dark:bg-[#111113] border-t border-[#E4E4E7] dark:border-[#222225] scroll-mt-20"
      >
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-xl mx-auto space-y-2.5 mb-10">
            <h2 className="font-display text-[28px] sm:text-[34px] font-bold tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              Why builders choose X-VibeBot
            </h2>
            <p className="text-[15px] text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Browser isolation vs. generic cloud spam tools.
            </p>
          </div>

          {/* Side-by-Side Comparison Matrix */}
          <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-[#FAFAFA] dark:bg-[#161619] overflow-hidden shadow-xs">
            <div className="grid grid-cols-12 bg-[#F4F4F5] dark:bg-[#1E1E23] px-5 py-3 text-[12.5px] font-semibold border-b border-[#E4E4E7] dark:border-[#26262B]">
              <div className="col-span-4 text-[#52525B] dark:text-[#9E9E9E]">Feature</div>
              <div className="col-span-4 text-rose-500">Generic Bots</div>
              <div className="col-span-4 text-[#EA580C] font-bold flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                <span>X-VibeBot</span>
              </div>
            </div>

            {/* Row 1 */}
            <div className="grid grid-cols-12 px-5 py-3.5 text-[13px] border-b border-[#E4E4E7] dark:border-[#222226] items-center">
              <div className="col-span-4 font-medium text-[#111111] dark:text-[#F5F5F5]">
                Account Safety
              </div>
              <div className="col-span-4 text-[#71717A] dark:text-[#8E8E8E] text-[12.5px]">
                High shadowban risk
              </div>
              <div className="col-span-4 text-emerald-500 font-semibold text-[12.5px] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>Undetected (Human jitter)</span>
              </div>
            </div>

            {/* Row 2 */}
            <div className="grid grid-cols-12 px-5 py-3.5 text-[13px] border-b border-[#E4E4E7] dark:border-[#222226] items-center">
              <div className="col-span-4 font-medium text-[#111111] dark:text-[#F5F5F5]">
                Reply Tone
              </div>
              <div className="col-span-4 text-[#71717A] dark:text-[#8E8E8E] text-[12.5px]">
                Cliché praise (&quot;Spot on! 🚀&quot;)
              </div>
              <div className="col-span-4 text-emerald-500 font-semibold text-[12.5px] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>Contextual &amp; opinionated</span>
              </div>
            </div>

            {/* Row 3 */}
            <div className="grid grid-cols-12 px-5 py-3.5 text-[13px] border-b border-[#E4E4E7] dark:border-[#222226] items-center">
              <div className="col-span-4 font-medium text-[#111111] dark:text-[#F5F5F5]">
                Credentials
              </div>
              <div className="col-span-4 text-[#71717A] dark:text-[#8E8E8E] text-[12.5px]">
                Requires X password
              </div>
              <div className="col-span-4 text-emerald-500 font-semibold text-[12.5px] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>Cookie sync (0 passwords)</span>
              </div>
            </div>

            {/* Row 4 */}
            <div className="grid grid-cols-12 px-5 py-3.5 text-[13px] border-b border-[#E4E4E7] dark:border-[#222226] items-center">
              <div className="col-span-4 font-medium text-[#111111] dark:text-[#F5F5F5]">
                Pacing
              </div>
              <div className="col-span-4 text-[#71717A] dark:text-[#8E8E8E] text-[12.5px]">
                24/7 repetitive bursts
              </div>
              <div className="col-span-4 text-emerald-500 font-semibold text-[12.5px] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>Circadian sleep schedule</span>
              </div>
            </div>

            {/* Row 5 */}
            <div className="grid grid-cols-12 px-5 py-3.5 text-[13px] items-center">
              <div className="col-span-4 font-medium text-[#111111] dark:text-[#F5F5F5]">
                Control
              </div>
              <div className="col-span-4 text-[#71717A] dark:text-[#8E8E8E] text-[12.5px]">
                Uncontrolled auto-spam
              </div>
              <div className="col-span-4 text-emerald-500 font-semibold text-[12.5px] flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>Queue review or autopilot</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          6. WORKFLOW STEPS ("How It Works in 3 Steps")
      ─────────────────────────────────────────────────────────────── */}
      <section id="workflow" className="py-20 md:py-24 relative scroll-mt-20">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-xl mx-auto space-y-2.5 mb-12">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#EA580C]/10 text-[#EA580C] text-[12px] font-semibold">
              <Zap className="w-3.5 h-3.5" />
              <span>Simple Setup</span>
            </div>
            <h2 className="font-display text-[28px] sm:text-[34px] font-bold tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              Up and running in 3 steps
            </h2>
            <p className="text-[15px] text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Connect your session and start showing up in discussions.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-6">
            {/* Step 1 */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 space-y-3 shadow-xs">
              <div className="w-8 h-8 rounded-lg bg-[#EA580C] text-white font-display font-bold flex items-center justify-center text-[14px]">
                1
              </div>
              <h3 className="font-display text-[17px] font-bold text-[#111111] dark:text-[#F5F5F5]">
                Connect Session
              </h3>
              <p className="text-[13.5px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                Sync browser cookies in one click. Zero passwords stored or transmitted.
              </p>
            </div>

            {/* Step 2 */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 space-y-3 shadow-xs">
              <div className="w-8 h-8 rounded-lg bg-[#06B6D4] text-white font-display font-bold flex items-center justify-center text-[14px]">
                2
              </div>
              <h3 className="font-display text-[17px] font-bold text-[#111111] dark:text-[#F5F5F5]">
                Listen on Radar
              </h3>
              <p className="text-[13.5px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                Track niche topics. High-signal threads are drafted automatically in your voice.
              </p>
            </div>

            {/* Step 3 */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#26262B] bg-white dark:bg-[#141416] p-6 space-y-3 shadow-xs">
              <div className="w-8 h-8 rounded-lg bg-[#10B981] text-white font-display font-bold flex items-center justify-center text-[14px]">
                3
              </div>
              <h3 className="font-display text-[17px] font-bold text-[#111111] dark:text-[#F5F5F5]">
                Review or Autopilot
              </h3>
              <p className="text-[13.5px] text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                Approve drafts in 1 click, or let safe autopilot publish on your sleep schedule.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          6.5 FREQUENTLY ASKED QUESTIONS (FAQ)
      ─────────────────────────────────────────────────────────────── */}
      <section id="faq" className="py-20 md:py-24 bg-[#FAFAFA] dark:bg-[#0E0E0E] border-t border-[#E4E4E7] dark:border-[#222225] relative scroll-mt-20">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 space-y-10">
          <div className="text-center max-w-xl mx-auto space-y-2.5">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#EA580C]/10 text-[#EA580C] text-[12px] font-semibold">
              <HelpCircle className="w-3.5 h-3.5" />
              <span>FAQ</span>
            </div>
            <h2 className="font-display text-[28px] sm:text-[34px] font-bold tracking-[-0.03em] text-[#111111] dark:text-[#F5F5F5] text-balance">
              Frequently asked questions
            </h2>
            <p className="text-[15px] text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Safety, voice calibration, and daily workflow.
            </p>
          </div>

          <div className="space-y-2.5">
            {LANDING_FAQS.map((faq, idx) => {
              const isOpen = openLandingFaq === idx;
              return (
                <div
                  key={idx}
                  className="rounded-xl border border-[#E4E4E7] dark:border-[#262626] bg-white dark:bg-[#141416] overflow-hidden transition-all shadow-xs"
                >
                  <button
                    type="button"
                    onClick={() => setOpenLandingFaq(isOpen ? null : idx)}
                    className="w-full p-4 sm:p-5 text-left flex items-center justify-between gap-4 hover:bg-[#F8F8F9] dark:hover:bg-[#18181A] transition-colors"
                  >
                    <span className="text-[14.5px] sm:text-[15px] font-semibold text-[#111111] dark:text-[#F5F5F5] leading-snug">
                      {faq.q}
                    </span>
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 border border-[#E4E4E7] dark:border-[#2C2C30] transition-transform duration-200 ${
                        isOpen ? "rotate-180 bg-[#EA580C] text-white border-transparent" : "text-[#71717A]"
                      }`}
                    >
                      <ChevronDown className="w-3.5 h-3.5" />
                    </div>
                  </button>
                  {isOpen && (
                    <div className="px-4 pb-4 sm:px-5 sm:pb-5 pt-1 text-[13.5px] leading-relaxed text-[#52525B] dark:text-[#A1A1AA] border-t border-[#E4E4E7]/60 dark:border-[#222225]">
                      {faq.a}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          6.5 PRICING & SUBSCRIPTION PACKAGES
      ─────────────────────────────────────────────────────────────── */}
      <section id="pricing" className="py-24 bg-white dark:bg-[#0E0E0E] border-t border-[#E4E4E7] dark:border-[#222225] transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-12">
          <div className="text-center max-w-2xl mx-auto space-y-3">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#EA580C]/10 dark:bg-[#EA580C]/15 border border-[#EA580C]/30 text-[#EA580C] text-[12px] font-semibold">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Transparent & Fair Pricing</span>
            </div>
            <h2 className="font-display text-[28px] sm:text-[36px] font-bold tracking-tight text-[#111111] dark:text-[#F5F5F5] text-balance">
              Simple plans for creators at every scale
            </h2>
            <p className="text-[14.5px] text-[#52525B] dark:text-[#A1A1AA] text-pretty">
              Every plan includes Full Autopilot and safe human-mimicking jitter. Start free with 15,000 daily tokens.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* Free Trial */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#262626] bg-[#FAFAFA] dark:bg-[#141416] p-6 flex flex-col justify-between space-y-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-bold text-[#111111] dark:text-[#F5F5F5]">Free 7-Day Trial</h3>
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                    7 Days
                  </span>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-extrabold text-[#111111] dark:text-[#F5F5F5]">$0</span>
                  <span className="text-xs text-[#71717A] dark:text-[#8E8E8E]">/ 7 days</span>
                </div>
                <p className="text-xs text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  Test-drive the full studio with zero commitment. No credit card required.
                </p>
                <div className="pt-2 border-t border-[#E4E4E7] dark:border-[#222225] space-y-2.5 text-xs text-[#52525B] dark:text-[#D4D4D8]">
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span><strong>15,000</strong> tokens / day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>Up to 10 daily interactions</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>2 auto original posts/day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>Full Autopilot + Review Queue</span>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onLaunchStudio("signup")}
                className="w-full h-10 rounded-xl border border-[#E4E4E7] dark:border-[#2D2D35] bg-white dark:bg-[#1E1E22] hover:bg-[#F4F4F5] dark:hover:bg-[#28282E] text-[#111111] dark:text-[#F5F5F5] font-semibold text-xs transition-colors"
              >
                Start Free Trial
              </button>
            </div>

            {/* Starter */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#262626] bg-[#FAFAFA] dark:bg-[#141416] p-6 flex flex-col justify-between space-y-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-bold text-[#111111] dark:text-[#F5F5F5]">Starter</h3>
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                    Solo Builders
                  </span>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-extrabold text-[#111111] dark:text-[#F5F5F5]">$9</span>
                  <span className="text-xs text-[#71717A] dark:text-[#8E8E8E]">/ month</span>
                </div>
                <p className="text-xs text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  For creators building momentum with steady, consistent daily presence.
                </p>
                <div className="pt-2 border-t border-[#E4E4E7] dark:border-[#222225] space-y-2.5 text-xs text-[#52525B] dark:text-[#D4D4D8]">
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span><strong>50,000</strong> tokens / day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>Up to 15 daily interactions</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>3 auto original posts/day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    <span>Full Autopilot + Review Queue</span>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onLaunchStudio("signup")}
                className="w-full h-10 rounded-xl border border-[#E4E4E7] dark:border-[#2D2D35] bg-white dark:bg-[#1E1E22] hover:bg-[#F4F4F5] dark:hover:bg-[#28282E] text-[#111111] dark:text-[#F5F5F5] font-semibold text-xs transition-colors"
              >
                Choose Starter
              </button>
            </div>

            {/* Creator Pro */}
            <div className="rounded-2xl border-2 border-[#EA580C] bg-white dark:bg-[#18181B] p-6 flex flex-col justify-between space-y-6 shadow-lg shadow-[#EA580C]/10 relative">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-[#EA580C] text-white text-[10.5px] font-bold tracking-wide uppercase shadow-xs">
                Most Popular
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-bold text-[#111111] dark:text-[#F5F5F5]">Creator Pro</h3>
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[#EA580C]/15 text-[#EA580C] border border-[#EA580C]/30">
                    Power Creators
                  </span>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-extrabold text-[#111111] dark:text-[#F5F5F5]">$24</span>
                  <span className="text-xs text-[#71717A] dark:text-[#8E8E8E]">/ month</span>
                </div>
                <p className="text-xs text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  For active founders scaling niche authority, high reply reach, and daily threads.
                </p>
                <div className="pt-2 border-t border-[#E4E4E7] dark:border-[#222225] space-y-2.5 text-xs text-[#52525B] dark:text-[#D4D4D8]">
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-[#EA580C] shrink-0" />
                    <span><strong>150,000</strong> tokens / day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-[#EA580C] shrink-0" />
                    <span>Up to 35 daily interactions</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-[#EA580C] shrink-0" />
                    <span>6 auto original posts/day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-[#EA580C] shrink-0" />
                    <span>Full Autopilot + 12-Draft Queue</span>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onLaunchStudio("signup")}
                className="w-full h-10 rounded-xl bg-[#EA580C] hover:bg-[#D94F06] text-white font-semibold text-xs shadow-md shadow-[#EA580C]/25 transition-all"
              >
                Choose Creator Pro
              </button>
            </div>

            {/* Growth */}
            <div className="rounded-2xl border border-[#E4E4E7] dark:border-[#262626] bg-[#FAFAFA] dark:bg-[#141416] p-6 flex flex-col justify-between space-y-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-bold text-[#111111] dark:text-[#F5F5F5]">Growth</h3>
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                    High Velocity
                  </span>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-extrabold text-[#111111] dark:text-[#F5F5F5]">$59</span>
                  <span className="text-xs text-[#71717A] dark:text-[#8E8E8E]">/ month</span>
                </div>
                <p className="text-xs text-[#52525B] dark:text-[#A1A1AA] leading-relaxed">
                  Maximum throughput, priority feed radar scans, and unlimited manual drafting.
                </p>
                <div className="pt-2 border-t border-[#E4E4E7] dark:border-[#222225] space-y-2.5 text-xs text-[#52525B] dark:text-[#D4D4D8]">
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-purple-500 shrink-0" />
                    <span><strong>400,000</strong> tokens / day</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-purple-500 shrink-0" />
                    <span>Up to 50 daily interactions</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-purple-500 shrink-0" />
                    <span>6 auto posts + unlimited manual</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check className="w-3.5 h-3.5 text-purple-500 shrink-0" />
                    <span>Priority radar + 20-Draft Queue</span>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onLaunchStudio("signup")}
                className="w-full h-10 rounded-xl border border-[#E4E4E7] dark:border-[#2D2D35] bg-white dark:bg-[#1E1E22] hover:bg-[#F4F4F5] dark:hover:bg-[#28282E] text-[#111111] dark:text-[#F5F5F5] font-semibold text-xs transition-colors"
              >
                Choose Growth
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          7. BOTTOM CALL TO ACTION BANNER
      ─────────────────────────────────────────────────────────────── */}
      <section className="py-20 bg-gradient-to-b from-white to-[#F4F4F5] dark:from-[#111113] dark:to-[#09090A] border-t border-[#E4E4E7] dark:border-[#222225] relative overflow-hidden">
        {/* Glow backdrop */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[300px] bg-[#EA580C]/15 rounded-full blur-3xl pointer-events-none" />

        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 text-center space-y-5 relative z-10">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-[#18181A] border border-[#2D2D35] p-1 shadow-xl flex items-center justify-center overflow-hidden">
            <img
              src="/logos/logo_enhanced_chibi_bot.png"
              alt="X-VibeBot Mascot"
              className="w-full h-full object-cover"
            />
          </div>

          <h2 className="font-display text-[30px] sm:text-[40px] font-extrabold tracking-[-0.035em] text-[#111111] dark:text-[#F5F5F5] text-balance">
            Start growing on X today
          </h2>

          <p className="text-[15px] sm:text-[16px] text-[#52525B] dark:text-[#A1A1AA] max-w-lg mx-auto text-pretty">
            Put an authentic AI companion in your corner and show up in the conversations that matter.
          </p>

          <div className="pt-2">
            <button
              type="button"
              onClick={() => onLaunchStudio("signup")}
              className="h-12 px-7 rounded-xl bg-[#EA580C] hover:bg-[#D94F06] active:scale-[0.98] text-white font-semibold text-[14.5px] shadow-[0_4px_24px_rgba(234,88,12,0.35)] inline-flex items-center gap-2 transition-all"
            >
              <span>Launch Studio Free</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>

          <div className="text-[12px] text-[#71717A] dark:text-[#787878]">
            No credit card required • 60-second setup
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          8. CLEAN MONOCHROME FOOTER
      ─────────────────────────────────────────────────────────────── */}
      <footer className="border-t border-[#E4E4E7] dark:border-[#222225] bg-white dark:bg-[#0E0E0E] py-12 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col md:flex-row items-center justify-between gap-6 text-[13px] text-[#71717A] dark:text-[#8E8E8E]">
          {/* Brand Left */}
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-[#111111] dark:bg-[#18181A] border border-[#27272A] p-0.5 flex items-center justify-center overflow-hidden">
              <img
                src="/logos/logo_enhanced_chibi_bot.png"
                alt="Logo Icon"
                className="w-full h-full object-cover"
              />
            </div>
            <span className="font-display font-semibold text-[#111111] dark:text-[#F5F5F5]">
              X-VibeBot Studio
            </span>
            <span>•</span>
            <span>© {new Date().getFullYear()} Autonomous Social Agent</span>
          </div>

          {/* Links Right */}
          <div className="flex items-center gap-6">
            <a
              href="#simulator"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Simulator
            </a>
            <a
              href="#bento"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Architecture
            </a>
            <a
              href="#pricing"
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Pricing
            </a>
            <button
              type="button"
              onClick={() => onLaunchStudio("signin")}
              className="hover:text-[#111111] dark:hover:text-[#F5F5F5] transition-colors"
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => onLaunchStudio("signup")}
              className="text-[#EA580C] hover:underline font-semibold"
            >
              Launch Studio
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
