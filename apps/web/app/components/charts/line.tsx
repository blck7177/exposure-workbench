"use client";

import React, { useState } from "react";

import { C, lin, niceTicks, Tooltip, useTooltip, useWidth, type TipRow } from "./frame";

/**
 * A line chart with a crosshair (V13-S6).
 *
 * The crosshair finds the X. A reader aims at a date, never at a 2px line, and
 * the readout lists every series at that date — so the pointer never has to land
 * on a stroke to get a value.
 *
 * `bands` shade an interval (a drawdown episode) and `markers` rule a date (a
 * filing arriving). Both are the reason to show a price series on a research
 * product at all: the reader can see what the price did around the moment this
 * desk's evidence is dated from.
 *
 * `sub` draws a second, shorter plot BENEATH the first, on its own baseline — a
 * drawdown under a value line. It is deliberately not a second y-axis on one
 * plot: two scales sharing a frame invent a correlation by choosing where they
 * line up. These are two plots, stacked.
 */

export type Series = {
  key: string;
  label: string;
  points: (number | null)[];
  colour: string;
  width?: number;
  area?: boolean;
  endLabel?: string;
};

export type Band = { from: number; to: number; at?: number; label?: string };

/**
 * The window the reader has narrowed the plot to (V25).
 *
 * A VIEW, and only a view: `from`/`to` are indices into the same points, the
 * main plot is drawn over that slice, and nothing is recomputed — no rolling
 * measure is re-derived over the selection, no figure changes. A brushed
 * volatility would be a measure computed in a browser, which is the one thing
 * this page does not do. The sub-plot always draws the whole span, because it
 * is the map the selection is made on.
 */
export type Brush = {
  from: number;
  to: number;
  onChange: (range: { from: number; to: number } | null) => void;
};

