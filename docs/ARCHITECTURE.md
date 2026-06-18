# Architecture

## Overview

Exposure Workbench is a **database-backed portfolio exposure workflow demo**.

```
Next.js Web UI  →  FastAPI  →  Postgres
                                 ↑
                            Worker (async)
                                 ↓
                        ExposureWorkflow (deterministic)
                                 ↓
                        ReportAgent (LLM / LangGraph)
```

## Key Design Principles

- **Calculation layer is deterministic** — all analytics produce the same output given the same inputs. LLM is never in the calculation path.
- **Agent layer is interpretive** — LLM reads structured metrics and writes natural-language explanation and report.
- **Every run is persisted** — all metrics, alerts, and reports are written to Postgres. The dashboard reads from DB, not from real-time calculation.
- **Workflow events drive the UI timeline** — each pipeline step writes a `workflow_events` record, which the UI polls to show live progress.

## Services

| Service | Port | Description |
|---------|------|-------------|
| exposure-api | 8103 | FastAPI — creates runs, serves dashboard data |
| exposure-worker | — | Python polling loop — executes workflow tasks |
| exposure-web | 3103 | Next.js — three-panel workspace UI |
| postgres | 5433 | Persistent store for all run data |

## Data Flow

```
Seeded Postgres data
  ↓
POST /api/exposure-runs  →  creates exposure_run + task
  ↓
Worker claims task
  ↓
ExposureWorkflow executes steps (writes workflow_events at each step)
  ↓
Analytics layer: exposure → P&L → factor attribution → risk metrics → limits
  ↓
ReportAgent: generates executive summary + markdown report
  ↓
Results persisted: exposure_metrics, risk_alerts, daily_reports
  ↓
UI polls GET /api/exposure-runs/{id}  →  shows live status + timeline
  ↓
Dashboard renders metrics, charts, alerts, report
```
