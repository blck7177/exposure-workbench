"""Research subagent session (M8 step) — bounded tool-calling loop.

Not a conversation: a single-shot analyst that explores an issuer with the
FACE_RESEARCH tools and finishes by calling submit_brief. The explorer IS the
writer — no hand-off — so every number it writes is one it just fetched.

Enforcement is inherited, not re-implemented: every tool call goes through the
registry wrapper (budget, trace, evidence refs), reached over an MCP client on
the resident tool face (MCP_PLAN P4, R4). The loop just relays tool results back
to the model until submit_brief is accepted or the budget runs out.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.agents.meta_agent import TOOL_RESULT_LIMIT
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

_SYSTEM = """You are an equity issuer-research analyst producing an Issuer Risk Brief for a portfolio team.

You have tools for financial facts and calculations, filing search/read, market \
stats, portfolio alerts, and one external-research search. Every tool result \
carries a `table`: the names and values of the figures it put on the table, the \
passages (chunk_/src_) it returned, and the rows (series/absence/task) it minted. \
Only what is on the table can be pointed at — never compute or recall figures \
yourself.

The brief is six sections, each a list of BLOCKS. A figure is a SLOT {ref, name} \
using a name exactly as the `table` spelled it; the reader is shown the table's \
own value, so you never write a number. Text carries no digits except dates. A \
sentence resting on a passage names that passage in the block's `cites`. A claim \
that something rose or fell is a `trend` on the series it was read from; a claim \
that something was not reported is an `absence` on the row the refused read \
minted; a comparison or ranking is a `metric_table` of slots — its labels are \
derived from the slots' names, so a cell is never text.

Work efficiently within your tool budget: get the issuer snapshot, pull the key \
financial series and changes, read/search the relevant filing sections, check \
market reaction and any portfolio alerts, and search external context once if the \
filings don't explain a development. Then call submit_brief.

submit_brief takes financial_summary, key_changes, management_explanation, \
market_context, portfolio_implications and open_questions. Every section but \
open_questions must point at evidence from this session; open_questions needs no \
cites. If a submission is refused, the refusal names the section and the block — \
fix exactly that block and resubmit. Do not invent ids or names."""


async def run_research_session(
    db_factory,
    session_id: str,
    ticker: str,
    deny: Sequence[str] = (),
    max_turns: int = 30,
) -> dict:
    """Drive the loop. No registry: the tools and the database they commit into
    are behind the mount now, one session per tool call there exactly as before,
    so trace and ledger still persist as they happen.

    db_factory came back at V4-S2, and it is not the tools' database returning
    with it. Nothing on this side reaches a tool through it; it writes one row —
    the completion this loop just paid for — and a completion is the one event
    the mount never sees, because it happens on this side of the door. R4's
    absence was about the tools; this is the ledger for what R4 does not cover.

    `deny` is the tool names removed from the research face for this run — how
    skip-flags work, unchanged in kind and moved in mechanism. The mount serves
    FACE_RESEARCH minus deny, so dropping search_external_research still means
    the capability does not exist for this session rather than an in-loop 'if
    skip' branch. What moved is where the narrowing is said: it travels in the
    token instead of in a face this side constructs, because the face itself no
    longer lives here and two places trimming one face is the error class R4
    removes."""
    settings = get_settings()
    model = settings.openai_model

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Produce the Issuer Risk Brief for {ticker.upper()}."},
    ]

    brief_id: str | None = None
    turn = 0
    # One connection for the run, where a chat turn gets one per turn: a research
    # session IS the unit of work, and its lifetime budget is spent inside it.
    # Which also fixes the token's lifetime — minted once here, and N8 sized its
    # 30 minutes against the task lease for exactly this run. The tenant comes
    # from the run's own owner, which the worker set before calling; a research
    # run outlives no request, so there is nothing ambient to inherit.
    async with tool_session(
        faces.FACE_NAME_RESEARCH, session_id=session_id,
        user_id=current_user_id(), deny=deny,
    ) as tools_session, llm_session(db_factory, session_id) as llm:
        tools = tools_session.tools

        for turn in range(max_turns):
            # No message_id: a research run has no message to hang a cost on. The
            # session IS the unit of work, and the run reaches it through
            # research_runs.agent_session_id — which is how the per-run view adds
            # these up (V4-S2).
            content, tool_calls = await llm.chat(
                messages=messages, tools=tools, model=model, temperature=0.2,
            )
            assistant_msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                # model stopped calling tools without submitting — nudge once, then stop
                if turn >= max_turns - 1:
                    break
                messages.append({"role": "user",
                                 "content": "Continue with tools, then call submit_brief."})
                continue

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await tools_session.call(name, args)
                # The same cap the meta-agent reads under: the table slice rides
                # inside the result (registry.invoke attaches result["table"]),
                # and a whole run's names at 8000 characters were cut before the
                # model could spell one it was then refused for misspelling.
                messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": ejson.dumps_capped(result, TOOL_RESULT_LIMIT),
                })
                if name == "submit_brief" and result.get("accepted"):
                    brief_id = result["brief_id"]

            if brief_id:
                break

    return {"brief_id": brief_id, "turns_used": turn + 1, "submitted": brief_id is not None}
