"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Markdown from "react-markdown";
import {
  Activity, BarChart3, AlertTriangle, CheckCircle2, Loader2,
  ShieldAlert, FileText, ChevronDown, ChevronUp, Search, Plus,
  Copy, Upload,
} from "lucide-react";
import { ChatPanel } from "./components/ChatPanel";
import { RunTimeline } from "./components/RunTimeline";
import { EvidenceDrawer } from "./components/Evidence";
import { AuthControls, AuthGate, SignedInProbe } from "./components/Auth";
import { PortfolioModal } from "./components/PortfolioModal";
import type {
  Portfolio, ExposureRun, ExposureRunSummary, Position, RiskAlert,
  FactorAttribution, ExposureMetrics, SectorExposure, IssuerExposure,
  WorkflowEvent,
} from "@/lib/types";
import {
  listPortfolios, getPositions, createRun, getRun, listRuns, cloneDemoPortfolio,
} from "@/lib/api";
import { explainApiError } from "@/lib/errors";
import {
  formatCurrency, formatDate, formatDateTime,
  statusBg,
} from "@/lib/formatting";

// ─── Utility formatters ────────────────────────────────────────────────────────

const fPct = (v: number | null | undefined, dec = 2) =>
  v == null ? "—" : `${(v * 100).toFixed(dec)}%`;

const fSign = (v: number | null | undefined) => {
  if (v == null) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${formatCurrency(v)}`;
};

const fSignPct = (v: number | null | undefined, dec = 2) => {
  if (v == null) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${(v * 100).toFixed(dec)}%`;
};

// ─── Step icon ──────────────────────────────────────────────────────────────

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${statusBg(status)}`}>
      {status === "running" && <Loader2 className="w-3 h-3 animate-spin" />}
      {status}
    </span>
  );
}

// ─── KPI card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, highlight,
}: {
  label: string; value: string; sub?: string; highlight?: "green" | "red" | "neutral";
}) {
  const valueColor =
    highlight === "green" ? "text-emerald-400" :
    highlight === "red"   ? "text-red-400" :
    "text-[#e6edf3]";
  return (
    <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
      <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-lg font-semibold leading-tight ${valueColor}`}>{value}</p>
      {sub && <p className="text-[10px] text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

// ─── Severity badge ───────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const cls = severity === "breach"
    ? "bg-red-500/10 text-red-400 ring-red-500/20"
    : "bg-amber-500/10 text-amber-400 ring-amber-500/20";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${cls}`}>
      {severity === "breach" ? <AlertTriangle className="w-2.5 h-2.5" /> : <ShieldAlert className="w-2.5 h-2.5" />}
      {severity.toUpperCase()}
    </span>
  );
}

// ─── First-run card ─────────────────────────────────────────────────────────

/**
 * The way in, for someone who has just signed up (V7-U2).
 *
 * The list a new account sees is never empty — RLS answers "mine plus public",
 * so the shared demo book is always in it — which made the left panel look like
 * a populated desk and left no place to say "start here". The one action that
 * gets a stranger to their own data in a single click, cloning the demo, was
 * reachable only from inside the New-portfolio modal, behind a `+` labelled for
 * someone who already knows what they want.
 */
function FirstRunCard({
  onCreated, onUploadCsv, prompt,
}: {
  onCreated: (p: Portfolio) => void;
  onUploadCsv: () => void;
  /** The sentence above the buttons; null where the surrounding copy said it. */
  prompt?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const clone = async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    try {
      onCreated(await cloneDemoPortfolio());
    } catch (e) {
      // Shown, not logged and forgotten. This is the single action the card
      // exists for, and a button that quietly does nothing is a worse first
      // minute than the bare list it replaced. The wording — quota with its
      // numbers, "sign in" on a 401 — is already decided in lib/errors.ts.
      setNotice(explainApiError(e).notice);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="m-2 rounded-lg border border-dashed border-[#30363d] bg-[#161b22] p-3">
      {prompt !== null && (
        <p className="text-[11px] text-slate-400 leading-relaxed">
          {prompt ?? <>Nothing here is yours yet — the book below is the shared demo. Take a copy of it, or bring your own holdings.</>}
        </p>
      )}
      <div className={`${prompt === null ? "" : "mt-3"} space-y-1.5`}>
        <button
          onClick={clone}
          disabled={busy}
          className="w-full flex items-center justify-center gap-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-medium py-1.5 rounded-md transition-colors"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Copy className="w-3.5 h-3.5" />}
          Clone demo
        </button>
        <button
          onClick={onUploadCsv}
          className="w-full flex items-center justify-center gap-1.5 border border-[#30363d] hover:bg-white/5 text-slate-300 text-xs py-1.5 rounded-md transition-colors"
        >
          <Upload className="w-3.5 h-3.5" /> Upload CSV
        </button>
      </div>
      {notice && <p className="mt-2 text-[10px] text-amber-400 leading-snug">{notice}</p>}
    </div>
  );
}

// ─── Left panel ─────────────────────────────────────────────────────────────

function LeftPanel({
  portfolios, selectedPortfolioId, onSelectPortfolio,
  runs, selectedRunId, onSelectRun, onPortfolioCreated,
  showFirstRunCard, setModalOpen,
}: {
  /** True only while the empty desk is being explained somewhere ELSE than here. */
  showFirstRunCard: boolean;
  /** Opening only. The dialog itself belongs to Home, which has two callers. */
  setModalOpen: (v: boolean) => void;
  portfolios: Portfolio[];
  selectedPortfolioId: string | null;
  onSelectPortfolio: (id: string) => void;
  runs: ExposureRunSummary[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
  onPortfolioCreated: (p: Portfolio) => void;
}) {
  return (
    <aside className="w-56 flex-shrink-0 border-r border-[#21262d] flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-[#21262d]">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-blue-400" />
          <span className="text-xs font-semibold text-slate-300">Portfolios</span>
          <button
            onClick={() => setModalOpen(true)}
            title="New portfolio"
            className="ml-auto text-slate-400 hover:text-slate-200 flex items-center"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {/* Only while the main panel is showing something else. An empty desk is
            explained in the centre now, where the eye already is; repeating the
            same two buttons in the sidebar at the same moment would be one
            prompt too many. It comes back the moment the reader clicks into the
            shared demo to look around — that is exactly when they need a way to
            take a copy, and the centre is no longer free to offer it.

            AuthGate, not a portfolios check: an anonymous visitor cannot own a
            book, so telling them their desk is empty would be nonsense, and the
            shop-window stays exactly what it is today. */}
        <AuthGate fallback={null}>
          {showFirstRunCard && (
            <FirstRunCard
              onCreated={onPortfolioCreated}
              onUploadCsv={() => setModalOpen(true)}
            />
          )}
        </AuthGate>

        {/* Portfolio list */}
        <div className="p-2">
          {portfolios.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelectPortfolio(p.id)}
              className={`w-full text-left px-3 py-2 rounded-md text-xs transition-colors mb-0.5 ${
                selectedPortfolioId === p.id
                  ? "bg-blue-600/20 text-blue-300 ring-1 ring-blue-500/30"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-300"
              }`}
            >
              <p className="font-medium truncate">{p.name}</p>
              <p className="text-[10px] opacity-60 mt-0.5">{p.currency} · {p.benchmark ?? "—"}</p>
            </button>
          ))}
        </div>

        {/* Run list */}
        {runs.length > 0 && (
          <>
            <div className="px-4 py-2 border-t border-[#21262d]">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">Recent Runs</p>
            </div>
            <div className="p-2 space-y-0.5">
              {runs.slice(0, 8).map((r) => (
                <button
                  key={r.id}
                  onClick={() => onSelectRun(r.id)}
                  className={`w-full text-left px-3 py-2 rounded-md text-xs transition-colors ${
                    selectedRunId === r.id
                      ? "bg-slate-700/40 ring-1 ring-slate-600/50"
                      : "hover:bg-white/5"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-slate-400 font-mono text-[10px] truncate">{formatDate(r.as_of_date)}</span>
                    <StatusBadge status={r.status} />
                  </div>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

// ─── What a run actually evaluated ──────────────────────────────────────────

/**
 * The last event a step wrote, or null if the step is not in this run.
 *
 * Last, not first: a step writes one event on entry — necessarily with an empty
 * payload, since the body has not run — and another on exit carrying what it
 * decided. Taking the first would render an empty payload forever.
 */
function stepPayload(
  events: WorkflowEvent[],
  stepName: string,
): Record<string, unknown> | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].step_name === stepName) return events[i].payload_summary;
  }
  return null;
}

