"""Evidence pack (M7): what a research session actually put on its table.

V15-S2a: the trail IS the table. What a session may cite is the union of what
its tools declared (services/table.py), and the pack a research run stores is
that set as a refs list. There is no separate walk over step payloads and no
separate existence check — a declared id was built from a row, so it exists.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import ledger as ledger_svc


async def collect_ids(db: AsyncSession, session_id: str) -> set[str]:
    """Every id on the session's table."""
    # V24: the facts the session was shown, and the rows they rest on — the
    # pack keeps both, so a brief's chip and its drill-through both resolve.
    led = await ledger_svc.load(db, session_id)
    refs = set(led.by_id)
    for rec in led.by_id.values():
        refs.update(s for s in (rec.get("sources") or []) if isinstance(s, str))
    return refs


async def materialize_pack(db: AsyncSession, session_id: str) -> list[dict]:
    """The table as a stored refs list (evidence_packs.pack). A refs list, not a
    snapshot — the append-only stores keep the referenced rows immutable."""
    return [{"id": rid} for rid in sorted(await collect_ids(db, session_id))]
