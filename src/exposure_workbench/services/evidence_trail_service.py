"""Evidence pack (M7): what a research session actually put on its table.

V15-S2a: the trail IS the table. What a session may cite is the union of what
its tools declared (services/table.py), and the pack a research run stores is
that set as a refs list. There is no separate walk over step payloads and no
separate existence check — a declared id was built from a row, so it exists.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import table as tb


async def collect_ids(db: AsyncSession, session_id: str) -> set[str]:
    """Every id on the session's table."""
    return set((await tb.load(db, session_id)).refs)


async def materialize_pack(db: AsyncSession, session_id: str) -> list[dict]:
    """The table as a stored refs list (evidence_packs.pack). A refs list, not a
    snapshot — the append-only stores keep the referenced rows immutable."""
    return [{"id": rid} for rid in sorted(await collect_ids(db, session_id))]
