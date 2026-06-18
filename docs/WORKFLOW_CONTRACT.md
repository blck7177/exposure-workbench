# Workflow Contract

## Exposure Update Workflow Steps

Each step writes a `workflow_events` record with `status: running | completed | failed`.

| Step | Name | Description |
|------|------|-------------|
| 1 | `load_inputs` | Load positions, market prices, factor prices, limits from DB |
| 2 | `validate_inputs` | Check for missing prices, stale data, duplicate positions |
| 3 | `calculate_exposure` | Market value, weights, sector/issuer exposure |
| 4 | `calculate_pnl` | Daily P&L, returns, top contributors/detractors |
| 5 | `calculate_attribution` | Factor regression, explained/residual return |
| 6 | `calculate_risk` | Rolling volatility, VaR, expected shortfall, stress |
| 7 | `check_limits` | Compare metrics against risk_limits config → generate alerts |
| 8 | `compare_previous_run` | Delta analysis vs previous completed run |
| 9 | `generate_report` | LLM/LangGraph generates executive summary + markdown report |
| 10 | `persist_outputs` | Write all results to DB, mark run completed |

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
