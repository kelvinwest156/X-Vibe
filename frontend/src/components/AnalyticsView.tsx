"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2,
  RefreshCw,
  Sparkles,
  ShieldCheck,
  Brain,
  ChevronDown,
  ChevronUp,
  TrendingUp,
  Activity,
  Layers,
  ArrowUpRight,
} from "lucide-react";

export interface AnalyticsData {
  kpis: {
    total_evaluated: number;
    published_count: number;
    scheduled_count: number;
    pending_count: number;
    skipped_count: number;
    failed_count: number;
    approval_rate: number;
    feed_likes_captured: number;
    feed_replies_captured: number;
    avg_engagement_score: number;
    avg_draft_length: number;
    daily_used: number;
    daily_cap: number;
    hourly_used?: number;
    hourly_cap?: number;
    learned_examples_count?: number;
  };
  strategy_brief?: {
    headline: string;
    insight: string;
    recommended_action: string;
    suggested_query: string;
  };
  learning_memory?: {
    approved: Array<{ tweet_text: string; reply_text: string; user_edited: boolean }>;
    skipped: Array<{ tweet_text: string; reason: string }>;
    total_learned: number;
  };
  velocity_shield?: {
    hourly_used: number;
    hourly_cap: number;
    daily_used: number;
    daily_cap: number;
    warmup_mode: boolean;
    smart_query_enabled: boolean;
    active_search_query: string;
    learned_examples_count: number;
  };
  content_mix: Array<{ label: string; key: string; count: number; color?: string }>;
  status_funnel: Array<{ label: string; count: number; color?: string }>;
  length_distribution: Array<{ label: string; count: number; color?: string }>;
  timeline: Array<{ time: string; evaluated: number; drafted: number; engagement: number }>;
  top_authors: Array<{
    author: string;
    interactions: number;
    likes: number;
    replies: number;
    score: number;
    last_type: string;
    status: string;
  }>;
}

// Modern Creator Studio Data Palette
const STUDIO_COLORS = {
  primary: "#0F172A", // slate-900
  secondary: "#475569", // slate-600
  muted: "#94A3B8", // slate-400
  cobalt: "#2563EB", // blue-600
  cobaltLight: "#60A5FA", // blue-400
  emerald: "#10B981", // emerald-500
  emeraldBg: "#ECFDF5",
  indigo: "#6366F1", // indigo-500
  amber: "#F59E0B", // amber-500
  border: "#E2E8F0",
  grid: "#F1F5F9",
};

const MIX_ACCENTS: Record<string, string> = {
  reply: "#2563EB",
  post: "#10B981",
  thread: "#6366F1",
};

function SmoothSparkline({ points, color }: { points: number[]; color: string }) {
  const w = 90;
  const h = 26;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const span = Math.max(max - min, 1);
  const pts = points.map((p, i) => [
    (i / Math.max(points.length - 1, 1)) * w,
    h - 3 - ((p - min) / span) * (h - 7),
  ]);
  const d = "M " + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ");
  return (
    <svg width={w} height={h} className="shrink-0 overflow-visible">
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      />
    </svg>
  );
}

