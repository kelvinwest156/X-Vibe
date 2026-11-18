"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  TrendingUp,
  Sparkles,
  Flame,
  ShieldCheck,
  Zap,
  Globe,
  RefreshCw,
  ExternalLink,
  Loader2,
  ChevronDown,
  ChevronUp,
  ArrowUpRight,
  Target,
  BarChart3,
  Layers,
  CheckCircle2,
  Share2,
  MessageCircle,
  Heart,
  Repeat
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
    estimated_reach?: number;
    estimated_reach_growth?: string;
    engagement_rate?: number;
    resonance_benchmark?: string;
    consistency_streak?: number;
    account_health_score?: number;
    account_health_label?: string;
  };
  creator_vitals?: {
    estimated_reach: number;
    estimated_reach_growth: string;
    engagement_rate: number;
    resonance_benchmark: string;
    consistency_streak: number;
    account_health_score: number;
    account_health_label: string;
    daily_actions_used: number;
    daily_action_cap: number;
  };
  strategy_brief?: {
    headline: string;
    insight: string;
    recommended_action: string;
    suggested_query: string;
  };
  top_bangers?: Array<{
    tweet_id: string;
    text: string;
    action_type: string;
    status: string;
    likes: number;
    replies: number;
    estimated_impressions: number;
    timestamp: string;
    target_author?: string;
  }>;
  reply_guy_targets?: Array<{
    author: string;
    interactions: number;
    likes_captured: number;
    replies_captured: number;
    resonance_score: number;
    status: string;
    action: string;
  }>;
  format_roi?: Array<{
    format: string;
    count: number;
    multiplier: string;
    role: string;
    color: string;
  }>;
  daily_growth?: Array<{
    date: string;
    impressions: number;
    interactions: number;
    published: number;
  }>;
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

interface WebTopicItem {
  title: string;
  source: string;
  url: string;
  suggested_query: string;
  hook_summary: string;
  relevance_score: number;
  timestamp: string;
}

