"""Securities search (V2-D) — typeahead over the investable universe.

Public read (security_master is shared, no RLS). Deterministic ranking; the UI
makes the user click a result, never auto-selecting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.session import get_db
from exposure_workbench.services import security_master_service

router = APIRouter()


@router.get("/securities/search")
async def search_securities(q: str = "", limit: int = 10, db: AsyncSession = Depends(get_db)):
    return await security_master_service.search(db, q, min(max(limit, 1), 25))
