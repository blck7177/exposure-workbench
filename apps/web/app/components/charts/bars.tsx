"use client";

import React from "react";

import { C, lin, niceTicks, Tooltip, useTooltip, useWidth, type TipRow } from "./frame";

/**
 * The bar family (V13-S6).
 *
 * Shared specs, because they are the ones a chart written in a hurry drops:
 * bars are capped at 24px so a slot's leftover is air; a data end is rounded and
 * the baseline end is square; adjacent fills are separated by a 2px gap in the
 * surface colour rather than by a stroke, because a stroke is data-weight ink
 * doing a spacer's job. Values are labelled selectively — never on every mark.
 */

const BAR = 22;
const R = 4;

/** A rounded data-end, square at the baseline. Direction decides which end. */
function barPath(x: number, y0: number, y1: number, w: number, up: boolean): string {
  const top = Math.min(y0, y1);
  const bottom = Math.max(y0, y1);
  if (bottom - top < R * 2) return `M${x} ${top}h${w}v${bottom - top}h${-w}Z`;
  return up
    ? `M${x} ${bottom}V${top + R}a${R} ${R} 0 0 1 ${R}-${R}h${w - 2 * R}a${R} ${R} 0 0 1 ${R} ${R}V${bottom}Z`
    : `M${x} ${top}V${bottom - R}a${R} ${R} 0 0 0 ${R} ${R}h${w - 2 * R}a${R} ${R} 0 0 0 ${R}-${R}V${top}Z`;
}

// ── waterfall ────────────────────────────────────────────────────────────────

export type WaterfallStep = { label: string; short?: string; value: number; total?: boolean };

/**
 * Where a number came from, one contribution at a time.
 *
 * A subtotal and a total are drawn from the baseline in grey; every other bar
 * floats from the running sum. The connector between bars is a hairline, not a
 * mark: it carries no value and must not read as one.
 */
