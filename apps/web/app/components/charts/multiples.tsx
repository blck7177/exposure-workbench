"use client";

import React from "react";

import { C, fmtDate, lin, Tooltip, useTooltip, useWidth, type TipRow } from "./frame";

/**
 * One small chart per thing, on a shared calendar axis (V25).
 *
 * WHY CALENDAR TIME, and not one step per update. This desk updated the demo
 * book six times in late July and then not again until August 20th. Drawn by
 * index, that five-week silence is one tick wide and the line reads as a steady
 * march; drawn by date, it is a five-week gap, which is what happened. The
 * points are still points — each is what one run recorded, and the line between
 * two of them is not a claim that anything was measured in between, which is
 * what the note under the panel says.
 *
 * WHY ONE Y-SCALE PER CHART AND ONE X-SCALE FOR ALL. The x is the same question
 * for every panel — when — so a shared domain is what makes the grid
 * comparable. The y is a different question per measure: MSFT's weight lives
 * near 16% and NVDA's near 4%, and a shared y would draw NVDA as a flat line at
 * the bottom of its cell. Each chart is about ITS OWN movement, and the tier
 * rules are what keep the reader from reading the amplitude as the point.
 *
 * A rule is drawn where a threshold sits, labelled at the left where there is
 * always room — a label at the right end fights the last value, which is the
 * one number that must be readable.
 */

export type MultiplePoint = { date: string; value: number };

export type MultipleRule = {
  value: number;
  colour: string;
  label: string;
};

export type Multiple = {
  key: string;
  label: string;
  points: MultiplePoint[];
  /** Thresholds this measure is judged against. Drawn only when they are within
   *  reach of the series — a warning tier four times the highest point drawn
   *  would flatten the line into the axis to make room for a rule nothing is
   *  near. */
  rules?: MultipleRule[];
  /** A short state word beside the name: `warning`, `breach`, `ok`. */
  status?: string | null;
  colour?: string;
  /** Drawn forward, others drawn back. The page's focus, not this component's. */
  lit?: boolean;
};

const CELL_H = 62;
const PAD_LEFT = 4;
const PAD_RIGHT = 46;