function StudioTile({
  title,
  sub,
  className = "",
  children,
  badge,
}: {
  title: string;
  sub?: string;
  className?: string;
  children: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-5 shadow-xs transition-shadow hover:shadow-sm ${className}`}
    >
      <header className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-[13.5px] font-semibold text-slate-900 dark:text-white tracking-tight">{title}</h3>
          {sub && <p className="text-[12px] text-slate-500 dark:text-[#A3A3A3] mt-0.5 leading-normal">{sub}</p>}
        </div>
        {badge}
      </header>
      {children}
    </motion.section>
  );
}

export default function AnalyticsView({
  data,
  onApplySuggestedQuery,
  onRefreshBrief,
  refreshingBrief = false,
}: {
  data: AnalyticsData | null;
  onApplySuggestedQuery?: (suggestedQuery: string) => void;
  onRefreshBrief?: () => void;
  refreshingBrief?: boolean;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [briefOpen, setBriefOpen] = useState(false);

  if (!data) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-28 bg-white dark:bg-[#181818] border border-slate-200 dark:border-[#262626] rounded-xl animate-pulse" />
          ))}
        </div>
        <div className="h-64 bg-white dark:bg-[#181818] border border-slate-200 dark:border-[#262626] rounded-xl flex flex-col items-center justify-center gap-3 text-slate-400 dark:text-[#737373]">
          <Loader2 className="w-5 h-5 animate-spin text-slate-500 dark:text-[#A3A3A3]" />
          <span className="text-xs font-medium">Synchronizing creator telemetry...</span>
        </div>
      </div>
    );
  }

  const {
    kpis,
    strategy_brief,
    learning_memory,
    velocity_shield,
    content_mix,
    status_funnel,
    length_distribution,
    timeline,
    top_authors,
  } = data;

  const pipeline = kpis.published_count + kpis.scheduled_count + kpis.pending_count;
  const mixTotal = content_mix.reduce((a, b) => a + b.count, 0);
  const hourlyUsed = velocity_shield?.hourly_used ?? kpis.hourly_used ?? 0;
  const hourlyCap = velocity_shield?.hourly_cap ?? kpis.hourly_cap ?? 6;
  const learnedCount = velocity_shield?.learned_examples_count ?? kpis.learned_examples_count ?? 0;
  const approvedSamples = learning_memory?.approved || [];

  // 4 Core Studio KPI Cards
  const kpiCards = [
    {
      label: "Active Pipeline",
      value: pipeline.toLocaleString(),
      subtext: `${kpis.published_count} posted · ${kpis.scheduled_count} scheduled`,
      spark: timeline.map((t) => t.drafted),
      color: STUDIO_COLORS.cobalt,
      icon: TrendingUp,
      badge: "Feed Velocity",
    },
    {
      label: "Approval Accuracy",
      value: `${kpis.approval_rate}%`,
      subtext: `${kpis.total_evaluated} scanned · ${learnedCount} voice models`,
      color: STUDIO_COLORS.emerald,
      icon: Brain,
      badge: "Few-Shot Style",
    },
    {
      label: "Feed Signal Captured",
      value: (kpis.feed_likes_captured + kpis.feed_replies_captured).toLocaleString(),
      subtext: `${kpis.feed_likes_captured} likes · ${kpis.feed_replies_captured} replies`,
      spark: timeline.map((t) => t.engagement),
      color: STUDIO_COLORS.indigo,
      icon: Activity,
      badge: "High Resonance",
    },
    {
      label: "Anti-Detection Pace",
      value: `${hourlyUsed}/${hourlyCap}`,
      subtext: `Today: ${kpis.daily_used}/${kpis.daily_cap} · Safe velocity`,
      color: hourlyUsed >= hourlyCap ? STUDIO_COLORS.amber : STUDIO_COLORS.emerald,
      icon: ShieldCheck,
      badge: "Bézier Guard Active",
    },
  ];

  // Timeline SVG calculations
  const W = 680;
  const H = 220;
  const padL = 36;
  const padR = 16;
  const padT = 16;
  const padB = 28;
  const maxEng = Math.max(...timeline.map((t) => t.engagement), 1);
  const maxDr = Math.max(...timeline.map((t) => t.drafted), 1);
  const n = Math.max(timeline.length - 1, 1);
  const x = (i: number) => padL + (i / n) * (W - padL - padR);
  const yEng = (v: number) => padT + (1 - v / maxEng) * (H - padT - padB);
  const yDr = (v: number) => padT + (1 - v / maxDr) * (H - padT - padB);

  const engPath = "M " + timeline.map((t, i) => `${x(i)},${yEng(t.engagement)}`).join(" L ");
  const drPath = "M " + timeline.map((t, i) => `${x(i)},${yDr(t.drafted)}`).join(" L ");
  const engArea = `${engPath} L ${x(timeline.length - 1)},${H - padB} L ${x(0)},${H - padB} Z`;

  // Donut geometry
  const R = 50;
  const CIRC = 2 * Math.PI * R;
  let acc = 0;

  const maxFunnel = Math.max(...status_funnel.map((s) => s.count), 1);
  const maxLen = Math.max(...length_distribution.map((l) => l.count), 1);

  return (
    <div className="space-y-4">
      {/* Sleek AI Strategy Brief Strip */}
      {strategy_brief && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl p-4 shadow-xs"
        >
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 font-medium text-[11.5px] shrink-0 border border-blue-200/60 dark:border-blue-800/60">
                <Sparkles className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                AI Strategy Pulse
              </span>

              <span className="font-semibold text-slate-900 dark:text-white text-[13.5px] truncate">
                {strategy_brief.headline}
              </span>

              <span className="hidden md:inline text-slate-300 dark:text-[#525252]">·</span>

              <span className="hidden md:inline text-slate-500 dark:text-[#A3A3A3] text-[12.5px] truncate max-w-md">
                {strategy_brief.recommended_action}
              </span>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {strategy_brief.suggested_query && onApplySuggestedQuery && (
                <button
                  type="button"
                  onClick={() => onApplySuggestedQuery(strategy_brief.suggested_query)}
                  className="inline-flex items-center gap-1.5 h-7 px-3 rounded-lg text-[12px] font-medium bg-slate-50 dark:bg-[#202020] hover:bg-slate-100 dark:hover:bg-[#262626] text-slate-800 dark:text-[#E5E5E5] border border-slate-200 dark:border-[#2E2E2E] transition-colors"
                  title="Switch active search query to this AI suggestion"
                >
                  <Sparkles className="w-3 h-3 text-blue-600 dark:text-blue-400" />
                  <span>Pulse: &ldquo;<strong className="font-semibold">{strategy_brief.suggested_query}</strong>&rdquo;</span>
                </button>
              )}

              {onRefreshBrief && (
                <button
                  type="button"
                  onClick={onRefreshBrief}
                  disabled={refreshingBrief}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-700 dark:hover:text-[#F3F3F3] hover:bg-slate-100 dark:hover:bg-[#262626] transition-colors"
                  title="Generate fresh AI strategy brief"
                >
                  {refreshingBrief ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600 dark:text-blue-400" />
                  ) : (
                    <RefreshCw className="w-3.5 h-3.5" />
                  )}
                </button>
              )}

              <button
                type="button"
                onClick={() => setBriefOpen((o) => !o)}
                className={`inline-flex items-center gap-1 h-7 px-3 rounded-lg text-[12px] font-medium transition-colors ${
                  briefOpen
                    ? "bg-slate-900 text-white dark:bg-white dark:text-black"
                    : "text-slate-600 dark:text-[#D4D4D4] hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-[#262626]"
                }`}
              >
                <span>{briefOpen ? "Hide" : "Diagnosis"}</span>
                {briefOpen ? (
                  <ChevronUp className="w-3.5 h-3.5" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>

          {/* Expandable Diagnosis Drawer */}
          <AnimatePresence>
            {briefOpen && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden mt-3 pt-3 border-t border-slate-100 dark:border-[#262626] text-[12.5px] space-y-2.5"
              >
                <div>
                  <span className="font-semibold text-slate-800 dark:text-[#E5E5E5] text-[12px]">Feed Analysis</span>
                  <p className="text-slate-600 dark:text-[#A3A3A3] mt-0.5 leading-relaxed">{strategy_brief.insight}</p>
                </div>
                <div>
                  <span className="font-semibold text-emerald-700 dark:text-emerald-400 text-[12px]">Creator Action</span>
                  <p className="text-slate-600 dark:text-[#A3A3A3] mt-0.5 leading-relaxed">{strategy_brief.recommended_action}</p>
                </div>
                <div className="flex items-center gap-3 pt-1 text-[11.5px] text-slate-400 dark:text-[#737373] flex-wrap">
                  <span className="text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                    <ShieldCheck className="w-3.5 h-3.5" /> Bézier Humanized Movements Active
                  </span>
                  <span>·</span>
                  <span>Variable Dwell Reading Time</span>
                  <span>·</span>
                  <span>Hourly Safety Cap: {hourlyUsed}/{hourlyCap} hr</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* 4 High-Signal Studio Metrics */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {kpiCards.map((card, i) => {
          const Icon = card.icon;
          return (
            <motion.div
              key={card.label}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: i * 0.04 }}
              className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-4 shadow-xs relative overflow-hidden"
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[12px] font-medium text-slate-500 dark:text-[#A3A3A3]">{card.label}</span>
                <span className="text-[10.5px] font-medium px-2 py-0.5 rounded-md bg-slate-50 dark:bg-[#202020] text-slate-600 dark:text-[#D4D4D4] border border-slate-100 dark:border-[#2E2E2E]/60">
                  {card.badge}
                </span>
              </div>
              <div className="flex items-end justify-between gap-3 mt-1">
                <div>
                  <div className="text-[26px] font-semibold text-slate-900 dark:text-white tracking-tight leading-none">
                    {card.value}
                  </div>
                  <p className="text-[11.5px] text-slate-500 dark:text-[#A3A3A3] mt-2 font-normal">{card.subtext}</p>
                </div>
                {card.spark && card.spark.some((v) => v > 0) && (
                  <SmoothSparkline points={card.spark} color={card.color} />
                )}
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Row 2: Engagement Timeline & Content Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <StudioTile
          title="Engagement & Draft Trajectory"
          sub="Organic engagement signals vs AI draft velocity over 2-hour rolling windows"
          className="lg:col-span-8"
          badge={
            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5 text-slate-600 dark:text-[#D4D4D4]">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-600 inline-block" /> Feed Engagement
              </span>
              <span className="flex items-center gap-1.5 text-slate-600 dark:text-[#D4D4D4]">
                <span className="w-2.5 h-2.5 rounded-full bg-indigo-500 inline-block" /> Drafts Generated
              </span>
            </div>
          }
        >
          <div className="w-full h-[220px] select-none">
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
              <defs>
                <linearGradient id="engGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563EB" stopOpacity="0.14" />
                  <stop offset="100%" stopColor="#2563EB" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              {[0, 0.25, 0.5, 0.75, 1].map((r) => {
                const yy = padT + r * (H - padT - padB);
                return (
                  <g key={r}>
                    <line x1={padL} x2={W - padR} y1={yy} y2={yy} className="stroke-slate-100 dark:stroke-[#262626]" strokeWidth="1" />
                    <text x={padL - 8} y={yy + 3.5} textAnchor="end" fontSize="10" className="fill-slate-400 dark:fill-[#737373]">
                      {Math.round((1 - r) * maxEng)}
                    </text>
                  </g>
                );
              })}

              {/* Gradient Area under Engagement */}
              <motion.path
                d={engArea}
                fill="url(#engGrad)"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6 }}
              />

              {/* Engagement Line */}
              <motion.path
                d={engPath}
                fill="none"
                stroke="#2563EB"
                strokeWidth="2.2"
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.8, ease: "easeOut" }}
              />

              {/* Drafts Line */}
              <motion.path
                d={drPath}
                fill="none"
                stroke="#6366F1"
                strokeWidth="2"
                strokeDasharray="4 3"
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.8, delay: 0.1, ease: "easeOut" }}
              />

              {/* Hover Crosshairs & Points */}
              {timeline.map((t, i) => (
                <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                  <rect
                    x={x(i) - 20}
                    y={padT}
                    width="40"
                    height={H - padT - padB}
                    fill="transparent"
                  />
                  <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" className="fill-slate-400 dark:fill-[#737373]">
                    {t.time}
                  </text>
                  {hover === i && (
                    <>
                      <line
                        x1={x(i)}
                        x2={x(i)}
                        y1={padT}
                        y2={H - padB}
                        className="stroke-slate-300 dark:stroke-[#2E2E2E]"
                        strokeDasharray="2 2"
                      />
                      <circle cx={x(i)} cy={yEng(t.engagement)} r="4" fill="#2563EB" stroke="#fff" strokeWidth="2" />
                      <circle cx={x(i)} cy={yDr(t.drafted)} r="3.5" fill="#6366F1" stroke="#fff" strokeWidth="2" />
                      <g transform={`translate(${Math.min(Math.max(x(i) - 60, padL), W - 140)}, ${padT + 4})`}>
                        <rect width="130" height="48" rx="6" fill="#181818" stroke="#262626" strokeWidth="1" />
                        <text x="10" y="16" fontSize="11" fontWeight="600" fill="#FFFFFF">
                          {t.time}
                        </text>
                        <text x="10" y="30" fontSize="10.5" fill="#93C5FD">
                          Engagement: {t.engagement}
                        </text>
                        <text x="10" y="42" fontSize="10" fill="#CBD5E1">
                          Drafts: {t.drafted} · Scanned: {t.evaluated}
                        </text>
                      </g>
                    </>
                  )}
                </g>
              ))}
            </svg>
          </div>
        </StudioTile>

        {/* Content Type Donut */}
        <StudioTile
          title="Content Mix"
          sub="Ratio of replies, standalone posts, and threads"
          className="lg:col-span-4"
        >
          <div className="flex items-center gap-5 pt-2">
            <div className="relative shrink-0">
              <svg width="128" height="128" viewBox="0 0 128 128" className="-rotate-90">
                <circle cx="64" cy="64" r={R} fill="none" className="stroke-slate-100 dark:stroke-[#262626]" strokeWidth="14" />
                {mixTotal > 0 &&
                  content_mix.map((seg) => {
                    const frac = seg.count / mixTotal;
                    const dash = frac * CIRC;
                    const off = -acc * CIRC;
                    acc += frac;
                    return (
                      <motion.circle
                        key={seg.key}
                        cx="64"
                        cy="64"
                        r={R}
                        fill="none"
                        stroke={MIX_ACCENTS[seg.key] || "#94A3B8"}
                        strokeWidth="14"
                        strokeDashoffset={off}
                        initial={{ strokeDasharray: `0 ${CIRC}` }}
                        animate={{ strokeDasharray: `${dash} ${CIRC}` }}
                        transition={{ duration: 0.7, ease: "easeOut" }}
                      />
                    );
                  })}
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold text-slate-900 dark:text-white leading-none">{mixTotal}</span>
                <span className="text-[11px] text-slate-400 dark:text-[#737373] mt-1">Total items</span>
              </div>
            </div>

            <ul className="flex-1 space-y-2.5">
              {content_mix.map((m) => (
                <li key={m.key} className="flex items-center justify-between text-[12.5px]">
                  <span className="flex items-center gap-2 text-slate-600 dark:text-[#D4D4D4]">
                    <span
                      className="w-2.5 h-2.5 rounded-full inline-block"
                      style={{ background: MIX_ACCENTS[m.key] || "#94A3B8" }}
                    />
                    <span className="capitalize">{m.label}</span>
                  </span>
                  <span className="font-semibold text-slate-900 dark:text-white">
                    {m.count}{" "}
                    <span className="text-slate-400 dark:text-[#737373] font-normal text-[11px]">
                      ({mixTotal > 0 ? Math.round((m.count / mixTotal) * 100) : 0}%)
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </StudioTile>
      </div>

      {/* Row 3: Pipeline Funnel, Length Spectrum & High Resonance Conversations */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Status Funnel */}
        <StudioTile title="Publishing Funnel" sub="From raw scan to scheduled & live" className="lg:col-span-4">
          <ul className="space-y-3 pt-1">
            {status_funnel.map((s, i) => {
              const colors = ["#10B981", "#3B82F6", "#F59E0B", "#94A3B8"];
              return (
                <li key={s.label}>
                  <div className="flex items-center justify-between text-[12.5px] mb-1.5">
                    <span className="text-slate-600 dark:text-[#D4D4D4] font-medium">{s.label}</span>
                    <span className="font-semibold text-slate-900 dark:text-white">{s.count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-100 dark:bg-[#222222] overflow-hidden">
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: colors[i % colors.length] }}
                      initial={{ width: 0 }}
                      animate={{ width: `${(s.count / maxFunnel) * 100}%` }}
                      transition={{ duration: 0.6, ease: "easeOut" }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </StudioTile>

        {/* Draft Length Calibration */}
        <StudioTile
          title="Draft Length Profile"
          sub="Character distribution across replies"
          className="lg:col-span-3"
        >
          <div className="flex items-end justify-between gap-3 h-[130px] pt-2">
            {length_distribution.map((l, i) => {
              const barColors = ["#60A5FA", "#3B82F6", "#818CF8"];
              return (
                <div key={l.label} className="flex-1 flex flex-col items-center justify-end h-full">
                  <span className="text-[12px] font-semibold text-slate-900 dark:text-white mb-1">{l.count}</span>
                  <motion.div
                    className="w-full max-w-[42px] rounded-t-md"
                    style={{ background: barColors[i % barColors.length] }}
                    initial={{ height: 0 }}
                    animate={{ height: `${Math.max((l.count / maxLen) * 90, l.count ? 6 : 2)}px` }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                  />
                </div>
              );
            })}
          </div>
          <div className="flex justify-between gap-2 mt-2 pt-1 border-t border-slate-100 dark:border-[#262626]">
            {length_distribution.map((l) => (
              <span key={l.label} className="flex-1 text-center text-[10.5px] text-slate-500 dark:text-[#A3A3A3] font-medium">
                {l.label.replace(/\s*\(.*\)/, "")}
              </span>
            ))}
          </div>
        </StudioTile>

        {/* Top Conversations */}
        <StudioTile
          title="High-Resonance Conversations"
          sub="Ranked by likes + 3x reply engagement"
          className="lg:col-span-5"
        >
          {top_authors.length === 0 ? (
            <p className="text-xs text-slate-400 dark:text-[#737373] py-6 text-center">
              Scan your feed to rank active niche conversations.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="text-left text-slate-400 dark:text-[#737373] text-[11px] font-medium border-b border-slate-100 dark:border-[#262626]">
                    <th className="pb-2">Creator</th>
                    <th className="pb-2 text-right">Likes</th>
                    <th className="pb-2 text-right">Replies</th>
                    <th className="pb-2 text-right">Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 dark:divide-[#262626]/50">
                  {top_authors.map((a) => (
                    <tr key={a.author} className="hover:bg-slate-50/70 dark:hover:bg-[#202020] transition-colors">
                      <td className="py-2 font-medium text-slate-900 dark:text-white truncate max-w-[140px]">
                        {a.author}
                      </td>
                      <td className="py-2 text-right text-slate-600 dark:text-[#A3A3A3]">{a.likes}</td>
                      <td className="py-2 text-right text-slate-600 dark:text-[#A3A3A3]">{a.replies}</td>
                      <td className="py-2 text-right font-semibold text-slate-900 dark:text-white">{a.score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </StudioTile>
      </div>

      {/* Row 4: 2026 Anti-Detection Telemetry & Few-Shot Voice Memory */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Anti-Detection Telemetry */}
        <StudioTile
          title="Anti-Detection & Biometric Shield"
          sub="Behavioral throttling protecting your profile from shadowbans and rate-limits"
          className="lg:col-span-5"
          badge={
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/50 px-2 py-0.5 rounded-md border border-emerald-200 dark:border-emerald-800/60">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /> Shield Active
            </span>
          }
        >
          <div className="space-y-4 pt-1">
            {/* 60-min rolling cap */}
            <div>
              <div className="flex items-center justify-between text-[12px] mb-1.5">
                <span className="text-slate-600 dark:text-[#D4D4D4] font-medium">Rolling 60-min velocity</span>
                <span className="font-semibold text-slate-900 dark:text-white">
                  {hourlyUsed} / {hourlyCap} actions (Safe)
                </span>
              </div>
              <div className="h-2 rounded-full bg-slate-100 dark:bg-[#222222] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min(100, (hourlyUsed / Math.max(hourlyCap, 1)) * 100)}%`,
                    background: hourlyUsed >= hourlyCap ? "#F59E0B" : "#10B981",
                  }}
                />
              </div>
            </div>

            {/* Daily Cap */}
            <div>
              <div className="flex items-center justify-between text-[12px] mb-1.5">
                <span className="text-slate-600 dark:text-[#D4D4D4] font-medium">Daily action quota</span>
                <span className="font-semibold text-slate-900 dark:text-white">
                  {kpis.daily_used} / {kpis.daily_cap} actions
                </span>
              </div>
              <div className="h-2 rounded-full bg-slate-100 dark:bg-[#222222] overflow-hidden">
                <div
                  className="h-full rounded-full bg-slate-800 dark:bg-blue-600 transition-all"
                  style={{
                    width: `${Math.min(100, (kpis.daily_used / Math.max(kpis.daily_cap, 1)) * 100)}%`,
                  }}
                />
              </div>
            </div>

            {/* Biometric indicators */}
            <div className="grid grid-cols-2 gap-2.5 pt-1 text-[11.5px]">
              <div className="p-3 bg-slate-50 dark:bg-[#202020] border border-slate-200/70 dark:border-[#262626] rounded-lg">
                <span className="text-slate-500 dark:text-[#A3A3A3] block mb-1">Mouse Curve</span>
                <span className="font-semibold text-emerald-700 dark:text-emerald-400">Cubic Bézier Dynamics</span>
              </div>
              <div className="p-3 bg-slate-50 dark:bg-[#202020] border border-slate-200/70 dark:border-[#262626] rounded-lg">
                <span className="text-slate-500 dark:text-[#A3A3A3] block mb-1">Prefix Guard</span>
                <span className="font-semibold text-emerald-700 dark:text-emerald-400">65% Jaccard Diversity</span>
              </div>
            </div>
          </div>
        </StudioTile>

        {/* Self-Learning Voice Memory Showcase */}
        <StudioTile
          title="Self-Learning Voice Memory (Few-Shot Style)"
          sub={`${learnedCount} approved or edited replies actively teaching Gemini your exact phrasing`}
          className="lg:col-span-7"
          badge={
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/50 px-2 py-0.5 rounded-md border border-blue-200 dark:border-blue-800/60">
              <Brain className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" /> Active Tuning
            </span>
          }
        >
          {approvedSamples.length === 0 ? (
            <div className="p-6 text-center text-slate-400 dark:text-[#737373] text-xs">
              Approve or edit a draft in the Queue to start building your few-shot voice memory.
            </div>
          ) : (
            <div className="space-y-2.5 max-h-[180px] overflow-y-auto pr-1">
              {approvedSamples.slice(0, 4).map((sample, idx) => (
                <div
                  key={idx}
                  className="p-3 bg-slate-50/80 dark:bg-[#202020] border border-slate-200/70 dark:border-[#262626] rounded-lg text-[12px] space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-500 dark:text-[#A3A3A3] truncate max-w-[380px] font-normal">
                      On: &ldquo;{sample.tweet_text}&rdquo;
                    </span>
                    <span
                      className={`text-[10px] font-semibold px-2 py-0.5 rounded-md ${
                        sample.user_edited
                          ? "bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60"
                          : "bg-emerald-50 dark:bg-emerald-950/50 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
                      }`}
                    >
                      {sample.user_edited ? "User-Edited Gold Standard" : "Approved Voice"}
                    </span>
                  </div>
                  <p className="font-medium text-slate-900 dark:text-white flex items-start gap-2">
                    <span className="text-blue-600 dark:text-blue-400 font-bold shrink-0">↳</span>
                    <span>{sample.reply_text}</span>
                  </p>
                </div>
              ))}
            </div>
          )}
        </StudioTile>
      </div>
    </div>
  );
}
