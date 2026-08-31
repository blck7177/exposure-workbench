// Core domain types mirroring the API response shapes

export interface Portfolio {
  id: string;
  name: string;
  description: string | null;
  currency: string;
  base_nav: number | null;
  benchmark: string | null;
  manager: string | null;
  is_active: boolean;
  // V7-U2. True for the shared demo book, which every visitor sees whether or
  // not they own anything. "The list is not empty" is therefore not the same
  // question as "this person has a portfolio", and the first-run card on the
  // left panel turns on the second one.
  is_public: boolean;
  // V7-Q: whether the CALLER owns this book. Independent of is_public — the
  // shared demo can be both public and somebody's. `!is_public` used to stand
  // in for this and stopped being true the moment the demo was handed over.
  is_own: boolean;
}

export interface Position {
  id: string;
  ticker: string;
  asset_class: string;
  sector: string | null;
  region: string | null;
  currency: string;
  quantity: number;
  cost_basis: number | null;
  price: number | null;
  market_value: number | null;
  as_of_date: string;
}

/**
 * Why a step stopped — the KIND of failure, and only that (V13-S2).
 *
 * The exception's own words (a provider's 429 JSON, an internal hostname) are
 * kept in the database for the operator and are not served: the demo book is
 * public, so anything on this payload is readable by any visitor. The sentence
 * the reader sees is looked up from the code in lib/errors.ts.
 */
export interface RunError {
  code: string;
}

export interface WorkflowEvent {
  id: number;
  step_name: string;
  status: "running" | "completed" | "failed" | "skipped";
  message: string | null;
  duration_ms: number | null;
  // What the step DECIDED, not just that it finished (V7-U4): `evaluated` from
  // check_limits, `scenarios_unevaluated` / `scenarios_evaluated` from
  // calculate_risk. Untyped on purpose — each step writes its own keys and a
  // union here would have to be edited by anyone adding one, which is how the
  // column would quietly go back to being unread.
  payload_summary: Record<string, unknown>;
  // V13-S2. Derived server-side from payload_summary, so there is one copy of
  // the fact. Null on a step that succeeded and on every event written before
  // V13 — which the UI renders as its generic sentence rather than as a claim
  // about a cause it does not have.
  error: RunError | null;
  created_at: string;
}

export interface ExposureMetrics {
  portfolio_market_value: number | null;
  daily_pnl: number | null;
  daily_return: number | null;
  gross_exposure: number | null;
  net_exposure: number | null;
  gross_exposure_pct: number | null;
  net_exposure_pct: number | null;
  rolling_vol_30d: number | null;
  rolling_vol_60d: number | null;
  var_95_1d: number | null;
  expected_shortfall_95: number | null;
  max_drawdown: number | null;
  stress_loss_tech: number | null;
  stress_loss_rates: number | null;
  stress_loss_credit: number | null;
  stress_loss_market: number | null;
}

export interface SectorExposure {
  sector: string;
  market_value: number | null;
  weight: number | null;
  weight_change: number | null;
}

export interface IssuerExposure {
  ticker: string;
  sector: string | null;
  market_value: number | null;
  weight: number | null;
  weight_change: number | null;
  daily_pnl: number | null;
  daily_return: number | null;
}

export interface FactorAttribution {
  factor_name: string;
  factor_ticker: string | null;
  beta: number | null;
  factor_return: number | null;
  contribution: number | null;
  r_squared: number | null;
}

export interface RiskAlert {
  id: string;
  alert_type: string;
  severity: "warning" | "breach";
  entity_type: string | null;
  entity_id: string | null;
  current_value: number | null;
  limit_value: number | null;
  utilization: number | null;
  message: string | null;
  created_at: string;
}

export interface DailyReport {
  id: string;
  agent_mode: string | null;
  executive_summary: string | null;
  key_movements: string | null;
  factor_explanation: string | null;
  risk_alert_explanation: string | null;
  recommended_actions: string | null;
  markdown_report: string | null;
  confidence_flags: Record<string, unknown>;
  // Alive, and rendered (page.tsx). Not the field V4-S2 deleted: a daily report
  // really is one completion, so direct_llm_agent writes this on every run. The
  // brief's identically named column was the same idea applied to a 30-turn
  // session, where it could never be filled — that one is gone, this one stays.
  llm_model: string | null;
  created_at: string;
}

export interface ExposureRun {
  id: string;
  portfolio_id: string;
  status: "pending" | "running" | "completed" | "failed";
  as_of_date: string;
  task_id: string | null;
  triggered_by: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  workflow_events: WorkflowEvent[];
  metrics: ExposureMetrics | null;
  sector_exposures: SectorExposure[];
  issuer_exposures: IssuerExposure[];
  factor_attributions: FactorAttribution[];
  risk_alerts: RiskAlert[];
  daily_report: DailyReport | null;
}

// The list endpoint (GET /api/exposure-runs) returns a lightweight summary — no
// nested events/metrics/report. Kept as its own type so a summary can never be
// passed where a full run (with workflow_events etc.) is rendered: that mismatch
// is a compile error, not a runtime crash.
export interface ExposureRunSummary {
  id: string;
  portfolio_id: string;
  status: RunStatus;
  as_of_date: string;
  triggered_by: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Task {
  id: string;
  type: string;
  status: string;
  payload: Record<string, unknown>;
  worker_id: string | null;
  claimed_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  retry_count: number;
  lease_until: string | null;
  created_at: string;
}

export type RunStatus = "pending" | "running" | "completed" | "failed";

/**
 * How old what you are looking at actually is (V13-S1).
 *
 * Two dates kept apart on purpose: the run's reporting date and the newest
 * session the market has traded. "Aug 20" alone does not say whether that is
 * the freshest data there is or a week of silence, and the top bar was showing
 * exactly that much.
 */
export interface Freshness {
  portfolio_id: string;
  latest_completed_run: string | null;
  run_as_of: string | null;
  latest_market_session: string | null;
  sessions_behind: number | null;
  runs_in_flight: number;
  detail: string | null;
  /** When the next scheduled update fires, if one is armed (V13 §9-④). */
  next_update: string | null;
}

export interface Me {
  user_id: string;
  email: string | null;
  // V13-S7 (§9-②): when this person first confirmed the disclaimer; null = not
  // yet, and the confirmation bar shows until it is set. Set once, never moved.
  disclaimer_acknowledged_at: string | null;
}

// ─── Daily quota (V2-E4) ──────────────────────────────────────────────────────

export interface UsagePool {
  kind: string;
  used: number;
  limit: number;
  remaining: number;
  // V7-Q: this account is exempt from the refusal (it is still counted). The
  // badge must say so, or an exempt tester reads "0/10" while turns keep going
  // through and has no way to tell that from a broken counter.
  unlimited?: boolean;
}

export interface Usage {
  day: string;
  resets_at: string;
  pools: UsagePool[];
}
