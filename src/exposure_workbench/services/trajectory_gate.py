"""V8-C2 — two criteria about what the turn DID, checked at the exit (M17).

Every gate before this one asks about the answer: are the cited ids real, do the
numbers appear in the cited evidence, is a figure stated without a source. None
of them can see the SHAPE of the work, and two failures live entirely in that
shape.

  R1  An answer that attributes a portfolio's move to an issuer's filings, having
      never looked at what the positions actually contributed. Every sentence in
      it can be individually true and cited. The causal claim joining them is the
      part nothing checked, and it is the part the reader acts on. Observed: the
      question "why are there large drawdowns" produced fifteen tool calls, all
      of them filing retrieval, and an answer built from risk-factor disclosure —
      standing text that was equally true on every day the book rose.

  R2  Six research runs enqueued and none of them mentioned. Enqueuing is a
      commitment of the desk's quota and of the user's waiting; a turn that
      spends it silently leaves work in flight that nobody knows to collect.

Both refusals are escapable at ZERO tool cost, which is DP4 and not a nicety:
V7-Q2 produced a gate that could only be satisfied by spending a budget already
exhausted, and the turn then had no exit at all. R1 is satisfied by dropping the
filing citation; R2 by naming ids the model already has in its context. Each
refusal says so in the sentence, because a refusal the model cannot act on is
indistinguishable to it from a broken server.

Scope is the MESSAGE, not the session. A session criterion would be satisfied by
a tool call from four questions ago — and would then be satisfied forever, which
is a criterion that stops criticising.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import AgentStep

# Evidence that speaks for the BOOK, and evidence that speaks for an ISSUER.
# R1 is about a sentence that joins the two.
_PORTFOLIO_PREFIXES = ("run_", "alert_")
_FILING_PREFIXES = ("chunk_", "src_")

# Tools whose result shows what the book's own positions did. Reading any of them
# is what R1 asks for.
#
# get_portfolio_snapshot is the weakest member and is included deliberately: it
# carries weights and daily returns rather than contributions, so it does not
# decompose the move — but it does put the book's own numbers in front of the
# model before it reaches for a filing, which is the ordering this criterion is
# about. Requiring the strongest tool would make the criterion a rule about
# which tool to call; requiring any of the three makes it a rule about looking.
_ATTRIBUTION_READS = ("get_attribution", "reconcile_move", "get_portfolio_snapshot")

_DELEGATION_TOOL = "start_issuer_research"
# Two is a turn that delegated and said which. Three is where "I have started
# some research" begins to hide the count.
_DELEGATION_SILENCE_LIMIT = 2


async def _steps(db: AsyncSession, session_id: str, message_id: str) -> list[AgentStep]:
    return list((await db.execute(
        select(AgentStep)
        .where(AgentStep.session_id == session_id, AgentStep.message_id == message_id)
        .order_by(AgentStep.seq))).scalars().all())


def _ids_from(step: AgentStep, prefix: str) -> list[str]:
    out = []
    for ref in step.evidence_refs or []:
        rid = ref.get("id") if isinstance(ref, dict) else ref
        if isinstance(rid, str) and rid.startswith(prefix):
            out.append(rid)
    return out


async def check(
    db: AsyncSession, session_id: str, message_id: str | None,
    text: str, citation_ids: list[str],
) -> dict | None:
    """The refusal, or None.

    `message_id` is None outside a turn (a direct call, the recipe path). There
    is no trajectory to judge then, and inventing a scope would mean judging one
    turn's answer against another turn's steps.
    """
    if message_id is None:
        return None

    steps = await _steps(db, session_id, message_id)
    completed = [s for s in steps if s.status == "completed"]

    # ── R1: order ─────────────────────────────────────────────────────────────
    cites_portfolio = [c for c in citation_ids if c.startswith(_PORTFOLIO_PREFIXES)]
    cites_filing = [c for c in citation_ids if c.startswith(_FILING_PREFIXES)]
    if cites_portfolio and cites_filing:
        looked = [s for s in completed if s.tool_name in _ATTRIBUTION_READS]
        if not looked:
            return {
                "error": "attribution_not_read",
                "problems": [{
                    "reason": "portfolio_claim_supported_by_filings_only",
                    "portfolio_citations": cites_portfolio,
                    "filing_citations": cites_filing,
                }],
                "detail": (
                    "this answer explains something about the portfolio using an issuer's "
                    "filings, and nothing in this turn read what the positions actually "
                    "contributed. A 10-K describes an issuer over quarters and cannot "
                    "account for a day. Two ways out: call get_attribution or "
                    "reconcile_move on the run and say what the numbers show, or drop the "
                    "filing-based claim and answer with the portfolio evidence alone — "
                    "the second costs no tool calls."
                ),
            }

    # ── R2: delegation restraint ──────────────────────────────────────────────
    enqueued: list[str] = []
    for s in completed:
        if s.tool_name == _DELEGATION_TOOL:
            enqueued.extend(_ids_from(s, "rrun_"))
    if len(enqueued) > _DELEGATION_SILENCE_LIMIT:
        missing = [rid for rid in enqueued if rid not in text]
        if missing:
            return {
                "error": "delegated_work_unreported",
                "problems": [{"reason": "enqueued_but_not_named", "run_ids": missing}],
                "detail": (
                    f"this turn started {len(enqueued)} research runs and the reply names "
                    f"{len(enqueued) - len(missing)} of them. Work in flight that the user "
                    "is not told about is work nobody collects. List every run id in the "
                    "text — you already have them, so this costs no tool calls."
                ),
            }

    return None
