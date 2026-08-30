"use client";

import Link from "next/link";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { AuditOnly } from "../audit";
import { C, fmtDate, fmtMoney, fmtPct, fmtSignedPct, titleFromKey } from "../charts/frame";
import { ReturnHistogram, Sparkline } from "../charts/line";
import { collapseSteps, stepPhrase } from "../steps";
import type { History } from "@/lib/charts";
import { explainRunError } from "@/lib/errors";
import { formatDateTime, formatDuration } from "@/lib/formatting";
import type {
  DailyReport, ExposureMetrics, ExposureRun, Freshness, IssuerExposure,
  RiskAlert, SectorExposure, WorkflowEvent,
} from "@/lib/types";

/**
 * The book's sections that are not charts (V13-S6c).
 *
 * The rule they share with the panels: a number appears here only if a run
 * stored it. Where the old dashboard printed a run id, a task id, a model name
 * and a token count above the numbers, those move behind the audit switch —
 * still rendered, still exact, addressed to the person running the desk rather
 * than to the person reading their own book.
 */

// ── how old this is ──────────────────────────────────────────────────────────

export function FreshnessLine({ freshness }: { freshness: Freshness | null }) {
  if (!freshness) return null;
  const behind = freshness.sessions_behind;
  const stale = behind != null && behind > 0;
  return (
    <p className="flex items-center gap-2 text-[11.5px] text-slate-500">
      <span aria-hidden className={stale ? "text-amber-500" : "text-emerald-500"}>●</span>
      {freshness.detail ?? (
        <>Priced to {fmtDate(freshness.run_as_of)}
          {stale && ` · ${behind} session${behind === 1 ? "" : "s"} behind the market`}</>
      )}
      {freshness.runs_in_flight > 0 && (
        <span className="text-blue-400">· {freshness.runs_in_flight} update in flight</span>
      )}
    </p>
  );
}

// ── what this run found ──────────────────────────────────────────────────────

/**
 * The strip under the title.
 *
 * Every chip names the comparison it is making, because they are not the same
 * one: the day's move is against the previous session, a weight shift is
 * against the previous RUN, and a check is against a level in the mandate. A
 * strip that ran them together would read as one comparison and be wrong about
 * two of them.
 */
export function WhatThisRunFound({ run, metrics, alerts, sectors, checks }: {
  run: ExposureRun;
  metrics: ExposureMetrics | null;
  alerts: RiskAlert[];
  sectors: SectorExposure[];
  checks: number | null;
}) {
  const moved = [...sectors]
    .filter((s) => s.weight_change != null)
    .sort((a, b) => Math.abs(b.weight_change as number) - Math.abs(a.weight_change as number))[0];
  const warnings = alerts.filter((a) => a.severity === "warning").length;
  const breaches = alerts.filter((a) => a.severity === "breach").length;

  const chip = (key: string, body: React.ReactNode, tone?: "warn" | "crit", title?: string) => (
    <span key={key} title={title}
      className={`inline-flex items-center gap-1.5 rounded px-2 py-1 border ${
        tone === "crit" ? "border-red-900/60 bg-red-950/30 text-red-300"
        : tone === "warn" ? "border-amber-900/60 bg-amber-950/25 text-amber-300"
        : "border-[#21262d] bg-[#11161d] text-slate-300"}`}>
      {body}
    </span>
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-wider text-slate-600 pr-1">
        {fmtDate(run.as_of_date)}
      </span>
      {metrics?.daily_pnl != null && chip("day",
        <>Day{" "}
          <b className={metrics.daily_pnl < 0 ? "text-red-400" : "text-emerald-400"}>
            {fmtMoney(metrics.daily_pnl)}
          </b>
          <span className="text-slate-500">{fmtSignedPct(metrics.daily_return, 2)}</span>
        </>, undefined, "Against the previous session's close")}
      {breaches > 0 && chip("br", <>{breaches} breach{breaches === 1 ? "" : "es"}</>, "crit",
        "A mandate limit was crossed")}
      {warnings > 0 && chip("wn", <>{warnings} warning{warnings === 1 ? "" : "s"}</>, "warn",
        "Above a warning tier, below the breach tier")}
      {checks != null && chip("ck",
        <><b>{checks}</b> <span className="text-slate-500">checks evaluated</span></>, undefined,
        "Every limit this run measured, whether or not it fired")}
      {metrics?.var_95_1d != null && chip("var",
        <>VaR 95% <b>{fmtPct(metrics.var_95_1d, 2)}</b></>, undefined,
        "Historical, one day, from the run's own return window")}
      {moved && chip("sec",
        <>{titleFromKey(moved.sector)} <b>{fmtPct(moved.weight ?? 0, 1)}</b>{" "}
          <span className="text-slate-500">
            {Math.abs(moved.weight_change as number) < 0.0005
              ? "unchanged"
              : `${fmtSignedPct(moved.weight_change, 1)} vs previous run`}
          </span></>, undefined,
        "Sector weight, compared with the previous exposure run")}
    </div>
  );
}

