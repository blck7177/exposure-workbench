"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Activity, BarChart3, RefreshCw, AlertTriangle, CheckCircle2,
  Loader2, ChevronRight, TrendingUp, TrendingDown,
  ShieldAlert, FileText, ChevronDown, ChevronUp, Search, Plus,
} from "lucide-react";
import { ChatPanel } from "./components/ChatPanel";
import { RunTimeline } from "./components/RunTimeline";
import { EvidenceDrawer } from "./components/Evidence";
import { AuthControls } from "./components/Auth";
import { PortfolioModal } from "./components/PortfolioModal";
import type {
  Portfolio, ExposureRun, ExposureRunSummary, Position, RiskAlert,
  FactorAttribution, ExposureMetrics, SectorExposure, IssuerExposure,
} from "@/lib/types";
import { listPortfolios, getPositions, createRun, getRun, listRuns } from "@/lib/api";
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

// ─── Left panel ─────────────────────────────────────────────────────────────

function LeftPanel({
  portfolios, selectedPortfolioId, onSelectPortfolio,
  runs, selectedRunId, onSelectRun, onPortfolioCreated,
}: {
  portfolios: Portfolio[];
  selectedPortfolioId: string | null;
  onSelectPortfolio: (id: string) => void;
  runs: ExposureRunSummary[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
  onPortfolioCreated: (p: Portfolio) => void;
}) {
  const [modalOpen, setModalOpen] = useState(false);
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
      <PortfolioModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(p) => { setModalOpen(false); onPortfolioCreated(p); }}
      />

      <div className="flex-1 overflow-y-auto">
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
                {report.recommended_actions && (
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Recommended Actions</p>
                    <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{report.recommended_actions}</p>
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
  portfolio, positions, run,
}: {
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
  const returnPositive = (metrics?.daily_return ?? 0) >= 0;

  if (!portfolio) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <BarChart3 className="w-12 h-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Select a portfolio to view the dashboard</p>
        </div>
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
                          <Link href={`/issuer/${ie.ticker}`} className="inline-flex items-center gap-1 hover:text-sky-400" title="Investigate issuer">
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
                            <Link href={`/issuer/${pos.ticker}`} className="inline-flex items-center gap-1 hover:text-sky-400" title="Investigate issuer">
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
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [runs, setRuns] = useState<ExposureRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<ExposureRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPortfolios()
      .then((data) => {
        setPortfolios(data);
        if (data.length > 0) setSelectedPortfolioId(data[0].id);
      })
      .catch((e) => setError(e.message));
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
      setSelectedPortfolioId(created.id);
      setCurrentRun(null);
      setSelectedRunId(null);
      setRuns([]);
    }).catch(console.error);
  }, []);

  const selectedPortfolio = portfolios.find((p) => p.id === selectedPortfolioId) ?? null;

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
        <LeftPanel
          portfolios={portfolios}
          selectedPortfolioId={selectedPortfolioId}
          onSelectPortfolio={(id) => {
            setSelectedPortfolioId(id);
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
        />
      </div>
      <EvidenceDrawer />
      <ChatPanel />
    </div>
  );
}
