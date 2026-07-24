# P9 — Full-System Validation & Coverage

Final acceptance for the Issuer Intelligence MVP (P0–P9). All figures are from live
data against real EDGAR / yfinance / OpenAI / Tavily.

## Per-issuer readiness coverage

| Ticker | Facts | Sections | Chunks | Norm. metrics |
|--------|------:|---------:|-------:|--------------:|
| AAPL | 5,815 | 34 | 182 | 13 |
| AMZN | 7,021 | 34 | 279 | 12 |
| GOOGL | 8,311 | 32 | 337 | 12 |
| JPM | 15,519 | 31 | 1,098 | 6 |
| LLY | 5,092 | 32 | 260 | 11 |
| MSFT | 8,031 | 32 | 348 | 13 |
| NVDA | 7,709 | 32 | 287 | 13 |
| XOM | 4,975 | 29 | 287 | 9 |

JPM (a bank) correctly exposes only 6 metrics — it does not tag GrossProfit,
OperatingIncomeLoss, CostOfRevenue or capex. Absence is honest, not patched.

## System totals

companies 10 · filings 16 · financial_facts 62,473 · filing_chunks 3,078 ·
calc_ledger 85 · research_sources 15 · issuer_briefs 3 · agent_sessions 17 ·
agent_steps 107.

## Acceptance checks

- **Exposure regression (red line):** the existing 10-step exposure pipeline runs
  green on real data with non-zero metrics (MV ~$10.26M) — unchanged by the upgrade.
- **Two full research runs:** NVDA (16 citations) and AAPL (17 citations) produced
  complete Issuer Risk Briefs end to end through the real worker/API.
- **Citation gate (M9):** zero hallucinated citations across persisted briefs; the
  gate rejected out-of-trail submissions before accepting a corrected one.
- **Idempotency:** readiness re-run with the same window leaves facts/chunks
  unchanged (AAPL 5,815 / 182 twice); recipe re-run appends but yields identical
  values; index re-run is a no-op.
- **MCP keystone:** an external MCP client produced the same trace + ledger as the
  in-process agent (enforcement below the transport).

## Architecture grep audit (all clean)

- External SDKs (edgar/yfinance/tavily/openai) appear only under `providers/` and
  `llm/` — never in `analytics/`, `tools/`, `agents/`, or `routes/`.
- `analytics/` imports no DB and no providers (pure functions).
- Evidence four-stores (financial_facts, filing_chunks, calc_ledger,
  research_sources) have no UPDATE/DELETE in services (append-only).
- `tools/` import services only — the one leak (research_tools importing a
  provider) was fixed by moving provider selection into research_search_service.
- No `_mock_output`/`mock_mode` in new Python code (only the retained legacy
  exposure report agent).

## Tests

`pytest -m "not live"` → 75 passed. `pytest -m live` → 6 passed (need DB + keys).