export function LineChart({
  x, series, height = 220, plotHeight, padLeft = 52, yFormat, bands = [], markers = [],
  sub, xTicks, tipRows, ariaLabel, brush,
}: {
  x: string[];
  series: Series[];
  height?: number;
  plotHeight?: number;
  padLeft?: number;
  yFormat: (v: number) => string;
  bands?: Band[];
  markers?: { at: number; label: string }[];
  sub?: { points: number[]; height: number; colour: string; format: (v: number) => string };
  xTicks?: { at: number; label: string }[];
  tipRows: (i: number) => TipRow[];
  ariaLabel: string;
  /** Drag on the sub-plot to narrow the main plot. Requires `sub`: the strip
   *  the selection is made on is the strip that keeps showing the whole span. */
  brush?: Brush;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const [hover, setHover] = useState<number | null>(null);
  const [dragFrom, setDragFrom] = useState<number | null>(null);

  const w = Math.max(width, 240);
  const padRight = 14;
  const top = 10;
  const mainH = plotHeight ?? height - (sub ? sub.height + 42 : 30);
  const n = x.length;
  // The full span: the sub-plot's scale, and the one the brush is drawn on.
  const X = (i: number) => padLeft + (n <= 1 ? 0 : (i / (n - 1)) * (w - padLeft - padRight));

  // What the main plot is showing. Not a different series — the same points,
  // between two indices — so nothing is recomputed to narrow it.
  const from = brush ? Math.max(0, Math.min(brush.from, n - 1)) : 0;
  const to = brush ? Math.max(from, Math.min(brush.to, n - 1)) : n - 1;
  const vn = to - from + 1;
  const MX = (i: number) =>
    padLeft + (vn <= 1 ? 0 : ((i - from) / (vn - 1)) * (w - padLeft - padRight));
  const inView = (i: number) => i >= from && i <= to;

  const all = series.flatMap((s) => s.points.slice(from, to + 1).filter((v): v is number => v != null));
  if (n === 0 || all.length === 0) {
    return <div ref={ref} className="text-xs text-slate-600 py-6">No data for this window.</div>;
  }
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo) * 0.04 || 1;
  const Y = lin(lo - pad, hi + pad, top + mainH, top);
  const ticks = niceTicks(lo, hi, 3);

  const path = (pts: (number | null)[]) => {
    const out: string[] = [];
    let pen = false;
    pts.forEach((v, i) => {
      if (v == null || !inView(i)) { pen = false; return; }
      out.push(`${pen ? "L" : "M"}${MX(i).toFixed(1)} ${Y(v).toFixed(1)}`);
      pen = true;
    });
    return out.join("");
  };

  const subTop = top + mainH + 18;
  const subLo = sub ? Math.min(...sub.points, 0) : 0;
  const SY = sub ? lin(subLo, 0, subTop + sub.height, subTop) : null;

  /** The point index under a pointer, on whichever scale that plot uses. */
  const indexAt = (clientX: number, host: SVGSVGElement | null, whole: boolean) => {
    if (!host) return null;
    const rect = host.getBoundingClientRect();
    const frac = (clientX - rect.left - (padLeft / w) * rect.width)
      / Math.max(1, rect.width * (1 - (padLeft + padRight) / w));
    const span = whole ? n - 1 : vn - 1;
    const base = whole ? 0 : from;
    return Math.max(whole ? 0 : from,
      Math.min(whole ? n - 1 : to, base + Math.round(Math.max(0, Math.min(1, frac)) * span)));
  };

  const move = (ev: React.PointerEvent<SVGRectElement>) => {
    const i = indexAt(ev.clientX, ev.currentTarget.ownerSVGElement, false);
    if (i == null) return;
    setHover(i);
    show(ev.clientX, ev.clientY, x[i], tipRows(i));
  };
  const leave = () => { setHover(null); hide(); };

  // The brush handlers work on the sub-plot's own scale, which is always the
  // whole span: a selection made inside the current selection could never be
  // widened again.
  const brushDown = (ev: React.PointerEvent<SVGRectElement>) => {
    if (!brush) return;
    const i = indexAt(ev.clientX, ev.currentTarget.ownerSVGElement, true);
    if (i == null) return;
    setDragFrom(i);
    ev.currentTarget.setPointerCapture(ev.pointerId);
  };
  const brushMove = (ev: React.PointerEvent<SVGRectElement>) => {
    if (!brush || dragFrom == null) return;
    const i = indexAt(ev.clientX, ev.currentTarget.ownerSVGElement, true);
    if (i == null) return;
    brush.onChange({ from: Math.min(dragFrom, i), to: Math.max(dragFrom, i) });
  };
  const brushUp = (ev: React.PointerEvent<SVGRectElement>) => {
    if (!brush || dragFrom == null) return;
    const i = indexAt(ev.clientX, ev.currentTarget.ownerSVGElement, true);
    // A click rather than a drag clears the selection: the gesture that made
    // the window is the gesture that undoes it.
    if (i != null && Math.abs(i - dragFrom) < 2) brush.onChange(null);
    setDragFrom(null);
  };

  const brushed = brush != null && (from > 0 || to < n - 1);

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padLeft} x2={w - padRight} y1={Y(t)} y2={Y(t)} stroke={C.grid} strokeWidth={1} />
            <text x={padLeft - 6} y={Y(t) + 3.5} textAnchor="end" fontFamily="var(--font-geist-mono)"
              fontSize={10.5} fill={C.ink3}>{yFormat(t)}</text>
          </g>
        ))}
        {bands.filter((b) => b.to >= from && b.from <= to).map((b, k) => (
          <g key={`${b.from}-${k}`}>
            <rect x={MX(Math.max(b.from, from))} y={top}
              width={Math.max(2, MX(Math.min(b.to, to)) - MX(Math.max(b.from, from)))} height={mainH}
              fill="rgba(231,236,243,0.06)" />
            {b.label && b.at != null && inView(b.at) && (
              <text x={MX(b.at)} y={top + mainH - 6} textAnchor="middle" fontSize={10.5} fill={C.crit}>
                {b.label}
              </text>
            )}
          </g>
        ))}
        {markers.filter((m) => inView(m.at)).map((m) => (
          <g key={`${m.at}-${m.label}`}>
            <line x1={MX(m.at)} x2={MX(m.at)} y1={top} y2={top + mainH} stroke={C.ink3} strokeWidth={1} />
            <text x={MX(m.at) + 4} y={top + 10} fontSize={10} fill={C.ink3}>{m.label}</text>
          </g>
        ))}
        <line x1={padLeft} x2={w - padRight} y1={top + mainH} y2={top + mainH} stroke={C.axis} />
        {series.map((s) => {
          const d = path(s.points);
          const lastIdx = s.points.reduce<number>(
            (acc, v, i) => (v != null && inView(i) ? i : acc), -1);
          const lastVal = lastIdx >= 0 ? s.points[lastIdx] : null;
          return (
            <g key={s.key}>
              {s.area && lastIdx >= 0 && (
                <path d={`${d}L${MX(lastIdx)} ${top + mainH}L${MX(from)} ${top + mainH}Z`}
                  fill={s.colour} opacity={0.1} />
              )}
              <path d={d} fill="none" stroke={s.colour} strokeWidth={s.width ?? 2}
                strokeLinejoin="round" strokeLinecap="round" />
              {lastVal != null && (
                <circle cx={MX(lastIdx)} cy={Y(lastVal)} r={4} fill={s.colour}
                  stroke="#11161d" strokeWidth={2} />
              )}
              {s.endLabel && lastVal != null && !brushed && (
                <text x={MX(lastIdx) - 7} y={Y(lastVal) - 9} textAnchor="end" fontSize={11} fill="#e6edf3">
                  {s.endLabel}
                </text>
              )}
            </g>
          );
        })}
        {sub && SY && (
          <g>
            <line x1={padLeft} x2={w - padRight} y1={subTop} y2={subTop} stroke={C.grid} />
            <path
              d={`${sub.points.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${SY(v).toFixed(1)}`).join("")}L${X(n - 1)} ${subTop}L${X(0)} ${subTop}Z`}
              fill={sub.colour} opacity={0.22} />
            <path d={sub.points.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${SY(v).toFixed(1)}`).join("")}
              fill="none" stroke={sub.colour} strokeWidth={1} />
            <text x={padLeft - 6} y={subTop + sub.height + 3} textAnchor="end"
              fontFamily="var(--font-geist-mono)" fontSize={10} fill={C.ink3}>{sub.format(subLo)}</text>
            <text x={padLeft - 6} y={subTop + 3} textAnchor="end"
              fontFamily="var(--font-geist-mono)" fontSize={10} fill={C.ink3}>0</text>
            {brushed && (
              <g pointerEvents="none">
                <rect x={padLeft} y={subTop - 4} width={Math.max(0, X(from) - padLeft)}
                  height={sub.height + 8} fill="#0d1117" opacity={0.55} />
                <rect x={X(to)} y={subTop - 4} width={Math.max(0, w - padRight - X(to))}
                  height={sub.height + 8} fill="#0d1117" opacity={0.55} />
                <rect x={X(from)} y={subTop - 4} width={Math.max(2, X(to) - X(from))}
                  height={sub.height + 8} fill="none" stroke={C.s1} strokeWidth={1.5} />
              </g>
            )}
            {brush && (
              <rect x={padLeft} y={subTop - 6} width={Math.max(1, w - padLeft - padRight)}
                height={sub.height + 12} fill="transparent" style={{ cursor: "ew-resize" }}
                onPointerDown={brushDown} onPointerMove={brushMove} onPointerUp={brushUp} />
            )}
          </g>
        )}
        {(xTicks ?? []).filter((t) => inView(t.at)).map((t) => (
          <text key={`${t.at}-${t.label}`} x={MX(t.at)} y={height - 4} textAnchor="middle"
            fontFamily="var(--font-geist-mono)" fontSize={10} fill={C.ink3}>{t.label}</text>
        ))}
        {hover != null && inView(hover) && (
          <g>
            <line x1={MX(hover)} x2={MX(hover)} y1={top} y2={top + mainH} stroke={C.ink3} strokeWidth={1} />
            {series.map((s) => {
              const v = s.points[hover];
              return v == null ? null : (
                <circle key={s.key} cx={MX(hover)} cy={Y(v)} r={4} fill={s.colour}
                  stroke="#11161d" strokeWidth={2} />
              );
            })}
          </g>
        )}
        <rect x={padLeft} y={top} width={Math.max(1, w - padLeft - padRight)} height={mainH}
          fill="transparent" style={{ cursor: "crosshair" }}
          onPointerMove={move} onPointerLeave={leave} />
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
/**
 * A 26px trend for a stat tile. No axis and no tooltip: the tile's value is the
 * number, and this is only the shape of how it got there.
 */
