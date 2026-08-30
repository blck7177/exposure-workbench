"use client";

import { useState } from "react";

import {
  C, ChartCard, fmtDate, fmtMoney, fmtMonth, fmtPct, fmtSignedPct, titleFromKey,
  type TableSpec,
} from "../charts/frame";
import { LineChart } from "../charts/line";
import { DivergingBars, Meters, TierBars, Waterfall, type WaterfallStep } from "../charts/bars";
import { Heatmap } from "../charts/grids";
import { Legend } from "../charts/frame";
import type { FactorCorrelation, History, LimitBook, Scenario } from "@/lib/charts";
import type { FactorAttribution, IssuerExposure } from "@/lib/types";

/**
 * The book's panels (V13-S6c).
 *
 * Each one renders something a run already recorded. None of them computes a
 * measure: where a percentage appears that the server did not send — a
 * holding's share of the day — it is a stored dollar amount over a stored
 * dollar amount, which is a way of writing the same fact down, not a second
 * opinion about it.
 *
 * Every panel carries a `note`. That is not decoration: these are the sentences
 * that say what the picture is NOT — quantities held fixed, factors held flat,
 * a coefficient that is not quotable alone. The old dashboard drew the numbers
 * and left those sentences in the payload.
 */

// ── value and drawdown ───────────────────────────────────────────────────────

