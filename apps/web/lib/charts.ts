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
  /** V25: the windows this endpoint accepts. The client used to hard-code `3y`,
   *  which was a copy of a list that lived in the handler and outlived the day
   *  anyone remembered the other two were there. */
  spans?: string[];
  benchmark: string;
  /** The episodes scan's ledger row — the chart's series-level citation. Daily
   *  points have no row each and never will; this is what "how was this worked
   *  out" opens. */
  episodes_calc_id?: string;
  window?: { from: string; to: string; sessions: number };
  points: HistoryPoint[];
  episodes: Episode[];
  /** Stated, not hidden: today's holdings at historical prices. */
  valuation_assumption?: string;
  /** V20: method statements from the server, keyed like ExposureRun.methods. */
  methods?: Record<string, string>;
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
  /** V25: tier minus measured, signed — negative means the check is already
   *  past that tier. Null where either side was not recorded; never zero,
   *  which would read as "exactly at the tier". */
  room_warning: number | null;
  room_breach: number | null;
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

/**
 * Whether the day's two decompositions close (V25).
 *
 * Typed since V13 and never called until now: the page drew the waterfall and
 * left the identity that says it adds up in the payload. `holds` is the
 * endpoint's own verdict against its own tolerance — not a comparison this
 * page performs, which would be a second opinion free to differ in the eighth
 * decimal.
 */
export type Identity = {
  statement: string;
  gap: number;
  tolerance: number;
  holds: boolean;
  terms: number;
};

export type Reconcile = {
  run_id?: string;
  as_of?: string;
  reconciles?: boolean;
  identity_positions?: Identity & { sum_of_contributions: number; daily_return: number };
  identity_factors?: Identity & {
    attribution_portfolio_return: number;
    sum_of_factor_contributions: number;
    alpha_plus_residual: number;
  };
  factor_share?: number;
  unexplained_share?: number;
  collinear?: boolean;
  factor_note?: string;
  calc_id?: string;
  /** `run_not_reconcilable` when the run did not record what the identities
   *  need — a fact about that run, with its own sentence in `detail`. */
  error?: string;
  detail?: string;
  missing?: string[];
};

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

// ── the book across its updates (V25) ────────────────────────────────────────

/**
 * One dated update of a book: what that run measured.
 *
 * `runs_that_day` is how many completed runs the point stands for — the demo
 * book has five dated 2026-09-03, re-runs of one close — and
 * `weight_change_vs_prev` is against the previous DATED update, computed
 * server-side beside both figures. Null on the first update and on a name the
 * book did not hold then; those are the same answer and neither is a zero.
 */
export type UpdateIssuer = {
  ticker: string; sector: string | null;
  weight: number | null; market_value: number | null;
  contribution: number | null; daily_pnl: number | null; daily_return: number | null;
  weight_change_vs_prev: number | null;
};

export type UpdateSector = {
  sector: string; weight: number | null; market_value: number | null;
  weight_change_vs_prev: number | null;
};

export type UpdateCheck = {
  key: string; current: number | null; warning: number | null; breach: number | null;
  status: "ok" | "warning" | "breach" | null; fired: boolean;
};

export type Update = {
  as_of: string;
  run_id: string;
  runs_that_day: number;
  metrics: {
    market_value: number | null; daily_pnl: number | null; daily_return: number | null;
    vol_30d: number | null; vol_60d: number | null; max_drawdown: number | null;
    alerts: number;
  } | null;
  issuers: UpdateIssuer[];
  sectors: UpdateSector[];
  checks: UpdateCheck[];
};

export type RunSeries = {
  portfolio_id: string;
  span: string;
  spans: string[];
  updates: Update[];
  /** The server's own name for each check and sector, so the series and the
   *  meters beside it do not call one check two things. */
  labels: { checks: Record<string, string>; sectors: Record<string, string> };
  detail: string | null;
};

export const getRunSeries = (id: string, span = "1y") =>
  j<RunSeries>(`/api/portfolios/${id}/run-series?span=${span}`);

// ── an issuer ────────────────────────────────────────────────────────────────

export type PriceIndex = {
  ticker: string; benchmark: string; span: string; basis?: string; spans?: string[];
  points: { date: string; value: number; benchmark: number | null }[];
  filings: { date: string; form: string; accession: string; url: string | null }[];
  detail?: string;
};

/** One slot of a series. `value === null` means no held filing can reach this
 *  window — the engine's own finding (V10 DP2), not a figure we chose to omit.
 *
 *  The end is spelled `period_end`, which is what the server sends
 *  (analytics/units.POINT_PERIOD_KEY) and is the key every point of every
 *  series on this desk carries. It was typed here as `end` and read as `end` by
 *  the ladder, so `s.end` was undefined on every slot the API has ever
 *  returned: the bars were positioned at NaN and the year axis threw. A wire
 *  type is a claim about the wire, and this one was not true (V25). */
