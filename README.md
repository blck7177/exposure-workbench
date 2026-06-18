# Exposure Workbench

A **database-backed portfolio exposure workflow demo** — reads portfolio/market/limit data, executes deterministic risk calculations, and uses LLM/LangGraph to generate daily exposure briefings and management reports.

## Quick Start

```bash
# 1. Copy env file and add your API keys
cp .env.example .env

# 2. Start all services
docker compose up --build

# 3. Seed the demo database (run once)
pip install -e .
python scripts/seed_demo_db.py

# 4. Open the UI
open http://localhost:3103
```

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
