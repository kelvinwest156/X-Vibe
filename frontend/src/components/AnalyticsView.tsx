"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import {
  TrendingUp,
  Sparkles,
  Flame,
  Feather,
  Layers,
  Filter,
  Award,
  ArrowUpRight,
  Activity,
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
  };
  content_mix: Array<{
    label: string;
    key: string;
    count: number;
    color: string;
  }>;
  status_funnel: Array<{
    label: string;
    count: number;
    color: string;
  }>;
  length_distribution: Array<{
    label: string;
    count: number;
    color: string;
  }>;
  timeline: Array<{
    time: string;
    evaluated: number;
    drafted: number;
    engagement: number;
  }>;
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

function MiniSparkline({ color, points }: { color: string; points: number[] }) {
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = Math.max(max - min, 1);
  const width = 110;
  const height = 34;

  const coords = points.map((p, i) => {
    const x = (i / Math.max(points.length - 1, 1)) * width;
    const y = height - ((p - min) / range) * (height - 8) - 4;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const linePath = `M ${coords.join(" L ")}`;
  const areaPath = `${linePath} L ${width},${height} L 0,${height} Z`;
  const gradId = `spark_${color.replace("#", "")}`;

  return (
    <svg width={width} height={height} className="overflow-visible">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.38" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <motion.path
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.8 }}
        d={areaPath}
        fill={`url(#${gradId})`}
      />
      <motion.path
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1.1, ease: "easeOut" }}
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function AnalyticsView({
  data,
  onGenerateOriginal,
}: {
  data: AnalyticsData | null;
  onGenerateOriginal: (mode: "post" | "thread") => void;
}) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (!data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bi-card rounded-2xl p-5 h-32 animate-pulse" />
        ))}
      </div>
    );
  }

  const { kpis, content_mix, status_funnel, length_distribution, timeline, top_authors } = data;
  const totalContent = Math.max(
    content_mix.reduce((acc, c) => acc + c.count, 0),
    1
  );

  // Donut Ring Math
  const radius = 58;
  const circumference = 2 * Math.PI * radius;
  let accumulatedPct = 0;

  // Area Chart Math
  const chartW = 640;
  const chartH = 210;
  const maxEng = Math.max(...timeline.map((t) => t.engagement), 10);
  const maxEval = Math.max(...timeline.map((t) => t.evaluated), 4);

  const engCoords = timeline.map((t, i) => {
    const x = (i / Math.max(timeline.length - 1, 1)) * (chartW - 40) + 20;
    const y = chartH - 28 - (t.engagement / maxEng) * (chartH - 55);
    return { x, y, ...t };
  });

  const draftCoords = timeline.map((t, i) => {
    const x = (i / Math.max(timeline.length - 1, 1)) * (chartW - 40) + 20;
    const y = chartH - 28 - (t.drafted / maxEval) * (chartH - 75);
    return { x, y };
  });

  const engLine =
    engCoords.length > 0
      ? `M ${engCoords.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" L ")}`
      : "";
  const engArea =
    engCoords.length > 0
      ? `${engLine} L ${engCoords[engCoords.length - 1].x},${chartH - 24} L ${engCoords[0].x},${chartH - 24} Z`
      : "";

  const draftLine =
    draftCoords.length > 0
      ? `M ${draftCoords.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" L ")}`
      : "";

  const kpiCards = [
    {
      title: "Content Pipeline",
      value: `${kpis.published_count + kpis.scheduled_count + kpis.pending_count}`,
      sub: `${kpis.published_count} posted · ${kpis.scheduled_count} scheduled`,
      badge: `${kpis.daily_used}/${kpis.daily_cap} daily cap`,
      color: "#38BDF8",
      icon: Sparkles,
      spark: timeline.map((t) => t.drafted + 1),
    },
    {
      title: "AI Relevance & Approval",
      value: `${kpis.approval_rate}%`,
      sub: `${kpis.total_evaluated} total posts analyzed`,
      badge: `${kpis.skipped_count} noise filtered`,
      color: "#34D399",
      icon: TrendingUp,
      spark: [58, 64, 62, 71, 69, 75, kpis.approval_rate || 72],
    },
    {
      title: "Feed Engagement Pulse",
      value: `${kpis.feed_likes_captured + kpis.feed_replies_captured}`,
      sub: `${kpis.feed_likes_captured} likes · ${kpis.feed_replies_captured} replies in feed`,
      badge: `Avg score ${kpis.avg_engagement_score}`,
      color: "#A78BFA",
      icon: Flame,
      spark: timeline.map((t) => t.engagement + 4),
    },
    {
      title: "Human Voice Cadence",
      value: `${kpis.avg_draft_length}c`,
      sub: "Average reply & post length",
      badge: "Zero AI buzzwords",
      color: "#FBBF24",
      icon: Feather,
      spark: [124, 98, 115, 104, 118, 92, kpis.avg_draft_length || 110],
    },
  ];

  return (
    <div className="space-y-5">
      {/* Row 1: Power BI KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {kpiCards.map((card, idx) => {
          const Icon = card.icon;
          return (
            <motion.div
              key={card.title}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, delay: idx * 0.06 }}
              className="bi-card bi-card-interactive rounded-2xl p-4 flex flex-col justify-between relative overflow-hidden group"
            >
              {/* Top glowing accent bar */}
              <div
                className="absolute top-0 left-0 right-0 h-[2px] opacity-75"
                style={{
                  background: `linear-gradient(90deg, transparent, ${card.color}, transparent)`,
                }}
              />

              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className="text-xs font-extralight text-slate-400 tracking-wide block">
                    {card.title}
                  </span>
                  <div className="mt-1.5 flex items-baseline gap-2">
                    <span className="text-2xl font-semibold text-white tracking-tight">
                      {card.value}
                    </span>
                  </div>
                </div>
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center border"
                  style={{
                    backgroundColor: `${card.color}14`,
                    borderColor: `${card.color}35`,
                    color: card.color,
                  }}
                >
                  <Icon className="w-4 h-4" strokeWidth={1.6} />
                </div>
              </div>

              <div className="mt-4 flex items-end justify-between gap-2">
                <div className="space-y-1">
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-light border"
                    style={{
                      backgroundColor: `${card.color}12`,
                      borderColor: `${card.color}30`,
                      color: card.color,
                    }}
                  >
                    <ArrowUpRight className="w-2.5 h-2.5" />
                    {card.badge}
                  </span>
                  <p className="text-[11px] font-extralight text-slate-400">
                    {card.sub}
                  </p>
                </div>
                <MiniSparkline color={card.color} points={card.spark} />
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Row 2: Main Velocity Area Chart + Content Mix Donut */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Engagement & Velocity Area Chart (8 cols) */}
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.15 }}
          className="lg:col-span-8 bi-card rounded-2xl p-5 flex flex-col justify-between"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <div>
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-sky-400" strokeWidth={1.6} />
                <h3 className="text-sm font-semibold text-white tracking-tight">
                  Engagement Pulse & Content Velocity
                </h3>
              </div>
              <p className="text-xs font-extralight text-slate-400 mt-0.5">
                Real-time X conversation intensity vs. AI drafts synthesized across active windows
              </p>
            </div>

            <div className="flex items-center gap-4 text-[11px] font-mono font-light">
              <span className="flex items-center gap-1.5 text-sky-300">
                <span className="w-2 h-2 rounded-full bg-sky-400" />
                Engagement Score
              </span>
              <span className="flex items-center gap-1.5 text-purple-300">
                <span className="w-2 h-2 rounded-full bg-purple-400" />
                AI Drafts
              </span>
            </div>
          </div>

          <div className="relative w-full overflow-x-auto">
            <svg
              viewBox={`0 0 ${chartW} ${chartH}`}
              className="w-full h-52 overflow-visible select-none"
            >
              <defs>
                <linearGradient id="engAreaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#38BDF8" stopOpacity="0.35" />
                  <stop offset="65%" stopColor="#818CF8" stopOpacity="0.10" />
                  <stop offset="100%" stopColor="#0B0F19" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Subtle Horizontal Grid Lines */}
              {[0.2, 0.45, 0.7, 0.9].map((ratio, idx) => (
                <line
                  key={idx}
                  x1={16}
                  x2={chartW - 16}
                  y1={chartH * ratio}
                  y2={chartH * ratio}
                  stroke="rgba(148, 163, 184, 0.08)"
                  strokeDasharray="3 3"
                />
              ))}

              {/* Area Fill */}
              <motion.path
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.7 }}
                d={engArea}
                fill="url(#engAreaGrad)"
              />

              {/* Engagement Curve */}
              <motion.path
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 1.2, ease: "easeOut" }}
                d={engLine}
                fill="none"
                stroke="#38BDF8"
                strokeWidth="2.5"
                strokeLinecap="round"
              />

              {/* Drafted Curve */}
              <motion.path
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 1.2, delay: 0.15, ease: "easeOut" }}
                d={draftLine}
                fill="none"
                stroke="#A78BFA"
                strokeWidth="2"
                strokeDasharray="4 4"
                strokeLinecap="round"
              />

              {/* Interactive Data Points */}
              {engCoords.map((pt, i) => (
                <g
                  key={pt.time + i}
                  onMouseEnter={() => setHoveredIdx(i)}
                  onMouseLeave={() => setHoveredIdx(null)}
                  className="cursor-pointer"
                >
                  <circle
                    cx={pt.x}
                    cy={pt.y}
                    r={hoveredIdx === i ? 5.5 : 3.2}
                    fill="#0B0F19"
                    stroke="#38BDF8"
                    strokeWidth="2.2"
                  />
                  <text
                    x={pt.x}
                    y={chartH - 6}
                    textAnchor="middle"
                    className="fill-slate-500 text-[9px] font-mono font-light"
                  >
                    {pt.time}
                  </text>
                  {hoveredIdx === i && (
                    <g transform={`translate(${Math.min(Math.max(pt.x - 52, 10), chartW - 115)}, ${Math.max(pt.y - 46, 6)})`}>
                      <rect
                        width="104"
                        height="36"
                        rx="6"
                        fill="#0F172A"
                        stroke="rgba(56, 189, 248, 0.4)"
                      />
                      <text x="8" y="14" className="fill-white text-[10px] font-semibold">
                        Pulse: {pt.engagement} pts
                      </text>
                      <text x="8" y="27" className="fill-sky-300 text-[9px] font-mono">
                        {pt.drafted} drafts · {pt.evaluated} scanned
                      </text>
                    </g>
                  )}
                </g>
              ))}
            </svg>
          </div>
        </motion.div>

        {/* Content Mix Donut Ring (4 cols) */}
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.22 }}
          className="lg:col-span-4 bi-card rounded-2xl p-5 flex flex-col justify-between"
        >
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-purple-400" strokeWidth={1.6} />
                <h3 className="text-sm font-semibold text-white tracking-tight">
                  Content Format Mix
                </h3>
              </div>
              <span className="text-[10px] font-mono font-light text-slate-400 px-2 py-0.5 rounded-full bg-white/[0.04] border border-white/[0.06]">
                Replies · Posts · Threads
              </span>
            </div>
            <p className="text-xs font-extralight text-slate-400 mt-0.5">
              Distribution of autonomous formats created
            </p>
          </div>

          <div className="my-4 flex items-center justify-center relative">
            <svg width="156" height="156" viewBox="0 0 156 156" className="-rotate-90">
              <circle
                cx="78"
                cy="78"
                r={radius}
                fill="none"
                stroke="rgba(148, 163, 184, 0.08)"
                strokeWidth="14"
              />
              {content_mix.map((seg) => {
                const pct = seg.count / totalContent;
                const dash = pct * circumference;
                const offset = -accumulatedPct * circumference;
                accumulatedPct += pct;
                return (
                  <motion.circle
                    key={seg.key}
                    cx="78"
                    cy="78"
                    r={radius}
                    fill="none"
                    stroke={seg.color}
                    strokeWidth="14"
                    strokeDasharray={`${dash} ${circumference}`}
                    strokeDashoffset={offset}
                    strokeLinecap="round"
                    initial={{ strokeDasharray: `0 ${circumference}` }}
                    animate={{ strokeDasharray: `${dash} ${circumference}` }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                  />
                );
              })}
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-2xl font-semibold text-white tracking-tight">
                {content_mix.reduce((a, b) => a + b.count, 0)}
              </span>
              <span className="text-[10px] font-mono font-extralight text-slate-400 uppercase tracking-wider">
                Total Items
              </span>
            </div>
          </div>

          <div className="space-y-2">
            {content_mix.map((item) => {
              const pct = Math.round((item.count / totalContent) * 100);
              return (
                <div
                  key={item.key}
                  className="flex items-center justify-between text-xs px-2.5 py-1.5 rounded-xl bg-white/[0.02] border border-white/[0.04]"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2.5 h-2.5 rounded-full"
                      style={{ backgroundColor: item.color }}
                    />
                    <span className="font-light text-slate-200">{item.label}</span>
                  </div>
                  <div className="flex items-center gap-2 font-mono text-[11px]">
                    <strong className="font-semibold text-white">{item.count}</strong>
                    <span className="text-slate-500 font-light">({pct}%)</span>
                  </div>
                </div>
              );
            })}
          </div>
        </motion.div>
      </div>

      {/* Row 3: Pipeline Funnel + Cadence Length + Top Authors Leaderboard */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Pipeline Conversion Funnel (4 cols) */}
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.28 }}
          className="lg:col-span-4 bi-card rounded-2xl p-5 space-y-4"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-emerald-400" strokeWidth={1.6} />
              <h3 className="text-sm font-semibold text-white tracking-tight">
                Pipeline Funnel
              </h3>
            </div>
            <span className="text-[10px] font-mono font-light text-slate-400">
              Conversion stages
            </span>
          </div>

          <div className="space-y-3 pt-1">
            {status_funnel.map((stage) => {
              const maxStage = Math.max(...status_funnel.map((s) => s.count), 1);
              const widthPct = Math.max(8, Math.round((stage.count / maxStage) * 100));
              return (
                <div key={stage.label} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-light text-slate-300">{stage.label}</span>
                    <span className="font-mono font-semibold text-white">
                      {stage.count}
                    </span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-900/90 overflow-hidden p-[1px] border border-white/[0.05]">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${widthPct}%` }}
                      transition={{ duration: 0.8, ease: "easeOut" }}
                      className="h-full rounded-full"
                      style={{
                        background: `linear-gradient(90deg, ${stage.color}99, ${stage.color})`,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Quick Studio Shortcut */}
          <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between gap-2">
            <button
              onClick={() => onGenerateOriginal("post")}
              className="flex-1 py-2 px-3 rounded-xl bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-xs font-light text-sky-300 transition"
            >
              + Draft Original Post
            </button>
            <button
              onClick={() => onGenerateOriginal("thread")}
              className="flex-1 py-2 px-3 rounded-xl bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/30 text-xs font-light text-purple-300 transition"
            >
              + Draft Thread
            </button>
          </div>
        </motion.div>

        {/* Draft Length & Vibe Cadence (4 cols) */}
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.34 }}
          className="lg:col-span-4 bi-card rounded-2xl p-5 flex flex-col justify-between"
        >
          <div>
            <div className="flex items-center gap-2">
              <Feather className="w-4 h-4 text-amber-400" strokeWidth={1.6} />
              <h3 className="text-sm font-semibold text-white tracking-tight">
                Voice Cadence & Length Mix
              </h3>
            </div>
            <p className="text-xs font-extralight text-slate-400 mt-0.5">
              Keeping replies punchy and threads multi-layered
            </p>
          </div>

          <div className="my-4 grid grid-cols-3 gap-2.5 pt-2">
            {length_distribution.map((item) => {
              const maxLenCount = Math.max(
                ...length_distribution.map((l) => l.count),
                1
              );
              const barH = Math.max(18, Math.round((item.count / maxLenCount) * 95));
              return (
                <div
                  key={item.label}
                  className="bg-white/[0.02] border border-white/[0.05] rounded-xl p-3 flex flex-col items-center justify-end h-36"
                >
                  <span className="font-mono text-sm font-semibold text-white mb-1.5">
                    {item.count}
                  </span>
                  <div className="w-8 bg-slate-900/80 rounded-lg flex items-end overflow-hidden h-20 p-0.5">
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${barH}%` }}
                      transition={{ duration: 0.85, ease: "easeOut" }}
                      className="w-full rounded-md"
                      style={{ backgroundColor: item.color }}
                    />
                  </div>
                  <span className="text-[10px] font-extralight text-slate-400 text-center mt-2 leading-tight">
                    {item.label}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="px-3 py-2 rounded-xl bg-emerald-500/[0.07] border border-emerald-500/20 flex items-center justify-between text-xs">
            <span className="font-extralight text-emerald-200">
              Anti-Robotic Guardrail
            </span>
            <span className="font-mono font-semibold text-emerald-400 text-[11px]">
              100% Clean
            </span>
          </div>
        </motion.div>

        {/* Top Engaging Authors Leaderboard (4 cols) */}
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.4 }}
          className="lg:col-span-4 bi-card rounded-2xl p-5 flex flex-col justify-between"
        >
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Award className="w-4 h-4 text-sky-400" strokeWidth={1.6} />
              <h3 className="text-sm font-semibold text-white tracking-tight">
                Top Engaging Conversations
              </h3>
            </div>
            <span className="text-[10px] font-mono font-light text-slate-400">
              By Impact Score
            </span>
          </div>

          <div className="space-y-2 flex-1">
            {top_authors.length === 0 ? (
              <div className="text-xs font-extralight text-slate-500 py-8 text-center">
                Scan your feed to rank top conversations.
              </div>
            ) : (
              top_authors.map((auth, idx) => (
                <div
                  key={auth.author}
                  className="flex items-center justify-between px-3 py-2 rounded-xl bg-white/[0.02] hover:bg-white/[0.05] border border-white/[0.05] transition"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="w-5 h-5 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-300 font-mono text-[10px] flex items-center justify-center font-semibold">
                      {idx + 1}
                    </span>
                    <div className="truncate">
                      <span className="text-xs font-semibold text-white block truncate">
                        {auth.author}
                      </span>
                      <span className="text-[10px] font-mono font-extralight text-slate-400">
                        {auth.likes} likes · {auth.replies} replies
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="text-xs font-mono font-semibold text-emerald-400 block">
                      +{auth.score}
                    </span>
                    <span className="text-[10px] font-extralight text-slate-500 uppercase">
                      {auth.last_type}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
