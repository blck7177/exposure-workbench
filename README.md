# Exposure Workbench — Portfolio Exposure Analytics + Issuer Intelligence

A **database-backed portfolio risk + issuer intelligence application**. On top of the
original deterministic exposure workflow it adds, per issuer: SEC filing + XBRL fact
ingestion, deterministic financial analytics on an append-only calc ledger,
pgvector filing retrieval, an evidence-gated Issuer Risk Brief, and a single
meta-agent the user talks to — every factual answer traceable to a fact, a
calculation, a filing passage or a research source.

Every LLM-generated tool call travels over MCP to a container of its own.
`exposure-mcp` is resident — streamable HTTP, stateless, reachable only on the
compose network — and serves one mount per face: `/mcp/meta` for the meta-agent,
`/mcp/research` for the research subagent, each with its own registry built from
the one set of tool definitions and budget / schema / citation / audit
enforcement in a single wrapper below the transport. The loops are clients: the
api mints an internal 30-minute bearer per chat turn, the worker per research
run, and a middleware in front of each mount verifies it and binds that
request's tenant —
identity travels with the request, because a server that outlives the turn
cannot hold the turn's tenant. The face an agent sees is the mount it reached
minus whatever its token denies, so a skip flag takes `search_external_research`
out of the tool list rather than leaving a tool that refuses. The LLM call stays
in the loop and never crosses MCP. Deterministic code (recipes, REST wrappers)
calls the same functions through the same wrapper directly, in process, and a
standing parity test pins that both produce identical trace rows.
See docs/MCP_PLAN.md.

## Quick Start

```bash
# 1. Copy env and add keys. Needs (real data, no mocks): OPENAI_API_KEY,
#    TAVILY_API_KEY, EDGAR_IDENTITY ("Name email@domain"). See .env.example.
#    MCP_INTERNAL_SECRET is required too (openssl rand -hex 32): it signs the
#    bearer the agent loops carry to the tool container. Left empty,
#    exposure-mcp refuses to start and the api and the worker refuse to mint
#    one on the first turn or run — nothing runs unsigned.
#    Clerk keys are OPTIONAL: leave them blank and the app runs as an anonymous
#    read-only demo. Fill them in to enable sign-in and per-user portfolios.
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

### Signed in vs anonymous

Reads are public, writes need an account. Anonymous visitors see the demo
portfolio and its runs, briefs and evidence — that is the shop window and it is
meant to work without signing up. Everything that costs something (chat, running
an analysis, uploading a portfolio) requires signing in and lands in that user's
own tenant.

Isolation is enforced by Postgres row-level security, not by application `WHERE`
clauses: the runtime connects as a non-owner role, and an unset tenant sees only
rows explicitly marked public. Company-level evidence — filings, facts, prices,
the calculation ledger — is deliberately shared, because it is public fact and
copying it per user would be both wasteful and inconsistent.

Each account gets a daily allowance (chat turns, analysis runs, research runs)
visible at `GET /api/me/usage` and in the chat panel's header. Limits, tenancy,
concurrency and audit are described in [docs/PRODUCTION.md](docs/PRODUCTION.md).

Design docs: [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md) (v3),
[docs/MODULE_NOTES.md](docs/MODULE_NOTES.md) (M1–M13),
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) (P0–P9),
[docs/spikes/P9_COVERAGE.md](docs/spikes/P9_COVERAGE.md) (final validation).

A stdio debug door onto the same tool face runs via
`MCP_STDIO_USER_ID=user_... python -m apps.mcp.server` — the same server
constructor the mounts use, in process, over stdio; the identity is required,
checked against the users table, and bound as the same claims object an HTTP
request arrives with.

## Architecture

```
                      ┌──────────────────────────────────┐
  browser  ──HTTPS──▶ │ Caddy (production; same origin)  │
                      │   /api/*  →  8103    else → 3103 │
                      └──────────────────────────────────┘
                              │                  │
                     FastAPI (8103)        Next.js UI (3103)
                              │
                      Postgres 16 + pgvector (5433, loopback only)
                              ↑
                     Worker (async polling, lease + reaper)
                              ↓
                   ExposureWorkflow (deterministic, 11 steps)
                      ├── analytics/
                      └── agents/ (LLM report)

     FastAPI and Worker ──Bearer──▶ exposure-mcp (the agent tool face:
        /mcp/meta + /mcp/research; compose network, plus a loopback-only
        host port so the live parity guard can reach it)
```

In production the UI and the API share one origin, so the browser never makes a
cross-origin request and there is no CORS to configure. Locally there is no proxy
and the UI is built with an explicit API base — which is why that value is a
build argument, not a runtime setting.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full design.

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16 + React 19 + TypeScript + Tailwind |
| API | FastAPI + Pydantic v2 |
| Worker | Python async polling loop |
| Database | PostgreSQL 16 |
| Analytics | pandas + numpy + scipy |
| Report Agent | OpenAI |
| Identity | Clerk (optional; blank keys = anonymous demo) |
| Tenancy | Postgres row-level security |
| Orchestration | LangGraph (optional) |

## Demo Data

The demo uses a seeded PostgreSQL database simulating an internal portfolio system.
Portfolio: **US Growth & Income** — 8 equities + 2 ETFs (AAPL/MSFT/NVDA/AMZN/GOOGL/JPM/XOM/LLY/TLT/HYG).
It is public and read-only: anyone can look at it, and running or editing it means
cloning it into your own account first. Signed-in users can also upload their own
holdings as CSV against the full US listed universe.

## Development

```bash
# Run API locally (requires Postgres running)
uvicorn apps.api.main:app --reload --port 8103

# Run worker locally
python -m apps.worker.worker

# Run tests — offline by default (no DB, no network, no keys)
pytest -m "not live"

# The live suite needs the stack up; it exercises RLS, the lease reaper and the
# quota counters against a real Postgres.
pytest -m live
```

Deployment, and what is actually enforced once the link is public:
[docs/PRODUCTION.md](docs/PRODUCTION.md), [infra/Caddyfile.example](infra/Caddyfile.example).