// ── the tiles ────────────────────────────────────────────────────────────────

function Tile({ label, value, sub, tone, chart, basis }: {
  label: React.ReactNode; value: string; sub?: React.ReactNode;
  tone?: "up" | "down"; chart?: React.ReactNode; basis?: string;
}) {
  return (
    <div className="rounded-lg border border-[#21262d] bg-[#11161d] p-3 flex flex-col gap-1 min-w-0">
      <p className="text-[10px] uppercase tracking-wider text-slate-500 flex items-center gap-1.5">{label}</p>
      <p title={basis}
        className={`text-lg font-semibold leading-tight tabular-nums ${
          tone === "down" ? "text-red-400" : tone === "up" ? "text-emerald-400" : "text-[#e6edf3]"} ${
          basis ? "cursor-help decoration-dotted underline-offset-4 decoration-slate-600 underline" : ""}`}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-slate-500 truncate">{sub}</p>}
      {chart}
    </div>
  );
}

export function Tiles({ metrics, history, checks }: {
  metrics: ExposureMetrics | null;
  history: History | null;
  checks: { evaluated: number; fired: number } | null;
}) {
  if (!metrics) return null;
  const returns = (history?.points ?? [])
    .map((p) => p.return)
    .filter((v): v is number => v != null);
  const vols = (history?.points ?? []).slice(-260).map((p) => p.vol_30d);

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
      <Tile label="Portfolio value" value={fmtMoney(metrics.portfolio_market_value)}
        basis="Sum of the holdings at the run's own closing prices"
        sub={<>{fmtPct(metrics.gross_exposure_pct ?? 0, 0)} gross · {fmtPct(metrics.net_exposure_pct ?? 0, 0)} net</>} />
      <Tile label="Day P&L" value={fmtMoney(metrics.daily_pnl)}
        tone={metrics.daily_pnl != null && metrics.daily_pnl < 0 ? "down" : "up"}
        basis="Against the previous session's close, all holdings priced"
        sub={fmtSignedPct(metrics.daily_return, 2)} />
      <Tile label="VaR 95% · 1 day" value={fmtPct(metrics.var_95_1d, 2)}
        basis="Historical, from the return window this run fitted over"
        sub={<>ES 95% {fmtPct(metrics.expected_shortfall_95, 2)}</>}
        chart={metrics.var_95_1d != null && returns.length >= 20
          ? <ReturnHistogram returns={returns} quantile={metrics.var_95_1d}
              label="Daily returns, with the fifth percentile marked" />
          : undefined} />
      <Tile label="30-day volatility" value={fmtPct(metrics.rolling_vol_30d, 2)}
        basis="Rolling 30 sessions, annualised"
        sub={<>60-day {fmtPct(metrics.rolling_vol_60d, 2)}</>}
        chart={vols.filter((v) => v != null).length > 2
          ? <Sparkline points={vols} label="30-day volatility over the last year" colour={C.s1} />
          : undefined} />
      <Tile label="Max drawdown" value={fmtPct(metrics.max_drawdown, 2)}
        basis="Worst peak-to-trough over the window this run measured"
        sub={history?.episodes[0]
          ? <>deepest {fmtPct(-history.episodes[0].depth, 1)} over {history.episodes[0].trough_days} sessions</>
          : undefined} />
      <Tile label="Mandate checks" value={checks ? String(checks.evaluated) : "—"}
        sub={checks
          ? <>{checks.fired > 0
              ? <span className="text-amber-500">{checks.fired} fired</span>
              : "none fired"}</>
          : undefined} />
    </div>
  );
}

// ── warnings ─────────────────────────────────────────────────────────────────

