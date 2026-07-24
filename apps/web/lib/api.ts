import type { Portfolio, Position, ExposureRun, ExposureRunSummary, Task } from "./types";
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

// ─── Exposure Runs ────────────────────────────────────────────────────────────

export async function listRuns(portfolioId?: string): Promise<ExposureRunSummary[]> {
  const qs = portfolioId ? `?portfolio_id=${portfolioId}` : "";
  return fetchJson<ExposureRunSummary[]>(`/api/exposure-runs${qs}`);
}

export async function getRun(runId: string): Promise<ExposureRun> {
  return fetchJson<ExposureRun>(`/api/exposure-runs/${runId}`);
}

export async function createRun(
  portfolioId: string,
  asOfDate: string
): Promise<ExposureRun> {
  return fetchJson<ExposureRun>("/api/exposure-runs", {
    method: "POST",
    body: JSON.stringify({
      portfolio_id: portfolioId,
      as_of_date: asOfDate,
    }),
  });
}

// ─── Tasks (admin) ────────────────────────────────────────────────────────────

export async function listTasks(status?: string): Promise<Task[]> {
  const qs = status ? `?status=${status}` : "";
  return fetchJson<Task[]>(`/api/tasks${qs}`);
}
