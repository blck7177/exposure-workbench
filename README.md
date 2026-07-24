# Exposure Workbench — Portfolio Exposure Analytics + Issuer Intelligence

A **database-backed portfolio risk + issuer intelligence application**. On top of the
original deterministic exposure workflow it adds, per issuer: SEC filing + XBRL fact
ingestion, deterministic financial analytics on an append-only calc ledger,
pgvector filing retrieval, an evidence-gated Issuer Risk Brief, and a single
meta-agent the user talks to — every factual answer traceable to a fact, a
calculation, a filing passage or a research source.

The agent tool surface is exposed identically over REST (for the UI) and MCP (for an
external agent host), with budget / citation / audit enforcement in one wrapper below
the transport.

## Quick Start

```bash
# 1. Copy env and add keys. Needs (real data, no mocks): OPENAI_API_KEY,
#    TAVILY_API_KEY, EDGAR_IDENTITY ("Name email@domain"). See .env.example.
cp .env.example .env

# 2. Start all services (postgres uses the pgvector image)
docker compose up --build

# 3. Seed the demo DB (pulls REAL yfinance prices + seeds companies).
#    NOTE: after any schema change, rebuild the DB volume first:
#      docker compose down -v && docker compose up --build
pip install -e ".[dev]"
python scripts/seed_demo_db.py

# 4. Open the UI, then click any issuer ticker to Investigate
open http://localhost:3103
```

Design docs: [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md) (v3),
[docs/MODULE_NOTES.md](docs/MODULE_NOTES.md) (M1–M13),
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) (P0–P9),
[docs/spikes/P9_COVERAGE.md](docs/spikes/P9_COVERAGE.md) (final validation).

The MCP server (same tool face as the UI) runs standalone via
`python -m apps.mcp.server`.

## Architecture

```
Next.js UI (3103)  →  FastAPI (8103)  →  Postgres (5433)
                                              ↑
                                     Worker (async polling)
                                              ↓
                                   ExposureWorkflow (deterministic)
                                      ├── analytics/
                                      └── agents/ (LLM report)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full design.

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 + TypeScript + Tailwind |
| API | FastAPI + Pydantic v2 |
| Worker | Python async polling loop |
| Database | PostgreSQL 16 |
| Analytics | pandas + numpy + scipy |
| Report Agent | OpenAI / Anthropic (switchable) |
| Orchestration | LangGraph (optional) |

## Demo Data

The demo uses a seeded PostgreSQL database simulating an internal portfolio system.
Portfolio: **US Growth & Income** — 8 equities + 2 ETFs (AAPL/MSFT/NVDA/AMZN/GOOGL/JPM/XOM/LLY/TLT/HYG).

## Development

```bash
# Run API locally (requires Postgres running)
uvicorn apps.api.main:app --reload --port 8103

# Run worker locally
python -m apps.worker.worker

# Run tests
pytest
```
