"""Meta-agent-face tools (M10) — delegation + the respond gate.

Delegation tools only ENQUEUE (non-blocking): they return a run/task id
immediately, never wait for completion, so the meta-agent stays responsive and
the heavy work runs on the worker. respond is the meta-agent's exit, gated by the
same citation check as submit_brief (lighter: chat replies may cite nothing, but
whatever they cite must be real).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import Company
from exposure_workbench.services import company_service, research_run_service, task_service, usage_service
from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services import evidence_trail_service as trail
from exposure_workbench.services import numeric_verification as numeric
from exposure_workbench.services import trajectory_gate
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, Tool, ToolRegistry, current_message_id, current_session_id,
)

logger = logging.getLogger(__name__)


# ── delegation (enqueue-only, non-blocking) ─────────────────────────────────────

async def _ensure_company_ready(db: AsyncSession, ticker: str, reason: str) -> dict:
    tk = ticker.upper()
    try:
        await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": tk}
    except company_service.NotInvestigable:
        return {"error": "not_investigable", "ticker": tk}
    try:
        task = await task_service.create_task(db, task_type="company_readiness", payload={"ticker": tk},
                                              owner_user_id=current_user_id())
    except usage_service.QuotaExceeded as e:
        # Roll back before returning. charge() debits the user pool and then the
        # global backstop in one transaction; when the backstop refuses, this
        # tool RETURNS rather than raising, and meta_agent commits the session
        # straight afterwards — making the user's debit permanent for an action
        # that never ran. The session holds only this tool call, so discarding it
        # is exactly right.
        await db.rollback()
        return e.as_dict() | {"ticker": tk}
    task.payload = {**task.payload, "run_id": task.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "task_id": task.id, "kind": "company_readiness", "ticker": tk, "reason": reason}


async def _start_issuer_research(db: AsyncSession, ticker: str, reason: str) -> dict:
    tk = ticker.upper()
    try:
        company = await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": tk}
    except company_service.NotInvestigable:
        return {"error": "not_investigable", "ticker": tk}
    # Precheck before enqueuing: create_run raises ActiveRunExists only after the
    # task exists, and on this path the tool RETURNS normally, so meta_agent
    # commits — leaving an orphan task the worker is guaranteed to fail, and a
    # quota unit spent on a request that never had a chance.
    active = await research_run_service.get_active_run(db, company.id)
    if active is not None:
        return {"error": "active_run_exists", "run_id": active.id, "ticker": tk}
    try:
        task = await task_service.create_task(db, task_type="issuer_research", payload={"ticker": tk},
                                              owner_user_id=current_user_id())
    except usage_service.QuotaExceeded as e:
        # Roll back before returning. charge() debits the user pool and then the
        # global backstop in one transaction; when the backstop refuses, this
        # tool RETURNS rather than raising, and meta_agent commits the session
        # straight afterwards — making the user's debit permanent for an action
        # that never ran. The session holds only this tool call, so discarding it
        # is exactly right.
        await db.rollback()
        return e.as_dict() | {"ticker": tk}
    try:
        run = await research_run_service.create_run(
            db, company.id, None, triggered_by=f"agent:{current_session_id()}", task_id=task.id,
            owner_id=current_user_id(),
        )
    except research_run_service.ActiveRunExists as e:
        # Lost the race between the precheck above and create_run's own re-read.
        # Roll back: create_task has already charged a research unit and inserted
        # a tasks row, and this tool RETURNS rather than raises, so meta_agent
        # would commit both — costing the user one of three daily runs and
        # leaving an orphan task the worker is guaranteed to fail.
        await db.rollback()
        return {"error": "active_run_exists", "run_id": e.run_id, "ticker": tk}
    task.payload = {**task.payload, "run_id": run.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "run_id": run.id, "kind": "issuer_research", "ticker": tk, "reason": reason}


async def _start_exposure_run(db: AsyncSession, portfolio_id: str, reason: str,
                              as_of_date: str | None = None) -> dict:
    from exposure_workbench.services import exposure_run_service, portfolio_service
    # Only run portfolios the user owns — the public demo is read-only.
    # semantic, not security: the RLS WITH CHECK is the real stop; this just gives
    # the agent a structured error instead of an aborted transaction.
    pf = await portfolio_service.get_portfolio(db, portfolio_id)
    if pf is None or pf.owner_id != current_user_id():
        return {"error": "not_your_portfolio", "portfolio_id": portfolio_id,
                "detail": "you can only run a portfolio you own; clone the demo to run it"}
    # The reporting date is a server fact, not something for the model to guess:
    # an LLM-supplied date reached the workflow completely unchecked, and "today"
    # before the close compares the newest bar against itself.
    from exposure_workbench.services import market_data_service
    if as_of_date:
        try:
            as_of = __import__("datetime").date.fromisoformat(as_of_date)
        except ValueError:
            # Typed, like every other bad-argument case here. Flattened to
            # tool_error the model cannot tell "you formatted the argument wrong,
            # drop it" from "the server broke".
            return {"error": "invalid_as_of_date", "as_of_date": as_of_date,
                    "detail": "expected YYYY-MM-DD, or omit it for the last completed session"}
    else:
        as_of = await market_data_service.latest_session_date(db)
        if as_of is None:
            return {"error": "no_price_data", "detail": "no market prices are loaded yet"}

    try:
        task = await task_service.create_task(
            db, task_type="exposure_update",
            payload={"portfolio_id": portfolio_id, "as_of_date": as_of.isoformat()},
            owner_user_id=current_user_id(),
        )
    except usage_service.QuotaExceeded as e:
        await db.rollback()   # see _ensure_company_ready: never commit a half charge
        return e.as_dict() | {"portfolio_id": portfolio_id}
    run = await exposure_run_service.create_run(
        db, portfolio_id=portfolio_id, as_of_date=as_of,
        task_id=task.id, triggered_by=f"agent:{current_session_id()}",
    )
    task.payload = {**task.payload, "run_id": run.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "run_id": run.id, "kind": "exposure_update", "reason": reason}


# ── respond gate ────────────────────────────────────────────────────────────────

async def _respond_blocks(db: AsyncSession, blocks: list) -> dict:
    """V14-C. The exit, when the answer is blocks and its figures are slots.

    The inversion this batch is about: the gate stops checking numbers the model
    wrote and starts RESOLVING references the model gave. Nothing here reads a
    figure out of a sentence, because a sentence may not contain one.

    The order is the prose gate's, and for the same reasons. Shape first, because
    it costs no queries. Then the ids, because a claim resting on an id that was
    never returned is not worth resolving. Then the sentences the model did write
    — quotes are still a claim of verbatim reproduction. Then the slots. Then the
    two assertion classes, which no numeric check can see. The trajectory
    criteria last and unchanged, still budget-free, still escapable by editing
    the reply alone.
    """
    problems = ab.validate_shape(blocks)
    if problems:
        return {"error": "malformed_answer", "problems": problems,
                "detail": "an answer is a list of blocks; every figure is a slot naming "
                          "the evidence it comes from. Text carries the sentence"}

    refs = ab.refs_in(blocks)
    prose = ab.text_of(blocks)

    if refs:
        ok, bad_ids = await trail.validate_citations(db, current_session_id(), refs)
        if not ok:
            return {"error": "invalid_citations", "problems": bad_ids,
                    "detail": "every id an answer leans on must come from a tool result "
                              "you called this session"}

        bad_quotes = numeric.verify_quotes(
            prose, await numeric.resolve_cited_passages(db, refs))
        if bad_quotes:
            return {"error": "unverified_quote", "problems": bad_quotes,
                    "detail": "quotation marks say these words appear in a cited passage "
                              "exactly as written. Reproduce the source wording, cite the "
                              "passage that carries it, or drop the marks and paraphrase"}

        values, _quoted = await numeric.resolve_cited_values(db, refs)
        resolved, slot_problems = ab.resolve(blocks, values)
        if slot_problems:
            return {"error": "unresolved_slots", "problems": slot_problems,
                    "detail": "each slot names one figure held by the id it points at. A "
                              "problem carrying `available` lists the labels that id holds"}

        assertion_problems = ab.check_assertion_refs(
            blocks, await trail.rows_for(db, refs))
        if assertion_problems:
            return {"error": "unsupported_assertion", "problems": assertion_problems,
                    "detail": "a claim about a sequence, and a claim that something was "
                              "not reported, each rest on the row that recorded it"}
    else:
        resolved = []
        # No refs at all is legitimate — a greeting, a clarifying question — and
        # the shape check has already established there are no slots to resolve,
        # because a slot without a ref is refused there. Nothing further to do.

    trajectory = await trajectory_gate.check(
        db, current_session_id(), current_message_id(), prose, refs)
    if trajectory:
        return trajectory

    filled = ab.rendered(blocks, resolved)
    # Two strings, and they are not the same string. `prose` is what the model
    # WROTE — the quote rule and the trajectory criteria read it, and a figure
    # the ledger supplied must not appear there or it would be judged as the
    # model's wording. What is returned as the answer's text has the figures put
    # back, because "net rates exposure is , and it loses if rates rise" is not
    # an answer, and that is what a transcript or a reader without a block
    # renderer would otherwise be shown.
    return {"responded": True, "format": "blocks",
            "blocks": filled, "text": ab.prose_of(filled),
            "citations": refs,
            "verified": {"figures": len(resolved), "sources": len(refs),
                         "matches": [{"label": r.label, "value": r.value,
                                      "unit_class": r.unit_class, "source_id": r.ref}
                                     for r in resolved]}}


async def _respond(db: AsyncSession, text: str, citations: list[str] | None = None) -> dict:
    """Meta-agent exit. A reply that states no number may cite nothing — a
    greeting or a clarifying question is not a factual claim. A reply that states
    a number must cite, and any cited id must be in the session's evidence trail
    and resolve in the DB.

    The empty-citations branch reaches `db` only through the trajectory check,
    and that check returns before its first query when there is no message scope
    — which is the case in every direct call. So a refusal about numbers or
    citations is still provable without a database, and a test passing None gets
    the same answer production does.

    That is a weaker statement than the one this docstring used to make ("never
    touches db"), and the criterion is what changed it: R2 is about a turn that
    enqueued six research runs and mentioned none, and such a reply cites nothing
    at all. A criterion that skipped the uncited branch would skip the shape it
    exists to catch.
    """
    # A non-string citation is REFUSED, not dropped. Dropping it was the worse
    # of the two, and the schema comment below already said so: tool results are
    # object-shaped ({"type": ..., "id": ...}), so a model citing what it just
    # read back is the likely author of one — and the silent filter turned that
    # into an answer with NO citations, which then failed the numbers gate with
    # "call a tool to get them first" when it had already called one. The model
    # was told to do the thing it had done.
    malformed = [c for c in (citations or []) if not isinstance(c, str)]
    if malformed:
        return {
            "error": "invalid_citations",
            "problems": [
                {"citation": repr(c), "reason": "not_a_string"} for c in malformed
            ],
            "detail": "cite the plain id string, e.g. 'alert_1a2b3c', not the object it came in",
        }

    citation_ids = list(citations or [])
    # Bound on every path out of the checks below, because the successful return
    # reads it unconditionally: an answer with no numbers in it verified nothing,
    # and saying "0 figures checked" is the true statement about it.
    verified: list[dict] = []

    if citation_ids:
        ok, problems = await trail.validate_citations(db, current_session_id(), citation_ids)
        if not ok:
            # An answer that states no numbers may cite nothing, and a model that
            # does not know that invents ids to satisfy the gate. Measured: every
            # "this cannot be produced" answer in the battery hit this refusal —
            # three for three — and worked up through citing tool names and
            # `co_jpm` to inventing `run_?` before landing on the empty list that
            # was correct all along.
            return {"error": "invalid_citations", "problems": problems,
                    "detail": ("cited ids must come from tool results you called this "
                               "session" + ("; this reply states no numbers, so an empty "
                                            "citations list is correct here"
                                            if not numeric.extract_numbers(text) else ""))}
        # The ids are real; now what the answer asserts about them has to be.
        # Quotation marks first: they are a claim of verbatim reproduction, and
        # a filings answer can be pure prose with no number in it — in which case
        # everything below this ran on an empty list and the reply passed having
        # been checked for nothing at all.
        bad_quotes = numeric.verify_quotes(
            text, await numeric.resolve_cited_passages(db, citation_ids))
        if bad_quotes:
            return {"error": "unverified_quote", "problems": bad_quotes,
                    "detail": "quotation marks say these words appear in a cited passage "
                              "exactly as written. Reproduce the source wording, cite the "
                              "passage that carries it, or drop the marks and paraphrase — "
                              "a paraphrase is not checked here and does not claim to be "
                              "verbatim"}
        stated = numeric.extract_numbers(text)
        if stated:
            values, quoted = await numeric.resolve_cited_values(db, citation_ids)
            bad, verified = numeric.verify_with_matches(stated, values, quoted)
            if bad:
                # Three options, and the third one matters. Observed live: asked
                # to summarise a pre-V3 brief, the agent hit this three times
                # running and then gave up with an apology — because the brief
                # itself states figures its own citations do not support, and
                # neither re-citing nor recomputing can conjure evidence that was
                # never there. Omitting the figure and answering with the rest is
                # a legitimate, honest move, and the model has no way to know
                # that unless the refusal says so.
                # A number refused for being indeterminate needs different
                # advice from one refused for being absent: re-citing cannot fix
                # it, and each problem already names what IS determinate.
                if all(p["reason"] == "not_quotable_individually" for p in bad):
                    return {"error": "unverified_numbers", "problems": bad,
                            "detail": "these figures are real, and the rows carrying them "
                                      "record that they are not determined on their own. "
                                      "Quote the aggregate each problem names, or say the "
                                      "direction without the coefficient"}
                return {"error": "unverified_numbers", "problems": bad,
                        "detail": "each number must match a value held by the evidence you "
                                  "cited. Re-cite the id that actually carries it, compute it "
                                  "with a tool so it has one (a problem carrying `derivable` "
                                  "names the exact call), or leave that figure out and answer "
                                  "with what you can support — a partial answer that holds up "
                                  "is worth more than a complete one that does not. Do not "
                                  "swap in a different measure because it is easier to cite"}
    else:
        # Zero citations used to skip validation entirely, so a reply made
        # entirely of numbers passed the gate untouched — the one shape the gate
        # exists to stop. Enforced here rather than by making `citations` a
        # required schema field, because that would also block the number-free
        # replies this branch deliberately allows.
        stated = numeric.extract_numbers(text)
        if stated:
            return {"error": "citations_required",
                    "numbers_found": numeric.raw_forms(stated),
                    "detail": "a reply that states numbers must cite the evidence ids "
                              "they came from; call a tool to get them first"}

    # V8-C2. The last thing checked, and the only one that looks at the TURN
    # rather than at the answer. Placed after the citation and number checks
    # because those are cheaper and because a trajectory complaint about an
    # answer whose ids are fake would be the less useful of two true refusals.
    #
    # Both refusals here are escapable by editing the reply alone — the gate is
    # budget-free, so a turn that has spent everything can still take either
    # exit. That is DP4, and it is the property V7-Q2 was the absence of.
    trajectory = await trajectory_gate.check(
        db, current_session_id(), current_message_id(), text, citation_ids)
    if trajectory:
        return trajectory

    # What the gate found, kept rather than discarded (V13-S3). Every figure that
    # got here matched something a cited row holds — the gate has always known
    # which, and has always thrown it away the moment it decided not to refuse.
    #
    # Keeping it is the difference between a product whose numbers are checked
    # and one that says its numbers are checked: the reader can be shown the
    # count, and can hover a figure to see what stands behind it. It is a record
    # of a check that already happened, not a new claim — nothing here can make
    # an answer pass that would not have passed anyway.
    return {"responded": True, "text": text, "citations": citation_ids,
            "verified": {"figures": len(verified), "sources": len(citation_ids),
                         "matches": verified}}


# ── registration ────────────────────────────────────────────────────────────────

def register_meta_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="ensure_company_ready",
        display="Preparing {ticker}'s filings and prices",
        description="Enqueue a data-readiness pass for an issuer (ingest/index/price). Returns immediately.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string", "description": "why readiness is needed now"},
        }, "required": ["ticker", "reason"], "additionalProperties": False},
        fn=_ensure_company_ready, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="start_issuer_research",
        display="Starting a research run on {ticker}",
        description="Enqueue a full issuer research run (produces an Issuer Risk Brief). Returns a run id immediately.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string"},
        }, "required": ["ticker", "reason"], "additionalProperties": False},
        fn=_start_issuer_research, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="start_exposure_run",
        display="Starting an exposure run",
        description="Enqueue a portfolio exposure run. Returns a run id immediately.",
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
            # Nullable because the description tells the model to omit it, and
            # a model that has decided not to use an optional argument says so
            # with null about as often as by leaving it out.
            "as_of_date": {"type": ["string", "null"], "description":
                "YYYY-MM-DD. Omit unless the user asked for a specific date — "
                "the server reports on the last completed session by default."},
            "reason": {"type": "string"},
        }, "required": ["portfolio_id", "reason"], "additionalProperties": False},
        fn=_start_exposure_run, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="respond",
        display="Resolving every figure against the ledger, then answering",
        description=(
            "Reply to the user. An answer is a list of BLOCKS, and every figure in it is a "
            "SLOT naming the evidence it comes from — you do not write numbers into "
            "sentences, because the ledger's own value is what the reader is shown. "
            "Blocks: `paragraph` (runs: a list mixing strings and slots, in reading order), "
            "`metric_table` (columns + rows, each cell a string or a slot — use it whenever "
            "you are comparing or ranking), `chart` (kind bar/line/waterfall + series_ref, "
            "the calc id of a series you read), `trend` (text + series_ref: a claim that "
            "something rose or fell rests on the sequence it was read from), `absence` "
            "(text + absence_ref: a claim that something was not reported rests on the row "
            "the refused read minted). A slot is {ref, label} or {ref, value} — label is "
            "the ledger's own name for the figure, value is the figure as the tool "
            "returned it — a NUMBER either way. Everything that is not a figure is "
            "text: ids, tickers, dates, period labels and whole sentences go in the "
            "run beside the slot, not inside it. A reply that states nothing factual "
            "needs no slots at all."
        ),
        json_schema={"type": "object", "properties": {
            "blocks": {
                "type": "array",
                "description": "the answer, in reading order",
                "items": {"type": "object", "properties": {
                    "type": {"type": "string",
                             "enum": list(ab.BLOCK_TYPES)},
                    "runs": {"type": "array",
                             "description": "paragraph only: strings and slots in order",
                             "items": {"type": ["string", "object"]}},
                    "columns": {"type": "array", "items": {"type": "string"},
                                "description": "metric_table only: the column headings"},
                    "rows": {"type": "array",
                             "description": "metric_table only: one list of cells per row, "
                                            "each cell a string or a slot",
                             "items": {"type": "array",
                                       "items": {"type": ["string", "object"]}}},
                    "title": {"type": "string"},
                    "text": {"type": "string",
                             "description": "trend and absence only: the claim, without figures"},
                    "kind": {"type": "string", "enum": list(ab.CHART_KINDS),
                             "description": "chart only"},
                    "series_ref": {"type": "string",
                                   "description": "chart and trend only: the calc id of the series"},
                    "absence_ref": {"type": "string",
                                    "description": "absence only: the calc id of the recorded refusal"},
                }, "required": ["type"], "additionalProperties": False},
            },
            # The sharpest of the nullable cases: respond is the session's only
        }, "required": ["blocks"], "additionalProperties": False},
        fn=_respond_blocks, tool_class=GATE,
    ))
    return reg
