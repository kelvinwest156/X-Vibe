"use client";

import { useState } from "react";
import {
  DailySeriesPoint,
  formatCompactTokens,
  formatFullNumber,
  formatUsd,
} from "@/lib/api";
import { cn } from "@/lib/cn";

interface AdminSpendChartProps {
  series: DailySeriesPoint[];
  days: number;
  loading?: boolean;
}

type ChartMetric = "spend" | "tokens";

export function AdminSpendChart({ series, days, loading = false }: AdminSpendChartProps) {
  const [metric, setMetric] = useState<ChartMetric>("spend");
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (loading) {
    return (
      <div className="rounded-lg border border-line bg-surface p-5">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="h-4 w-44 rounded bg-line/70" />
            <div className="h-3 w-64 rounded bg-line/50" />
          </div>
          <div className="h-7 w-36 rounded bg-line/60" />
        </div>
        <div className="mt-6 h-52 w-full rounded bg-canvas border border-line/60" />
      </div>
    );
  }

  const values = series.map((pt) => (metric === "spend" ? pt.cost_usd : pt.total_tokens));
  const maxVal = Math.max(...values, metric === "spend" ? 0.01 : 1000);
  const totalPeriodCost = series.reduce((acc, p) => acc + p.cost_usd, 0);
  const totalPeriodTokens = series.reduce((acc, p) => acc + p.total_tokens, 0);
  const hasAnyData = series.some((p) => p.calls > 0 || p.total_tokens > 0 || p.cost_usd > 0);

  const svgWidth = 640;
  const svgHeight = 200;
  const padTop = 16;
  const padBottom = 28;
  const padLeft = 8;
  const padRight = 8;
  const plotW = svgWidth - padLeft - padRight;
  const plotH = svgHeight - padTop - padBottom;

  const count = Math.max(series.length, 1);
  const stepW = plotW / count;
  const barW = Math.max(8, Math.min(36, stepW * 0.56));

  const activePoint = hoveredIdx !== null ? series[hoveredIdx] : null;

  return (
    <div className="rounded-lg border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink text-balance">
            Daily AI ledger ({days} days)
          </h2>
          <p className="mt-0.5 text-xs text-muted text-pretty">
            Total {formatUsd(totalPeriodCost)} across {formatCompactTokens(totalPeriodTokens)} tokens.
          </p>
        </div>

        <div
          role="group"
          aria-label="Chart metric"
          className="inline-flex rounded-md border border-line bg-canvas p-0.5 text-xs"
        >
          <button
            type="button"
            onClick={() => setMetric("spend")}
            className={cn(
              "rounded px-2.5 py-1 font-medium",
              metric === "spend" ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
            )}
          >
            Spend
          </button>
          <button
            type="button"
            onClick={() => setMetric("tokens")}
            className={cn(
              "rounded px-2.5 py-1 font-medium",
              metric === "tokens" ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"
            )}
          >
            Tokens
          </button>
        </div>
      </div>

      {/* Hover readout bar (stable height — prevents layout jump) */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-canvas px-3 py-2 text-xs">
        {activePoint ? (
          <>
            <span className="font-medium text-ink">{activePoint.label}</span>
            <div className="flex flex-wrap items-center gap-4 font-mono tabular-nums text-muted">
              <span className="text-ink font-medium">{formatUsd(activePoint.cost_usd)}</span>
              <span>{formatFullNumber(activePoint.total_tokens)} tok</span>
              <span className="text-emerald-600 dark:text-emerald-500">
                {formatCompactTokens(activePoint.cache_hit_tokens)} cached
              </span>
              <span>{activePoint.calls} calls</span>
            </div>
          </>
        ) : (
          <>
            <span className="text-muted">Hover or focus any day bar to inspect cache hits and cost</span>
            <div className="flex items-center gap-3 text-muted">
              <span className="inline-flex items-center gap-1.5">
                <span className="size-2 rounded-sm bg-emerald-600" />
                {metric === "spend" ? "Daily spend" : "Cache hit"}
              </span>
              {metric === "tokens" && (
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-2 rounded-sm bg-ink/70" />
                  Uncached + output
                </span>
              )}
            </div>
          </>
        )}
      </div>

      {!hasAnyData ? (
        <div className="mt-4 flex h-44 flex-col items-center justify-center rounded-md border border-dashed border-line bg-canvas px-4 text-center">
          <p className="text-sm font-medium text-ink">No AI token usage recorded yet</p>
          <p className="mt-1 max-w-sm text-xs text-muted text-pretty">
            Token spend and DeepSeek prompt-cache savings appear here automatically as creators scan feeds or draft posts.
          </p>
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <svg
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            className="h-52 w-full min-w-[360px]"
            role="img"
            aria-label={`Daily ${metric} chart over the last ${days} days`}
            onMouseLeave={() => setHoveredIdx(null)}
          >
            {/* Horizontal hairline gridlines */}
            {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
              const y = padTop + plotH * (1 - ratio);
              return (
                <line
                  key={ratio}
                  x1={padLeft}
                  x2={svgWidth - padRight}
                  y1={y}
                  y2={y}
                  stroke="currentColor"
                  className="text-line"
                  strokeWidth={1}
                />
              );
            })}

            {series.map((pt, idx) => {
              const val = metric === "spend" ? pt.cost_usd : pt.total_tokens;
              const barH = val > 0 ? Math.max(3, (val / maxVal) * plotH) : 0;
              const centerX = padLeft + idx * stepW + stepW / 2;
              const x = centerX - barW / 2;
              const y = padTop + plotH - barH;
              const isActive = hoveredIdx === idx;

              // Split bar into cache_hit vs remaining tokens when viewing tokens
              const cacheRatio =
                metric === "tokens" && pt.total_tokens > 0
                  ? Math.min(1, pt.cache_hit_tokens / pt.total_tokens)
                  : 1;
              const cachedH = barH * cacheRatio;
              const uncachedH = Math.max(0, barH - cachedH);

              const showLabel =
                series.length <= 10 ||
                idx === 0 ||
                idx === series.length - 1 ||
                idx % Math.ceil(series.length / 7) === 0;

              return (
                <g
                  key={pt.date}
                  tabIndex={0}
                  role="button"
                  aria-label={`${pt.label}: ${formatUsd(pt.cost_usd)}, ${formatFullNumber(pt.total_tokens)} tokens, ${pt.calls} calls`}
                  onMouseEnter={() => setHoveredIdx(idx)}
                  onFocus={() => setHoveredIdx(idx)}
                  onBlur={() => setHoveredIdx((prev) => (prev === idx ? null : prev))}
                  className="cursor-pointer outline-none"
                >
                  {/* Full-column hover hit target */}
                  <rect
                    x={padLeft + idx * stepW}
                    y={padTop}
                    width={stepW}
                    height={plotH}
                    fill="transparent"
                  />

                  {isActive && (
                    <rect
                      x={padLeft + idx * stepW + 2}
                      y={padTop}
                      width={Math.max(0, stepW - 4)}
                      height={plotH}
                      rx={3}
                      fill="currentColor"
                      className="text-ink/5"
                    />
                  )}

                  {barH > 0 && metric === "spend" && (
                    <rect
                      x={x}
                      y={y}
                      width={barW}
                      height={barH}
                      rx={2}
                      className={cn(
                        isActive ? "fill-emerald-600" : "fill-emerald-600/80"
                      )}
                    />
                  )}

                  {barH > 0 && metric === "tokens" && (
                    <>
                      {uncachedH > 0 && (
                        <rect
                          x={x}
                          y={y}
                          width={barW}
                          height={uncachedH}
                          rx={2}
                          className={cn(
                            isActive ? "fill-ink/85" : "fill-ink/60"
                          )}
                        />
                      )}
                      {cachedH > 0 && (
                        <rect
                          x={x}
                          y={padTop + plotH - cachedH}
                          width={barW}
                          height={cachedH}
                          rx={2}
                          className={cn(
                            isActive ? "fill-emerald-600" : "fill-emerald-600/85"
                          )}
                        />
                      )}
                    </>
                  )}

                  {showLabel && (
                    <text
                      x={centerX}
                      y={svgHeight - 8}
                      textAnchor="middle"
                      className="fill-muted font-mono text-[10px]"
                    >
                      {pt.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </div>
  );
}
