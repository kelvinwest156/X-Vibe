"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";

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
  content_mix: Array<{ label: string; key: string; count: number; color: string }>;
  status_funnel: Array<{ label: string; count: number; color: string }>;
  length_distribution: Array<{ label: string; count: number; color: string }>;
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

// Power BI default data palette
const C = {
  teal: "#01b8aa",
  slate: "#374649",
  yellow: "#f2c811",
  coral: "#fd625e",
  sky: "#8ad4eb",
  plum: "#a66999",
  grid: "#edebe9",
  axis: "#8a8886",
};

const MIX_COLORS: Record<string, string> = {
  reply: C.slate,
  post: C.teal,
  thread: C.yellow,
};
const FUNNEL_COLORS = [C.teal, C.sky, C.yellow, "#c8c6c4"];
const LENGTH_COLORS = [C.sky, C.teal, C.slate];

function Spark({ points, color }: { points: number[]; color: string }) {
  const w = 96;
  const h = 28;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const span = Math.max(max - min, 1);
  const pts = points.map((p, i) => [
    (i / Math.max(points.length - 1, 1)) * w,
    h - 3 - ((p - min) / span) * (h - 6),
  ]);
  const d = "M " + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ");
  return (
    <svg width={w} height={h} className="shrink-0">
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth="1.75"
        strokeLinejoin="round"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.9, ease: "easeOut" }}
      />
    </svg>
  );
}

function Tile({
  title,
  sub,
  className = "",
  children,
  delay = 0,
}: {
  title: string;
  sub?: string;
  className?: string;
  children: React.ReactNode;
  delay?: number;
}) {
  return (
    <motion.section
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.35, delay }}
      className={`tile p-4 ${className}`}
    >
      <header className="mb-3">
        <h3 className="tile-title">{title}</h3>
        {sub && <p className="tile-sub mt-0.5">{sub}</p>}
      </header>
      {children}
    </motion.section>
  );
}

