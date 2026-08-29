import type { Portfolio, Position, ExposureRun, ExposureRunSummary, Freshness, Task, Usage } from "./types";
import { apiFetch as fetchJson } from "./http";

// setAuthTokenGetter now lives in ./http (the shared transport); re-export so
// existing importers keep working.
export { setAuthTokenGetter } from "./http";

// ─── Portfolios ───────────────────────────────────────────────────────────────

export async function listPortfolios(): Promise<Portfolio[]> {
  return fetchJson<Portfolio[]>("/api/portfolios");
}

export async function getPortfolio(id: string): Promise<Portfolio> {
  return fetchJson<Portfolio>(`/api/portfolios/${id}`);
}

export async function getPositions(portfolioId: string): Promise<Position[]> {
  return fetchJson<Position[]>(`/api/portfolios/${portfolioId}/positions`);
}

export async function getFreshness(portfolioId: string): Promise<Freshness> {
  return fetchJson<Freshness>(`/api/portfolios/${portfolioId}/freshness`);
}

// ─── Portfolio create / upload / clone (V2-B, authenticated) ────────────────────

export async function createPortfolio(name: string, csvText?: string): Promise<Portfolio> {
  return fetchJson<Portfolio>("/api/portfolios", {
    method: "POST",
    body: JSON.stringify({ name, csv_text: csvText || null }),
  });
}

export async function cloneDemoPortfolio(): Promise<Portfolio> {
  return fetchJson<Portfolio>("/api/portfolios/clone-demo", { method: "POST", body: "{}" });
}

export async function uploadPositions(
  portfolioId: string,
  csvText: string
): Promise<{ portfolio_id: string; as_of_date: string; positions: number }> {
  return fetchJson(`/api/portfolios/${portfolioId}/upload`, {
    method: "POST",
    body: JSON.stringify({ csv_text: csvText }),
  });
}

// ─── Securities universe search (V2-D typeahead) ────────────────────────────────

export interface SecurityHit {
  ticker: string;
  name: string | null;
  exchange: string | null;
  is_etf: boolean;
  has_cik: boolean;
  has_prices: boolean;
}

export async function searchSecurities(q: string): Promise<SecurityHit[]> {
  return fetchJson<SecurityHit[]>(`/api/securities/search?q=${encodeURIComponent(q)}`);
}

// ─── Exposure Runs ────────────────────────────────────────────────────────────

export async function listRuns(portfolioId?: string): Promise<ExposureRunSummary[]> {
  const qs = portfolioId ? `?portfolio_id=${portfolioId}` : "";
  return fetchJson<ExposureRunSummary[]>(`/api/exposure-runs${qs}`);
}

export async function getRun(runId: string): Promise<ExposureRun> {
  return fetchJson<ExposureRun>(`/api/exposure-runs/${runId}`);
}

/**
 * Omit asOfDate to report on the last completed session (the usual case).
 *
 * There is no `triggered_by` to pass: what a run is called is a fact about which
 * door it came through, and the door knows (V13-S1).
 */
export async function createRun(
  portfolioId: string,
  asOfDate?: string
): Promise<ExposureRun> {
  return fetchJson<ExposureRun>("/api/exposure-runs", {
    method: "POST",
    body: JSON.stringify({
      portfolio_id: portfolioId,
      ...(asOfDate ? { as_of_date: asOfDate } : {}),
    }),
  });
}

// ─── Tasks (admin) ────────────────────────────────────────────────────────────

export async function listTasks(status?: string): Promise<Task[]> {
  const qs = status ? `?status=${status}` : "";
  return fetchJson<Task[]>(`/api/tasks${qs}`);
}

// ─── Daily quota (V2-E4) ──────────────────────────────────────────────────────

export async function getMyUsage(): Promise<Usage> {
  return fetchJson<Usage>("/api/me/usage");
}
