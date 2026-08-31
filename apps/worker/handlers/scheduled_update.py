"""Scheduled update handler — sync first, resolve the date second, mint third
(V13 §9-④A).

This is a DOOR, not a workflow: it does for the 06:30 clock what the
POST /exposure-runs route does for a person — syncs the book's market data,
resolves the reporting date, and mints an exposure run plus its exposure_update
task. The run itself then goes through the ordinary task machinery under its
own lease.

WHY THE PRE-SYNC EXISTS when ExposureWorkflow's own first step is sync_prices:
the workflow's sync covers the RUN's window, [as_of - lookback, as_of] — it
deliberately refreshes only the stretch the run reads, so it can never move
as_of forward. as_of is stamped at mint time from latest_session_date() and
honoured exactly downstream. At 06:30 the newest session in the store is
whatever the last run left there; minting before syncing would pin the report
to that stale session, and the fresh bars the workflow fetched minutes later
could not unpin it. So: sync to now, THEN read the newest session, THEN stamp
it. The workflow's own sync still runs and still earns its place — it is what
puts the refresh on the run's visible timeline, and what keeps a person's runs
honest too.

Failure honesty (V13-S2): nothing here is caught. A provider outage, a book
with no priced session, a quota exhausted — each fails this task with the real
exception, the worker machinery records it, and no run row exists to strand
because the mint is the LAST thing that happens.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

# The ticker universe comes from the same sources of truth the market_data_sync
# door reads: the benchmark constant and the factor panel from
# configs/factor_config.yaml. Holdings are scoped to THIS portfolio, not every
# portfolio — the clock fires per book.
from apps.worker.handlers.market_data_sync import _BENCHMARK, _factor_tickers
from exposure_workbench.db.models import Position
from exposure_workbench.providers.yfinance_market_data_provider import (
    YFinanceMarketDataProvider,
)
from exposure_workbench.services import (
    exposure_run_service,
    market_data_service,
    portfolio_service,
    task_service,
)
from exposure_workbench.services.market_data_ingestion_service import (
    ingest_factor_prices,
    ingest_market_prices,
)
from exposure_workbench.services.schedule_service import TRIGGERED_BY_SCHEDULER

logger = logging.getLogger(__name__)

# Same window as the market_data_sync door's default: the upsert makes the
# overlap free, and inventing a second number here would just be a second thing
# to keep aligned with what the regressions read.
_LOOKBACK_DAYS = 365


async def handle(db: AsyncSession, task: Any) -> None:
    """Runs under the schedule's owner tenant — the worker restored it from
    task.owner_user_id (V2-A) — so the portfolio read, the quota charge and the
    run row all land as that user."""
    payload = task.payload or {}
    portfolio_id = payload.get("portfolio_id")
    schedule_id = payload.get("schedule_id")
    if not portfolio_id:
        raise ValueError(f"Task {task.id} missing portfolio_id in payload")

    # Owner comes from the portfolio row, not the payload copy: the payload is
    # an audit trail of what the tick saw, and the row is what is true now.
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if portfolio is None:
        raise ValueError(
            f"Task {task.id}: portfolio {portfolio_id} not visible under this "
            f"task's tenant — schedule {schedule_id} points at a book its owner "
            "no longer holds"
        )

    logger.info(
        "[scheduled_update] schedule %s: syncing %s before minting",
        schedule_id, portfolio_id,
    )

    # (1) Sync — holdings + benchmark into market_prices, the factor panel into
    # factor_prices, through the same ingestion functions market_data_sync uses.
    tickers = [
        t for (t,) in (
            await db.execute(
                select(Position.ticker)
                .where(Position.portfolio_id == portfolio_id)
                .distinct()
            )
        ).all()
    ]
    market_tickers = list(dict.fromkeys([*sorted(tickers), _BENCHMARK]))
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    provider = YFinanceMarketDataProvider()
    await ingest_market_prices(db, market_tickers, start, end, provider)
    factor_tickers = _factor_tickers()
    if factor_tickers:
        await ingest_factor_prices(db, factor_tickers, start, end, provider)

    # (2) Resolve the reporting date AFTER the sync — the whole point of this
    # handler's ordering; see the module docstring.
    as_of = await market_data_service.latest_session_date(db)
    if as_of is None:
        raise ValueError(
            f"Task {task.id}: no priced session exists even after syncing "
            f"{portfolio_id} — nothing to report on"
        )

    # (3) Mint, exactly the way the API door does — task, run, and the run id
    # written back into the task's payload. triggered_by is this door's own
    # constant (V13-S1): the payload's copy is never read.
    child = await task_service.create_task(
        db,
        task_type="exposure_update",
        payload={
            "portfolio_id": portfolio_id,
            "as_of_date": as_of.isoformat(),
            "triggered_by": TRIGGERED_BY_SCHEDULER,
        },
        owner_user_id=portfolio.owner_id,
    )
    run = await exposure_run_service.create_run(
        db,
        portfolio_id=portfolio_id,
        as_of_date=as_of,
        task_id=child.id,
        triggered_by=TRIGGERED_BY_SCHEDULER,
    )
    child.payload = {**child.payload, "run_id": run.id}
    flag_modified(child, "payload")

    logger.info(
        "[scheduled_update] schedule %s minted run %s (task %s) for %s as of %s",
        schedule_id, run.id, child.id, portfolio_id, as_of,
    )
