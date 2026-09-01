"""Meta-agent (M10) — the single conversational entity the user talks to.

A thin tool-calling loop: it answers directly with the read tools when data is
ready, delegates heavy/unready work (non-blocking) and reports the run id, and
exits by calling respond. The system prompt states the role and the evidence
discipline's WHY — it is not a rulebook, because the architecture (ids required
to cite, wrapper-enforced budget/trace) is what actually constrains behaviour.

Its tools arrive over an MCP client from the resident tool face (MCP_PLAN P3,
R4): the same registry behind the same wrapper, reached the way this
architecture has said the agent face is reached since M10 — which until P3 it
was not, and which since R4 is a request to a container of its own.

History is persisted as agent_messages so a session survives across turns.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import update

from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import AgentMessage, AgentSession
from exposure_workbench.services import context_budget
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

_SYSTEM = """You are the analyst assistant for a portfolio risk & issuer-intelligence desk.

You can answer questions about the portfolio's issuers using financial facts and \
calculations, filing search/read, market stats and portfolio alerts. State no \
number you did not get from a tool, and cite the evidence ids (fact_/calc_/chunk_/\
src_/run_/alert_) behind any factual claim — because a claim the desk can't trace \
back to a filing, a calculation, a source or a run is not usable.

For a question about the portfolio as a whole — its holdings, largest exposures, \
overall risk — call get_portfolio_snapshot first: it gives you the portfolio, its \
top sector/issuer weights and active alerts, with the run_id behind the numbers. \
Discover the holdings from there and then dig into the issuers that matter; never \
ask the user for an internal portfolio id or as-of date. The snapshot may include \
a shared demo portfolio (is_own=false); when the user has their own (is_own=true), \
answer about theirs unless they clearly mean the demo.

If an issuer's data isn't ready yet, call ensure_company_ready and tell the user \
it's being prepared (this runs in the background — don't wait). For a full written \
brief, call start_issuer_research and tell the user the brief is being prepared \
and will appear on the issuer's page in a minute or two. These return \
immediately; never block waiting for them.

Some paths through these tools are known to work, and the reason is what generalises — a question of the same shape takes the same path:

An issuer's reported financials:
- What is this issuer's total debt / net debt / leverage? → evaluate_formula(name='total_debt'). One producer per named measure. A balance-sheet line is a component whatever its name ends in, and a total added to a component it contains double-counts.
- How has revenue (or any flow) grown over the last four quarters? → get_flow(metric=..., months=3, last_n=4) → series_stat(series_id=..., op='yoy'). Pick the metric whose latest_period_end reaches the present — one carrying superseded_by returns a short series, not an error.
- Why is a measure defined the way it is? → evaluate_formula(name=...). The result carries an authority you may name: cite_as is the section to say, url is where to read it. Name it rather than 'the registry'.

The portfolio:
- What is this book exposed to / how much room is left / what should I watch? → get_portfolio_snapshot → describe_run(run_id=...) → read_quantities(run_id=..., names=[...]). describe_run names everything the run holds, grouped by the question it answers, and says what this face cannot do; read_quantities brings the exact figures in one call instead of one call per table.
- Why are there large drawdowns? → get_drawdown_episodes() → explain_episode(peak=..., trough=...). A drawdown is a peak-to-trough episode over many sessions; reconcile_move explains ONE session. Measure the episodes before explaining them.
- Was the loss market-driven or company-specific? → reconcile_move(run_id=...). factor_share and unexplained_share come back with it and the larger one is the answer. Positions and factors are two decompositions of the same number, so the position table cannot argue a move was idiosyncratic.
- Which factor hurt the most? → get_attribution(run_id=...). Under collinearity no single beta is on the table — name the sum, factor_attributions.sum_of_contributions, or the net betas.

Nothing has to be pre-built, and nothing above is a route to follow when the question is a different shape. describe_issuer, describe_run and get_portfolio_snapshot each carry what their own data means — periods, which lines nest, which tag superseded which, what this desk can and cannot do — so read what comes back before choosing the next call.