export function ValueAndDrawdown({ history }: { history: History }) {
  const pts = history.points;
  const x = pts.map((p) => p.date);
  const step = Math.max(1, Math.floor(pts.length / 6));
  const xTicks = pts
    .map((p, i) => ({ at: i, label: fmtMonth(p.date) }))
    .filter((_, i) => i % step === 0 && i < pts.length - step / 2);

  // Episodes are drawn as bands over the value line, by index. Only the ones
  // deep enough to have a name in the run's own record: shading every dip would
  // shade the whole chart and say nothing.
  const idx = new Map(pts.map((p, i) => [p.date, i]));
  const bands = history.episodes
    .filter((e) => e.depth >= 0.1)
    .map((e) => ({
      from: idx.get(e.peak) ?? 0,
      to: idx.get(e.recovery ?? e.trough) ?? idx.get(e.trough) ?? 0,
      at: idx.get(e.trough),
      label: fmtPct(-e.depth, 1),
    }))
    .filter((b) => b.to > b.from);

  const table: TableSpec = {
    columns: ["Date", "Book", `${history.benchmark}, indexed`, "Drawdown", "30-day vol"],
    rows: pts
      .filter((_, i) => i % Math.max(1, Math.floor(pts.length / 60)) === 0)
      .map((p) => [fmtDate(p.date), fmtMoney(p.value), fmtMoney(p.benchmark),
                   fmtPct(p.drawdown, 2), p.vol_30d == null ? "—" : fmtPct(p.vol_30d, 2)]),
  };

  return (
    <ChartCard
      title="Value and drawdown"
      aside={history.window
        ? `${history.window.sessions} sessions to ${fmtDate(history.window.to)} · ${history.benchmark} indexed to the same start`
        : undefined}
      table={table}
      note={history.valuation_assumption}>
      <LineChart
        x={x}
        height={260}
        series={[
          { key: "book", label: "Book", points: pts.map((p) => p.value), colour: C.s1, area: true,
            endLabel: fmtMoney(pts[pts.length - 1]?.value) },
          { key: "bench", label: `${history.benchmark}, indexed`, points: pts.map((p) => p.benchmark),
            colour: C.grey, width: 1.5 },
        ]}
        bands={bands}
        sub={{ points: pts.map((p) => p.drawdown), height: 44, colour: C.crit, format: (v) => fmtPct(v, 1) }}
        xTicks={xTicks}
        yFormat={(v) => fmtMoney(v)}
        ariaLabel="Portfolio value against its benchmark, with drawdown from peak beneath"
        tipRows={(i) => {
          const p = pts[i];
          return [
            { label: "Book", value: fmtMoney(p.value), colour: C.s1 },
            { label: history.benchmark, value: fmtMoney(p.benchmark), colour: C.grey },
            { label: "Drawdown", value: fmtPct(p.drawdown, 2), colour: C.crit },
            ...(p.vol_30d == null ? [] : [{ label: "30-day vol", value: fmtPct(p.vol_30d, 2) }]),
          ];
        }}
      />
      <Legend items={[
        { label: "Book", colour: C.s1, shape: "line" },
        { label: `${history.benchmark}, indexed`, colour: C.grey, shape: "line" },
        { label: "Drawdown from peak", colour: C.crit, shape: "swatch" },
        { label: "Episode deeper than 10%", shape: "swatch" },
      ]} />
      {history.episodes.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
          {history.episodes.slice(0, 3).map((e) => (
            <li key={e.peak}>
              <span className="text-slate-400">{fmtPct(-e.depth, 1)}</span>{" "}
              {fmtDate(e.peak)} → {fmtDate(e.trough)} ({e.trough_days} sessions)
              {e.recovered ? `, back in ${e.recovery_days}` : ", not yet recovered"}
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  );
}

// ── where the day went ───────────────────────────────────────────────────────

export function WhereTheDayWent({ factors, issuers, dailyReturn, dailyPnl, names }: {
  factors: FactorAttribution[];
  issuers: IssuerExposure[];
  dailyReturn: number | null;
  dailyPnl: number | null;
  /** Factor ticker → the name the correlation window uses for it, so the two
   *  panels about the same regression do not call the same factor two things. */
  names: Record<string, string>;
}) {
  const nameOf = (f: FactorAttribution) =>
    (f.factor_ticker ? names[f.factor_ticker] : undefined) ?? titleFromKey(f.factor_name);
  const [mode, setMode] = useState<"factors" | "holdings">("factors");

  const explained = factors.reduce((a, f) => a + (f.contribution ?? 0), 0);
  const factorSteps: WaterfallStep[] = [
    ...factors
      .filter((f) => f.contribution != null)
      .sort((a, b) => (a.contribution ?? 0) - (b.contribution ?? 0))
      .map((f) => ({ label: nameOf(f), short: f.factor_ticker ?? undefined,
                     value: f.contribution as number })),
    ...(dailyReturn == null ? [] : [{ label: "Stock-specific", short: "Specific",
                                     value: dailyReturn - explained }]),
    ...(dailyReturn == null ? [] : [{ label: "Day", value: dailyReturn, total: true }]),
  ];

  const holdingSteps: WaterfallStep[] = [
    ...issuers
      .filter((i) => i.daily_pnl != null)
      .sort((a, b) => (a.daily_pnl ?? 0) - (b.daily_pnl ?? 0))
      .map((i) => ({ label: i.ticker, value: i.daily_pnl as number })),
    ...(dailyPnl == null ? [] : [{ label: "Day", value: dailyPnl, total: true }]),
  ];

  const byFactor = mode === "factors";
  const steps = byFactor ? factorSteps : holdingSteps;
  const format = byFactor ? (v: number) => fmtSignedPct(v, 2) : (v: number) => fmtMoney(v);

  return (
    <ChartCard
      title="Where the day went"
      controls={
        <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
          {(["factors", "holdings"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
              className={`px-2 py-0.5 ${mode === m ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
              {m === "factors" ? "By factor" : "By holding"}
            </button>
          ))}
        </div>
      }
      table={{
        columns: byFactor ? ["Factor", "Beta", "Factor return", "Contribution"] : ["Holding", "Day P&L", "Day return"],
        rows: byFactor
          ? factors.map((f) => [nameOf(f), f.beta?.toFixed(3) ?? "—",
                                fmtSignedPct(f.factor_return, 2), fmtSignedPct(f.contribution, 3)])
          : issuers.map((i) => [i.ticker, fmtMoney(i.daily_pnl), fmtSignedPct(i.daily_return, 2)]),
      }}
      note={byFactor
        ? "The factor sum is quotable; the individual betas behind it are not — see the correlations beside this."
        : "Two decompositions of the same day. This one is in dollars because that is what the run stored per holding; the factor view is in percent for the same reason."}>
      <Waterfall steps={steps} format={format} height={210}
        ariaLabel={byFactor ? "The day's return decomposed by factor" : "The day's profit and loss by holding"} />
      <Legend items={[
        { label: "Added", colour: C.s3, shape: "swatch" },
        { label: "Cost", colour: C.neg, shape: "swatch" },
        { label: "Total", colour: C.grey, shape: "swatch" },
      ]} />
    </ChartCard>
  );
}

// ── the mandate book ─────────────────────────────────────────────────────────

export function MandateBook({ book, inert }: { book: LimitBook; inert: string[] }) {
  const withLevels = book.checks.filter((c) => c.current != null).length;
  return (
    <ChartCard
      title="Mandate book"
      aside={`${book.checks.length} checks · ${fmtDate(book.as_of)}`}
      table={{
        columns: ["Check", "Group", "Measured", "Warning", "Breach", "State"],
        rows: book.checks.map((c) => [
          c.label, c.group, c.current == null ? "—" : fmtPct(c.current, 2),
          c.warning == null ? "—" : fmtPct(c.warning, 2),
          c.breach == null ? "—" : fmtPct(c.breach, 2),
          c.status ?? (c.fired ? "fired" : "—"),
        ]),
      }}
      note={<>
        {book.detail ?? "Every check the run evaluated, not only the ones that fired. The limits are this book's own."}
        {inert.length > 0 && (
          <> <span className="text-amber-500/90">
            {inert.length} limit{inert.length === 1 ? " is" : "s are"} set on{" "}
            {inert.length === 1 ? "a name" : "names"} this book does not hold
            ({inert.join(", ")}), so {inert.length === 1 ? "it was" : "they were"} never
            consulted.</span></>
        )}
      </>}>
      {withLevels === 0 ? (
        // The honest empty state. Drawing 27 empty tracks would read as
        // "measured, and at zero" — which is the one thing they are not.
        <div className="py-2">
          <p className="text-xs text-slate-400 leading-relaxed">
            This run evaluated <span className="text-slate-200">{book.checks.length}</span> checks
            and <span className="text-slate-200">{book.checks.filter((c) => c.fired).length}</span> of
            them fired, but it ran before this desk recorded what each check measured, so there are
            no levels to draw. The next run records them.
          </p>
          <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-[11px]">
            {book.checks.map((c) => (
              <li key={c.key} className="flex items-center gap-2 truncate">
                <span aria-hidden className={c.fired ? "text-amber-500" : "text-slate-700"}>●</span>
                <span className={c.fired ? "text-slate-300" : "text-slate-500"}>{c.label}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <Meters
          meters={book.checks.map((c) => ({
            key: c.key, label: c.label, group: c.group,
            current: c.current, warning: c.warning, breach: c.breach,
            status: c.status, utilisation: c.utilisation,
          }))}
          format={(v) => (v == null ? "—" : fmtPct(v, 2))}
        />
      )}
    </ChartCard>
  );
}

// ── factor betas and their correlations ──────────────────────────────────────

export function FactorBetas({ factors, collinear, maxVif, names }: {
  factors: FactorAttribution[];
  collinear: boolean;
  maxVif: number | null;
  names: Record<string, string>;
}) {
  const nameOf = (f: FactorAttribution) =>
    (f.factor_ticker ? names[f.factor_ticker] : undefined) ?? titleFromKey(f.factor_name);
  const rows = factors
    .filter((f) => f.beta != null)
    .map((f) => ({
      key: f.factor_name,
      label: nameOf(f),
      value: f.beta as number,
      tip: [
        { label: "Beta", value: (f.beta as number).toFixed(3) },
        { label: "Factor return", value: fmtSignedPct(f.factor_return, 2) },
        { label: "Contribution", value: fmtSignedPct(f.contribution, 3) },
        ...(f.r_squared == null ? [] : [{ label: "R² of this factor alone", value: f.r_squared.toFixed(3) }]),
      ],
    }));

  return (
    <ChartCard
      title="Factor betas"
      aside={collinear ? "outlined: not quotable alone" : undefined}
      table={{
        columns: ["Factor", "Ticker", "Beta", "R²"],
        rows: factors.map((f) => [nameOf(f), f.factor_ticker ?? "—",
                                  f.beta?.toFixed(4) ?? "—", f.r_squared?.toFixed(4) ?? "—"]),
      }}
      note={collinear
        ? <><span className="text-amber-500">VIF {maxVif?.toFixed(1)} — the factors move together.</span>{" "}
            The combined explanation is well determined; no single coefficient is, which is why every
            bar is drawn open.</>
        : "Fitted over the same window as the correlations beside this."}>
      <DivergingBars rows={rows} dashed={collinear} format={(v) => v.toFixed(2)}
        ariaLabel="Factor betas, positive and negative" />
    </ChartCard>
  );
}

export function FactorCorrelations({ corr }: { corr: FactorCorrelation }) {
  if (!corr.matrix || corr.labels.length === 0) {
    return (
      <ChartCard title="Factor correlations" note={corr.detail}>
        <p className="text-xs text-slate-500 py-6">{corr.detail ?? "This run did not record a factor window."}</p>
      </ChartCard>
    );
  }
  const strongest = strongestPair(corr);
  return (
    <ChartCard
      title="Factor correlations"
      aside={corr.window ? `${corr.window.observations} sessions` : undefined}
      table={{
        columns: ["", ...corr.labels],
        rows: corr.matrix.map((row, i) => [corr.labels[i],
          ...row.map((v) => (v == null ? "—" : v.toFixed(2)))]),
      }}
      note={strongest
        ? <>{strongest} — factors moving as one is what the regression cannot separate.</>
        : "The same window the betas were fitted over."}>
      <Heatmap labels={corr.labels} matrix={corr.matrix} window={corr.window}
        ariaLabel="Correlations between the factors the regression used" />
      <Legend items={[
        { label: "toward +1", colour: C.s1, shape: "swatch" },
        { label: "0", colour: C.mid, shape: "swatch" },
        { label: "toward −1", colour: C.neg, shape: "swatch" },
      ]} />
    </ChartCard>
  );
}

/** The pair a reader should look at, named from the matrix rather than chosen
 *  by hand — so the sentence stays true when the factor set changes. */
function strongestPair(corr: FactorCorrelation): string | null {
  if (!corr.matrix) return null;
  let best: { a: string; b: string; v: number } | null = null;
  corr.matrix.forEach((row, i) => row.forEach((v, k) => {
    if (k <= i || v == null) return;
    if (!best || Math.abs(v) > Math.abs(best.v)) best = { a: corr.labels[i], b: corr.labels[k], v };
  }));
  if (!best) return null;
  const { a, b, v } = best as { a: string; b: string; v: number };
  return `${a}–${b} ${v.toFixed(2)}`;
}

// ── stress ───────────────────────────────────────────────────────────────────

export function Stress({ scenarios }: { scenarios: Scenario[] }) {
  const evaluated = scenarios.filter((s) => s.loss_pct != null);
  const unevaluated = scenarios.filter((s) => s.loss_pct == null);
  const anyTier = evaluated.some((s) => s.warning != null || s.breach != null);

  return (
    <ChartCard
      title="If the market broke"
      aside={`${evaluated.length} scenarios · shocks propagate through each holding's beta`}
      table={{
        columns: ["Scenario", "Estimated loss", "Warning", "Breach", "Held flat"],
        rows: scenarios.map((s) => [
          s.label, s.loss_pct == null ? (s.reason ?? "not evaluated") : fmtPct(s.loss_pct, 2),
          s.warning == null ? "—" : fmtPct(s.warning, 2),
          s.breach == null ? "—" : fmtPct(s.breach, 2),
          s.held_flat.join(", ") || "—",
        ]),
      }}
      note={<>Factors a scenario says nothing about are held flat — an assumption, not a measurement.
        Hover a bar for the shocks it applies and what it leaves still.
        {!anyTier && evaluated.length > 0 && " This run recorded no tiers for these, so nothing here judges the losses."}</>}>
      <TierBars
        bars={evaluated.map((s) => ({
          key: s.key, label: s.label, value: s.loss_pct as number,
          warning: s.warning, breach: s.breach,
          tip: [
            ...Object.entries(s.shocks).map(([k, v]) => ({ label: k, value: fmtSignedPct(v, 1) })),
            { label: "Held flat", value: s.held_flat.join(", ") || "nothing" },
          ],
        }))}
        format={(v) => fmtPct(v, 2)}
        ariaLabel="Estimated loss under each stress scenario"
      />
      {unevaluated.length > 0 && (
        <p className="mt-2 text-[11px] text-slate-500">
          Not evaluated: {unevaluated.map((s) => `${s.label} (${s.reason ?? "no reason recorded"})`).join("; ")}.
        </p>
      )}
      <Legend items={[
        { label: "Estimated loss", colour: C.s1, shape: "swatch" },
        ...(anyTier ? [{ label: "Warning tier", colour: C.warn, shape: "tick" as const },
                       { label: "Breach tier", colour: C.crit, shape: "tick" as const }] : []),
      ]} />
    </ChartCard>
  );
}
