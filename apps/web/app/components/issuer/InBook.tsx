"use client";

import { C, fmtDate, fmtMoney, fmtPct, fmtSignedPct } from "../charts/frame";
import { useEvidence } from "../evidence/Column";
import type { LimitCheckRow, RunSeries } from "@/lib/charts";
import type { Snapshot } from "@/lib/issuer";

/**
 * The position, as the book the reader came from records it (V25).
 *
 * ONE ROW, not a panel. The reader arrived here from their book by clicking a
 * holding; what they need before the page starts talking about filings is what
 * this name is to them — what it is worth, how much of the book it is, what it
 * did today, and whether it is near the line they set for it. Four facts and a
 * check. Everything else about the position belongs on the book page, which is
 * one click back and is where the comparisons live.
 *
 * Every figure is read from that book's own latest completed run. The snapshot
 * used to answer this with the newest `issuer_exposures` row on ANY book, so a
 * signed-in reader looking at their own MSFT could be shown the public demo's
 * market value and weight with nothing on the page saying whose. The page has
 * always arrived with `?portfolio=`; now that parameter decides, and without it
 * there is no row and no strip.
 */

export function InBook({ ticker, snapshot, series, checks, bookName }: {
  ticker: string;
  snapshot: Snapshot;
  /** The book's dated updates, for the weight's move and its path. */
  series: RunSeries | null;
  /** The book's latest limit book, for this name's own tier and the room left. */
  checks: LimitCheckRow[];
  bookName: string | null;
}) {
  const { open } = useEvidence();
  const exposure = snapshot.portfolio_exposure;
  if (!exposure) return null;

  const updates = series?.updates ?? [];
  const last = updates[updates.length - 1];
  const row = last?.issuers.find((i) => i.ticker === ticker);
  const previous = updates.length > 1 ? updates[updates.length - 2].as_of : null;
  const check = checks.find((c) => c.key === `issuer_concentration:${ticker}`);
  const path = updates.flatMap((u) => {
    const r = u.issuers.find((i) => i.ticker === ticker);
    return r?.weight == null ? [] : [{ date: u.as_of, value: r.weight }];
  });

  return (
    <section className="rounded-lg border border-[#21262d] bg-[#11161d] flex flex-wrap items-stretch">
      <Cell label="In this book" tone="head">
        <div className="text-[12.5px] font-medium text-slate-200 truncate max-w-[190px]">
          {bookName ?? "This book"}
        </div>
        <div className="text-[10.5px] text-slate-500">{fmtDate(exposure.as_of)} update</div>
      </Cell>

      <Cell label="Market value">
        <Figure>{fmtMoney(exposure.market_value)}</Figure>
        <Sub>{fmtDate(exposure.as_of)} close</Sub>
      </Cell>

      <Cell label="Weight">
        <Figure>{fmtPct(exposure.weight, 2)}</Figure>
        <Sub>
          {row?.weight_change_vs_prev == null
            ? "no earlier update to compare"
            : <span className={row.weight_change_vs_prev < 0 ? "text-red-400" : "text-emerald-400"}>
                {fmtSignedPct(row.weight_change_vs_prev, 2)} vs {fmtDate(previous)}
              </span>}
        </Sub>
      </Cell>

      <Cell label="Day">
        <Figure tone={(exposure.daily_pnl ?? 0) < 0 ? "down" : "up"}>
          {fmtMoney(exposure.daily_pnl)}
        </Figure>
        <Sub>
          {fmtSignedPct(exposure.daily_return, 2)} on the name
          {exposure.contribution != null && <> · {fmtSignedPct(exposure.contribution, 3)} of the book&apos;s day</>}
        </Sub>
      </Cell>

      {check && check.current != null && (
        <Cell label={
          <span className="flex items-center gap-2">
            {check.label}
            {check.status && check.status !== "ok" && (
              <span className="font-mono text-[9.5px] px-1.5 rounded bg-amber-500/15 text-amber-400">
                {check.status}
              </span>
            )}
          </span>
        }>
          <Meter check={check} />
          <Sub>
            <span className="text-slate-300">{fmtPct(check.current, 2)}</span> ·{" "}
            {fmtPct(check.warning, 0)} warning · {fmtPct(check.breach, 0)} breach
            {check.room_warning != null && (
              <> · {check.room_warning < 0
                ? <span className="text-amber-400">over by {fmtPct(-check.room_warning, 2)}</span>
                : <>{fmtPct(check.room_warning, 2)} of room</>}</>
            )}
          </Sub>
        </Cell>
      )}

      {path.length > 1 && (
        <Cell label={`${path.length} updates`}>
          <Path points={path} warning={check?.warning ?? null} />
        </Cell>
      )}

      <div className="flex flex-col justify-center gap-1 px-3.5 py-2 text-[11px]">
        {check?.alert_id && (
          <button onClick={() => open(check.alert_id as string)}
            className="text-teal-400 hover:text-teal-300 text-left">Open the alert</button>
        )}
        <button onClick={() => open(exposure.run_id)}
          className="text-slate-400 hover:text-slate-200 text-left">
          The run this is from
        </button>
      </div>
    </section>
  );
}