export function SmallMultiples({
  charts, format, columns = 2, ariaLabel, onPoint, dimOthers = false, axisLabels,
}: {
  charts: Multiple[];
  format: (v: number) => string;
  columns?: number;
  ariaLabel: string;
  /** Hovering a chart tells the page what is being pointed at. */
  onPoint?: (key: string | null) => void;
  dimOthers?: boolean;
  /** The dates written under the grid. Given rather than derived so the row of
   *  charts and the caption cannot disagree about the window. */
  axisLabels?: string[];
}) {
  const { tip, show, hide } = useTooltip();
  const days = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
  const all = charts.flatMap((c) => c.points.map((p) => days(p.date)));
  if (all.length === 0) {
    return <p className="text-xs text-slate-600 py-6">No update has recorded this yet.</p>;
  }
  const t0 = Math.min(...all);
  const t1 = Math.max(...all);

  return (
    <div className="relative">
      <div className="grid gap-x-4 gap-y-2.5"
        style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        role="group" aria-label={ariaLabel}>
        {charts.map((chart) => (
          <One key={chart.key} chart={chart} t0={t0} t1={t1} format={format}
            dimmed={dimOthers && chart.lit === false}
            onEnter={() => onPoint?.(chart.key)} onLeave={() => onPoint?.(null)}
            show={show} hide={hide} />
        ))}
      </div>
      {axisLabels && axisLabels.length > 0 && (
        <div className="flex justify-between font-mono text-[9.5px] text-slate-600 mt-1"
          style={{ paddingRight: PAD_RIGHT }}>
          {axisLabels.map((l, i) => <span key={`${l}-${i}`}>{l}</span>)}
        </div>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

function One({ chart, t0, t1, format, dimmed, onEnter, onLeave, show, hide }: {
  chart: Multiple;
  t0: number; t1: number;
  format: (v: number) => string;
  dimmed: boolean;
  onEnter: () => void;
  onLeave: () => void;
  show: (x: number, y: number, title: string, rows: TipRow[]) => void;
  hide: () => void;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const w = Math.max(width, 120);
  const days = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
  const X = (iso: string) =>
    PAD_LEFT + (t1 === t0 ? 0 : (days(iso) - t0) / (t1 - t0)) * (w - PAD_LEFT - PAD_RIGHT);

  const values = chart.points.map((p) => p.value);
  if (values.length === 0) return <div ref={ref} />;
  // A rule joins the domain only when the series is already within reach of it:
  // otherwise the line it is meant to judge gets squashed to make room.
  const near = (chart.rules ?? []).filter(
    (r) => r.value <= Math.max(...values) * 1.35 && r.value >= Math.min(...values) * 0.6);
  const lo = Math.min(...values, ...near.map((r) => r.value));
  const hi = Math.max(...values, ...near.map((r) => r.value));
  const pad = (hi - lo) * 0.18 || Math.abs(hi) * 0.05 || 0.001;
  const Y = lin(lo - pad, hi + pad, CELL_H - 6, 8);
  const colour = chart.colour ?? C.s1;
  const last = chart.points[chart.points.length - 1];

  return (
    <div ref={ref} className="min-w-0" style={{ opacity: dimmed ? 0.4 : 1 }}
      onPointerEnter={onEnter} onPointerLeave={() => { onLeave(); hide(); }}>
      <div className="flex items-baseline justify-between gap-2 text-[11px] mb-0.5">
        <span className={`truncate ${chart.lit === false ? "text-slate-500" : "text-slate-300"}`}>
          {chart.label}
        </span>
        {chart.status && chart.status !== "ok" && (
          <span className="font-mono text-[9.5px] px-1.5 rounded bg-amber-500/15 text-amber-400 shrink-0">
            {chart.status}
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${w} ${CELL_H}`} width="100%" height={CELL_H} role="img"
        aria-label={`${chart.label}, ${chart.points.length} updates, ending ${format(last.value)}`}>
        {near.map((r) => (
          <g key={r.label}>
            <line x1={PAD_LEFT} x2={w - PAD_RIGHT} y1={Y(r.value)} y2={Y(r.value)}
              stroke={r.colour} strokeWidth={1.25} strokeDasharray="3 3" />
            <text x={PAD_LEFT + 1} y={Y(r.value) - 3} fontFamily="var(--font-geist-mono)"
              fontSize={8.5} fill={r.colour}>{r.label}</text>
          </g>
        ))}
        <path
          d={chart.points.map((p, i) => `${i ? "L" : "M"}${X(p.date).toFixed(1)} ${Y(p.value).toFixed(1)}`).join("")}
          fill="none" stroke={colour} strokeWidth={chart.lit ? 2 : 1.6}
          strokeLinejoin="round" strokeLinecap="round" />
        {chart.points.map((p) => (
          <circle key={p.date} cx={X(p.date)} cy={Y(p.value)} r={2} fill={colour} />
        ))}
        <circle cx={X(last.date)} cy={Y(last.value)} r={3.4} fill={colour}
          stroke="#11161d" strokeWidth={1.5} />
        <text x={X(last.date) + 6} y={Y(last.value) + 3.5} fontFamily="var(--font-geist-mono)"
          fontSize={10} fill="#e6edf3">{format(last.value)}</text>
        {chart.points.map((p) => (
          <rect key={`h-${p.date}`} x={X(p.date) - 6} y={0} width={12} height={CELL_H}
            fill="transparent"
            onPointerMove={(e) => show(e.clientX, e.clientY, chart.label, [
              { label: fmtDate(p.date), value: format(p.value), colour },
              ...(chart.rules ?? []).map((r) => ({ label: r.label, value: format(r.value), colour: r.colour })),
            ])}
            onPointerLeave={hide} />
        ))}
      </svg>
    </div>
  );
}