export default function AnalyticsView({ data }: { data: AnalyticsData | null }) {
  const [hover, setHover] = useState<number | null>(null);

  if (!data) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="tile h-28 animate-pulse" />
          ))}
        </div>
        <div className="tile h-[300px] flex flex-col items-center justify-center gap-3 text-ink-2">
          <Loader2 className="w-6 h-6 animate-spin" aria-label="Loading" />
          <span className="caption">Loading analytics</span>
        </div>
      </div>
    );
  }

  const {
    kpis,
    strategy_brief,
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

  const kpiTiles = [
    {
      label: "In pipeline",
      value: pipeline.toLocaleString(),
      note: `${kpis.published_count} published, ${kpis.scheduled_count} scheduled`,
      spark: timeline.map((t) => t.drafted),
      color: C.teal,
    },
    {
      label: "Approval rate",
      value: `${kpis.approval_rate}%`,
      note: `${kpis.total_evaluated} posts reviewed · ${learnedCount} voice samples`,
      color: C.slate,
    },
    {
      label: "Feed engagement",
      value: (kpis.feed_likes_captured + kpis.feed_replies_captured).toLocaleString(),
      note: `${kpis.feed_likes_captured} likes, ${kpis.feed_replies_captured} replies`,
      spark: timeline.map((t) => t.engagement),
      color: C.yellow,
    },
    {
      label: "Anti-detection pace",
      value: `${hourlyUsed}/${hourlyCap} hr`,
      note: `Today ${kpis.daily_used}/${kpis.daily_cap} · Avg ${kpis.avg_draft_length}c`,
      color: C.coral,
    },
  ];

  // Line chart geometry
  const W = 640;
  const H = 220;
  const padL = 34;
  const padR = 12;
  const padT = 12;
  const padB = 26;
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
  const R = 52;
  const CIRC = 2 * Math.PI * R;
  let acc = 0;

  const maxFunnel = Math.max(...status_funnel.map((s) => s.count), 1);
  const maxLen = Math.max(...length_distribution.map((l) => l.count), 1);

  return (
    <div className="space-y-3">
      {strategy_brief && (
        <motion.section
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="tile p-4 relative"
        >
          <span
            className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-[4px]"
            style={{ background: C.yellow }}
          />
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1 max-w-3xl">
              <div className="flex items-center gap-2">
                <span className="tag" style={{ background: "#fff8d6", color: "#5c4800" }}>
                  AI Strategy Brief
                </span>
                {velocity_shield?.smart_query_enabled && (
                  <span className="tag">
                    Smart Query: {velocity_shield.active_search_query}
                  </span>
                )}
                {velocity_shield?.warmup_mode && (
                  <span className="tag" style={{ background: "#dff6dd", color: "#107c41" }}>
                    Warmup Shield Active
                  </span>
                )}
              </div>
              <h3 className="text-[14px] font-semibold text-ink pt-0.5">
                {strategy_brief.headline}
              </h3>
              <p className="text-[12.5px] text-ink-2 leading-relaxed">
                {strategy_brief.insight}{" "}
                <strong className="font-semibold text-ink">Next step:</strong>{" "}
                {strategy_brief.recommended_action}
              </p>
            </div>
            <div className="flex flex-col items-end gap-1 text-right shrink-0">
              <span className="caption">2026 Biometric & Velocity Shield</span>
              <span className="text-[12px] font-semibold text-[#107c41]">
                Bezier Mouse · Dwell Time · {hourlyUsed}/{hourlyCap} Hourly Cap
              </span>
              <span className="caption">
                Suggested Pulse: &ldquo;{strategy_brief.suggested_query}&rdquo;
              </span>
            </div>
          </div>
        </motion.section>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpiTiles.map((k, i) => (
          <motion.div
            key={k.label}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.05 }}
            className="tile p-4 relative"
          >
            <span
              className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l-[4px]"
              style={{ background: k.color }}
            />
            <p className="caption">{k.label}</p>
            <div className="mt-1 flex items-end justify-between gap-2">
              <span className="text-[30px] leading-none font-semibold text-ink tracking-tight">
                {k.value}
              </span>
              {k.spark && k.spark.some((v) => v > 0) && <Spark points={k.spark} color={k.color} />}
            </div>
            <p className="tile-sub mt-2">{k.note}</p>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        <Tile
          title="Engagement and drafts over time"
          sub="Likes and replies seen in the feed, against drafts created, per 2-hour window"
          className="lg:col-span-8"
          delay={0.1}
        >
          <div className="flex items-center gap-4 mb-1 caption">
            <span className="flex items-center gap-1.5">
              <i className="w-3 h-[3px] inline-block" style={{ background: C.teal }} /> Engagement
            </span>
            <span className="flex items-center gap-1.5">
              <i className="w-3 h-[3px] inline-block" style={{ background: C.yellow }} /> Drafts
            </span>
          </div>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[230px] select-none">
            {[0, 0.25, 0.5, 0.75, 1].map((r) => {
              const yy = padT + r * (H - padT - padB);
              return (
                <g key={r}>
                  <line x1={padL} x2={W - padR} y1={yy} y2={yy} stroke={C.grid} />
                  <text x={padL - 6} y={yy + 3} textAnchor="end" fontSize="10" fill={C.axis}>
                    {Math.round((1 - r) * maxEng)}
                  </text>
                </g>
              );
            })}
            <motion.path
              d={engArea}
              fill={C.teal}
              fillOpacity="0.12"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6 }}
            />
            <motion.path
              d={engPath}
              fill="none"
              stroke={C.teal}
              strokeWidth="2.25"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 1, ease: "easeOut" }}
            />
            <motion.path
              d={drPath}
              fill="none"
              stroke={C.yellow}
              strokeWidth="2.25"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 1, delay: 0.1, ease: "easeOut" }}
            />
            {timeline.map((t, i) => (
              <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect
                  x={x(i) - 22}
                  y={padT}
                  width="44"
                  height={H - padT - padB}
                  fill="transparent"
                />
                <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" fill={C.axis}>
                  {t.time}
                </text>
                {hover === i && (
                  <>
                    <line
                      x1={x(i)}
                      x2={x(i)}
                      y1={padT}
                      y2={H - padB}
                      stroke="#c8c6c4"
                      strokeDasharray="3 3"
                    />
                    <circle cx={x(i)} cy={yEng(t.engagement)} r="4" fill={C.teal} />
                    <circle cx={x(i)} cy={yDr(t.drafted)} r="4" fill={C.yellow} />
                    <g
                      transform={`translate(${Math.min(Math.max(x(i) - 62, padL), W - 138)}, ${padT})`}
                    >
                      <rect width="124" height="46" rx="2" fill="#fff" stroke="#c8c6c4" />
                      <text x="8" y="16" fontSize="11" fontWeight="600" fill="#252423">
                        {t.time}
                      </text>
                      <text x="8" y="30" fontSize="10" fill="#605e5c">
                        Engagement {t.engagement}
                      </text>
                      <text x="8" y="41" fontSize="10" fill="#605e5c">
                        Drafts {t.drafted}, scanned {t.evaluated}
                      </text>
                    </g>
                  </>
                )}
              </g>
            ))}
          </svg>
        </Tile>

        <Tile title="Content by type" className="lg:col-span-4" delay={0.15}>
          <div className="flex items-center gap-5">
            <div className="relative shrink-0">
              <svg width="132" height="132" viewBox="0 0 132 132" className="-rotate-90">
                <circle cx="66" cy="66" r={R} fill="none" stroke={C.grid} strokeWidth="16" />
                {mixTotal > 0 &&
                  content_mix.map((seg) => {
                    const frac = seg.count / mixTotal;
                    const dash = frac * CIRC;
                    const off = -acc * CIRC;
                    acc += frac;
                    return (
                      <motion.circle
                        key={seg.key}
                        cx="66"
                        cy="66"
                        r={R}
                        fill="none"
                        stroke={MIX_COLORS[seg.key] || C.sky}
                        strokeWidth="16"
                        strokeDashoffset={off}
                        initial={{ strokeDasharray: `0 ${CIRC}` }}
                        animate={{ strokeDasharray: `${dash} ${CIRC}` }}
                        transition={{ duration: 0.8, ease: "easeOut" }}
                      />
                    );
                  })}
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-semibold text-ink leading-none">{mixTotal}</span>
                <span className="caption mt-1">total</span>
              </div>
            </div>
            <ul className="flex-1 space-y-2.5">
              {content_mix.map((m) => (
                <li key={m.key} className="flex items-center justify-between text-[13px]">
                  <span className="flex items-center gap-2 text-ink-2">
                    <i
                      className="w-2.5 h-2.5 inline-block"
                      style={{ background: MIX_COLORS[m.key] || C.sky }}
                    />
                    {m.label}
                  </span>
                  <span className="font-semibold text-ink">{m.count}</span>
                </li>
              ))}
            </ul>
          </div>
        </Tile>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        <Tile title="Where posts end up" className="lg:col-span-4" delay={0.2}>
          <ul className="space-y-3">
            {status_funnel.map((s, i) => (
              <li key={s.label}>
                <div className="flex items-center justify-between text-[13px] mb-1">
                  <span className="text-ink-2">{s.label}</span>
                  <span className="font-semibold text-ink">{s.count}</span>
                </div>
                <div className="h-[10px] bg-[#f3f2f1]">
                  <motion.div
                    className="h-full"
                    style={{ background: FUNNEL_COLORS[i % FUNNEL_COLORS.length] }}
                    initial={{ width: 0 }}
                    animate={{ width: `${(s.count / maxFunnel) * 100}%` }}
                    transition={{ duration: 0.7, ease: "easeOut" }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </Tile>

        <Tile title="Draft length" sub="Characters per generated draft" className="lg:col-span-3" delay={0.25}>
          <div className="flex items-end justify-between gap-3 h-[132px]">
            {length_distribution.map((l, i) => (
              <div key={l.label} className="flex-1 flex flex-col items-center justify-end h-full">
                <span className="text-[13px] font-semibold text-ink mb-1">{l.count}</span>
                <motion.div
                  className="w-full max-w-[44px]"
                  style={{ background: LENGTH_COLORS[i % LENGTH_COLORS.length] }}
                  initial={{ height: 0 }}
                  animate={{ height: `${Math.max((l.count / maxLen) * 88, l.count ? 6 : 2)}px` }}
                  transition={{ duration: 0.7, ease: "easeOut" }}
                />
              </div>
            ))}
          </div>
          <div className="flex justify-between gap-3 mt-2">
            {length_distribution.map((l) => (
              <span key={l.label} className="flex-1 text-center caption leading-tight">
                {l.label.replace(/\s*\(.*\)/, "")}
              </span>
            ))}
          </div>
        </Tile>

        <Tile
          title="Top conversations"
          sub="Ranked by likes plus 3 per reply"
          className="lg:col-span-5"
          delay={0.3}
        >
          {top_authors.length === 0 ? (
            <p className="caption py-6">Scan your feed to see ranked conversations.</p>
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left caption border-b border-line">
                  <th className="pb-1.5 font-medium">Author</th>
                  <th className="pb-1.5 font-medium text-right">Likes</th>
                  <th className="pb-1.5 font-medium text-right">Replies</th>
                  <th className="pb-1.5 font-medium text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {top_authors.map((a) => (
                  <tr key={a.author} className="border-b border-[#f3f2f1] last:border-0">
                    <td className="py-1.5 font-semibold text-ink truncate max-w-[140px]">
                      {a.author}
                    </td>
                    <td className="py-1.5 text-right text-ink-2">{a.likes}</td>
                    <td className="py-1.5 text-right text-ink-2">{a.replies}</td>
                    <td className="py-1.5 text-right font-semibold text-ink">{a.score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Tile>
      </div>
    </div>
  );
}