function Cell({ label, children, tone }: {
  label: React.ReactNode; children: React.ReactNode; tone?: "head";
}) {
  return (
    <div className={`px-3.5 py-2 border-r border-[#21262d] last:border-r-0 flex flex-col
                     justify-center gap-0.5 min-w-0 ${tone === "head" ? "bg-[#0f141b]" : ""}`}>
      <div className="text-[9.5px] uppercase tracking-[0.08em] text-slate-500 whitespace-nowrap">
        {label}
      </div>
      {children}
    </div>
  );
}

function Figure({ children, tone }: { children: React.ReactNode; tone?: "up" | "down" }) {
  return (
    <div className={`text-[14px] font-semibold leading-tight tabular-nums whitespace-nowrap ${
      tone === "down" ? "text-red-400" : tone === "up" ? "text-emerald-400" : "text-[#e6edf3]"}`}>
      {children}
    </div>
  );
}

function Sub({ children }: { children: React.ReactNode }) {
  return <div className="text-[10.5px] text-slate-500 whitespace-nowrap">{children}</div>;
}

/** The check as a distance to its breach tier, with the warning tier marked —
 *  the same shape the mandate meters use, so one check reads one way. */
function Meter({ check }: { check: LimitCheckRow }) {
  const utilisation = Math.min(100, Math.max(0, (check.utilisation ?? 0) * 100));
  const tick = check.warning != null && check.breach ? (check.warning / check.breach) * 100 : null;
  return (
    <div className="relative h-[5px] w-[150px] rounded bg-[#16243a] my-1">
      <span className="absolute inset-y-0 left-0 rounded"
        style={{ width: `${utilisation}%`,
                 background: check.status === "breach" ? C.crit
                   : check.status === "warning" ? C.warn : C.s1 }} />
      {tick != null && (
        <span className="absolute block w-px h-[11px] -top-[3px] bg-slate-400" style={{ left: `${tick}%` }} />
      )}
      <span className="absolute block w-px h-[11px] -top-[3px]" style={{ left: "100%", background: C.crit }} />
    </div>
  );
}

/** The weight at each dated update. Small on purpose: it answers "is this new",
 *  and the book page answers everything after that. */
function Path({ points, warning }: {
  points: { date: string; value: number }[];
  warning: number | null;
}) {
  const w = 108;
  const h = 30;
  const t0 = Date.parse(`${points[0].date}T00:00:00Z`);
  const t1 = Date.parse(`${points[points.length - 1].date}T00:00:00Z`);
  const values = points.map((p) => p.value);
  const near = warning != null && warning <= Math.max(...values) * 1.4;
  const lo = Math.min(...values, ...(near ? [warning as number] : []));
  const hi = Math.max(...values, ...(near ? [warning as number] : []));
  const pad = (hi - lo) * 0.2 || 0.001;
  const X = (d: string) =>
    2 + (t1 === t0 ? 0 : (Date.parse(`${d}T00:00:00Z`) - t0) / (t1 - t0)) * (w - 4);
  const Y = (v: number) => h - 3 - ((v - (lo - pad)) / ((hi + pad) - (lo - pad))) * (h - 6);
  const last = points[points.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img"
      aria-label={`Weight across ${points.length} updates, ending ${fmtPct(last.value, 2)}`}>
      {near && (
        <line x1={2} x2={w - 2} y1={Y(warning as number)} y2={Y(warning as number)}
          stroke={C.warn} strokeDasharray="2 2" />
      )}
      <path d={points.map((p, i) => `${i ? "L" : "M"}${X(p.date).toFixed(1)} ${Y(p.value).toFixed(1)}`).join("")}
        fill="none" stroke={C.s1} strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={X(last.date)} cy={Y(last.value)} r={2.6} fill={C.s1} />
    </svg>
  );
}
