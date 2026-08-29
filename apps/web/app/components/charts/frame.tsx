"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The parts every chart on this desk is made of (V13-S6).
 *
 * Three rules live here rather than in each chart, because they are the ones
 * that get dropped when a chart is written in a hurry:
 *
 *  - Every chart has a table. It is the accessible twin, and on this product it
 *    is also the audit surface: a reader checking a number should not have to
 *    hover a 2px line to read it.
 *  - A tooltip enhances and never gates. Everything it shows is in the table.
 *  - Values lead, labels follow. In a legend the reader has the number and wants
 *    the series; in a tooltip they have the series and want the number.
 */

// ── formatting ───────────────────────────────────────────────────────────────

export const fmtMoney = (v: number | null | undefined): string => {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `$${Math.round(v).toLocaleString()}`;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
};

export const fmtPct = (v: number | null | undefined, d = 2): string =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

export const fmtSignedPct = (v: number | null | undefined, d = 2): string =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `2026-03-28` → `Mar 28, 2026`, without constructing a Date: the string is
 *  already a calendar date and `new Date("2026-03-28")` is UTC midnight, which
 *  renders as the 27th for anyone west of Greenwich. */
export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso || iso.length < 10) return "—";
  return `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${Number(iso.slice(8, 10))}, ${iso.slice(0, 4)}`;
};

export const fmtMonth = (iso: string): string =>
  `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(2, 4)}`;

// ── scales ───────────────────────────────────────────────────────────────────

export const lin = (d0: number, d1: number, r0: number, r1: number) =>
  (v: number): number => (d1 === d0 ? r0 : r0 + ((v - d0) / (d1 - d0)) * (r1 - r0));

/** Ticks on round numbers. Axis labels carry the values that are not directly
 *  labelled, so they have to be readable rather than merely correct. */
export function niceTicks(lo: number, hi: number, n = 3): number[] {
  if (!isFinite(lo) || !isFinite(hi) || hi === lo) return [lo];
  const span = hi - lo;
  const p = Math.pow(10, Math.floor(Math.log10(span / n)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => span / s <= n + 1) ?? p;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
    out.push(Number(v.toFixed(10)));
  }
  return out;
}

// ── the hover layer ──────────────────────────────────────────────────────────

export type TipRow = { label: string; value: string; colour?: string };

export function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; title: string; rows: TipRow[] } | null>(null);
  const show = useCallback((x: number, y: number, title: string, rows: TipRow[]) =>
    setTip({ x, y, title, rows }), []);
  const hide = useCallback(() => setTip(null), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setTip(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return { tip, show, hide };
}

export function Tooltip({ tip }: { tip: { x: number; y: number; title: string; rows: TipRow[] } | null }) {
  const ref = useRef<HTMLDivElement>(null);
  if (!tip) return null;
  // Flipped away from the edge rather than clipped by it.
  const w = ref.current?.offsetWidth ?? 220;
  const h = ref.current?.offsetHeight ?? 80;
  const left = tip.x + 14 + w > window.innerWidth - 12 ? tip.x - w - 14 : tip.x + 14;
  const top = tip.y + 14 + h > window.innerHeight - 12 ? tip.y - h - 14 : tip.y + 14;
  return (
    <div ref={ref} role="tooltip"
      className="fixed z-[60] max-w-[320px] rounded-md border border-[#30363d] bg-[#1d2530] px-3 py-2 text-xs shadow-xl pointer-events-none"
      style={{ left, top }}>
      <div className="font-mono text-[10px] uppercase tracking-wide text-teal-300 mb-1">{tip.title}</div>
      {tip.rows.map((r, i) => (
        <div key={i} className="flex justify-between gap-4 leading-relaxed">
          <span className="text-slate-400">
            {r.colour && (
              <i className="inline-block w-2.5 h-0.5 align-middle mr-1.5 rounded-sm"
                 style={{ background: r.colour }} />
            )}
            {r.label}
          </span>
          <span className="text-slate-100 font-medium tabular-nums">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── the frame ────────────────────────────────────────────────────────────────

export type TableSpec = { columns: string[]; rows: (string | number)[][] };

/**
 * A chart card: title, an optional aside, the chart, its legend, and a Table
 * toggle that is never optional.
 *
 * `note` sits under the chart and is where a chart says what it is NOT — the
 * assumption a line makes, the factor a scenario holds still. Those sentences
 * are the honest half of every panel here and they are given a place rather
 * than left to whoever remembers.
 */
export function ChartCard({
  title, aside, note, table, controls, children,
}: {
  title: string;
  aside?: React.ReactNode;
  note?: React.ReactNode;
  table?: TableSpec;
  controls?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className="rounded-lg border border-[#21262d] bg-[#11161d]">
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-[#21262d]">
        <h3 className="text-sm font-medium text-slate-200">{title}</h3>
        {aside && <span className="text-[11px] text-slate-500 truncate">{aside}</span>}
        <div className="ml-auto flex items-center gap-2">
          {controls}
          {table && (
            <button
              onClick={() => setShowTable((v) => !v)}
              aria-pressed={showTable}
              className="text-[11px] px-2 py-0.5 rounded border border-[#30363d] text-slate-400 hover:text-slate-200 hover:border-slate-500">
              {showTable ? "Chart" : "Table"}
            </button>
          )}
        </div>
      </header>
      <div className="px-4 py-3">
        {showTable && table ? <DataTable spec={table} /> : children}
      </div>
      {note && (
        <footer className="px-4 py-2 border-t border-[#21262d] text-[11px] text-slate-500 leading-snug">
          {note}
        </footer>
      )}
    </section>
  );
}

export function DataTable({ spec }: { spec: TableSpec }) {
  return (
    <div className="overflow-x-auto max-h-[420px]">
      <table className="w-full text-xs">
        <thead>
          <tr>
            {spec.columns.map((c, i) => (
              <th key={c}
                className={`text-[10px] uppercase tracking-wide font-medium text-slate-500 border-b border-[#21262d] py-1.5 px-2 ${i ? "text-right" : "text-left"}`}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}
                  className={`border-b border-[#161b22] py-1.5 px-2 ${j ? "text-right font-mono tabular-nums text-slate-300" : "text-slate-400"}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Legend({ items }: { items: { label: string; colour?: string; shape?: "line" | "swatch" | "tick" | "dashed" }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-2 text-[11px] text-slate-400">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          {it.shape === "tick" ? (
            <i className="inline-block w-0 h-2.5 border-l-2" style={{ borderColor: it.colour }} />
          ) : it.shape === "dashed" ? (
            <i className="inline-block w-2.5 h-2.5 rounded-sm border border-dashed border-slate-400" />
          ) : it.shape === "swatch" ? (
            <i className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: it.colour }} />
          ) : (
            <i className="inline-block w-3.5 h-0.5 rounded-sm" style={{ background: it.colour }} />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

/** Chart colours. Validated against this surface for colour-blind separation
 *  and contrast (dataviz check, dark surface #11161d); status colours are a
 *  separate set and never stand in for a series. */
export const C = {
  s1: "#3987e5", s2: "#d95926", s3: "#199e70",
  grey: "#4e5b6b", mid: "#2c3743",
  neg: "#e66767", warn: "#e0b15a", crit: "#f07a6a", good: "#4cc38a",
  seq: ["#86b6ef", "#3987e5", "#1c5cab", "#184f95"],
  grid: "#212a35", axis: "#2c3743", ink3: "#6c7887",
};

/** Width from the element, so a chart re-lays out when a panel resizes. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}
