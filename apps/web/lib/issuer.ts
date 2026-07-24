// Issuer Intelligence API client + types.
// Uses the shared transport (lib/http) so its POST writes (chat, research,
// ensure-ready) carry the Clerk bearer token, same as lib/api.

import { apiFetch as j } from "./http";

// ─── types ──────────────────────────────────────────────────────────────────
export type CompanyRow = { ticker: string; name: string; sector: string | null; is_investigable: boolean };

export type MetricAvail = { metric: string; periods: number; latest_period_end: string };

export type Snapshot = {
  company: { ticker: string; name: string; cik: string | null; exchange: string | null; sector: string | null; industry: string | null; is_investigable: boolean };
  latest_filing: { form_type: string; filing_date: string; accession: string; source_url: string | null } | null;
  portfolio_exposure: { market_value: number | null; weight: number | null; daily_return: number | null } | null;
  available_metrics: MetricAvail[];
};

export type CalcRow = { calc_id: string; operation: string; params: any; result: any; primitive_version: string };
export type FilingRow = { accession: string; form_type: string; filing_date: string; period_end: string | null; source_url: string | null; sections: { id: string; item_code: string | null; title: string | null }[] };
export type SourceRow = { id: string; title: string | null; url: string; publisher: string | null; published_date: string | null; snippet: string | null; search_query: string | null };
export type Brief = {
  id: string; research_run_id: string;
  financial_summary: string | null; key_changes: string | null; management_explanation: string | null;
  market_context: string | null; portfolio_implications: string | null; open_questions: string | null;
  citations: string[]; confidence_flags: Record<string, unknown>; created_at: string | null;
};
export type Evidence = { type: string; id: string; body: Record<string, any>; provenance: Record<string, any>; upstream: { type: string; id: string }[] };
export type ResearchRun = { id: string; company_id: string; status: string; agent_session_id: string | null; error_message: string | null; started_at: string | null; completed_at: string | null };
export type AgentStep = { seq: number; step_type: string; tool_name: string | null; status: string; result_summary: string | null; evidence_refs: { type: string; id: string }[]; created_at: string };
export type AgentMessage = { id: string; role: string; content: string | null; citations: string[] };
export type SessionDetail = { id: string; kind: string; tools_used: number; messages: AgentMessage[]; steps: AgentStep[] };

// ─── reads ──────────────────────────────────────────────────────────────────
export const listCompanies = () => j<CompanyRow[]>("/api/companies");
export const getSnapshot = (t: string) => j<Snapshot>(`/api/issuers/${t}/snapshot`);
export const getFinancials = (t: string) => j<{ ticker: string; calcs: CalcRow[] }>(`/api/issuers/${t}/financials`);
export const getFilings = (t: string) => j<{ ticker: string; filings: FilingRow[] }>(`/api/issuers/${t}/filings`);
export const getSection = (id: string) => j<{ id: string; item_code: string; title: string; text: string }>(`/api/filing-sections/${id}`);
export const getResearchSources = (t: string) => j<{ ticker: string; sources: SourceRow[] }>(`/api/issuers/${t}/research-sources`);
export const getLatestBrief = (t: string) => j<{ ticker: string; brief: Brief | null }>(`/api/issuers/${t}/latest-brief`);
export const getEvidence = (id: string) => j<Evidence>(`/api/evidence/${id}`);

// ─── runs / agent ─────────────────────────────────────────────────────────────
export const ensureReady = (t: string) => j<{ task_id: string; status: string }>(`/api/companies/${t}/ensure-ready`, { method: "POST", body: JSON.stringify({ ticker: t }) });
export const startResearch = (t: string) => j<ResearchRun>("/api/research-runs", { method: "POST", body: JSON.stringify({ ticker: t, portfolio_id: "port_001" }) });
export const getResearchRun = (id: string) => j<ResearchRun>(`/api/research-runs/${id}`);

export const createSession = () => j<{ id: string }>("/api/agent/sessions", { method: "POST", body: "{}" });
export const postMessage = (sid: string, text: string) => j<{ session_id: string; message_id: string; text: string; citations: string[] }>(`/api/agent/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ text }) });
export const getSessionDetail = (sid: string) => j<SessionDetail>(`/api/agent/sessions/${sid}`);
