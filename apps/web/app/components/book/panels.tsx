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
import { SmallMultiples, type Multiple } from "../charts/multiples";
import { useFocus } from "./Focus";
import type {
  FactorCorrelation, History, LimitBook, Reconcile, RunSeries, Scenario,
} from "@/lib/charts";
import type { FactorAttribution, IssuerExposure } from "@/lib/types";
import { useEvidence } from "../evidence/Column";

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

export function ValueAndDrawdown({ history, span, onSpan, onAsk }: {
  history: History;
  /** The window asked for. The list comes from the endpoint (`history.spans`),
   *  so the control offers what the server accepts rather than a copy of it. */
  span: string;
  onSpan: (span: string) => void;
  onAsk: (q: string) => void;
}) {
  const { open } = useEvidence();
  // A view over the same points, and only that: nothing is recomputed for a
  // narrower window, because a rolling measure re-derived in a browser would be
  // a second opinion about a figure the run already stated.
  const [window_, setWindow] = useState<{ from: number; to: number } | null>(null);
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
  const at = (date: string | null | undefined) =>
    date == null ? undefined
      : idx.get(date) ?? (pts.findIndex((p) => p.date >= date) >= 0
        ? pts.findIndex((p) => p.date >= date) : undefined);
  const bands = history.episodes
    .filter((e) => e.depth >= 0.1)
    .map((e) => ({
      from: at(e.peak) ?? 0,
      to: at(e.recovery ?? e.trough) ?? at(e.trough) ?? 0,
      at: at(e.trough),
      label: fmtPct(-e.depth, 1),
    }))
    .filter((b) => b.to > b.from);

  const shown = window_
    ? pts.slice(Math.max(0, window_.from), Math.min(pts.length, window_.to + 1))
    : pts;
  const table: TableSpec = {
    columns: ["Date", "Book", `${history.benchmark}, indexed`, "Drawdown", "30-day vol"],
    rows: shown
      .filter((_, i) => i % Math.max(1, Math.floor(shown.length / 60)) === 0)
      .map((p) => [fmtDate(p.date), fmtMoney(p.value), fmtMoney(p.benchmark),
                   fmtPct(p.drawdown, 2), p.vol_30d == null ? "—" : fmtPct(p.vol_30d, 2)]),
  };
  const spans = history.spans ?? [span];

  return (
    <ChartCard
      title="Value and drawdown"
      info={[history.methods?.value_path, history.methods?.drawdown].filter(Boolean).join(" ")}
      aside={history.window
        ? `${history.window.sessions} sessions to ${fmtDate(history.window.to)} · ${history.benchmark} indexed to the same start`
        : undefined}
      controls={
        <div className="flex items-center gap-2">
          {window_ && (
            <button onClick={() => setWindow(null)}
              className="text-[11px] px-2 py-0.5 rounded border border-[#30363d] text-slate-400 hover:text-slate-200 hover:border-slate-500">
              {fmtDate(shown[0]?.date)} – {fmtDate(shown[shown.length - 1]?.date)} ✕
            </button>
          )}
          <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
            {spans.map((s) => (
              <button key={s} onClick={() => { setWindow(null); onSpan(s); }} aria-pressed={s === span}
                className={`px-2 py-0.5 ${s === span ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
                {s}
              </button>
            ))}
          </div>
        </div>
      }
      table={table}
      note={<>{history.valuation_assumption}
        {history.episodes_calc_id && (
          <>{" — "}
            <button onClick={() => open(history.episodes_calc_id as string)}
              className="text-teal-400 hover:text-teal-300 hover:underline">
              how the episodes were worked out
            </button>
          </>
        )}. Drag the drawdown strip to narrow the value line above it; nothing is
        recomputed for the narrower window.</>}>
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
        brush={{ from: window_?.from ?? 0, to: window_?.to ?? pts.length - 1, onChange: setWindow }}
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
        <ul className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
          {history.episodes.slice(0, 3).map((e) => {
            const from = at(e.peak);
            const to = at(e.recovery ?? e.trough) ?? at(e.trough);
            return (
              <li key={e.peak} className="inline-flex items-center gap-2 rounded border border-[#30363d] px-2 py-0.5">
                <button
                  onClick={() => (from != null && to != null && to > from
                    ? setWindow({ from, to }) : undefined)}
                  className="text-left hover:text-slate-300"
                  title="Narrow the chart to this episode">
                  <span className="text-slate-400">{fmtPct(-e.depth, 1)}</span>{" "}
                  {fmtDate(e.peak)} → {fmtDate(e.trough)} ({e.trough_days} sessions)
                  {e.recovered ? `, back in ${e.recovery_days}` : ", not yet recovered"}
                </button>
                <button
                  onClick={() => onAsk(
                    `Explain the episode from ${e.peak} to ${e.trough}: what was it made of?`)}
                  className="text-teal-400 hover:text-teal-300 shrink-0"
                  title="Ask the analyst what this window was made of">
                  Explain
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </ChartCard>
  );
}

// ── where the day went ───────────────────────────────────────────────────────

export function WhereTheDayWent({ factors, issuers, dailyReturn, dailyPnl, names, info, reconcile }: {
  info?: string | null;
  factors: FactorAttribution[];
  issuers: IssuerExposure[];
  dailyReturn: number | null;
  dailyPnl: number | null;
  /** Factor ticker → the name the correlation window uses for it, so the two
   *  panels about the same regression do not call the same factor two things. */
  names: Record<string, string>;
  /** V25. Whether the day's two decompositions close, from the endpoint that
   *  performs the check — typed since V13 and never called. The page states the
   *  server's verdict and does not form one of its own: a comparison made here
   *  would be free to differ in the eighth decimal from the one the ledger
   *  recorded. */
  reconcile: Reconcile | null;
}) {
  const { open } = useEvidence();
  const { focus, point } = useFocus();
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
      info={info}
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
        focusKey={byFactor
          ? (focus?.kind === "factor" ? focus.key : null)
          : (focus?.kind === "ticker" ? focus.key : null)}
        onPoint={(key) => point(key ? { kind: byFactor ? "factor" : "ticker", key } : null)}
        ariaLabel={byFactor ? "The day's return decomposed by factor" : "The day's profit and loss by holding"} />
      <Legend items={[
        { label: "Added", colour: C.s3, shape: "swatch" },
        { label: "Cost", colour: C.neg, shape: "swatch" },
        { label: "Total", colour: C.grey, shape: "swatch" },
      ]} />
      <Reconciles reconcile={reconcile} onOpen={open} />
    </ChartCard>
  );
}

/**
 * Whether the day adds up — the endpoint's own answer, under the chart it is about.
 *
 * Two identities: the positions' contributions sum to the day's return, and the
 * factor contributions plus alpha and the residual sum to the return the
 * regression was fitted against. Both were computed, recorded and never shown;
 * the page drew the decomposition and left the proof that it closes in the
 * payload.
 *
 * `holds` is the server's verdict against the server's tolerance. Nothing here
 * compares two numbers — a check performed in the browser would be a second
 * opinion, and the two would eventually disagree in the last decimal.
 */
function Reconciles({ reconcile, onOpen }: {
  reconcile: Reconcile | null;
  onOpen: (id: string) => void;
}) {
  if (!reconcile) return null;
  if (reconcile.error) {
    return (
      <p className="mt-2.5 pt-2 border-t border-[#21262d] text-[11px] text-slate-500">
        {reconcile.detail ?? "This run did not record everything the identities need, so whether "
          + "the day adds up cannot be stated for it."}
      </p>
    );
  }
  const positions = reconcile.identity_positions;
  const factors = reconcile.identity_factors;
  const mark = (ok: boolean | undefined) => (
    <span className={ok ? "text-emerald-400" : "text-amber-400"}>{ok ? "✓" : "✕"}</span>
  );
  return (
    <div className="mt-2.5 pt-2 border-t border-[#21262d] flex flex-wrap items-center gap-x-5 gap-y-1
                    text-[11px] text-slate-500 tabular-nums">
      {positions && (
        <span>
          <span className="text-slate-400">Positions</span>{" "}
          {positions.terms} contributions sum to{" "}
          <b className="font-medium text-slate-200">{fmtSignedPct(positions.sum_of_contributions, 3)}</b>
          {" = "}the day&apos;s {fmtSignedPct(positions.daily_return, 3)} {mark(positions.holds)}
        </span>
      )}
      {factors && (
        <span>
          <span className="text-slate-400">Factors</span>{" "}
          {fmtSignedPct(factors.sum_of_factor_contributions, 3)} explained{" "}
          {factors.alpha_plus_residual < 0 ? "−" : "+"}{" "}
          {fmtSignedPct(Math.abs(factors.alpha_plus_residual), 3)} alpha and residual{" = "}
          <b className="font-medium text-slate-200">
            {fmtSignedPct(factors.attribution_portfolio_return, 3)}
          </b> {mark(factors.holds)}
        </span>
      )}
      {reconcile.factor_share != null && (
        <span>the factors account for <b className="font-medium text-slate-200">
          {fmtPct(reconcile.factor_share, 0)}</b> of it</span>
      )}
      {reconcile.calc_id && (
        <button onClick={() => onOpen(reconcile.calc_id as string)}
          className="ml-auto text-teal-400 hover:text-teal-300 hover:underline">
          the calculation that checked this
        </button>
      )}
    </div>
  );
}

// ── the mandate book ─────────────────────────────────────────────────────────

const BOOK_MODES = ["Now", "Across updates"] as const;
type BookMode = (typeof BOOK_MODES)[number];

/**
 * Every mandate check, two ways (V25).
 *
 * `Now` is what it always was: each check's reading against its tiers, ordered
 * by how close it is to a breach. `Across updates` is the same checks as
 * series, because "16.3% against a 15% tier" and "16.3%, up from 15.9% a week
 * ago and 15.1% in June" are different books and the page could only ever say
 * the first. One panel and not two, because the question is one question: how
 * close, and which way is it going.
 *
 * The series shows the six checks nearest their tiers rather than all twenty:
 * twenty small charts is a wall, and the ones a reader is looking for are the
 * ones with the least room. The rest stay one click away in `Now`.
 */
export function MandateBook({ book, inert, series }: {
  book: LimitBook;
  inert: string[];
  /** The dated updates. Absent while the read is in flight, or on a book with
   *  one update — in which case there is no series to draw and the control does
   *  not appear. */
  series: RunSeries | null;
}) {
  const withLevels = book.checks.filter((c) => c.current != null).length;
  const { open } = useEvidence();
  const [mode, setMode] = useState<BookMode>("Now");
  const canCompare = (series?.updates.length ?? 0) > 1;
  const across = canCompare && mode === "Across updates";

  // Nearest a breach first — the same order the meters use, so the six drawn
  // are the six at the top of the list a reader has just been looking at.
  const nearest = [...book.checks]
    .filter((c) => c.utilisation != null)
    .sort((a, b) => (b.utilisation ?? 0) - (a.utilisation ?? 0))
    .slice(0, 6);

  const charts: Multiple[] = across && series
    ? nearest.map((check) => ({
        key: check.key,
        label: check.label,
        status: check.status,
        points: series.updates.flatMap((u) => {
          const row = u.checks.find((c) => c.key === check.key);
          // A loss check reads as a magnitude against its tier; the sign is on
          // the day's P&L, which the tiles say. Reading it as a distance is what
          // makes "0.6% of a 2% tier" comparable with the weights beside it.
          return row?.current == null ? [] : [{ date: u.as_of, value: Math.abs(row.current) }];
        }),
        rules: [
          ...(check.warning == null ? [] : [{
            value: check.warning, colour: C.warn, label: `warn ${fmtPct(check.warning, 0)}`,
          }]),
          ...(check.breach == null ? [] : [{
            value: check.breach, colour: C.crit, label: `breach ${fmtPct(check.breach, 0)}`,
          }]),
        ],
      }))
    : [];

  return (
    <ChartCard
      title="Mandate book"
      aside={across
        ? `${nearest.length} nearest their tiers · ${series?.updates.length} updates`
        : `${book.checks.length} checks · ${fmtDate(book.as_of)}`}
      controls={canCompare ? (
        <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
          {BOOK_MODES.map((m) => (
            <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
              className={`px-2 py-0.5 ${mode === m ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
              {m}
            </button>
          ))}
        </div>
      ) : undefined}
      table={across && series ? {
        columns: ["Update", ...nearest.map((c) => c.label)],
        rows: series.updates.map((u) => [
          fmtDate(u.as_of),
          ...nearest.map((c) => {
            const row = u.checks.find((r) => r.key === c.key);
            return row?.current == null ? "—" : fmtPct(Math.abs(row.current), 2);
          }),
        ]),
      } : {
        columns: ["Check", "Group", "Measured", "Warning", "Breach", "Room to warning", "State"],
        rows: book.checks.map((c) => [
          c.label, c.group, c.current == null ? "—" : fmtPct(c.current, 2),
          c.warning == null ? "—" : fmtPct(c.warning, 2),
          c.breach == null ? "—" : fmtPct(c.breach, 2),
          c.room_warning == null ? "—" : fmtSignedPct(c.room_warning, 2),
          c.status ?? (c.fired ? "fired" : "—"),
        ]),
      }}
      note={<>
        {across
          ? <>The six checks with the least room, at every dated update. Each point is what that
              run measured; the rules are the tiers this book set. A loss check is drawn as a
              distance from zero, which is how its tier judges it.</>
          : (book.detail ?? "Every check the run evaluated, not only the ones that fired. The limits are this book's own.")}
        {inert.length > 0 && (
          <> <span className="text-amber-500/90">
            {inert.length} limit{inert.length === 1 ? " is" : "s are"} set on{" "}
            {inert.length === 1 ? "a name" : "names"} this book does not hold
            ({inert.join(", ")}), so {inert.length === 1 ? "it was" : "they were"} never
            consulted.</span></>
        )}
      </>}>
      {across ? (
        <SmallMultiples
          charts={charts}
          columns={2}
          format={(v) => fmtPct(v, 1)}
          axisLabels={(series?.updates ?? []).length > 3
            ? [fmtMonth(series!.updates[0].as_of),
               fmtMonth(series!.updates[Math.floor(series!.updates.length / 2)].as_of),
               fmtMonth(series!.updates[series!.updates.length - 1].as_of)]
            : (series?.updates ?? []).map((u) => fmtMonth(u.as_of))}
          ariaLabel="The checks nearest their tiers, at each dated update"
        />
      ) : withLevels === 0 ? (
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
                {c.alert_id ? (
                  <button onClick={() => open(c.alert_id as string)}
                    title="Open the alert this check wrote"
                    className="truncate text-left text-slate-300 hover:text-slate-100 hover:underline decoration-dotted underline-offset-2">
                    {c.label}
                  </button>
                ) : (
                  <span className={c.fired ? "text-slate-300" : "text-slate-500"}>{c.label}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <Meters
          meters={book.checks.map((c) => ({
            key: c.key, label: c.label, group: c.group,
            current: c.current, warning: c.warning, breach: c.breach,
            status: c.status, utilisation: c.utilisation, openId: c.alert_id,
          }))}
          format={(v) => (v == null ? "—" : fmtPct(v, 2))}
          onOpen={open}
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
  const { focus, point } = useFocus();
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
        focusKey={focus?.kind === "factor" ? focus.key : null}
        onPoint={(key) => point(key ? { kind: "factor", key } : null)}
        ariaLabel="Factor betas, positive and negative" />
    </ChartCard>
  );
}

export function FactorCorrelations({ corr, info }: { corr: FactorCorrelation; info?: string | null }) {
  const { focus, point } = useFocus();
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
      info={info}
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
        focusKey={focus?.kind === "factor" ? focus.key : null}
        onPoint={(key) => point(key ? { kind: "factor", key } : null)}
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

export function Stress({ scenarios, runId }: { scenarios: Scenario[]; runId: string }) {
  const { open } = useEvidence();
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
        onOpen={open}
        bars={evaluated.map((s) => ({
          key: s.key, label: s.label, value: s.loss_pct as number,
          warning: s.warning, breach: s.breach,
          // Stress rows are children of the run, not ledger rows of their own —
          // the honest click-through is the run that measured them.
          openId: runId,
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