/**
 * The alerts, said in words rather than in the row that recorded them.
 *
 * `risk_alerts.message` is written for the log: `Issuer LLY: 13.8% vs limit
 * 12.0% [WARNING]`, and for a stress alert `Stress scenario: market_downside:
 * 7.4% vs limit 6.0% [WARNING]` — a bracketed severity the page already shows
 * as a colour, and an internal scenario key. Those sentences are on rows that
 * exist and are not being rewritten.
 *
 * So the panel does not print the sentence. It builds one from the alert's own
 * structured fields, and takes the SUBJECT from the limit book, which is the
 * server's own name for the same check — `Market down 10%` for
 * `stress_loss:market_downside`. Nothing is mapped here by hand: the key an
 * alert carries is the key the check carries, and if a new limit type appears
 * its label arrives with it.
 */
function alertKey(a: RiskAlert): string {
  return a.entity_id ? `${a.alert_type}:${a.entity_id}` : a.alert_type;
}

export function Warnings({ alerts, labels, onAsk }: {
  alerts: RiskAlert[];
  /** Check key → the server's name for it, from the run's limit book. */
  labels: Record<string, string>;
  onAsk: (q: string) => void;
}) {
  if (alerts.length === 0) return null;
  return (
    <section className="rounded-lg border border-[#21262d] bg-[#11161d] overflow-hidden">
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-[#21262d]">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
        <h3 className="text-sm font-medium text-slate-200">Warnings</h3>
        <span className="text-[11px] text-slate-500">{alerts.length} fired</span>
      </header>
      <ul className="divide-y divide-[#21262d]">
        {alerts.map((a) => {
          const pct = a.utilization == null ? null : Math.max(0, Math.min(1, a.utilization));
          // Underscores and colons are how a key is spelled, not how it is read.
          // This is what a label looks like before the limit book lands, and it
          // is never the stored sentence — that is the thing being replaced.
          const subject = labels[alertKey(a)]
            ?? `${a.entity_id ?? a.alert_type}`.replace(/[_:]/g, " ");
          const group = a.entity_type === "issuer" ? "Issuer concentration"
            : a.entity_type === "sector" ? "Sector concentration"
            : a.alert_type.startsWith("stress") ? "Stress, propagated through each holding's beta"
            : "Portfolio";
          return (
            <li key={a.id} className="flex items-start gap-3 px-4 py-3">
              <span aria-hidden
                className={`mt-1 w-0.5 self-stretch rounded ${a.severity === "breach" ? "bg-red-500" : "bg-amber-500"}`} />
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] text-slate-300 leading-snug">
                  <b className="font-medium text-slate-200">{subject}</b>
                  {a.current_value != null && <> is <b className="text-slate-100">{fmtPct(a.current_value, 1)}</b></>}
                  {a.limit_value != null && <>, against a {fmtPct(a.limit_value, 1)} {a.severity} tier</>}
                  .
                </p>
                <p className="mt-0.5 text-[10.5px] text-slate-500">
                  {group} · this book&apos;s own limit
                </p>
                {pct != null && (
                  <div className="mt-1.5 h-1 rounded bg-[#1b2230] relative overflow-hidden max-w-md">
                    <span className="absolute inset-y-0 left-0 rounded"
                      style={{ width: `${pct * 100}%`,
                               background: a.severity === "breach" ? C.crit : C.warn }} />
                  </div>
                )}
                <AuditOnly>
                  <span className="block mt-1 font-mono text-[10px] text-slate-600">
                    {a.id} · {alertKey(a)} · current {a.current_value} · limit {a.limit_value}
                    {a.message ? <><br />{a.message}</> : null}
                  </span>
                </AuditOnly>
              </div>
              <button
                onClick={() => onAsk(`${subject} is at ${fmtPct(a.current_value, 1)} against a ${fmtPct(a.limit_value, 1)} ${a.severity} tier — what should I make of it?`)}
                className="shrink-0 text-[11px] px-2 py-1 rounded border border-[#30363d] text-slate-400 hover:text-slate-100 hover:border-slate-500">
                Ask
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── holdings ─────────────────────────────────────────────────────────────────

export function Holdings({ issuers, asOf, portfolioId, onAsk }: {
  issuers: IssuerExposure[];
  asOf: string;
  portfolioId: string | null;
  onAsk: (q: string) => void;
}) {
  if (issuers.length === 0) return null;
  const rows = [...issuers].sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0));
  return (
    <section className="rounded-lg border border-[#21262d] bg-[#11161d] overflow-hidden">
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-[#21262d]">
        <h3 className="text-sm font-medium text-slate-200">Holdings</h3>
        <span className="text-[11px] text-slate-500">{rows.length} · {fmtDate(asOf)} close</span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-slate-500">
              <th className="text-left font-medium py-1.5 px-4">Ticker</th>
              <th className="text-left font-medium py-1.5 px-2">Sector</th>
              <th className="text-right font-medium py-1.5 px-2">Market value</th>
              <th className="text-right font-medium py-1.5 px-2">Weight</th>
              <th className="text-right font-medium py-1.5 px-2">Day</th>
              <th className="py-1.5 px-4" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#21262d]">
            {rows.map((i) => (
              <tr key={i.ticker} className="hover:bg-[#161b22]">
                <td className="py-1.5 px-4">
                  <Link href={`/issuer/${i.ticker}${portfolioId ? `?portfolio=${portfolioId}` : ""}`}
                    className="font-mono text-[11.5px] text-blue-400 hover:text-blue-300 hover:underline">
                    {i.ticker}
                  </Link>
                </td>
                <td className="py-1.5 px-2 text-slate-500">{titleFromKey(i.sector)}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-slate-300">{fmtMoney(i.market_value)}</td>
                <td className="py-1.5 px-2 text-right tabular-nums text-slate-300">{fmtPct(i.weight, 2)}</td>
                <td className={`py-1.5 px-2 text-right tabular-nums ${
                  (i.daily_return ?? 0) < 0 ? "text-red-400" : "text-emerald-400"}`}>
                  {fmtSignedPct(i.daily_return, 2)}
                </td>
                <td className="py-1.5 px-4 text-right">
                  <button onClick={() => onAsk(`Why did ${i.ticker} move on ${fmtDate(asOf)}?`)}
                    className="text-[11px] text-slate-500 hover:text-slate-200">Ask</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── the briefing ─────────────────────────────────────────────────────────────

/**
 * The written report, with the badge its own gate earns.
 *
 * The count is not a claim this component makes: `generate_report` records
 * `numbers_checked` on the run, and the gate it comes from is stricter than the
 * chat gate — every number in the report has to be a VALUE OF A ROW of this run,
 * not merely present in something cited. The badge is absent when the run did
 * not record a count, rather than defaulting to a reassuring one.
 */
export function Briefing({ report, checked }: {
  report: DailyReport;
  checked: number | null;
}) {
  const parts: [string, string | null][] = [
    ["Key movements", report.key_movements],
    ["What explained the day", report.factor_explanation],
    ["The warnings", report.risk_alert_explanation],
    ["What to consider", report.recommended_actions],
  ];
  return (
    <section className="rounded-lg border border-[#21262d] bg-[#11161d]">
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-[#21262d] flex-wrap">
        <h3 className="text-sm font-medium text-slate-200">Daily briefing</h3>
        {checked != null && (
          <span title="Every number in this report was matched to a value of a row of this run before it was stored. A report that failed is not written at all."
            className="inline-flex items-center gap-1.5 font-mono text-[10.5px] tracking-wide text-teal-300 border border-teal-800/60 bg-teal-950/40 rounded px-2 py-0.5">
            <span aria-hidden className="font-semibold">✓</span>
            {checked} figure{checked === 1 ? "" : "s"} checked against this run
          </span>
        )}
        <AuditOnly>
          <span className="ml-auto font-mono text-[10px] text-slate-600">
            {report.id} · {report.llm_model ?? "model not recorded"} · {report.agent_mode}
          </span>
        </AuditOnly>
      </header>
      <div className="px-4 py-3 text-[12.5px] leading-relaxed text-slate-300">
        {report.executive_summary && (
          <p className="whitespace-pre-wrap">{report.executive_summary}</p>
        )}
        <details className="mt-3 group">
          <summary className="cursor-pointer list-none text-[11.5px] text-slate-500 hover:text-slate-300 select-none">
            <span aria-hidden className="font-mono mr-1 group-open:hidden">▸</span>
            <span aria-hidden className="font-mono mr-1 hidden group-open:inline">▾</span>
            Full briefing
          </summary>
          <div className="mt-2 flex flex-col gap-3">
            {parts.filter(([, body]) => body).map(([title, body]) => (
              <div key={title}>
                <h4 className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{title}</h4>
                <p className="whitespace-pre-wrap">{body}</p>
              </div>
            ))}
          </div>
        </details>
      </div>
    </section>
  );
}

// ── the run, folded away ─────────────────────────────────────────────────────

/**
 * What the run did, at the bottom and closed.
 *
 * This was the middle third of the screen: a live step list that appeared while
 * a run was working and vanished when it finished, so the one moment a reader
 * might ask "how was this produced" was the one moment there was nothing to
 * look at. It is a record now, and it stays.
 */
export function RunRail({ run }: { run: ExposureRun }) {
  const events = run.workflow_events ?? [];
  const steps = collapseSteps(events);
  const done = steps.filter((e) => e.status !== "running");
  const failed = steps.find((e) => e.status === "failed");
  const seconds = run.started_at && run.completed_at
    ? Math.round((Date.parse(run.completed_at) - Date.parse(run.started_at)) / 1000)
    : null;

  return (
    <section className="rounded-lg border border-[#21262d] bg-[#11161d]">
      <details>
        <summary className="cursor-pointer list-none px-4 py-2.5 flex items-center gap-2 text-[11.5px] text-slate-500 select-none">
          {run.status === "completed"
            ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
            : <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />}
          <span className="text-slate-400">
            {run.status === "completed" ? "Updated" : `Run ${run.status}`}
            {run.completed_at ? ` ${formatDateTime(run.completed_at)}` : ""}
          </span>
          {seconds != null && <span>· {seconds}s</span>}
          <span>· {done.length} steps</span>
          <span className="ml-auto font-mono">show steps ▸</span>
        </summary>
        <div className="px-4 pb-3 border-t border-[#21262d] pt-2">
          {failed && (
            <p className="mb-2 text-[12px] text-amber-400">
              {explainRunError(failed.error?.code, failed.message)}
            </p>
          )}
          <ol className="flex flex-col gap-1 text-[11.5px] text-slate-400">
            {done.map((e) => (
              <li key={e.id} className="flex items-baseline gap-2">
                <span className={`flex-1 ${e.status === "failed" ? "text-amber-400" : ""}`}>
                  {stepPhrase(e)}
                </span>
                {e.duration_ms != null && (
                  <span className="font-mono text-[10px] text-slate-600 tabular-nums">
                    {formatDuration(e.duration_ms)}
                  </span>
                )}
              </li>
            ))}
          </ol>
          <AuditOnly>
            <div className="mt-3 pt-2 border-t border-[#21262d] font-mono text-[10px] text-slate-600 break-all">
              {run.id} · {run.task_id ?? "no task"} · {run.triggered_by ?? "unrecorded"}
              <ul className="mt-1 flex flex-col gap-0.5">
                {events.map((e) => (
                  <li key={`a-${e.id}`}>
                    {e.step_name} · {e.status}
                    {Object.keys(e.payload_summary ?? {}).length > 0
                      ? ` · ${JSON.stringify(e.payload_summary).slice(0, 160)}`
                      : ""}
                  </li>
                ))}
              </ul>
            </div>
          </AuditOnly>
        </div>
      </details>
    </section>
  );
}

/** What `check_limits` and `generate_report` recorded, read from the run rather
 *  than recomputed — one place decides, and it is the place that did the work. */
export function readStepFacts(events: WorkflowEvent[]) {
  const of = (name: string) =>
    events.filter((e) => e.step_name === name && Object.keys(e.payload_summary ?? {}).length > 0).pop();
  const limits = of("check_limits")?.payload_summary as
    { evaluated?: string[]; inert_overrides?: string[] } | undefined;
  const report = of("generate_report")?.payload_summary as { numbers_checked?: number } | undefined;
  return {
    evaluated: Array.isArray(limits?.evaluated) ? limits.evaluated.length : null,
    // A threshold set on a sector or issuer this book does not hold, so the run
    // never consulted it. Not an error — the desk may be holding it for a
    // position it plans to take — but a limit that silently does nothing is
    // exactly the thing a mandate page must not let pass for one that ran.
    inertOverrides: Array.isArray(limits?.inert_overrides) ? limits.inert_overrides : [],
    numbersChecked: typeof report?.numbers_checked === "number" ? report.numbers_checked : null,
  };
}
