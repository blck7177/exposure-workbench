"""The stdio debug door onto the tool face (M8/M10).

For local debugging: open an inspector against a running database and watch a
tool call land. The server itself is built by tools/mcp_server.py, which the
agents also use — this module is the stdio entry point and nothing else.

Two things it deliberately cannot do:

It cannot choose a database role. It used to build its own engine on
DATABASE_URL — the OWNER role, which bypasses row-level security — so the one
place a tool call reached the database outside the tenant mechanism was the
agent-facing one. It borrows the application's app_rls factory now, and a test
reads the import graph to keep it that way.

It cannot be anonymous. It ran every call under one process-global session with
owner_id=None, which meant the trace could not say whose work it was and RLS had
no tenant to scope to. MCP_STDIO_USER_ID is required, checked against the users
table before the first request, and there is no demo fallback: a debug door is
always opened by somebody.

What it can do is unchanged by MCP_PLAN R2, but how it says who it is is not.
The constructor no longer takes an identity, so this door binds the same
InternalClaims the HTTP mounts bind — once, at startup, because a stdio process
is exactly one caller for its whole life. It mints no token: there is no request
to authenticate here, and a self-issued one would let the process hand itself an
identity other than the one it just checked against the users table. So there is
still exactly one identity mechanism, read from one place, and the door only
differs in where the claims come from.

Run standalone over stdio:
    MCP_STDIO_USER_ID=user_... python -m apps.mcp.server
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from mcp.server.lowlevel import Server
from sqlalchemy import select

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.auth.internal_token import InternalClaims
from exposure_workbench.db.models import User
from exposure_workbench.db.session import get_session_factory
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import faces, mcp_request
from exposure_workbench.tools.mcp_server import build_mcp_server
from exposure_workbench.tools.registries import build_meta_registry

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("mcp-server")

STDIO_USER_ENV = "MCP_STDIO_USER_ID"


def stdio_user_id(env: dict | None = None) -> str:
    """Whose door this is. Absent or blank is a startup failure, not a default.

    A blank value is how a shell passes along a variable it does not have, so it
    is refused for the same reason an unset one is.
    """
    raw = (env if env is not None else os.environ).get(STDIO_USER_ENV) or ""
    user_id = raw.strip()
    if not user_id:
        raise RuntimeError(
            f"{STDIO_USER_ENV} is required: the stdio door runs as a real user so "
            "its trace can be attributed and RLS has a tenant to scope to. Set it "
            "to a row in the users table."
        )
    return user_id


class _Session:
    """The one agent session the stdio process records its work under."""

    user_id: str | None = None
    id: str | None = None


_session = _Session()


async def _open(user_id: str) -> str:
    """Validate the identity against the users table, then open the session.

    The check is a read under that user's own tenant, which is also the first
    proof that the GUC injection works from this entry point.
    """
    current_user_ctx.set(user_id)
    factory = get_session_factory()
    async with factory() as db:
        exists = (await db.execute(select(User.id).where(User.id == user_id))).scalar_one_or_none()
        if exists is None:
            raise RuntimeError(
                f"{STDIO_USER_ENV}={user_id!r} is not a row in users. The door does not "
                "create accounts; use an id that already exists."
            )
        # kind='mcp' so a debug session is distinguishable in the monitor from a
        # user's chat. per_turn=False because this is a process, not a
        # conversation: it never claims a turn, so a per-turn counter would be
        # spent once and never reset (V3-R6).
        s = await sess.create_session(db, kind="mcp", owner_id=user_id, per_turn=False)
        await db.commit()
        logger.info("stdio session %s opened for %s", s.id, user_id)
        return s.id


async def build_stdio_server() -> Server:
    """The debug door: whole meta face, real user, the app's own factory."""
    if _session.id is None:
        _session.user_id = stdio_user_id()
        _session.id = await _open(_session.user_id)
    # The claims the handlers read, stated by the process instead of arriving in
    # a header, and bound on every build rather than only on the first: whoever
    # runs the server this returns has to be holding the binding, and that is
    # not necessarily the task that opened the session. Never reset — an HTTP
    # request ends and a stdio connection does not, so there is nothing to
    # unwind and no second caller to unwind it for. deny is empty because a skip
    # flag belongs to a research run, and this door opens the whole meta face by
    # definition.
    mcp_request.bind(InternalClaims(
        user_id=_session.user_id,
        session_id=_session.id,
        face=faces.FACE_NAME_META,
    ))
    return build_mcp_server(
        build_meta_registry(),
        faces.FACE_META_AGENT,
        db_factory=get_session_factory(),
        face_name=faces.FACE_NAME_META,
    )


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    server = await build_stdio_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
