"""Market-data routes — enqueue a market_data_sync task. Pure enqueue, no judgment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import require_user
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.session import get_db
from exposure_workbench.services import task_service, usage_service

router = APIRouter()


# One quota unit buys ONE sync, so the sync itself has to be bounded — otherwise
# a single charged action could ask for ten thousand symbols over twenty years and
# spend the afternoon inside the price provider. The caps are generous for any
# real portfolio and ruinous for nobody.
MAX_SYNC_TICKERS = 50
MAX_LOOKBACK_DAYS = 365 * 5


class SyncRequest(BaseModel):
    # None => portfolio holdings + SPY + factor config
    tickers: list[str] | None = Field(default=None, max_length=MAX_SYNC_TICKERS)
    lookback_days: int = Field(default=365, ge=1, le=MAX_LOOKBACK_DAYS)


class SyncResponse(BaseModel):
    task_id: str
    status: str


@router.post("/market-data/sync", response_model=SyncResponse, status_code=201)
async def sync_market_data(
    body: SyncRequest,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await task_service.create_task(
            db,
            task_type="market_data_sync",
            payload={"tickers": body.tickers, "lookback_days": body.lookback_days},
            owner_user_id=user.user_id,
        )
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    await db.commit()
    return SyncResponse(task_id=task.id, status=task.status)