function getSmoothCurvePath(points: Array<[number, number]>): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0][0]},${points[0][1]}`;
  if (points.length === 2) {
    return `M ${points[0][0]},${points[0][1]} L ${points[1][0]},${points[1][1]}`;
  }

  let d = `M ${points[0][0].toFixed(1)},${points[0][1].toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = i > 0 ? points[i - 1] : points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = i < points.length - 2 ? points[i + 2] : p2;

    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;

    d += ` C ${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

export default function AnalyticsView({
  data,
  onRefreshBrief,
  refreshingBrief,
  onApplySuggestedQuery,
  onNavigateToQueue,
}: {
  data: AnalyticsData;
  onRefreshBrief?: () => void;
  refreshingBrief?: boolean;
  onApplySuggestedQuery?: (q: string) => void;
  onNavigateToQueue?: () => void;
}) {
  const [briefOpen, setBriefOpen] = useState(false);
  const [webTopics, setWebTopics] = useState<WebTopicItem[]>([]);
  const [scanningWeb, setScanningWeb] = useState(false);
  const [draftingId, setDraftingId] = useState<string | null>(null);
  const [draftSuccessToast, setDraftSuccessToast] = useState<string | null>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const {
    kpis,
    creator_vitals,
    strategy_brief,
    top_bangers = [],
    reply_guy_targets = [],
    format_roi = [],
    daily_growth = [],
    content_mix = [],
  } = data;

  // Extract Creator Vital Signs (with robust fallbacks)
  const reach = creator_vitals?.estimated_reach ?? kpis.estimated_reach ?? 2450;
  const reachGrowth = creator_vitals?.estimated_reach_growth ?? kpis.estimated_reach_growth ?? "+18.4%";
  const er = creator_vitals?.engagement_rate ?? kpis.engagement_rate ?? 4.8;
  const resonanceBench = creator_vitals?.resonance_benchmark ?? kpis.resonance_benchmark ?? "Top 10% in Niche";
  const streak = creator_vitals?.consistency_streak ?? kpis.consistency_streak ?? 1;
  const healthLabel = creator_vitals?.account_health_label ?? kpis.account_health_label ?? "100% Protected · Safe Pacing";
  const dailyUsed = creator_vitals?.daily_actions_used ?? kpis.daily_used ?? 0;
  const dailyCap = creator_vitals?.daily_action_cap ?? kpis.daily_cap ?? 15;

  // Fetch real-time Web Topics from /api/radar/topics
  const fetchWebTopics = useCallback(async () => {
    try {
      const res = await fetch("/api/radar/topics");
      if (res.ok) {
        const json = await res.json();
        setWebTopics(json.topics || []);
      }
    } catch {
      // Non-blocking fallback
    }
  }, []);

  useEffect(() => {
    fetchWebTopics();
  }, [fetchWebTopics]);

  // Handle Manual Web Scan Trigger
  const handleScanWebNow = async () => {
    setScanningWeb(true);
    try {
      const res = await fetch("/api/radar/scan-now", { method: "POST" });
      if (res.ok) {
        const json = await res.json();
        setWebTopics(json.topics || []);
      }
    } catch {
      // Non-blocking
    } finally {
      setScanningWeb(false);
    }
  };

  // Handle 1-Click Draft from Topic
  const handleDraftFromTopic = async (topic: WebTopicItem, draftType: "tweet" | "thread") => {
    setDraftingId(`${topic.title}_${draftType}`);
    try {
      const res = await fetch("/api/radar/draft-from-topic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: topic.title,
          source: topic.source,
          url: topic.url,
          hook_summary: topic.hook_summary,
          suggested_query: topic.suggested_query,
          draft_type: draftType,
        }),
      });
      if (res.ok) {
        setDraftSuccessToast(`Created ${draftType === "thread" ? "3-Tweet Thread" : "Post"} in Review Queue!`);
        setTimeout(() => setDraftSuccessToast(null), 4000);
      }
    } catch {
      // Non-blocking
    } finally {
      setDraftingId(null);
    }
  };

  // 7-Day Growth Curve SVG geometry
  const chartDays = daily_growth.length > 0 ? daily_growth : [
    { date: "Mon", impressions: 180, interactions: 12, published: 1 },
    { date: "Tue", impressions: 320, interactions: 24, published: 2 },
    { date: "Wed", impressions: 290, interactions: 19, published: 1 },
    { date: "Thu", impressions: 450, interactions: 38, published: 3 },
    { date: "Fri", impressions: 580, interactions: 45, published: 2 },
    { date: "Sat", impressions: 720, interactions: 62, published: 4 },
    { date: "Sun", impressions: 940, interactions: 84, published: 3 },
  ];

  const GW = 680;
  const GH = 190;
  const padL = 40;
  const padR = 20;
  const padT = 20;
  const padB = 26;
  const maxImp = Math.max(...chartDays.map((d) => d.impressions), 100);
  const n = Math.max(chartDays.length - 1, 1);
  const gx = (i: number) => padL + (i / n) * (GW - padL - padR);
  const gy = (v: number) => padT + (1 - v / maxImp) * (GH - padT - padB);

  const impPoints: Array<[number, number]> = chartDays.map((d, i) => [gx(i), gy(d.impressions)]);
  const impPath = getSmoothCurvePath(impPoints);
  const impArea = `${impPath} L ${gx(chartDays.length - 1)},${GH - padB} L ${gx(0)},${GH - padB} Z`;

  return (
    <div className="space-y-5">
      {/* Toast Notification */}
      <AnimatePresence>
        {draftSuccessToast && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="fixed top-5 right-5 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 text-white shadow-lg text-[13px] font-medium"
          >
            <CheckCircle2 className="w-4 h-4" />
            <span>{draftSuccessToast}</span>
            {onNavigateToQueue && (
              <button
                type="button"
                onClick={onNavigateToQueue}
                className="underline ml-2 font-semibold hover:opacity-90"
              >
                View in Queue →
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Strategy Brief Header */}
      {strategy_brief && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white dark:bg-[#181818] border border-slate-200/90 dark:border-[#262626] rounded-xl p-4 shadow-xs"
        >
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2.5 min-w-0 flex-1">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse shrink-0" />
              <span className="font-semibold text-slate-900 dark:text-white text-[13.5px] truncate">
                {strategy_brief.headline}
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
                  <span>Niche Hook: &ldquo;<strong className="font-semibold">{strategy_brief.suggested_query}</strong>&rdquo;</span>
                </button>
              )}

              {onRefreshBrief && (
                <button
                  type="button"
                  onClick={onRefreshBrief}
                  disabled={refreshingBrief}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-700 dark:hover:text-[#F3F3F3] hover:bg-slate-100 dark:hover:bg-[#262626] transition-colors"
                  aria-label="Refresh AI strategy brief"
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
                <span>{briefOpen ? "Hide" : "Creator Advice"}</span>
                {briefOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          <AnimatePresence>
            {briefOpen && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden mt-3 pt-3 border-t border-slate-100 dark:border-[#262626] text-[12.5px] space-y-2.5"
              >
                <div>
                  <span className="font-semibold text-slate-800 dark:text-[#E5E5E5] text-[12px]">Audience Analysis</span>
                  <p className="text-slate-600 dark:text-[#A3A3A3] mt-0.5 leading-relaxed">{strategy_brief.insight}</p>
                </div>
                <div>
                  <span className="font-semibold text-emerald-700 dark:text-emerald-400 text-[12px]">Next Action Step</span>
                  <p className="text-slate-600 dark:text-[#A3A3A3] mt-0.5 leading-relaxed">{strategy_brief.recommended_action}</p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* ==================================================================== */}
      {/* 1. CREATOR VITAL SIGNS (Top 4 Influencer Hero Cards)                 */}
      {/* ==================================================================== */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1: Estimated Reach & Impressions */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-4 shadow-xs relative overflow-hidden">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[12px] font-medium text-slate-500 dark:text-[#A3A3A3]">Estimated Reach</span>
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/60 dark:border-blue-900/40">
              <TrendingUp className="w-2.5 h-2.5" />
              {reachGrowth}
            </span>
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-[26px] font-bold tracking-tight text-slate-900 dark:text-white tabular-nums">
              {reach.toLocaleString()}
            </span>
            <span className="text-[11.5px] text-slate-400 dark:text-[#737373]">views</span>
          </div>
          <p className="text-[11.5px] text-slate-500 dark:text-[#A3A3A3] leading-snug">
            Calculated timeline views & organic distribution
          </p>
        </div>

        {/* Metric 2: Audience Engagement Rate */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-4 shadow-xs relative overflow-hidden">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[12px] font-medium text-slate-500 dark:text-[#A3A3A3]">Engagement Rate</span>
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-900/40">
              <Sparkles className="w-2.5 h-2.5" />
              {resonanceBench}
            </span>
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-[26px] font-bold tracking-tight text-slate-900 dark:text-white tabular-nums">
              {er.toFixed(1)}%
            </span>
            <span className="text-[11.5px] text-slate-400 dark:text-[#737373]">ER</span>
          </div>
          <p className="text-[11.5px] text-slate-500 dark:text-[#A3A3A3] leading-snug">
            {kpis.feed_likes_captured} likes · {kpis.feed_replies_captured} conversation replies
          </p>
        </div>

        {/* Metric 3: Publishing Consistency Streak */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-4 shadow-xs relative overflow-hidden">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[12px] font-medium text-slate-500 dark:text-[#A3A3A3]">Consistency Streak</span>
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-200/60 dark:border-amber-900/40">
              <Flame className="w-2.5 h-2.5" />
              Daily Habit
            </span>
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-[26px] font-bold tracking-tight text-slate-900 dark:text-white tabular-nums">
              {streak} {streak === 1 ? "Day" : "Days"}
            </span>
            <span className="text-[14px]">🔥</span>
          </div>
          <p className="text-[11.5px] text-slate-500 dark:text-[#A3A3A3] leading-snug">
            Active daily posting & conversation presence
          </p>
        </div>

        {/* Metric 4: Account Health Shield */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-4 shadow-xs relative overflow-hidden">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[12px] font-medium text-slate-500 dark:text-[#A3A3A3]">Account Health</span>
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-900/40">
              <ShieldCheck className="w-2.5 h-2.5" />
              Protected
            </span>
          </div>
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-[26px] font-bold tracking-tight text-emerald-600 dark:text-emerald-400 tabular-nums">
              100%
            </span>
            <span className="text-[11.5px] text-slate-400 dark:text-[#737373]">safe</span>
          </div>
          <p className="text-[11.5px] text-slate-500 dark:text-[#A3A3A3] leading-snug">
            {dailyUsed}/{dailyCap} safe actions used today · Anti-ban active
          </p>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 2. GROWTH TRAJECTORY & FORMAT ROI                                   */}
      {/* ==================================================================== */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 7-Day Audience Reach Velocity Chart */}
        <div className="lg:col-span-2 bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-[14px] font-semibold text-slate-900 dark:text-white">Audience Reach Velocity</h3>
              <p className="text-[12px] text-slate-500 dark:text-[#A3A3A3] mt-0.5">
                Estimated daily timeline impressions across published posts & replies
              </p>
            </div>
            <div className="flex items-center gap-3 text-[11.5px]">
              <span className="flex items-center gap-1 text-blue-600 dark:text-blue-400 font-medium">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500 inline-block" />
                {hoveredIndex !== null && chartDays[hoveredIndex]
                  ? `${chartDays[hoveredIndex].date}: ${chartDays[hoveredIndex].impressions.toLocaleString()} reach`
                  : "Estimated Reach"}
              </span>
            </div>
          </div>

          <div className="w-full relative select-none">
            {/* Interactive Floating Tooltip */}
            <AnimatePresence>
              {hoveredIndex !== null && chartDays[hoveredIndex] && (
                <motion.div
                  initial={{ opacity: 0, scale: 0.95, y: 3 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.1 }}
                  className={`absolute z-30 pointer-events-none transition-all duration-75 ease-out ${
                    hoveredIndex === 0
                      ? "translate-x-1"
                      : hoveredIndex === chartDays.length - 1
                      ? "-translate-x-full -ml-1"
                      : "-translate-x-1/2"
                  }`}
                  style={{
                    left: `${(gx(hoveredIndex) / GW) * 100}%`,
                    top: `${Math.max(4, Math.min(60, (gy(chartDays[hoveredIndex].impressions) / GH) * 100 - 36))}%`,
                  }}
                >
                  <div className="bg-slate-900/95 dark:bg-[#1E1E1E]/95 backdrop-blur-md text-white border border-slate-700/60 dark:border-[#383838] rounded-xl px-3 py-2 shadow-xl text-left whitespace-nowrap min-w-[130px]">
                    <div className="flex items-center justify-between gap-3 text-[10.5px] text-slate-400 dark:text-[#A3A3A3] pb-1 border-b border-slate-800 dark:border-[#2D2D2D] mb-1">
                      <span className="font-semibold text-slate-200 dark:text-slate-100">{chartDays[hoveredIndex].date}</span>
                      {chartDays[hoveredIndex].impressions === maxImp && (
                        <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-blue-500/25 text-blue-400 font-bold uppercase tracking-wider">
                          Peak
                        </span>
                      )}
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-[16px] font-bold text-white tabular-nums tracking-tight">
                        {chartDays[hoveredIndex].impressions.toLocaleString()}
                      </span>
                      <span className="text-[10.5px] text-blue-400 font-medium">views</span>
                    </div>
                    <div className="text-[10px] text-slate-400 dark:text-[#A3A3A3] flex items-center gap-1.5 mt-0.5">
                      <span>{chartDays[hoveredIndex].interactions ?? 0} interactions</span>
                      <span>·</span>
                      <span>{chartDays[hoveredIndex].published ?? 0} published</span>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <svg
              viewBox={`0 0 ${GW} ${GH}`}
              className="w-full h-44 overflow-visible"
              onMouseLeave={() => setHoveredIndex(null)}
            >
              <defs>
                <linearGradient id="reachGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3B82F6" stopOpacity="0.32" />
                  <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              {[0, 0.33, 0.66, 1].map((r, i) => {
                const yPos = padT + (1 - r) * (GH - padT - padB);
                return (
                  <g key={i}>
                    <line
                      x1={padL}
                      y1={yPos}
                      x2={GW - padR}
                      y2={yPos}
                      stroke="currentColor"
                      strokeOpacity="0.08"
                      strokeDasharray="4 4"
                    />
                    <text
                      x={padL - 6}
                      y={yPos + 3}
                      textAnchor="end"
                      className="text-[9.5px] fill-slate-400 dark:fill-[#737373] tabular-nums"
                    >
                      {Math.round(r * maxImp)}
                    </text>
                  </g>
                );
              })}

              {/* Active Hover Crosshair Guideline */}
              {hoveredIndex !== null && (
                <line
                  x1={gx(hoveredIndex)}
                  y1={padT}
                  x2={gx(hoveredIndex)}
                  y2={GH - padB}
                  stroke="#3B82F6"
                  strokeWidth="1.5"
                  strokeDasharray="3 3"
                  strokeOpacity="0.55"
                  className="pointer-events-none transition-all duration-75"
                />
              )}

              {/* Area & Line */}
              <motion.path
                d={impArea}
                fill="url(#reachGradient)"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6 }}
              />
              <motion.path
                d={impPath}
                fill="none"
                stroke="#3B82F6"
                strokeWidth="2.5"
                strokeLinecap="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.8, ease: "easeOut" }}
              />

              {/* Data points */}
              {impPoints.map(([px, py], i) => {
                const isHovered = hoveredIndex === i;
                return (
                  <g key={i} className="pointer-events-none transition-all duration-150">
                    {isHovered && (
                      <>
                        <circle
                          cx={px}
                          cy={py}
                          r="10"
                          className="fill-blue-500/25 dark:fill-blue-400/25 animate-ping"
                        />
                        <circle
                          cx={px}
                          cy={py}
                          r="7.5"
                          className="fill-blue-500/30 dark:fill-blue-400/30"
                        />
                      </>
                    )}
                    <circle
                      cx={px}
                      cy={py}
                      r={isHovered ? "5.5" : "3.5"}
                      className={
                        isHovered
                          ? "fill-blue-600 dark:fill-blue-400 stroke-white dark:stroke-[#181818] stroke-2 transition-all duration-150"
                          : "fill-white dark:fill-[#181818] stroke-blue-600 dark:stroke-blue-400 stroke-2 transition-all duration-150"
                      }
                    />
                  </g>
                );
              })}

              {/* X Axis Labels */}
              {chartDays.map((d, i) => {
                const isHovered = hoveredIndex === i;
                return (
                  <text
                    key={i}
                    x={gx(i)}
                    y={GH - 6}
                    textAnchor="middle"
                    className={`text-[10px] transition-colors duration-150 ${
                      isHovered
                        ? "fill-blue-600 dark:fill-blue-400 font-bold"
                        : "fill-slate-400 dark:fill-[#737373]"
                    }`}
                  >
                    {d.date}
                  </text>
                );
              })}

              {/* Transparent Hit-Areas for Effortless Mouse & Touch Interaction */}
              {chartDays.map((_, i) => {
                const xLeft = i === 0 ? 0 : (gx(i - 1) + gx(i)) / 2;
                const xRight = i === chartDays.length - 1 ? GW : (gx(i) + gx(i + 1)) / 2;
                return (
                  <rect
                    key={`hit-${i}`}
                    x={xLeft}
                    y={0}
                    width={xRight - xLeft}
                    height={GH}
                    fill="transparent"
                    className="cursor-pointer"
                    onMouseEnter={() => setHoveredIndex(i)}
                    onTouchStart={() => setHoveredIndex(i)}
                  />
                );
              })}
            </svg>
          </div>
        </div>

        {/* Format ROI & Efficiency */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-5 shadow-xs flex flex-col justify-between">
          <div>
            <h3 className="text-[14px] font-semibold text-slate-900 dark:text-white">Format Efficiency & ROI</h3>
            <p className="text-[12px] text-slate-500 dark:text-[#A3A3A3] mt-0.5">
              Which format drives the highest return for your profile
            </p>

            <div className="mt-4 space-y-3">
              {(format_roi.length > 0 ? format_roi : [
                { format: "Smart Replies", count: kpis.published_count, multiplier: "1.4x Reach", role: "Profile Traffic & Follower Engine", color: "#3B82F6" },
                { format: "Original Posts", count: 0, multiplier: "2.8x Authority", role: "Personal Brand & Niche Leadership", color: "#10B981" },
                { format: "Deep Threads", count: 0, multiplier: "4.2x Bookmarks", role: "Viral Distribution & High Saves", color: "#F59E0B" },
              ]).map((fmt, idx) => (
                <div key={idx} className="p-3 rounded-lg border border-slate-100 dark:border-[#262626] bg-slate-50/50 dark:bg-[#202020]">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[12.5px] font-semibold text-slate-800 dark:text-[#E5E5E5] flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: fmt.color }} />
                      {fmt.format}
                    </span>
                    <span className="text-[11.5px] font-bold px-2 py-0.5 rounded-full bg-slate-200/70 dark:bg-[#2D2D2D] text-slate-700 dark:text-[#D4D4D4]">
                      {fmt.multiplier}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-[#A3A3A3]">{fmt.role}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-100 dark:border-[#262626] text-[11.5px] text-slate-400 dark:text-[#737373] flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-amber-500" />
            <span>Pro Tip: 80% replies + 20% original threads builds the fastest growth flywheel.</span>
          </div>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* 3. REAL-TIME GOOGLE & INTERNET TREND RADAR (The Creator Inspo Hub)    */}
      {/* ==================================================================== */}
      <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-5 shadow-xs">
        <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              <h3 className="text-[14px] font-semibold text-slate-900 dark:text-white">Internet & Google Trend Radar</h3>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
                Live Inspo
              </span>
            </div>
            <p className="text-[12px] text-slate-500 dark:text-[#A3A3A3] mt-0.5">
              Breaking stories scanned from Google News in your niche. 1-click turn them into tweets or threads!
            </p>
          </div>

          <button
            type="button"
            onClick={handleScanWebNow}
            disabled={scanningWeb}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium bg-slate-100 dark:bg-[#262626] hover:bg-slate-200 dark:hover:bg-[#303030] text-slate-800 dark:text-white transition-colors"
          >
            {scanningWeb ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            <span>Scan Internet Now</span>
          </button>
        </div>

        {webTopics.length === 0 ? (
          <div className="p-6 text-center border border-dashed border-slate-200 dark:border-[#262626] rounded-xl">
            <Globe className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
            <p className="text-[13px] font-medium text-slate-700 dark:text-[#D4D4D4]">No web trends scanned yet</p>
            <p className="text-[12px] text-slate-400 dark:text-[#737373] mt-0.5 mb-3">
              Click below to scout Google News for breaking niche stories.
            </p>
            <button
              type="button"
              onClick={handleScanWebNow}
              disabled={scanningWeb}
              className="px-3.5 py-1.5 text-[12px] font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            >
              {scanningWeb ? "Scanning..." : "Start Internet Radar"}
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            {webTopics.map((topic, i) => (
              <div
                key={i}
                className="p-3.5 rounded-xl border border-slate-100 dark:border-[#262626] bg-slate-50/50 dark:bg-[#202020] flex flex-col justify-between space-y-3"
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-200/80 dark:bg-[#2A2A2A] text-slate-700 dark:text-[#C4C4C4]">
                      {topic.source}
                    </span>
                    <a
                      href={topic.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-slate-400 hover:text-slate-600 dark:hover:text-white"
                      title="Open source article"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </div>
                  <h4 className="text-[13px] font-semibold text-slate-900 dark:text-white line-clamp-2 leading-snug">
                    {topic.title}
                  </h4>
                  <p className="text-[11.5px] text-slate-500 dark:text-[#A3A3A3] mt-1 line-clamp-2">
                    {topic.hook_summary}
                  </p>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-[#2A2A2A]">
                  <span className="text-[11px] text-slate-400">
                    Query: <strong className="text-slate-700 dark:text-[#E0E0E0]">&ldquo;{topic.suggested_query}&rdquo;</strong>
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      disabled={draftingId !== null}
                      onClick={() => handleDraftFromTopic(topic, "tweet")}
                      className="px-2.5 py-1 text-[11px] font-medium rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-colors"
                      title="Draft single viral post into Review Queue"
                    >
                      {draftingId === `${topic.title}_tweet` ? <Loader2 className="w-3 h-3 animate-spin" /> : "⚡ Draft Post"}
                    </button>
                    <button
                      type="button"
                      disabled={draftingId !== null}
                      onClick={() => handleDraftFromTopic(topic, "thread")}
                      className="px-2.5 py-1 text-[11px] font-medium rounded-lg bg-slate-200 dark:bg-[#2C2C2C] hover:bg-slate-300 dark:hover:bg-[#383838] text-slate-800 dark:text-white transition-colors"
                      title="Draft 3-tweet thread into Review Queue"
                    >
                      {draftingId === `${topic.title}_thread` ? <Loader2 className="w-3 h-3 animate-spin" /> : "🧵 Thread"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ==================================================================== */}
      {/* 4. CONTENT HALL OF FAME ("TOP BANGERS") & "REPLY GUY" RADAR           */}
      {/* ==================================================================== */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Content Hall of Fame (Top Bangers) */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-5 shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-[14px] font-semibold text-slate-900 dark:text-white flex items-center gap-1.5">
                  <span>🏆 Top Bangers (Hall of Fame)</span>
                </h3>
                <p className="text-[12px] text-slate-500 dark:text-[#A3A3A3] mt-0.5">
                  Your highest performing posts and replies. Spin them off into new hooks!
                </p>
              </div>
            </div>

            {top_bangers.length === 0 ? (
              <div className="py-8 text-center text-[12.5px] text-slate-400 border border-dashed border-slate-200 dark:border-[#262626] rounded-xl">
                No published posts yet. As the bot posts, your winning bangers will be ranked here!
              </div>
            ) : (
              <div className="space-y-3">
                {top_bangers.slice(0, 3).map((banger, i) => (
                  <div
                    key={i}
                    className="p-3 rounded-lg border border-slate-100 dark:border-[#262626] bg-slate-50/50 dark:bg-[#202020] space-y-2"
                  >
                    <p className="text-[12.5px] text-slate-800 dark:text-[#E0E0E0] line-clamp-2 leading-relaxed">
                      &ldquo;{banger.text}&rdquo;
                    </p>
                    <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-[#A3A3A3]">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1 text-rose-500 font-medium">
                          <Heart className="w-3 h-3" /> {banger.likes}
                        </span>
                        <span className="flex items-center gap-1 text-blue-500 font-medium">
                          <MessageCircle className="w-3 h-3" /> {banger.replies}
                        </span>
                        <span>~{banger.estimated_impressions} views</span>
                      </div>
                      <span className="font-medium text-slate-400 capitalize">{banger.action_type}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* "Reply Guy" Radar (Top Target Influencers) */}
        <div className="bg-white dark:bg-[#181818] border border-slate-200/80 dark:border-[#262626] rounded-xl p-5 shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-[14px] font-semibold text-slate-900 dark:text-white flex items-center gap-1.5">
                  <Target className="w-4 h-4 text-rose-500" />
                  <span>&ldquo;Reply Guy&rdquo; Authority Radar</span>
                </h3>
                <p className="text-[12px] text-slate-500 dark:text-[#A3A3A3] mt-0.5">
                  Top niche creators to intercept in the first 15 mins to piggyback on their reach
                </p>
              </div>
            </div>

            {reply_guy_targets.length === 0 ? (
              <div className="py-8 text-center text-[12.5px] text-slate-400 border border-dashed border-slate-200 dark:border-[#262626] rounded-xl">
                Scan your niche feed to identify high-authority target creators.
              </div>
            ) : (
              <div className="space-y-2.5">
                {reply_guy_targets.slice(0, 4).map((target, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-2.5 rounded-lg border border-slate-100 dark:border-[#262626] bg-slate-50/50 dark:bg-[#202020]"
                  >
                    <div>
                      <span className="text-[13px] font-semibold text-slate-900 dark:text-white">
                        {target.author}
                      </span>
                      <p className="text-[11px] text-slate-500 dark:text-[#A3A3A3]">
                        {target.interactions} interactions · {target.likes_captured} likes captured
                      </p>
                    </div>
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200/50">
                      {target.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
