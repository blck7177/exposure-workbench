// Issuer Intelligence API client + types.
// Uses the shared transport (lib/http) so its POST writes (chat, research,
// ensure-ready) carry the Clerk bearer token, same as lib/api.

import { apiFetch as j } from "./http";
import type { TimelineEvent } from "@/app/components/RunTimeline";

// ─── types ──────────────────────────────────────────────────────────────────
export type CompanyRow = { ticker: string; name: string; sector: string | null; is_investigable: boolean };

export type MetricAvail = { metric: string; periods: number; latest_period_end: string };

export type Snapshot = {
  company: { ticker: string; name: string; cik: string | null; exchange: string | null; sector: string | null; industry: string | null; is_investigable: boolean };
  latest_filing: { form_type: string; filing_date: string; accession: string; source_url: string | null } | null;
  portfolio_exposure: { market_value: number | null; weight: number | null; daily_return: number | null } | null;
  available_metrics: MetricAvail[];
};

export type CalcRow = {
  calc_id: string | null; operation: string | null; params: any; result: any; primitive_version: string | null;
  label?: string;            // V10: the recipe's own name for the row
  unavailable?: string;      // V10: present when the recipe could not compute it
};
export type FilingRow = { accession: string; form_type: string; filing_date: string; period_end: string | null; source_url: string | null; sections: { id: string; item_code: string | null; title: string | null }[] };
export type SourceRow = { id: string; title: string | null; url: string; publisher: string | null; published_date: string | null; snippet: string | null; search_query: string | null };
export type Brief = {
  id: string; research_run_id: string;
  financial_summary: string | null; key_changes: string | null; management_explanation: string | null;
  market_context: string | null; portfolio_implications: string | null; open_questions: string | null;
  citations: string[]; confidence_flags: Record<string, unknown>; created_at: string | null;
};
// `label` is what this piece of evidence IS, in words — "Gross profit · Dec 28,
// 2025 – Mar 28, 2026" rather than `calc 2b5395` (V13-S3). Built server-side
// from fields that are on the row, so one definition serves every surface.
export type Evidence = { type: string; id: string; label?: string; body: Record<string, any>; provenance: Record<string, any>; upstream: { type: string; id: string }[] };
// workflow_events is the run's outer timeline (V7-U1). It arrives empty from the
// POST — the run has only just been enqueued — and fills in on the polls.
// error_message is present ONLY when the failure's own words were written for a
// reader; otherwise error_code is what a sentence is looked up from, and there
// is no `error_detail` — the exception's own words stay server-side, because
// this payload is readable by anyone who can see the run (V13-S2).
export type ResearchRun = { id: string; company_id: string; status: string; agent_session_id: string | null; error_message: string | null; error_code: string | null; started_at: string | null; completed_at: string | null; workflow_events: TimelineEvent[] };
// `display` is what this step DID, in the words a person watching would use —
// "Evaluating total debt for AAPL", not `evaluate_formula` (V13-S4). Null on the
// rows that are not actions: an llm_call is what the turn cost and a refusal is a
// call that did not happen, and both belong to the audit layer.
export type AgentStep = { seq: number; step_type: string; tool_name: string | null; status: string; result_summary: string | null; display: string | null; evidence_refs: { type: string; id: string }[]; created_at: string; prompt_tokens: number | null; completion_tokens: number | null };
/**
 * What the gate found for one figure, kept from the pass that accepted it (V13-S3).
 *
 * `span` indexes into the answer's own text, so a figure is located rather than
 * searched for — a substring search would attach the basis for "1.39" to the
 * "1.39" inside "21.39" the first time an answer held both.
 *
 * `how` is "value" when a cited row holds the number, "quoted" when it appears
 * verbatim in a cited passage; the latter names no single value because there
 * is none, and the passage is the support.
 */
export type VerifiedMatch = {
  span: [number, number];
  surface: string;
  how: "value" | "quoted";
  label?: string;
  source_id?: string;
  value?: number;
  unit_class?: string;
};

export type Verified = { figures: number; sources: number; matches: VerifiedMatch[] };

// meta carries out-of-band facts about the turn. {"gate":"exhausted"} means the
// loop ended without the citation gate accepting an answer — a refusal, not a reply.
// {"verified": …} is the record of the check that let this answer through — not a
// second opinion computed later, which would be free to disagree with the first.
export type AgentMessage = { id: string; role: string; content: string | null; citations: string[]; meta?: { gate?: string; verified?: Verified } & Record<string, unknown> };
export type SessionDetail = { id: string; kind: string; tools_used: number; messages: AgentMessage[]; steps: AgentStep[] };
// V13-S0. The list a person navigates their own conversations by. `title` is
// the first thing they asked — already written, already theirs — rather than a
// generated summary, which would be one more claim nothing checks.
export type SessionSummary = { id: string; kind: string; started_at: string; ended_at: string | null; title: string | null };

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
// portfolio_id is omitted when the caller has no portfolio in hand rather than
// defaulted: this used to send the demo book's id literally, so every run a
// signed-in user started from their own book was recorded against the demo and
// the brief's portfolio_implications was written about somebody else's holdings.
// The API has always taken it as optional.
export const startResearch = (t: string, portfolioId?: string) =>
  j<ResearchRun>("/api/research-runs", {
    method: "POST",
    body: JSON.stringify(portfolioId ? { ticker: t, portfolio_id: portfolioId } : { ticker: t }),
  });
export const getResearchRun = (id: string) => j<ResearchRun>(`/api/research-runs/${id}`);

export const createSession = () => j<{ id: string }>("/api/agent/sessions", { method: "POST", body: "{}" });
export const postMessage = (sid: string, text: string) => j<{ session_id: string; message_id: string; text: string; citations: string[]; meta?: Record<string, unknown> }>(`/api/agent/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ text }) });
export const getSessionDetail = (sid: string) => j<SessionDetail>(`/api/agent/sessions/${sid}`);
export const listSessions = () => j<SessionSummary[]>("/api/agent/sessions");
