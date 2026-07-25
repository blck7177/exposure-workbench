"""SQLAlchemy async engine and session factory.

Tenant isolation (V2-C): the app connects as the non-owner role app_rls, so
Postgres RLS policies bind. WHO the request is for is carried in the
current_user_ctx contextvar; the `after_begin` listener below turns that into a
transaction-local `app.user_id` GUC at the start of EVERY transaction — the
single injection point for the request path, the agent loop and the worker
alike. Transaction-local (set_config ..., true) means it resets on commit, so a
pooled connection can never leak one user's tenant into the next request. Unset
=> current_setting returns NULL => RLS shows only is_public rows (fail-closed).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_ctx


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


@event.listens_for(Session, "after_begin")
def _apply_tenant(session, transaction, connection):
    """Set the RLS tenant for this transaction from the contextvar. Fires for the
    sync Session that AsyncSession wraps. No-op when the contextvar is unset
    (anonymous / shared-table access) — RLS then falls back to is_public only."""
    uid = current_user_ctx.get()
    if uid is not None:
        connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": uid})


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url_app or settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a DB session per request."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
