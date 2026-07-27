# Workflow Contract

## Exposure Update Workflow Steps

Each step writes a `workflow_events` record with `status: running | completed | failed`.

| Step | Name | Description |
|------|------|-------------|
| 1 | `sync_prices` | Refresh bars for every held ticker over the run's own `[as_of - 90d, as_of]` window; record symbols the provider has nothing for and continue |
| 2 | `load_inputs` | Load positions, market prices, factor prices, limits from DB |
| 3 | `validate_inputs` | Fail the run if any holding has no price on or before `as_of`, or its newest price is older than `PRICE_STALENESS_DAYS`. Names every offender, not the first |
| 4 | `calculate_exposure` | Market value, weights, sector/issuer exposure |
| 5 | `calculate_pnl` | Daily P&L, returns, top contributors/detractors |
| 6 | `calculate_attribution` | Factor regression, explained/residual return |
| 7 | `calculate_risk` | Rolling volatility, VaR, expected shortfall, stress |
| 8 | `check_limits` | Compare metrics against risk_limits config → generate alerts |
| 9 | `compare_previous_run` | Delta analysis vs previous completed run (non-fatal) |
| 10 | `persist_outputs` | Write all results to DB, mark run completed |
| 11 | `generate_report` | LLM generates executive summary + markdown report (non-fatal) |

Two corrections landed with V2-E5, both of which this table had asserted for a
long time without the code agreeing:

- step 3 claimed to check stale data. It never did — it checked only that the
  positions and prices frames were non-empty, so an unpriced holding sailed
  through and was valued at $0. It now does what the row says.
- steps 10 and 11 were listed in the opposite order to the code.

Steps 9 and 11 are deliberately non-fatal: each logs a `failed` event and lets
the run finish. So a green run can legitimately show a red step, and
`steps_completed` can be shorter than the table.

## Task Types

| Type | Triggered by | Handler |
|------|-------------|---------|
| `exposure_update` | `POST /api/exposure-runs` | `handlers/exposure_update.py` |
| `market_data_sync` | `POST /api/market-data/sync` | `handlers/market_data_sync.py` |
| `scheduled_update` | APScheduler / schedule API | `handlers/scheduled_update.py` |

## Run Status Lifecycle

```
pending  →  running  →  completed
                    ↘  failed
```