export function Sparkline({ points, colour = C.s1, label }: {
  points: (number | null)[]; colour?: string; label: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const w = Math.max(width, 40);
  const h = 26;
  const vals = points.filter((v): v is number => v != null);
  if (vals.length < 2) return <div ref={ref} className="h-[26px]" />;
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const X = (i: number) => 2 + (i / (points.length - 1)) * (w - 6);
  const Y = lin(lo, hi, h - 3, 3);
  const pts = points
    .map((v, i) => (v == null ? null : ([X(i), Y(v)] as [number, number])))
    .filter((p): p is [number, number] => p !== null);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
  const end = pts[pts.length - 1];
  return (
    <div ref={ref}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label={label}>
        <path d={d} fill="none" stroke={C.grey} strokeWidth={1.5} strokeLinejoin="round" />
        <circle cx={end[0]} cy={end[1]} r={3.5} fill={colour} stroke="#11161d" strokeWidth={2} />
      </svg>
    </div>
  );
}

/**
 * The distribution a value-at-risk figure is the tail of.
 *
 * A sparkline of VaR over time would be nearly flat and say nothing — the window
 * is 750 sessions, so the number barely moves from day to day. What a reader
 * actually wants beside "1.39%" is the thing being measured: the returns, and
 * where the fifth percentile falls among them.
 */
export function ReturnHistogram({ returns, quantile, label }: {
  returns: number[]; quantile: number; label: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const w = Math.max(width, 60);
  const h = 26;
  const bins = 28;
  if (returns.length < 20) return <div ref={ref} className="h-[26px]" />;
  const lo = Math.min(...returns);
  const hi = Math.max(...returns);
  const bw = (hi - lo) / bins || 1;
  const counts = new Array<number>(bins).fill(0);
  returns.forEach((r) => { counts[Math.min(bins - 1, Math.floor((r - lo) / bw))] += 1; });
  const mx = Math.max(...counts, 1);
  const qx = ((-quantile - lo) / (hi - lo || 1)) * w;
  return (
    <div ref={ref}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label={label}>
        {counts.map((c, i) => {
          const inTail = lo + (i + 1) * bw <= -quantile;
          const bh = (c / mx) * (h - 2);
          return (
            <rect key={i} x={(i / bins) * w} y={h - bh} width={Math.max(1, w / bins - 1)}
              height={bh} fill={inTail ? C.crit : C.grey} opacity={inTail ? 1 : 0.7} />
          );
        })}
        <line x1={qx} x2={qx} y1={0} y2={h} stroke={C.crit} strokeWidth={1} />
      </svg>
    </div>
  );
}