/**
 * What ran, beside what it found (V7-U4).
 *
 * check_limits returns the (check, entity) pairs it evaluated and calculate_risk
 * records the scenarios it could not propagate a shock through; both have been
 * in workflow_events.payload_summary since V5 and neither had ever reached a
 * screen. Until now a check that never ran rendered identically to a check that
 * passed — underneath a green "All limits within bounds", which is the strongest
 * claim this product makes anywhere. `factors_held_flat` is the quieter half of
 * the same defect: market_downside says nothing about HYG, so HYG is held at
 * zero, and on the live book the beta to HYG is 1.29. That is an assertion about
 * the world, not an absence of one, and it used to vanish between the engine and
 * the page.
 */
function RunCoverage({ events }: { events: WorkflowEvent[] }) {
  const limits = stepPayload(events, "check_limits");
  const risk = stepPayload(events, "calculate_risk");

  // A run whose steps recorded nothing is a run that cannot answer this
  // question, and saying so is the whole point of the line: staying silent
  // about coverage is precisely the behaviour being removed here.
  if (limits === null && risk === null) {
    return <p className="px-1 text-[10px] text-slate-600">This run did not record what it evaluated.</p>;
  }

  const evaluated = (limits?.evaluated ?? []) as string[];
  const inert = (limits?.inert_overrides ?? []) as string[];
  const unevaluated = (risk?.scenarios_unevaluated ?? []) as { name: string; reason: string }[];
  const scenarios = (risk?.scenarios_evaluated ?? {}) as Record<string, { factors_held_flat: string[] }>;
  const heldFlat = Object.entries(scenarios).filter(([, s]) => s.factors_held_flat?.length > 0);

  return (
    <div className="px-1 space-y-1">
      <p className="text-[10px] text-slate-500">
        {evaluated.length} limit check{evaluated.length === 1 ? "" : "s"} evaluated
        {inert.length > 0 && (
          // A threshold the desk set on a name this book does not hold. Not an
          // error — they may be holding it for a position they plan to take —
          // but a limit that cannot fire, and the names belong on hover rather
          // than in a line that has to stay glanceable.
          <span title={inert.join("\n")}>
            {" · "}{inert.length} override{inert.length === 1 ? "" : "s"} inert
          </span>
        )}
      </p>
      {unevaluated.map((u) => (
        <p key={u.name} className="text-[10px] text-amber-500/70 leading-snug">
          {u.name.replace(/_/g, " ")} not evaluated — {u.reason}
        </p>
      ))}
      {heldFlat.map(([name, s]) => (
        <p key={name} className="text-[10px] text-slate-500 leading-snug">
          {name.replace(/_/g, " ")} holds {s.factors_held_flat.join(", ")} flat
        </p>
      ))}
    </div>
  );
}