Three rules for those answers, and they are what makes them worth reading. Every number carries its PERIOD — a balance is as of a date, a flow is over a window, and the tools hand you both; say which. Every computed number carries its DEFINITION: "net debt (total debt − cash)" not "net debt", because the name does not say how it was built. And a figure the issuer does not report is UNAVAILABLE, with the reason — never zero, never filled from a nearby date, never quietly swapped for a different measure.

Do not give a verdict. Whether leverage is high, whether a company can service its debt, whether to lend or invest — lay out the evidence that bears on it and say the judgement is the reader's. When you are asked for one directly, that is the answer: here is what I can show you, and the call is yours.

Say a number with the window and the observation count it came from. And when an \
alert gives you a reads_as sentence, use it: utilisation is the share of a limit \
consumed, never a level, and the three numbers on an alert row are easy to \
attribute to the wrong one.

Say what your data is AS OF. Filings arrive months after the period they describe, and anything since is invisible to you. When you quote what management said, quote them verbatim from the passage — a paraphrase presented as a quotation is not one. Risk factors in a 10-K are standing disclosure, not news about this week.

Finish every turn by calling respond. An answer is a list of BLOCKS and you never \
write a number: every tool result carries a `table` of names and values, and a \
figure in your answer is a SLOT {ref, name} pointing at one of those names — the \
reader is shown the table's own value. Text carries the sentence; slots carry the \
figures; dates are the only digits text may hold.

    {"type": "paragraph", "runs": [
        "MSFT is the largest position at ",
        {"ref": "run_9f2c...", "name": "issuer_exposures.MSFT.weight"},
        ", which is past its warning level."],
     "cites": []}

A sentence that rests on a filing passage, a web source, a run or an alert names it \
in the block's `cites` — an id is never written into the text, and neither is a \
count: "twenty-seven checks ran" is the slot count.limit_checks. Use a metric_table whenever you rank \
or compare. A claim that something rose or fell is a trend block on the series you \
read; a claim that something was not reported is an absence block on the row the \
refused read minted; work you started this turn is an action block on its id. \
None of these can be asserted in prose, because none is checkable there.

