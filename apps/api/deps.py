"""FastAPI shared dependencies."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.session import get_db

# Re-export for use in route files
DbSession = AsyncGenerator[AsyncSession, None]