export type WindowSlot = {
  start: string; period_end: string;
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

export const getPriceIndex = (t: string, span = "1y", benchmark = "SPY") =>
  j<PriceIndex>(`/api/issuers/${t}/price-index?span=${span}&benchmark=${encodeURIComponent(benchmark)}`);
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

// ── how a composed figure was assembled ──────────────────────────────────────

export type ContainmentTerm = { metric: string; label: string; value: number | null; fact_id: string | null };
export type Containment = {
  ticker: string; formula: string; family: string;
  as_of: string | null;
  /** e.g. "long_term_debt_total + commercial_paper" — the cover, in words. */
  definition: string | null;
  taken: ContainmentTerm[];
  overlapping_not_added: (ContainmentTerm & {
    because: { part: string; part_label: string; already_in: string; already_in_label: string }[];
  })[];
  missing_at_this_date: { metric: string; label: string; last_reported: string | null }[];
  no_facts_for_issuer: { metric: string; label: string }[];
  outside_family: { metric: string; label: string }[];
  edges: { parent: string; child: string; observed: number }[];
  note?: string; detail?: string;
};

export const getContainment = (t: string, formula = "total_debt") =>
  j<Containment>(`/api/issuers/${t}/containment?formula=${encodeURIComponent(formula)}`);

// ── the recipe's series, for the margins panel ───────────────────────────────

export type PanelPoint = { end: string; value: number; fact_ids: string[] };
export type PanelSeries = {
  metric: string; label: string; calc_id: string; operation: string; points: PanelPoint[];
};
export type PanelSeriesResponse = {
  ticker: string; as_of: string | null; recipe_version: string | null;
  series: PanelSeries[];
  unavailable?: { metric: string; detail: string }[];
  chartable?: string[];
};

// ── the issuer's measures, and what can be drawn of each (V25) ───────────────

/** One window of a flow, as the picker states it. `derived` means a signed path
 *  over filed boundaries — Microsoft's June quarter is the fiscal year less its
 *  nine months, a figure no filing states. */
export type MeasureWindow = {
  start: string; end: string; value: number; derived: boolean; fact_ids: string[];
};
// NB `/measures` states its own `end` (services/measures_service._slot), which
// is a different serialiser from the ladder's; the two keys are not a mistake
// here, they are two endpoints and each type says what its own says.

export type MeasureView = "level" | "yoy" | "share" | "windows";

export type FlowMeasure = {
  metric: string; label: string; source: "filed" | "recipe";
  unit_class: string;
  periods?: number | null; through?: string | null;
  windows_filed?: string[] | null;
  windows_available?: string[];
  latest: MeasureWindow | null;
  /** The engine's own sentence when the latest window of that length cannot be
   *  derived. Never replaced by a window of another length. */
  latest_unreachable?: string | null;
  latest_12m?: MeasureWindow | null;
  latest_12m_unreachable?: string | null;
  views: MeasureView[];
  yoy_metric?: string | null;
  share_metric?: string | null;
  /** Set on a recipe row (free cash flow): its ledger row and how many points. */
  calc_id?: string;
  points?: number;
};

export type RatioMeasure = {
  metric: string; label: string; source: "recipe"; unit_class: string;
  calc_id: string; operation: string; points: number;
  latest: { end: string; value: number } | null;
  views: MeasureView[];
};

export type BalanceMeasure = {
  metric: string; label: string; source: "filed"; unit_class: string;
  readings?: number | null; through?: string | null;
  latest: { as_of: string; value: number; fact_ids: string[] } | null;
  views: MeasureView[];
  superseded_by?: string[] | null;
};

export type Measures = {
  ticker: string;
  /** The recipe's own as-of, which the ratios are anchored to and the filed
   *  flows are not. */
  as_of: string | null;
  recipe_version: string | null;
  flows: FlowMeasure[];
  ratios: RatioMeasure[];
  balances: BalanceMeasure[];
  unavailable: { metric: string; label?: string; detail: string }[];
};

export const getMeasures = (t: string) => j<Measures>(`/api/issuers/${t}/measures`);

export type BalanceSeries = {
  ticker: string; metric: string; label: string; unit_class: string;
  calc_id: string | null;
  points: { period_end: string; value: number; fact_ids: string[] }[];
  basis: string;
};

export const getBalanceSeries = (t: string, metric: string, lastN = 12) =>
  j<BalanceSeries>(`/api/issuers/${t}/balance-series?metric=${encodeURIComponent(metric)}&last_n=${lastN}`);

export type BriefSummary = {
  id: string; research_run_id: string; created_at: string | null;
  citations: number; sections: number; is_current: boolean;
};

export const getBriefs = (t: string) =>
  j<{ ticker: string; briefs: BriefSummary[] }>(`/api/issuers/${t}/briefs`);

export const getPanelSeries = (t: string, metrics?: string[]) =>
  j<PanelSeriesResponse>(`/api/issuers/${t}/panel-series${
    metrics?.length ? `?metrics=${encodeURIComponent(metrics.join(","))}` : ""}`);
