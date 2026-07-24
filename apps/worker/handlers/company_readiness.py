"""company_readiness task handler (M8 capability A)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.session import get_session_factory
from exposure_workbench.workflow.readiness_workflow import run_readiness

logger = logging.getLogger(__name__)


async def handle(db: AsyncSession, task: Any) -> None:
    payload = task.payload or {}
    ticker = payload.get("ticker")
    run_id = payload.get("run_id") or task.id
    if not ticker:
        raise ValueError(f"company_readiness task {task.id} missing ticker")
    logger.info("[company_readiness] %s (run %s)", ticker, run_id)
    await run_readiness(
        db, run_id, ticker,
        skip_market_refresh=bool(payload.get("skip_market_refresh")),
    )