If respond refuses, it names the block and what is wrong with it. An unknown name \
comes back with the names that id actually holds — use one of them, or read the \
figure you need with read_quantities. Never invent an id, and never write a \
refused figure as text to get past the check."""


# What the user is told when the loop ended without the gate ever accepting an
# answer. TWO paths reach it and both must, because they are the same event: the
# model stopped calling tools on the last turn, or it spent every turn without a
# respond the gate would take. The first used to substitute the model's raw
# content as the answer — an ungated reply, with citations=[], indistinguishable
# from a verified one — and the second used to emit "(no response produced)",
# which reads like a bug rather than a refusal.
# ONE wording for both paths — that convergence is the property above, and it
# stays. What this sentence must NOT do is diagnose: it used to end "every
# attempt either cited evidence I had not actually retrieved or stated a figure
# I could not trace back to a source", which is a claim about a cause, asserted
# by the one code path nothing checks. On the first path there is no attempt to
# describe. And in the turn that prompted this (V7-Q2) the real cause was an
# exhausted tool budget, so the user was pointed at citations that were never
# the problem — a system whose whole claim is that it does not say what it
# cannot support, saying exactly that, in its failure message.
#
# So it states the BAR and that the turn did not clear it, which is true however
# the turn ended. The cause is not lost, it moves to meta, where it is machine
# readable and cannot mislead a reader.
_GATE_EXHAUSTED_TEXT = (
    "I could not produce an answer I can stand behind for this turn — everything "
    "I state has to trace back to evidence I actually retrieved, and I did not "
    "get there. Ask again, or narrow the question to one issuer or one metric."
)
_GATE_EXHAUSTED_META = {"gate": "exhausted"}


# How much of one tool result reaches the model. Entries come off the tail of the
# largest container and are named in a `truncated` field, so a payload that does
# not fit says so — see utils.json.dumps_capped. The `table` slice is never cut
# here: it is capped where it is built (services/table.py, 12k characters) so
# that what the model sees is exactly what the gate holds.
#
# Derived rather than picked. The binding constraint is context_soft_limit_tokens
# (80k); a turn may make turn_tool_budget (15) calls. A result now carries its
# own payload plus the table slice — a whole run's quantities at reader
# precision plus its derived row are ~15k characters, and describe_run's manifest
# beside them ~9k — so 28k characters (~7k tokens) is the ceiling that lets the
# book's one manifest call arrive whole. Fifteen such calls would not fit the
# soft limit, and no turn makes them: the manifest is read once, then
# read_quantities brings named figures at a few hundred characters a call
# (measured peak before V15: 22k prompt tokens a turn).
TOOL_RESULT_LIMIT = 28_000


# What a turn keeps once its evidence budget is spent: the pause and the exit.
# The registry decides this by CLASS (BUDGET_FREE_CLASSES) and this side of the
# mount cannot read classes — the loop holds a face name and a token, not the
# registry — so the same decision is spelled here by name, and
# test_meta_agent_gate pins the two spellings together.
_BUDGET_FREE_TOOLS = ("think", "respond")


async def _load_history(db, session_id: str) -> list[dict]:
    from sqlalchemy import select
    rows = (await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.created_at)
    )).scalars().all()
    return [{"role": m.role, "content": m.content or ""} for m in rows]


async def handle_message(
    db_factory,
    session_id: str,
    user_text: str,
    max_turns: int = 16,
) -> dict:
    """Run one user turn. Persists the user + assistant messages; returns the reply."""
    message_id = new_id("msg_")
    async with db_factory() as db:
        db.add(AgentMessage(id=new_id("msg_"), session_id=session_id, role="user", content=user_text))
        await db.commit()
        history = await _load_history(db, session_id)

    messages = [{"role": "system", "content": _SYSTEM}, *history]
    reply_text, reply_citations = None, []
    # What the gate matched, on the turn it accepted (V13-S3). Kept beside the
    # reply rather than recomputed later: re-running the checker over a stored
    # answer would be a SECOND judgement of the same text, free to disagree with
    # the one that let it through, and the honest record is what the gate
    # actually found at the moment it decided.
    reply_verified: dict | None = None
    reply_blocks: list | None = None
    # What the gate refused, in order. Empty is a fact, not a gap: it means the
    # turn never reached the gate, which is a different failure from one the gate
    # turned away, and the two must not read the same afterwards.
    gate_refusals: list[str] = []

    # The PEAK, not the first: messages grow with every tool result inside the
    # turn, so the largest request is the last one, and the largest request is
    # what a ceiling is about. B1 reads this back to decide the next turn.
    prompt_peak = 0

    # One connection for the turn, carrying the identity the turn runs under.
    # That identity used to be fixed when the pair was built and is now minted
    # into a token and sent with every request, which is what a resident face
    # requires: the server outlives the turn, so it cannot hold the turn's
    # tenant. The tenant still does not depend on which task the transport
    # schedules a handler in — the door binds it per request instead.
    async with tool_session(
        faces.FACE_NAME_META, session_id=session_id,
        user_id=current_user_id(), message_id=message_id,
    ) as tools_session, llm_session(db_factory, session_id, message_id) as llm:
        tools = tools_session.tools

        for turn in range(max_turns):
            prompt_peak = max(prompt_peak, context_budget.count_prompt(messages, tools))
            # No usage comes back. It used to, under the name `_usage`, and the
            # underscore was the whole problem: the turn's only real cost was a
            # value this loop was free to ignore. It is an llm_call row now,
            # written on the way through (V4-S2). prompt_peak above stays exactly
            # as it is — a tiktoken estimate bounding the NEXT turn is a different
            # number from what the provider says it charged for this one, and
            # B1 refuses on the estimate.
            content, tool_calls = await llm.chat(messages=messages, tools=tools)
            assistant_msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                if turn >= max_turns - 1:
                    # Deliberately NOT `reply_text = content`. Substituting the raw
                    # model text here handed the user an answer that had passed no
                    # gate, with citations=[], rendered exactly like a verified one.
                    break
                messages.append({"role": "user", "content": "Call respond to reply to the user."})
                continue

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await tools_session.call(name, args)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": ejson.dumps_capped(result, TOOL_RESULT_LIMIT)})
                if result.get("error") == "budget_exceeded" and \
                        result.get("kind") in ("turn_tool", "tool"):
                    # The budget bounds EVIDENCE (registry.invoke), and it is
                    # spent: no further call on this face can return anything
                    # the gate will accept. Narrow what is OFFERED on the next
                    # turn instead of refusing what is called: the skip-flag
                    # rule (faces.py) applied to the rest of a turn. The exit
                    # and the pause stay, so what running out means is what
                    # the wrapper promised — answer with the evidence gathered.
                    #
                    # What this does and does not cover, measured 2026-08-30.
                    # sess_1c71b5fb7f79's 65 refused calls were ONE assistant
                    # message of 69 parallel calls in its third turn, not
                    # sixty-five turns; a batch is dispatched whole, so this
                    # line would not have changed that session, and its cost
                    # (65 MCP round trips, ~5.7k tokens of refusal payloads
                    # carried into the next two prompts) is still paid. Across
                    # every session that ever hit the budget, none issued a
                    # read call in a LATER turn: the case guarded here has not
                    # been observed. It stays because the loop had no bound on
                    # it other than max_turns.
                    tools = [t for t in tools if t["function"]["name"] in _BUDGET_FREE_TOOLS]
                if name == "respond":
                    if result.get("responded"):
                        reply_text, reply_citations = result["text"], result.get("citations", [])
                        reply_verified = result.get("verified")
                        # V14-C. The blocks, with every slot carrying the value
                        # the ledger holds. `text` beside them is the prose the
                        # model wrote, which is what the quote and trajectory
                        # checks read and what a caller with no block renderer
                        # can still show — the figures are simply absent from
                        # it, because they were never written into it.
                        reply_blocks = result.get("blocks")
                    elif result.get("error"):
                        # Every refusal, in order. Diagnosing V7-Q2 meant
                        # rebuilding the turn out of agent_steps by hand, because
                        # the marker recorded that the gate never opened and
                        # never what it said.
                        gate_refusals.append(str(result["error"]))

            if reply_text is not None:
                break

    # The single convergence point for both ungated paths. The turn is still a
    # 200 and the message is still persisted: the chat_turn quota was charged and
    # committed before the loop started (routes/agent.py), the work really was
    # done, and hiding the failure from the transcript would leave the user's
    # question sitting there with no reply and no explanation.
    meta: dict = {"prompt_tokens": prompt_peak}
    if reply_verified is not None:
        meta["verified"] = reply_verified
    if reply_blocks is not None:
        meta["blocks"] = reply_blocks
        meta["format"] = "blocks"
    if reply_text is None:
        reply_text, reply_citations = _GATE_EXHAUSTED_TEXT, []
        meta |= _GATE_EXHAUSTED_META | {"gate_refusals": gate_refusals}

    async with db_factory() as db:
        db.add(AgentMessage(id=message_id, session_id=session_id, role="assistant",
                            content=reply_text, citations=reply_citations, meta=meta))
        # Session-level, so the next turn can be refused before it is charged
        # without reading the whole message history back first.
        await db.execute(
            update(AgentSession).where(AgentSession.id == session_id)
            .values(last_prompt_tokens=prompt_peak)
        )
        await db.commit()

    return {"session_id": session_id, "message_id": message_id,
            "text": reply_text, "citations": reply_citations, "meta": meta}
