"""FastAPI main application — Exposure Workbench API."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from exposure_workbench.app_state.settings import get_settings
from apps.api.routes import portfolios, exposure_runs, tasks, market_data, research, agent

settings = get_settings()

app = FastAPI(
    title="Exposure Workbench API",
    description="Portfolio exposure workflow: deterministic analytics + LLM reporting",
    version="0.1.0",
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


@app.get("/")
def root():
    return {
        "service": "Exposure Workbench API",
        "version": "0.1.0",
        "demo_mode": settings.demo_mode,
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
