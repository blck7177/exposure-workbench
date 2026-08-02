"""Reading a brief back (V3-C1).

The meta-agent could commission an Issuer Risk Brief and then had no way to read
one — it spent a user's research quota on an artefact only the UI could see.
This is the read side.

What it returns is the block text plus THAT BLOCK'S OWN evidence ids, so the
agent transcribing a conclusion cites the filing passage or the calculation
underneath it. The brief id is returned as a plain string field and nothing
else: emitted as {"type": "brief", "id": ...} the wrapper would harvest it into
the evidence trail, and it would then pass the trail check and fail the
DB-existence check with a misleading "unresolved_in_db". A brief is a conclusion
drawn from evidence, not evidence — citing it would be a loop.

block_citations is NULL on briefs written before V3, because the flat citations
column is built with sorted(set(...)) at submit time and the association is
destroyed at the moment it is written. That is reported as the distinct fact it
is rather than reconstructed by guesswork.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import IssuerBrief

_BLOCKS = ("financial_summary", "key_changes", "management_explanation",
           "market_context", "portfolio_implications", "open_questions")


async def latest_visible(db: AsyncSession, company_id: str) -> dict | None:
    """The newest brief this caller may see, or None.

    Visibility is RLS: the policy on issuer_briefs shows a caller its own rows
    plus the public demo ones, so an anonymous reader gets the demo brief and
    another tenant's brief is simply not there. No WHERE clause here does that
    work, and adding one would only make it look as though it did.
    """
    brief = (await db.execute(
        select(IssuerBrief)
        .where(IssuerBrief.company_id == company_id)
        .order_by(IssuerBrief.created_at.desc())
    )).scalars().first()
    if brief is None:
        return None

    per_block = brief.block_citations or {}
    return {
        "brief_id": brief.id,               # a plain field: NOT a citable ref
        "created_at": brief.created_at,
        # Whose reading this is. RLS shows a caller its own briefs AND the public
        # demo ones, so "I can see it" and "I commissioned it" are different
        # facts, and without this the agent reports the demo's conclusions back
        # to a user as though they had paid for them. Same field name and same
        # reasoning as the portfolio snapshot's is_own — semantic, not security.
        "is_own": brief.owner_id is not None and brief.owner_id == current_user_id(),
        # The run this came out of: an rrun_ is not citable evidence, but it is
        # what get_task_status takes, so the agent can say when it was produced
        # and what else that run did.
        "research_run_id": brief.research_run_id,
        "blocks": {
            name: {
                "text": getattr(brief, name),
                # Present per block only for briefs written since V3; older rows
                # carry the flat list alone and say so by omission rather than by
                # having it invented for them.
                **({"citations": per_block[name]} if name in per_block else {}),
            }
            for name in _BLOCKS
            if getattr(brief, name)
        },
        "citations": list(brief.citations or []),
        "has_block_citations": bool(per_block),
    }