export function Waterfall({ steps, format, height = 200, ariaLabel }: {
  steps: WaterfallStep[];
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 260);
  const padLeft = 46;
  const padRight = 10;
  const top = 12;
  const plotH = height - 44;

  let cum = 0;
  const bars = steps.map((s) => {
    if (s.total) return { ...s, y0: 0, y1: s.value };
    const bar = { ...s, y0: cum, y1: cum + s.value };
    cum += s.value;
    return bar;
  });
  const lo = Math.min(0, ...bars.map((b) => Math.min(b.y0, b.y1)));
  const hi = Math.max(0, ...bars.map((b) => Math.max(b.y0, b.y1)));
  const Y = lin(lo, hi, top + plotH, top);
  const slot = (w - padLeft - padRight) / Math.max(1, bars.length);
  const bw = Math.min(BAR, slot * 0.62);
  // A centred label wider than its slot runs into both neighbours, and with ten
  // bars in a half-width panel `Stock-specific` overprinted `IWM` and `Day`.
  // Roughly 5.4px per character at this size; the full name stays in the
  // tooltip, which is where it was always going to be read anyway.
  const fit = (t: string) => {
    const max = Math.max(3, Math.floor(slot / 5.4));
    return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
  };

  // Label the ends and the extremes; a number on every bar goes unread.
  const biggest = Math.max(...bars.filter((b) => !b.total).map((b) => Math.abs(b.value)), 0);

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {niceTicks(lo, hi, 3).map((t) => (
          <g key={t}>
            <line x1={padLeft} x2={w - padRight} y1={Y(t)} y2={Y(t)} stroke={C.grid} />
            <text x={padLeft - 6} y={Y(t) + 3.5} textAnchor="end" fontFamily="var(--font-geist-mono)"
              fontSize={10} fill={C.ink3}>{format(t)}</text>
          </g>
        ))}
        <line x1={padLeft} x2={w - padRight} y1={Y(0)} y2={Y(0)} stroke={C.axis} />
        {bars.map((b, i) => {
          const x = padLeft + slot * i + (slot - bw) / 2;
          const up = b.value >= 0;
          const colour = b.total ? C.grey : up ? C.s1 : C.neg;
          const labelled = b.total || Math.abs(b.value) >= biggest * 0.25;
          return (
            <g key={b.label}>
              <path d={barPath(x, Y(b.y0), Y(b.y1), bw, up)} fill={colour} />
              {labelled && (
                <text x={x + bw / 2} y={up ? Y(Math.max(b.y0, b.y1)) - 5 : Y(Math.min(b.y0, b.y1)) + 12}
                  textAnchor="middle" fontSize={10.5} fill="#e6edf3">{format(b.value)}</text>
              )}
              <text x={x + bw / 2} y={height - 6} textAnchor="middle" fontSize={10}
                fill={b.total ? "#9aa7b7" : C.ink3}>
                <title>{b.label}</title>
                {fit(b.short ?? b.label)}
              </text>
              {i < bars.length - 1 && !bars[i + 1].total && (
                <line x1={x + bw} x2={padLeft + slot * (i + 1) + (slot - bw) / 2}
                  y1={Y(b.y1)} y2={Y(b.y1)} stroke={C.grid} />
              )}
              <rect x={padLeft + slot * i} y={top} width={slot} height={plotH} fill="transparent"
                onPointerMove={(e) => show(e.clientX, e.clientY, b.label, [
                  { label: b.total ? "Return" : "Contribution", value: format(b.value) },
                  ...(b.total ? [] : [{ label: "Running total", value: format(b.y1) }]),
                ])}
                onPointerLeave={hide} />
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

// ── horizontal bars, with the tiers a mandate sets ───────────────────────────

export type TierBar = {
  key: string; label: string; value: number;
  warning?: number | null; breach?: number | null;
  tip?: TipRow[];
};

/**
 * Losses (or any positive magnitude) against the levels that judge them.
 *
 * The tier rules are drawn as rules, not as a second bar: a threshold is a line
 * a value crosses, and drawing it as a bar would make the reader compare two
 * lengths when the question is which side of a mark they are on.
 */
export function TierBars({ bars, format, labelWidth = 150, ariaLabel, max }: {
  bars: TierBar[];
  format: (v: number) => string;
  labelWidth?: number;
  ariaLabel: string;
  max?: number;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 260);
  const rowH = 26;
  const height = bars.length * rowH + 22;
  const padRight = 66;
  const hi = max ?? Math.max(...bars.map((b) => Math.max(b.value, b.breach ?? 0)), 0.01) * 1.08;
  const X = lin(0, hi, labelWidth, w - padRight);
  const warn = bars.find((b) => b.warning != null)?.warning ?? null;
  const breach = bars.find((b) => b.breach != null)?.breach ?? null;

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {niceTicks(0, hi, 4).map((t) => (
          <g key={t}>
            <line x1={X(t)} x2={X(t)} y1={4} y2={height - 16} stroke={C.grid} />
            <text x={X(t)} y={height - 4} textAnchor="middle" fontFamily="var(--font-geist-mono)"
              fontSize={10} fill={C.ink3}>{format(t)}</text>
          </g>
        ))}
        {warn != null && <line x1={X(warn)} x2={X(warn)} y1={2} y2={height - 16} stroke={C.warn} strokeWidth={1.5} />}
        {breach != null && <line x1={X(breach)} x2={X(breach)} y1={2} y2={height - 16} stroke={C.crit} strokeWidth={1.5} />}
        {bars.map((b, i) => {
          const y = 6 + i * rowH;
          const over = b.warning != null && b.value >= b.warning;
          return (
            <g key={b.key}>
              <text x={labelWidth - 8} y={y + 12} textAnchor="end" fontSize={11.5} fill="#9aa7b7">
                {b.label}
              </text>
              <rect x={X(0)} y={y} width={Math.max(2, X(b.value) - X(0))} height={13} rx={3}
                fill={over ? C.warn : C.s1} />
              <text x={X(b.value) + 6} y={y + 11} fontSize={11} fill="#e6edf3"
                fontFamily="var(--font-geist-mono)">{format(b.value)}</text>
              <rect x={0} y={y - 4} width={w} height={rowH} fill="transparent"
                onPointerMove={(e) => show(e.clientX, e.clientY, b.label, b.tip ?? [
                  { label: "Value", value: format(b.value) },
                ])}
                onPointerLeave={hide} />
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

// ── diverging bars, for coefficients that have a sign ────────────────────────

export function DivergingBars({ rows, format, labelWidth = 84, ariaLabel, dashed }: {
  rows: { key: string; label: string; value: number; tip?: TipRow[] }[];
  format: (v: number) => string;
  labelWidth?: number;
  ariaLabel: string;
  /** Outline every bar: the row itself says the value is not determined alone. */
  dashed?: boolean;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 240);
  const rowH = 24;
  const height = rows.length * rowH + 20;
  const padRight = 52;
  const mx = Math.max(...rows.map((r) => Math.abs(r.value)), 0.01) * 1.1;
  const X = lin(-mx, mx, labelWidth, w - padRight);

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {niceTicks(-mx, mx, 4).map((t) => (
          <g key={t}>
            <line x1={X(t)} x2={X(t)} y1={4} y2={height - 14} stroke={t === 0 ? C.axis : C.grid} />
            <text x={X(t)} y={height - 3} textAnchor="middle" fontFamily="var(--font-geist-mono)"
              fontSize={10} fill={C.ink3}>{format(t)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const y = 6 + i * rowH;
          const x0 = X(Math.min(0, r.value));
          const x1 = X(Math.max(0, r.value));
          return (
            <g key={r.key}>
              <text x={labelWidth - 8} y={y + 11} textAnchor="end" fontSize={11.5} fill="#9aa7b7">
                {r.label}
              </text>
              <rect x={x0} y={y} width={Math.max(2, x1 - x0)} height={13} rx={3}
                fill={r.value >= 0 ? C.s1 : C.neg} />
              {dashed && (
                <rect x={x0 - 1.5} y={y - 1.5} width={Math.max(2, x1 - x0) + 3} height={16} rx={3}
                  fill="none" stroke="#9aa7b7" strokeWidth={1} strokeDasharray="2 2" />
              )}
              <text x={r.value >= 0 ? x1 + 6 : x0 - 6} y={y + 11}
                textAnchor={r.value >= 0 ? "start" : "end"} fontSize={11} fill="#e6edf3"
                fontFamily="var(--font-geist-mono)">{format(r.value)}</text>
              <rect x={0} y={y - 4} width={w} height={rowH} fill="transparent"
                onPointerMove={(e) => show(e.clientX, e.clientY, r.label, r.tip ?? [
                  { label: "Value", value: format(r.value) },
                ])}
                onPointerLeave={hide} />
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

// ── meters, for a book of checks ─────────────────────────────────────────────

export type Meter = {
  key: string; label: string; group: string;
  current: number | null; warning: number | null; breach: number | null;
  status: "ok" | "warning" | "breach" | null;
  utilisation: number | null;
  /** The alert a fired check wrote — the evidence a click opens. A check that
   *  did not fire has no row to open, and gets no affordance pretending it does. */
  openId?: string | null;
};

/**
 * Every mandate check, in order of how close it is to a breach.
 *
 * The track is a lighter step of the same ramp rather than a neutral grey, so
 * state reads across the whole bar; the tick is the warning tier's place on the
 * way to breach. A check with no recorded levels draws no bar and says so —
 * an empty meter would read as "measured, and at zero".
 */
export function Meters({ meters, format, onOpen }: {
  meters: Meter[];
  format: (v: number | null) => string;
  onOpen?: (id: string) => void;
}) {
  const { tip, show, hide } = useTooltip();
  const groups = Array.from(new Set(meters.map((m) => m.group)));
  return (
    <div className="relative max-h-[300px] overflow-y-auto pr-1">
      {groups.map((g) => (
        <div key={g}>
          <div className="font-mono text-[10px] uppercase tracking-wider text-slate-500 pt-2 pb-1 border-b border-[#21262d] mb-1">
            {g} · {meters.filter((m) => m.group === g).length}
          </div>
          {meters.filter((m) => m.group === g).map((m) => {
            const pct = m.utilisation == null ? null : Math.min(100, m.utilisation * 100);
            const tickAt = m.warning != null && m.breach ? (m.warning / m.breach) * 100 : null;
            return (
              <div key={m.key}
                role={m.openId && onOpen ? "button" : undefined}
                tabIndex={m.openId && onOpen ? 0 : undefined}
                onClick={m.openId && onOpen ? () => onOpen(m.openId as string) : undefined}
                onKeyDown={m.openId && onOpen
                  ? (e) => { if (e.key === "Enter") onOpen(m.openId as string); }
                  : undefined}
                className={`grid grid-cols-[minmax(0,1fr)_110px_120px] gap-3 items-center py-1 text-[11.5px] ${
                  m.openId && onOpen ? "cursor-pointer rounded hover:bg-[#161b22]" : ""}`}
                onPointerMove={(e) => show(e.clientX, e.clientY, m.label, [
                  { label: "Measured", value: format(m.current) },
                  { label: "Warning tier", value: format(m.warning) },
                  { label: "Breach tier", value: format(m.breach) },
                  { label: "Status", value: m.status ?? "not recorded" },
                ])}
                onPointerLeave={hide}>
                <div className={`truncate ${m.status && m.status !== "ok" ? "text-slate-200 font-medium" : "text-slate-400"}`}>
                  {m.label}
                </div>
                <div className="relative h-1.5 rounded-full bg-[#16243a]">
                  {pct != null && (
                    <i className="absolute left-0 top-0 h-full rounded-full block"
                      style={{ width: `${pct}%`, background: m.status === "breach" ? C.crit : m.status === "warning" ? C.warn : C.s1 }} />
                  )}
                  {tickAt != null && (
                    <i className="absolute block w-px h-3 -top-0.5 bg-slate-500" style={{ left: `${tickAt}%` }} />
                  )}
                </div>
                <div className="font-mono text-[10.5px] text-slate-500 text-right tabular-nums">
                  {m.current == null
                    ? <span className="italic">not recorded</span>
                    : <><span className="text-slate-200">{format(m.current)}</span> · {format(m.warning)} / {format(m.breach)}</>}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <Tooltip tip={tip} />
    </div>
  );
}

// ── a dot plot, for margins across windows of different length ───────────────

export function DotPlot({ categories, series, format, height = 190, ariaLabel }: {
  categories: string[];
  series: { key: string; label: string; colour: string; values: (number | null)[] }[];
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 240);
  const padLeft = 42;
  const padRight = 54;
  const top = 12;
  const plotH = height - 40;
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (all.length === 0) return <div ref={ref} className="text-xs text-slate-600 py-6">Nothing to plot.</div>;
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const padv = (hi - lo) * 0.12 || 1;
  const Y = lin(lo - padv, hi + padv, top + plotH, top);
  const X = (i: number) => padLeft + ((i + 0.5) / categories.length) * (w - padLeft - padRight);

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {niceTicks(lo, hi, 4).map((t) => (
          <g key={t}>
            <line x1={padLeft} x2={w - padRight} y1={Y(t)} y2={Y(t)} stroke={C.grid} />
            <text x={padLeft - 6} y={Y(t) + 3.5} textAnchor="end" fontFamily="var(--font-geist-mono)"
              fontSize={10} fill={C.ink3}>{format(t)}</text>
          </g>
        ))}
        {series.map((s) => {
          const pts = s.values.map((v, i) => (v == null ? null : ([X(i), Y(v)] as [number, number])));
          const line = pts.filter((p): p is [number, number] => p !== null)
            .map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
          const lastIdx = s.values.reduce<number>((acc, v, i) => (v != null ? i : acc), -1);
          return (
            <g key={s.key}>
              <path d={line} fill="none" stroke={s.colour} strokeWidth={1} opacity={0.45} />
              {pts.map((p, i) => p && (
                <circle key={i} cx={p[0]} cy={p[1]} r={4.5} fill={s.colour}
                  stroke="#11161d" strokeWidth={2}
                  onPointerMove={(e) => show(e.clientX, e.clientY, `${s.label} · ${categories[i]}`, [
                    { label: "Value", value: format(s.values[i] as number), colour: s.colour },
                  ])}
                  onPointerLeave={hide} />
              ))}
              {lastIdx >= 0 && (
                <text x={X(lastIdx) + 9} y={Y(s.values[lastIdx] as number) + 4} fontSize={11}
                  fill="#e6edf3" fontFamily="var(--font-geist-mono)">
                  {format(s.values[lastIdx] as number)}
                </text>
              )}
            </g>
          );
        })}
        {categories.map((c, i) => (
          <text key={c} x={X(i)} y={height - 6} textAnchor="middle" fontSize={10} fill={C.ink3}>{c}</text>
        ))}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
