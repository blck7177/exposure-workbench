"""Market data sync handler (M4) — pull real prices via yfinance into Postgres.

Data-driven ticker set when the payload doesn't pin tickers:
  market_prices  <- distinct portfolio holdings + SPY (benchmark)
  factor_prices  <- tickers from configs/factor_config.yaml

Analytics read these persisted rows; they never call yfinance directly.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import Position
from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
from exposure_workbench.services.market_data_ingestion_service import (
    ingest_factor_prices,
    ingest_market_prices,
)

logger = logging.getLogger(__name__)

_BENCHMARK = "SPY"


async def _portfolio_tickers(db: AsyncSession) -> list[str]:
    result = await db.execute(select(Position.ticker).distinct())
    return [r for (r,) in result.all()]


def _factor_tickers() -> list[str]:
    path = Path(get_settings().configs_dir) / "factor_config.yaml"
    cfg = yaml.safe_load(path.read_text()) if path.exists() else {}
    return [
        c["ticker"]
        for c in (cfg.get("factors") or {}).values()
        if isinstance(c, dict) and "ticker" in c
    ]


async def handle(db: AsyncSession, task: Any) -> None:
    payload = task.payload or {}
    lookback = int(payload.get("lookback_days") or 365)
    end = date.today()
    start = end - timedelta(days=lookback)
    provider = YFinanceMarketDataProvider()

    pinned = payload.get("tickers")
    if pinned:
        # Explicit ticker set: market prices only (caller-directed).
        counts = await ingest_market_prices(db, list(pinned), start, end, provider)
        logger.info("[market_data_sync] pinned market rows: %s", counts)
        return

    holdings = await _portfolio_tickers(db)
    market_tickers = list(dict.fromkeys([*holdings, _BENCHMARK]))
    factor_tickers = _factor_tickers()

    mkt = await ingest_market_prices(db, market_tickers, start, end, provider)
    logger.info("[market_data_sync] market rows: %s", mkt)
    if factor_tickers:
        fac = await ingest_factor_prices(db, factor_tickers, start, end, provider)
        logger.info("[market_data_sync] factor rows: %s", fac)
