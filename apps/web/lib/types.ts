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

export interface WorkflowEvent {
  id: number;
  step_name: string;
  status: "running" | "completed" | "failed" | "skipped";
  message: string | null;
  duration_ms: number | null;
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

// ─── Daily quota (V2-E4) ──────────────────────────────────────────────────────

export interface UsagePool {
  kind: string;
  used: number;
  limit: number;
  remaining: number;
}

export interface Usage {
  day: string;
  resets_at: string;
  pools: UsagePool[];
}