// ─── Middle panel — workflow runner ─────────────────────────────────────────

function MiddlePanel({
  selectedPortfolio, run, onRunUpdate,
}: {
  selectedPortfolio: Portfolio | null;
  run: ExposureRun | null;
  onRunUpdate: (run: ExposureRun) => void;
}) {
  const [launching, setLaunching] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [fullReportOpen, setFullReportOpen] = useState(false);

  const handleRunUpdate = async () => {
    if (!selectedPortfolio || launching) return;
    setLaunching(true);
    try {
      // No date: the browser's idea of "today" is not the market's. The server
      // reports on the last completed session, which before the close is
      // yesterday — asking for today would compare a bar against itself.
      // POST returns the full run (empty events until the worker fills it in) —
      // hand it straight up; polling on selectedRunId takes over from there.
      const created = await createRun(selectedPortfolio.id);
      onRunUpdate(created);
    } catch (e) {
      console.error("Failed to create run:", e);
    } finally {
      setLaunching(false);
    }
  };

  const report = run?.daily_report;

  // V6-G's verdict on the report below, taken from the step that produced it.
  // Not a pass/fail indicator: the gate raises rather than persisting, so a
  // report that exists has already passed. What this number adds is the SIZE of
  // the check standing behind text the reader is being asked to open.
  const gate = run ? stepPayload(run.workflow_events, "generate_report") : null;
  const numbersChecked = typeof gate?.numbers_checked === "number" ? gate.numbers_checked : null;

  const alerts = run?.risk_alerts ?? [];
  const breachCount = alerts.filter(a => a.severity === "breach").length;
  const warnCount = alerts.filter(a => a.severity === "warning").length;

  return (
    <div className="w-80 flex-shrink-0 border-r border-[#21262d] flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-[#21262d] flex items-center justify-between">
        <span className="text-sm font-semibold text-[#e6edf3]">Workflow</span>
        {run && <StatusBadge status={run.status} />}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Run action */}
        <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
          <p className="text-xs text-slate-400 mb-3">
            {selectedPortfolio ? selectedPortfolio.name : "Select a portfolio to begin"}
          </p>
          <button
            onClick={handleRunUpdate}
            disabled={!selectedPortfolio || launching}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium py-2 px-3 rounded-md transition-colors"
          >
            {launching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
            Run Daily Update
          </button>
        </div>

        {/* Alert summary */}
        {run?.status === "completed" && (alerts.length > 0 ? (
          <div className={`rounded-lg border p-3 ${breachCount > 0 ? "bg-red-900/10 border-red-500/30" : "bg-amber-900/10 border-amber-500/30"}`}>
            <div className="flex items-center gap-2">
              <AlertTriangle className={`w-4 h-4 ${breachCount > 0 ? "text-red-400" : "text-amber-400"}`} />
              <p className="text-xs font-medium text-slate-300">Risk Alerts</p>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              {breachCount > 0 && <span className="text-red-400">{breachCount} breach{breachCount > 1 ? "es" : ""}</span>}
              {breachCount > 0 && warnCount > 0 && " · "}
              {warnCount > 0 && <span className="text-amber-400">{warnCount} warning{warnCount > 1 ? "s" : ""}</span>}
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-900/10 p-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <p className="text-xs font-medium text-emerald-300">All limits within bounds</p>
            </div>
          </div>
        ))}

        {/* Coverage sits directly under the alert summary and deliberately is
            NOT a fourth bordered card: it is a footnote on the sentence above it
            ("2 breaches", "All limits within bounds"), and a caveat only reads
            as one when it is against the claim it qualifies. Boxed, it would
            compete with the alerts for the same glance and lose — which is the
            same way it lost as a database column nobody rendered. Muted grey for
            what ran, amber only for what did not. */}
        {run?.status === "completed" && <RunCoverage events={run.workflow_events} />}

        {/* Workflow timeline */}
        {run && (
          <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold text-slate-300">Pipeline</p>
              <span className="text-[10px] text-slate-500">{formatDate(run.as_of_date)}</span>
            </div>
            <RunTimeline events={run.workflow_events} />
          </div>
        )}

        {/* Agent briefing */}
        {report && (
          <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
            <button
              onClick={() => setReportOpen(!reportOpen)}
              className="w-full flex items-center justify-between"
            >
              <div className="flex items-center gap-2">
                <FileText className="w-3.5 h-3.5 text-purple-400" />
                <span className="text-xs font-semibold text-slate-300">Agent Briefing</span>
              </div>
              {reportOpen ? <ChevronUp className="w-3 h-3 text-slate-500" /> : <ChevronDown className="w-3 h-3 text-slate-500" />}
            </button>

            {report.executive_summary && (
              <p className="text-xs text-slate-400 mt-3 leading-relaxed line-clamp-4">
                {report.executive_summary}
              </p>
            )}

            {reportOpen && (
              <div className="mt-3 space-y-3 border-t border-[#21262d] pt-3">
                {report.key_movements && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Key Movements</p>
                    <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{report.key_movements}</p>
                  </div>
                )}
                {/* V7-U5. Written by the agent, checked by the V6-G gate, and
                    until now stored and never shown — the two fields that say
                    WHY the factor and alert numbers on the right-hand panel are
                    what they are. Ordered as the agent produces them: what
                    happened, then why, then what to do about it. */}
                {report.factor_explanation && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Factor Explanation</p>
                    <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{report.factor_explanation}</p>
                  </div>
                )}
                {report.risk_alert_explanation && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Risk Alert Explanation</p>
                    <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{report.risk_alert_explanation}</p>
                  </div>
                )}
                {report.recommended_actions && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Recommended Actions</p>
                    <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{report.recommended_actions}</p>
                  </div>
                )}

                {/* Collapsed by default, unlike the briefing that contains it.
                    markdown_report is the long form of the five fields already
                    on this card, in a 320px column: opening it by default would
                    push the model line, the mock-mode warning and the entire run
                    details panel below the fold on every completed run, to show
                    a reader something they already have in summary two inches
                    higher up. The count on the toggle is what makes it worth
                    opening while it is shut — that text is the only thing here
                    every number of which was matched against this run's own
                    rows. */}
                {report.markdown_report && (
                  <div>
                    <button
                      onClick={() => setFullReportOpen(!fullReportOpen)}
                      className="w-full flex items-center gap-1.5 text-[10px] text-slate-500 uppercase tracking-wider hover:text-slate-300"
                    >
                      {fullReportOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      Full report
                      {numbersChecked != null && (
                        <span className="ml-auto normal-case tracking-normal text-slate-600">
                          {numbersChecked} numbers checked against this run
                        </span>
                      )}
                    </button>
                    {fullReportOpen && (
                      // react-markdown 10 escapes raw HTML and never touches
                      // dangerouslySetInnerHTML, and no rehype plugin is passed
                      // here, so there is nothing for a sanitiser to do. The
                      // child selectors put back what Tailwind's preflight
                      // strips — without them every heading and list arrives as
                      // undifferentiated body text, and structure is most of
                      // what makes a long report readable in a narrow column.
                      <div className="mt-2 text-xs text-slate-400 leading-relaxed space-y-2 overflow-x-auto [&_h1]:text-slate-200 [&_h1]:font-semibold [&_h2]:text-slate-200 [&_h2]:font-semibold [&_h3]:text-slate-300 [&_h3]:font-medium [&_strong]:text-slate-200 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_code]:font-mono [&_code]:text-slate-300 [&_table]:w-full [&_th]:text-left [&_th]:text-slate-500 [&_th]:font-medium [&_td]:py-0.5">
                        <Markdown>{report.markdown_report}</Markdown>
                      </div>
                    )}
                  </div>
                )}

                {report.llm_model && (
                  <p className="text-[10px] text-slate-600">Model: {report.llm_model}</p>
                )}
                {Boolean((report.confidence_flags as Record<string, unknown>)?.mock_mode) && (
                  <p className="text-[10px] text-amber-600">⚠ Mock mode — configure OPENAI_API_KEY for full LLM reports</p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Run details */}
        {run && (
          <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4 space-y-2">
            <p className="text-xs font-semibold text-slate-300 mb-2">Run Details</p>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Run ID</span>
              <span className="text-slate-300 font-mono text-[10px]">{run.id}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Triggered</span>
              <span className="text-slate-300">{run.triggered_by}</span>
            </div>
            {run.started_at && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Started</span>
                <span className="text-slate-300">{formatDateTime(run.started_at)}</span>
              </div>
            )}
            {run.completed_at && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Completed</span>
                <span className="text-slate-300">{formatDateTime(run.completed_at)}</span>
              </div>
            )}
            {run.error_message && (
              <p className="text-xs text-red-400 mt-2 break-words">{run.error_message}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Right panel — dashboard ─────────────────────────────────────────────────

function RightPanel({
  portfolio, positions, run, firstRun, onCloned, onUploadCsv,
}: {
  firstRun: boolean;
  onCloned: (p: Portfolio) => void;
  onUploadCsv: () => void;
  portfolio: Portfolio | null;
  positions: Position[];
  run: ExposureRun | null;
}) {
  const metrics: ExposureMetrics | null = run?.metrics ?? null;
  const sectorExposures: SectorExposure[] = run?.sector_exposures ?? [];
  const issuerExposures: IssuerExposure[] = run?.issuer_exposures ?? [];
  const factorAttributions: FactorAttribution[] = run?.factor_attributions ?? [];
  const alerts: RiskAlert[] = run?.risk_alerts ?? [];

  // A KPI is coloured by what the limit engine DECIDED about it, never by a
  // threshold written here. Each card used to carry its own copy of the seed
  // defaults — VaR red above 3.5%, vol red above 25% — which made this file a
  // fourth source of thresholds behind risk_limits, the LimitBook and the seed,
  // and a stale one: a desk that overrides a limit on its own portfolio still
  // saw colours computed from someone else's numbers.
  // `value` is required, and green means "checked and inside the limit". A metric
  // the run could not compute — too few observations leaves var_95_1d null — has
  // no alert either, and colouring THAT green would say the check passed when it
  // never ran. Absence of an alert is only good news when there was a number to
  // judge.
  const alertHighlight = (
    alertType: string,
    value: number | null | undefined,
  ): "red" | "neutral" | "green" => {
    if (value == null) return "neutral";
    const hit = alerts.filter(a => a.alert_type === alertType);
    if (hit.some(a => a.severity === "breach")) return "red";
    if (hit.length > 0) return "neutral";
    return "green";
  };

  // Fallback for sector/issuer when no run yet
  const totalMV = positions.reduce((s, p) => s + (p.market_value ?? 0), 0);
  const fallbackSectors = Object.entries(
    positions.reduce<Record<string, number>>((acc, p) => {
      const s = p.sector ?? "Other";
      acc[s] = (acc[s] ?? 0) + (p.market_value ?? 0);
      return acc;
    }, {})
  ).sort((a, b) => b[1] - a[1]);

  const hasMetrics = metrics != null;
  const pnlPositive = (metrics?.daily_pnl ?? 0) >= 0;

  if (!portfolio) {
    // Two different empties, and they must not look alike. "Pick one" is only
    // useful advice when there IS one; for an account that owns nothing it is
    // an instruction with no object, and the reader is left to guess whether
    // something failed to load. So the first-run case says what is true — the
    // desk is empty — and carries the two actions that end it.
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        {firstRun ? (
          <div className="max-w-sm w-full text-center">
            <BarChart3 className="w-12 h-12 text-slate-700 mx-auto mb-4" />
            <p className="text-slate-300 text-sm font-medium">Your desk is empty</p>
            <p className="text-slate-500 text-xs mt-2 leading-relaxed">
              Take a copy of the shared demo book to see the whole workflow on real
              holdings, or upload your own. Either way the numbers on this screen
              will be yours.
            </p>
            <div className="mt-5 text-left">
              <FirstRunCard onCreated={onCloned} onUploadCsv={onUploadCsv} prompt={null} />
            </div>
          </div>
        ) : (
          <div className="text-center">
            <BarChart3 className="w-12 h-12 text-slate-700 mx-auto mb-3" />
            <p className="text-slate-500 text-sm">Select a portfolio to view the dashboard</p>
          </div>
        )}
      </div>
    );
  }

  const displayMV = metrics?.portfolio_market_value ?? totalMV;

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[#e6edf3]">{portfolio.name}</h1>
          <p className="text-xs text-slate-500 mt-0.5">{portfolio.currency} · {portfolio.benchmark ?? "No benchmark"}</p>
        </div>
        {run && (
          <div className="text-right">
            <StatusBadge status={run.status} />
            <p className="text-[10px] text-slate-500 mt-1">{formatDate(run.as_of_date)}</p>
          </div>
        )}
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-3 gap-3">
        <KpiCard
          label="Portfolio Value"
          value={formatCurrency(displayMV)}
          sub={hasMetrics ? `Gross: ${fPct(metrics?.gross_exposure_pct)} of NAV` : "Market value"}
        />
        <KpiCard
          label="Daily P&L"
          value={hasMetrics ? fSign(metrics!.daily_pnl) : "—"}
          sub={hasMetrics ? fSignPct(metrics!.daily_return) : "Run to compute"}
          highlight={hasMetrics ? (pnlPositive ? "green" : "red") : "neutral"}
        />
        <KpiCard
          label="VaR (95%, 1d)"
          value={hasMetrics ? fPct(metrics!.var_95_1d) : "—"}
          sub={hasMetrics ? `ES: ${fPct(metrics!.expected_shortfall_95)}` : "Run to compute"}
          highlight={alertHighlight("var_95", metrics?.var_95_1d)}
        />
        <KpiCard
          label="30d Volatility"
          value={hasMetrics ? fPct(metrics!.rolling_vol_30d) : "—"}
          sub={hasMetrics ? `60d: ${fPct(metrics!.rolling_vol_60d)}` : "Annualised"}
          highlight={alertHighlight("rolling_volatility_30d", metrics?.rolling_vol_30d)}
        />
        <KpiCard
          label="Max Drawdown"
          value={hasMetrics ? fPct(metrics!.max_drawdown) : "—"}
          sub="Worst fall from a peak, over the whole loaded window"
          /* No highlight: max drawdown is not one of the eight limit checks, so
             nothing has judged it and this card must not appear to have. The
             threshold that used to live here — red above 10% — was also a copy
             of a number the portfolio's own risk_limits rows are supposed to be
             the only source of, and it would now fire on every book: over a
             three-year window this book's drawdown is 17.7%, where over three
             months it was 5.9%. */
        />
        <KpiCard
          label="Positions"
          value={String(positions.length)}
          sub="Active holdings"
        />
      </div>

      {/* Risk alerts */}
      {alerts.length > 0 && (
        <div className="rounded-lg bg-[#161b22] border border-[#21262d] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#21262d] flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
            <p className="text-xs font-semibold text-slate-300">Risk Alerts</p>
            <span className="ml-auto text-[10px] text-slate-500">{alerts.length} total</span>
          </div>
          <div className="divide-y divide-[#21262d]">
            {alerts.map((alert) => (
              <div key={alert.id} className="px-4 py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs text-slate-300 leading-snug">{alert.message}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">
                    {alert.entity_type} · {alert.alert_type}
                    {alert.utilization != null && ` · ${(alert.utilization * 100).toFixed(0)}% of limit`}
                  </p>
                </div>
                <SeverityBadge severity={alert.severity} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sector exposure */}
      <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
        <p className="text-xs font-semibold text-slate-300 mb-4">Sector Exposure</p>
        <div className="space-y-3">
          {(sectorExposures.length > 0
            ? sectorExposures.map(se => ({
                sector: se.sector,
                weight: se.weight ?? 0,
                change: se.weight_change,
              }))
            : fallbackSectors.map(([sector, mv]) => ({
                sector,
                weight: totalMV > 0 ? mv / totalMV : 0,
                change: null,
              }))
          )
            .sort((a, b) => b.weight - a.weight)
            .map(({ sector, weight, change }) => (
              <div key={sector}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">{sector.replace(/_/g, " ")}</span>
                  <div className="flex items-center gap-2">
                    {change != null && Math.abs(change) > 0.001 && (
                      <span className={`text-[10px] ${change >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                        {change >= 0 ? "▲" : "▼"}{Math.abs(change * 100).toFixed(1)}%
                      </span>
                    )}
                    <span className="text-slate-300 font-medium">{fPct(weight)}</span>
                  </div>
                </div>
                <div className="h-1.5 bg-[#21262d] rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${
                      weight > 0.50 ? "bg-red-500" : weight > 0.40 ? "bg-amber-500" : "bg-blue-500"
                    }`}
                    style={{ width: `${Math.min(weight * 100, 100)}%` }}
                  />
                </div>
              </div>
            ))}
        </div>
      </div>

      {/* Issuer / holdings table */}
      {(issuerExposures.length > 0 || positions.length > 0) && (
        <div className="rounded-lg bg-[#161b22] border border-[#21262d] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#21262d]">
            <p className="text-xs font-semibold text-slate-300">Holdings</p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#21262d]">
                <th className="text-left px-4 py-2 text-slate-500 font-medium">Ticker</th>
                <th className="text-left px-4 py-2 text-slate-500 font-medium">Sector</th>
                <th className="text-right px-4 py-2 text-slate-500 font-medium">Market Value</th>
                <th className="text-right px-4 py-2 text-slate-500 font-medium">Weight</th>
                {issuerExposures.length > 0 && (
                  <th className="text-right px-4 py-2 text-slate-500 font-medium">Daily P&L</th>
                )}
              </tr>
            </thead>
            <tbody>
              {issuerExposures.length > 0
                ? issuerExposures
                    .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
                    .map((ie) => (
                      <tr key={ie.ticker} className="border-b border-[#21262d]/50 hover:bg-white/2 transition-colors group">
                        <td className="px-4 py-2 font-semibold text-slate-200">
                          {/* V7-U3: the book being looked at travels with the
                              ticker, so the research run is attributed to it.
                              The issuer page used to hardcode the demo's id,
                              which filed every signed-in user's research under
                              someone else's portfolio. */}
                          <Link href={`/issuer/${ie.ticker}?portfolio=${portfolio.id}`} className="inline-flex items-center gap-1 hover:text-sky-400" title="Investigate issuer">
                            {ie.ticker}<Search className="w-3 h-3 opacity-0 group-hover:opacity-60" />
                          </Link>
                        </td>
                        <td className="px-4 py-2 text-slate-400">{ie.sector?.replace(/_/g, " ") ?? "—"}</td>
                        <td className="px-4 py-2 text-right text-slate-200 font-medium">{formatCurrency(ie.market_value)}</td>
                        <td className="px-4 py-2 text-right text-slate-400">{fPct(ie.weight)}</td>
                        <td className={`px-4 py-2 text-right font-medium ${(ie.daily_pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {ie.daily_pnl != null ? fSign(ie.daily_pnl) : "—"}
                        </td>
                      </tr>
                    ))
                : positions
                    .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
                    .map((pos) => {
                      const w = displayMV > 0 ? (pos.market_value ?? 0) / displayMV : 0;
                      return (
                        <tr key={pos.id} className="border-b border-[#21262d]/50 hover:bg-white/2 transition-colors group">
                          <td className="px-4 py-2 font-semibold text-slate-200">
                            <Link href={`/issuer/${pos.ticker}?portfolio=${portfolio.id}`} className="inline-flex items-center gap-1 hover:text-sky-400" title="Investigate issuer">
                              {pos.ticker}<Search className="w-3 h-3 opacity-0 group-hover:opacity-60" />
                            </Link>
                          </td>
                          <td className="px-4 py-2 text-slate-400">{pos.sector?.replace(/_/g, " ") ?? "—"}</td>
                          <td className="px-4 py-2 text-right text-slate-200 font-medium">{formatCurrency(pos.market_value)}</td>
                          <td className="px-4 py-2 text-right text-slate-400">{fPct(w)}</td>
                        </tr>
                      );
                    })}
            </tbody>
          </table>
        </div>
      )}

      {/* Factor attribution */}
      {factorAttributions.length > 0 && (
        <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
          <p className="text-xs font-semibold text-slate-300 mb-4">Factor Attribution</p>
          <div className="space-y-3">
            {factorAttributions.slice(0, 6).map((fa) => {
              const contrib = fa.contribution ?? 0;
              const absMax = Math.max(...factorAttributions.map(f => Math.abs(f.contribution ?? 0)));
              const barPct = absMax > 0 ? (Math.abs(contrib) / absMax) * 100 : 0;
              return (
                <div key={fa.factor_name}>
                  <div className="flex justify-between text-xs mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400 capitalize">{fa.factor_name.replace(/_/g, " ")}</span>
                      <span className="text-[10px] text-slate-600">β={fa.beta?.toFixed(2) ?? "—"}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-slate-500">
                        R²={fa.r_squared?.toFixed(2) ?? "—"}
                      </span>
                      <span className={`font-medium ${contrib >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {fSignPct(contrib, 3)}
                      </span>
                    </div>
                  </div>
                  <div className="h-1 bg-[#21262d] rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${contrib >= 0 ? "bg-emerald-500/60" : "bg-red-500/60"}`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Stress scenarios (from metrics) */}
      {hasMetrics && metrics!.stress_loss_tech != null && (
        <div className="rounded-lg bg-[#161b22] border border-[#21262d] p-4">
          <p className="text-xs font-semibold text-slate-300 mb-4">Stress Scenarios</p>
          <div className="space-y-2">
            {[
              { name: "Tech Selloff", value: metrics!.stress_loss_tech },
              { name: "Rates Shock Up", value: metrics!.stress_loss_rates },
              { name: "Credit Spread Widening", value: metrics!.stress_loss_credit },
              { name: "Market Downside", value: metrics!.stress_loss_market },
            ]
              .filter(s => s.value != null)
              .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
              .map(({ name, value }) => {
                const loss = value ?? 0;
                const breach = loss > 0.08;
                const warn = loss > 0.06;
                return (
                  <div key={name} className="flex items-center justify-between text-xs py-1.5">
                    <span className="text-slate-400">{name}</span>
                    <span className={`font-medium ${breach ? "text-red-400" : warn ? "text-amber-400" : "text-slate-300"}`}>
                      −{fPct(loss)}
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* Prompt to run */}
      {!run && positions.length > 0 && (
        <div className="rounded-lg bg-[#161b22] border border-[#30363d] border-dashed p-6 text-center">
          <Activity className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-sm text-slate-500">Run a Daily Update to see risk metrics and analytics</p>
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  // The reader's explicit choice, and only that. What is actually shown is
  // derived below: null here means "has not chosen", which is a different thing
  // from "nothing is open".
  const [chosenPortfolioId, setChosenPortfolioId] = useState<string | null>(null);
  // null until the probe reports: "not known yet" and "signed out" must stay
  // distinguishable, see the selection effect below.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  // Lifted out of the sidebar: the main panel's first-run prompt opens the same
  // dialog, and a dialog owned by one of its two callers is a dialog the other
  // one has to reach for sideways.
  const [modalOpen, setModalOpen] = useState(false);

  // Derived while rendering, not set from an effect: the default is a function
  // of who is asking and what came back, so computing it here means there is
  // never a paint with nothing open followed by a correction.
  //
  // Picking the first row was right while every visitor was anonymous and the
  // first row was the shared demo — the shop window opening on something. It
  // stopped being right the moment accounts existed. A signed-in user who owns
  // nothing had the demo opened FOR them, and the panel that fills the screen
  // showed $10.8M and a -$141,973 day with nothing on it saying whose. The
  // sidebar said "the book below is the shared demo"; the numbers did not, and
  // the numbers are where the eye goes. Showing one person's money as another's
  // is the one thing this product must never do, even for the seconds it takes
  // to read the sidebar.
  //
  // So: anonymous opens on the demo, a user with books of their own opens on
  // one of those, and a user with none opens on nothing and is told why.
  // signedIn === null means the answer has not arrived; nothing opens until it
  // has, because guessing "anonymous" is what produces the flash of somebody
  // else's portfolio this exists to prevent.
  const defaultPortfolioId =
    signedIn === null || portfolios.length === 0
      ? null
      : signedIn
        ? (portfolios.find((p) => p.is_own)?.id ?? null)
        : portfolios[0].id;
  const selectedPortfolioId = chosenPortfolioId ?? defaultPortfolioId;
  const [positions, setPositions] = useState<Position[]>([]);
  const [runs, setRuns] = useState<ExposureRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<ExposureRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPortfolios()
      .then(setPortfolios)
      // Same reason as the issuer page: a transport string in the top bar is a
      // sentence nobody can act on, and lib/errors.ts already has one (V13-S2).
      .catch((e) => setError(explainApiError(e).notice));
  }, []);


  useEffect(() => {
    if (!selectedPortfolioId) return;
    let ignore = false;   // drop results that resolve after a portfolio switch
    getPositions(selectedPortfolioId).then((p) => { if (!ignore) setPositions(p); }).catch(console.error);
    listRuns(selectedPortfolioId).then((data) => {
      if (ignore) return;
      setRuns(data);
      // Auto-select most recent run
      if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].id);
      }
    }).catch(console.error);
    return () => { ignore = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPortfolioId]);

  // Poll active run
  useEffect(() => {
    if (!selectedRunId) return;
    let ignore = false;   // a getRun() in flight when selectedRunId changes must not clobber the new run
    const poll = async () => {
      try {
        const run = await getRun(selectedRunId);
        if (ignore) return;
        setCurrentRun(run);
        if (selectedPortfolioId) {
          listRuns(selectedPortfolioId).then((data) => { if (!ignore) setRuns(data); }).catch(console.error);
        }
      } catch (e) {
        console.error("Poll error:", e);
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => { ignore = true; clearInterval(interval); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId]);

  const handleRunUpdate = useCallback((created: ExposureRun) => {
    // The freshly created run is the full object; show it now and let the
    // selectedRunId poll effect stream in events/metrics as the worker runs.
    setCurrentRun(created);
    setSelectedRunId(created.id);
    if (selectedPortfolioId) {
      listRuns(selectedPortfolioId).then(setRuns).catch(console.error);
    }
  }, [selectedPortfolioId]);

  const handlePortfolioCreated = useCallback((created: Portfolio) => {
    // reload the (now auth-scoped) list and jump to the new portfolio
    listPortfolios().then((data) => {
      setPortfolios(data);
      setChosenPortfolioId(created.id);
      setCurrentRun(null);
      setSelectedRunId(null);
      setRuns([]);
    }).catch(console.error);
  }, []);

  const selectedPortfolio = portfolios.find((p) => p.id === selectedPortfolioId) ?? null;
  // Signed in, and everything visible belongs to somebody else. Computed here
  // because it decides what gets SELECTED as well as what gets rendered, and a
  // flag two components work out separately is a flag they can disagree about.
  const ownsNothing = !!signedIn && portfolios.length > 0 && !portfolios.some((p) => p.is_own);

  return (
    <div className="h-screen flex flex-col bg-[#0d1117]">
      {/* Top bar */}
      <header className="h-10 border-b border-[#21262d] flex items-center px-4 gap-3 shrink-0">
        <BarChart3 className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-slate-300">Exposure Workbench</span>
        <span className="text-xs text-slate-600">Portfolio Risk Workflow</span>
        <div className="ml-auto flex items-center gap-3">
          {error && (
            <span className="text-xs text-red-400 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> {error}
            </span>
          )}
          <AuthControls />
        </div>
      </header>

      {/* Three-panel workspace */}
      <div className="flex-1 flex overflow-hidden">
        <SignedInProbe onChange={setSignedIn} />
        <PortfolioModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onCreated={(p) => { setModalOpen(false); handlePortfolioCreated(p); }}
        />
        <LeftPanel
          showFirstRunCard={ownsNothing && !!selectedPortfolio}
          setModalOpen={setModalOpen}
          portfolios={portfolios}
          selectedPortfolioId={selectedPortfolioId}
          onSelectPortfolio={(id) => {
            setChosenPortfolioId(id);
            setCurrentRun(null);
            setSelectedRunId(null);
            setRuns([]);
          }}
          runs={runs}
          selectedRunId={selectedRunId}
          onSelectRun={(id) => {
            setSelectedRunId(id);
          }}
          onPortfolioCreated={handlePortfolioCreated}
        />
        <MiddlePanel
          selectedPortfolio={selectedPortfolio}
          run={currentRun}
          onRunUpdate={handleRunUpdate}
        />
        <RightPanel
          portfolio={selectedPortfolio}
          positions={positions}
          run={currentRun}
          firstRun={ownsNothing}
          onCloned={handlePortfolioCreated}
          onUploadCsv={() => setModalOpen(true)}
        />
      </div>
      <EvidenceDrawer />
      <ChatPanel />
    </div>
  );
}
