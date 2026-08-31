"use client";

import React from "react";

import { C, Tooltip, useTooltip, useWidth, fmtDate } from "./frame";

/**
 * The grid family (V13-S6): a heatmap, a window ladder, a coverage matrix and a
 * citation map.
 *
 * All four answer the same shape of question — what does this desk hold, and how
 * do the pieces relate — which is the question the issuer page could not answer
 * at all when it was 33 identifiers in a chip cloud.
 */

// ── correlation heatmap ──────────────────────────────────────────────────────

/**
 * A diverging scale on one hue per pole and a neutral middle: the midpoint must
 * read as "nothing", so it is grey rather than a third colour, and the poles are
 * warm against cool so they read as opposite.
 *
 * Only strong cells carry their number. A value in every cell of an 8×8 is 64
 * numbers nobody reads; the ones that matter here are the ones near ±1, because
 * those are the reason a single coefficient is not quotable.
 */
export function Heatmap({ labels, matrix, ariaLabel, window: win }: {
  labels: string[];
  matrix: (number | null)[][];
  ariaLabel: string;
  window?: { from: string; to: string; observations: number };
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 260);
  const n = labels.length;
  const padLeft = 76;
  const padTop = 16;
  const cell = Math.min(26, (w - padLeft - 6) / Math.max(1, n));
  const height = padTop + n * cell + 6;

  const colour = (v: number) => {
    const a = Math.abs(v);
    if (a < 0.05) return C.mid;
    const ramp = v > 0
      ? ["#1c3a63", "#1f4d8a", "#2565b3", "#3987e5", "#5598e7"]
      : ["#4a2326", "#6b2c30", "#9a3a3f", "#c94f52", "#e66767"];
    return ramp[Math.min(4, Math.floor(a * 5))];
  };
  const short = (s: string) => (s.length <= 4 ? s : s.slice(0, 3));

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {labels.map((l, j) => (
          <text key={`h-${l}`} x={padLeft + j * cell + cell / 2} y={padTop - 4} textAnchor="middle"
            fontFamily="var(--font-geist-mono)" fontSize={10} fill={C.ink3}>{short(l)}</text>
        ))}
        {matrix.map((row, i) => (
          <g key={`r-${labels[i]}`}>
            <text x={padLeft - 6} y={padTop + i * cell + cell / 2 + 4} textAnchor="end"
              fontSize={11} fill="#9aa7b7">{labels[i]}</text>
            {row.map((v, j) => {
              const x = padLeft + j * cell;
              const y = padTop + i * cell;
              if (i === j) {
                return <rect key={j} x={x + 1} y={y + 1} width={cell - 2} height={cell - 2}
                  rx={3} fill={C.grid} />;
              }
              return (
                <g key={j}>
                  <rect x={x + 1} y={y + 1} width={cell - 2} height={cell - 2} rx={3}
                    fill={v == null ? C.grid : colour(v)}
                    onPointerMove={(e) => show(e.clientX, e.clientY, `${labels[i]} × ${labels[j]}`, [
                      { label: "Correlation of daily returns", value: v == null ? "—" : v.toFixed(3) },
                      ...(win ? [{ label: "Window", value: `${win.observations} sessions to ${win.to}` }] : []),
                    ])}
                    onPointerLeave={hide} />
                  {v != null && Math.abs(v) >= 0.7 && (
                    <text x={x + cell / 2} y={y + cell / 2 + 3.5} textAnchor="middle" fontSize={9.5}
                      fill="#fff" pointerEvents="none" fontFamily="var(--font-geist-mono)">
                      {v.toFixed(2).replace("0.", ".")}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        ))}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

// ── the reported-window ladder ───────────────────────────────────────────────

export type LadderRow = {
  months: number;
  label: string;
  slots: { start: string; end: string; value: number | null;
           fact_ids?: string[]; terms?: { fact_id: string; sign: number }[];
           derivation?: string; unreachable?: string }[];
};

/**
 * Which windows of a measure this desk can produce, by window length.
 *
 * The distinction the panel exists to draw is NOT held-versus-missing, which is
 * what I first assumed. It is REPORTED versus DERIVED: a window with one term
 * came straight off a filing; one with several is a signed path over reported
 * boundaries — Apple's December quarter is the full year minus its nine months,
 * a figure no filing states and the engine can produce exactly. A slot the
 * engine cannot reach at all keeps its place, outlined, because dropping it
 * would let its neighbours close ranks and read as consecutive.
 */
export function WindowLadder({ rows, format, today, ariaLabel, onOpen }: {
  rows: LadderRow[];
  format: (v: number) => string;
  today?: string;
  ariaLabel: string;
  /** Open a slot's evidence. A slot's value stands on its boundary facts — a
   *  reported window on one, a derived window on each term of its signed path —
   *  and the click opens the first; the tooltip already names the whole path.
   *  An unreachable slot has no fact to open and stays inert. */
  onOpen?: (factId: string) => void;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 300);
  const padLeft = 74;
  const padRight = 16;
  const rowH = 34;
  const height = rows.length * rowH + 28;

  const days = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
  const all = rows.flatMap((r) => r.slots.flatMap((s) => [days(s.start), days(s.end)]));
  if (all.length === 0) return <div ref={ref} className="text-xs text-slate-600 py-6">No reported windows.</div>;
  const t0 = Math.min(...all);
  const t1 = Math.max(...all, today ? days(today) : -Infinity);
  const X = (iso: string) => padLeft + ((days(iso) - t0) / Math.max(1, t1 - t0)) * (w - padLeft - padRight);

  const years = Array.from(new Set(rows.flatMap((r) => r.slots.map((s) => s.end.slice(0, 4)))));

  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {years.map((y) => {
          const x = X(`${y}-01-01`);
          if (x < padLeft || x > w - padRight) return null;
          return (
            <g key={y}>
              <line x1={x} x2={x} y1={4} y2={height - 16} stroke={C.grid} />
              <text x={x + 3} y={height - 4} fontFamily="var(--font-geist-mono)" fontSize={10} fill={C.ink3}>{y}</text>
            </g>
          );
        })}
        {today && (
          <g>
            <line x1={X(today)} x2={X(today)} y1={4} y2={height - 16} stroke={C.ink3} />
            <text x={X(today) + 3} y={12} fontSize={10} fill={C.ink3}>today</text>
          </g>
        )}
        {rows.map((r, ri) => {
          const y = 16 + ri * rowH;
          return (
            <g key={r.months}>
              <text x={padLeft - 8} y={y + 13} textAnchor="end" fontSize={11} fill="#9aa7b7">{r.label}</text>
              {r.slots.map((s) => {
                const x0 = X(s.start) + 1;
                const x1 = X(s.end) - 1;
                const bw = Math.max(4, x1 - x0);
                const derived = (s.terms?.length ?? 0) > 1;
                const label = s.value == null ? "" : format(s.value);
                const fits = bw > label.length * 6.4 + 12;
                return (
                  <g key={`${r.months}-${s.end}`}>
                    {s.value == null ? (
                      <rect x={x0} y={y} width={bw} height={18} rx={4} fill="none"
                        stroke={C.ink3} strokeDasharray="3 3" />
                    ) : (
                      <rect x={x0} y={y} width={bw} height={18} rx={4}
                        fill={derived ? "none" : C.s1}
                        stroke={derived ? C.s1 : "none"} strokeWidth={derived ? 1.5 : 0} />
                    )}
                    {s.value != null && fits && (
                      <text x={x0 + bw / 2} y={y + 12.5} textAnchor="middle" fontSize={10}
                        fill={derived ? "#9ec5f4" : "#fff"} pointerEvents="none">{label}</text>
                    )}
                    <rect x={x0} y={y - 3} width={bw} height={24} fill="transparent"
                      style={onOpen && (s.fact_ids?.length || s.terms?.length)
                        ? { cursor: "pointer" } : undefined}
                      onClick={() => {
                        const id = s.fact_ids?.[0] ?? s.terms?.[0]?.fact_id;
                        if (id && onOpen) onOpen(id);
                      }}
                      onPointerMove={(e) => show(e.clientX, e.clientY, `${s.start} → ${s.end}`,
                        s.value == null
                          ? [{ label: "Not derivable", value: s.unreachable ?? "no path" }]
                          : [
                              { label: "Value", value: format(s.value) },
                              { label: "How", value: derived ? `derived from ${s.terms?.length} reported periods` : "reported directly" },
                              ...(s.derivation ? [{ label: "Path", value: s.derivation }] : []),
                            ])}
                      onPointerLeave={hide} />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

// ── coverage ─────────────────────────────────────────────────────────────────

/**
 * What this desk holds on an issuer, as a table rather than a chip cloud.
 *
 * The Snapshot tab used to list 33 identifiers with a count each, which answers
 * neither "can you answer my question" nor "how far back". A row per measure
 * with its kind, its periods and the date it runs to answers both — and a row
 * with a named successor says the thing a chip cannot: interest expense is not
 * absent by accident, it stopped being reported as a separate line.
 */
export function CoverageTable({ rows }: {
  rows: { metric: string; label: string; periods: number | null; latest: string | null;
          kind: string | null; windows_filed: string[] | null; superseded_by: string[] | null }[];
}) {
  return (
    <div className="overflow-x-auto max-h-[380px]">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-slate-500">
            <th className="text-left font-medium py-1.5 pr-3 border-b border-[#21262d]">Measure</th>
            <th className="text-left font-medium py-1.5 px-2 border-b border-[#21262d]">Kind</th>
            <th className="text-right font-medium py-1.5 px-2 border-b border-[#21262d]">Periods</th>
            <th className="text-left font-medium py-1.5 px-2 border-b border-[#21262d]">Through</th>
            <th className="text-left font-medium py-1.5 pl-2 border-b border-[#21262d]">Windows filed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.metric} className="align-top">
              <td className="py-1.5 pr-3 border-b border-[#161b22] text-slate-300">
                {r.label}
                {r.superseded_by?.length ? (
                  <span className="block text-[10.5px] text-amber-500/80 leading-snug">
                    no longer reported — see {r.superseded_by.join(", ")}
                  </span>
                ) : null}
              </td>
              <td className="py-1.5 px-2 border-b border-[#161b22] text-slate-500">{r.kind ?? "—"}</td>
              <td className="py-1.5 px-2 border-b border-[#161b22] text-right font-mono tabular-nums text-slate-400">
                {r.periods ?? "—"}
              </td>
              <td className="py-1.5 px-2 border-b border-[#161b22] text-slate-400 whitespace-nowrap">{fmtDate(r.latest)}</td>
              <td className="py-1.5 pl-2 border-b border-[#161b22] text-slate-500">
                {r.windows_filed?.length ? r.windows_filed.join(", ") : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── where a brief's evidence came from ───────────────────────────────────────

/**
 * Indexed passages per section, against the ones a brief actually cited.
 *
 * On Apple every cited passage comes from the 10-Q's MD&A while the 10-K's 77
 * risk-factor and financial-statement passages were searchable and not needed.
 * That is a fact about how this desk works which no other view shows, and it is
 * the kind of thing a reader checking a brief wants before they trust it.
 */
export function CitationMap({ sections, ariaLabel }: {
  sections: { form: string; item: string | null; title: string | null; passages: number; cited: number }[];
  ariaLabel: string;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const { tip, show, hide } = useTooltip();
  const w = Math.max(width, 300);
  const rowH = 22;
  const shown = sections.filter((s) => s.passages > 0).slice(0, 10);
  const height = shown.length * rowH + 6;
  const padLeft = Math.min(230, w * 0.42);
  const padRight = 92;
  const mx = Math.max(...shown.map((s) => s.passages), 1);
  const X = (v: number) => padLeft + (v / mx) * (w - padLeft - padRight);

  if (shown.length === 0) {
    return <div ref={ref} className="text-xs text-slate-600 py-6">No indexed passages yet.</div>;
  }
  return (
    <div ref={ref} className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} role="img" aria-label={ariaLabel}>
        {shown.map((s, i) => {
          const y = 4 + i * rowH;
          const name = `${s.form} · ${s.item ?? ""}`.trim();
          const title = (s.title ?? "").length > 24 ? `${(s.title ?? "").slice(0, 23)}…` : s.title ?? "";
          return (
            <g key={`${s.form}-${s.item}-${i}`}>
              <text x={padLeft - 8} y={y + 10} textAnchor="end" fontSize={11} fill="#9aa7b7">
                {name}{title ? ` · ${title}` : ""}
              </text>
              <rect x={X(0)} y={y} width={Math.max(2, X(s.passages) - X(0))} height={12} rx={3} fill={C.grey} />
              {s.cited > 0 && (
                <rect x={X(0)} y={y} width={Math.max(2, X(s.cited) - X(0))} height={12} rx={3} fill={C.s1} />
              )}
              <text x={X(s.passages) + 6} y={y + 10} fontSize={10.5} fill="#e6edf3"
                fontFamily="var(--font-geist-mono)">
                {s.passages}{s.cited ? ` · ${s.cited} cited` : ""}
              </text>
              <rect x={0} y={y - 4} width={w} height={rowH} fill="transparent"
                onPointerMove={(e) => show(e.clientX, e.clientY, name, [
                  { label: "Section", value: s.title ?? "—" },
                  { label: "Indexed passages", value: String(s.passages) },
                  { label: "Cited by the brief", value: String(s.cited) },
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
