/**
 * The chart reads (V13-S5), typed.
 *
 * Every one of these serves a panel and none of them computes anything: the
 * server reads what a run recorded, or calls the same service the analyst's own
 * tools call. That is the property the whole page rests on — a figure in a chart
 * and the same figure in an answer come from one place, so they cannot disagree.
 *
 * Nothing here is derived on the client for the same reason. A rolling
 * volatility recomputed in the browser would be a second opinion nobody asked
 * for, and it would differ in the third decimal, which on a risk page is where
 * trust goes.
 */

import { apiFetch as j } from "./http";

// ── the book ─────────────────────────────────────────────────────────────────

export type HistoryPoint = {
  date: string;
  value: number;
  drawdown: number;
  /** Null until 30 sessions have accumulated — not zero. */
  vol_30d: number | null;
  return: number | null;
  /** The benchmark indexed onto the book's own starting value, never a second axis. */
  benchmark: number | null;
};

export type Episode = {
  peak: string; trough: string; recovery: string | null;
  depth: number; trough_days: number; recovery_days: number | null; recovered: boolean;
};

export type History = {
  portfolio_id: string;
  span: string;
  benchmark: string;
  window?: { from: string; to: string; sessions: number };
  points: HistoryPoint[];
  episodes: Episode[];
  /** Stated, not hidden: today's holdings at historical prices. */
  valuation_assumption?: string;
  detail?: string;
};

export type LimitCheckRow = {
  key: string;
  label: string;
  group: "Portfolio" | "Issuer" | "Sector" | "Stress";
  fired: boolean;
  alert_id: string | null;
  /** Null on runs from before this desk recorded what a check measured. */
  current: number | null;
  warning: number | null;
  breach: number | null;
  status: "ok" | "warning" | "breach" | null;
  utilisation: number | null;
};

export type LimitBook = {
  run_id: string; as_of: string; checks: LimitCheckRow[]; detail: string | null;
};

export type Scenario = {
  key: string; label: string; description: string | null;
  shocks: Record<string, number>;
  loss_pct: number | null; loss_usd: number | null;
  /** What the scenario says nothing about, and therefore holds still. An
   *  assumption, not a measurement — which is why it is on the wire. */
  held_flat: string[];
  status: string | null; reason: string | null;
  warning: number | null; breach: number | null;
};

export type FactorCorrelation = {
  run_id: string;
  window?: { from: string; to: string; observations: number };
  max_vif: number | null;
  collinear: boolean;
  tickers: string[];
  labels: string[];
  matrix: (number | null)[][] | null;
  detail?: string;
};

export type Reconcile = Record<string, unknown> & { calc_id?: string; error?: string };

export const getHistory = (id: string, span = "3y") =>
  j<History>(`/api/portfolios/${id}/history?span=${span}`);
export const getLimitBook = (runId: string) =>
  j<LimitBook>(`/api/exposure-runs/${runId}/limit-book`);
export const getStress = (runId: string) =>
  j<{ run_id: string; scenarios: Scenario[] }>(`/api/exposure-runs/${runId}/stress`);
export const getFactorCorrelation = (runId: string) =>
  j<FactorCorrelation>(`/api/exposure-runs/${runId}/factor-correlation`);
export const getReconcile = (runId: string) =>
  j<Reconcile>(`/api/exposure-runs/${runId}/reconcile`);

// ── an issuer ────────────────────────────────────────────────────────────────

export type PriceIndex = {
  ticker: string; benchmark: string; span: string; basis?: string;
  points: { date: string; value: number; benchmark: number | null }[];
  filings: { date: string; form: string; accession: string; url: string | null }[];
  detail?: string;
};

/** One slot of a series. `value === null` means no held filing can reach this
 *  window — the engine's own finding (V10 DP2), not a figure we chose to omit. */
export type WindowSlot = {
  start: string; end: string;
  value: number | null;
  fact_ids?: string[];
  terms?: { fact_id: string; sign: number }[];
  derivation?: string;
  unreachable?: string;
};

export type ReportedWindows = {
  ticker: string; metric: string; label: string;
  fiscal: Record<string, unknown> | null;
  rows: { months: number; label: string; slots: WindowSlot[] }[];
  note?: string; detail?: string;
};

export type CoverageRow = {
  metric: string; label: string; periods: number | null; latest: string | null;
  kind: string | null; windows_filed: string[] | null; superseded_by: string[] | null;
};

export type CitationMap = {
  ticker: string; brief_id: string | null;
  sections: { form: string; filed: string; item: string | null; title: string | null;
              passages: number; cited: number }[];
  citation_mix: Record<string, number>;
};

export const getPriceIndex = (t: string, span = "1y") =>
  j<PriceIndex>(`/api/issuers/${t}/price-index?span=${span}`);
export const getWindows = (t: string, metric = "revenue") =>
  j<ReportedWindows>(`/api/issuers/${t}/windows?metric=${encodeURIComponent(metric)}`);
export const getCoverage = (t: string) =>
  j<{ ticker: string; measures: CoverageRow[] }>(`/api/issuers/${t}/coverage`);
export const getCitationMap = (t: string) =>
  j<CitationMap>(`/api/issuers/${t}/citation-map`);

// ── evidence labels, in bulk ─────────────────────────────────────────────────

export type EvidenceLabel = { type: string; label: string };

/** An answer citing seventeen things should not open seventeen requests to put
 *  words on its chips. Ids that no longer resolve are absent, not an error. */
export const getEvidenceLabels = (ids: string[]) =>
  ids.length === 0
    ? Promise.resolve({ labels: {} as Record<string, EvidenceLabel> })
    : j<{ labels: Record<string, EvidenceLabel> }>(
        `/api/evidence/labels?ids=${encodeURIComponent(ids.join(","))}`);

// ── this desk's own record ───────────────────────────────────────────────────

export type AuditSummary = {
  answers_gated: number;
  answers_refused: number;
  lookups_made: number;
  lookups_refused: number;
  model_calls: number;
  figures_checked: number;
};

export const getAuditSummary = () => j<AuditSummary>("/api/me/audit-summary");

export type ResearchRunSummary = {
  id: string; company_id: string; ticker: string | null; status: string;
  started_at: string | null; completed_at: string | null; error_code: string | null;
};

export const listResearchRuns = () => j<ResearchRunSummary[]>("/api/research-runs");
