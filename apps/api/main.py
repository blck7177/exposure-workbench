"""FastAPI main application — Exposure Workbench API."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth import internal_token
from apps.api.routes import portfolios, exposure_runs, tasks, market_data, research, agent, issuers, me, securities

settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Refuse to serve without the key the tool face is reached with (R5).

    Every chat turn mints an internal bearer, so an empty MCP_INTERNAL_SECRET
    means every turn fails — but it failed at the FIRST TURN, which is after the
    quota was charged and committed, and it reached the user as a 500. The
    container came up, the healthcheck passed, and the deployment looked fine
    until somebody talked to it. Startup is where a missing credential belongs,
    which is also where exposure-mcp and .env.example already say it is checked.

    In lifespan rather than at import: the offline suite imports this module to
    read the app's configuration, and a test that has no reason to know about
    the tool face should not need its key to collect.
    """
    internal_token.require_secret()
    yield


app = FastAPI(
    title="Exposure Workbench API",
    description="Portfolio exposure workflow: deterministic analytics + LLM reporting",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolios.router, prefix="/api", tags=["portfolios"])
app.include_router(exposure_runs.router, prefix="/api", tags=["exposure-runs"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(market_data.router, prefix="/api", tags=["market-data"])
app.include_router(research.router, prefix="/api", tags=["research"])
app.include_router(agent.router, prefix="/api", tags=["agent"])
app.include_router(issuers.router, prefix="/api", tags=["issuers"])
app.include_router(me.router, prefix="/api", tags=["identity"])
app.include_router(securities.router, prefix="/api", tags=["securities"])


@app.get("/")
async def root():
    return {
        "service": "Exposure Workbench API",
        "version": "0.1.0",
        "demo_mode": settings.demo_mode,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/health")
async def api_health():
    """The same check, reachable through the reverse proxy.

    In production Caddy routes only /api/* to this service and everything else to
    the web app, so a bare /health lands on Next.js and 404s — which reads as
    "the API is down" during exactly the smoke test meant to prove it is up.
    """
    return {"status": "ok"}
