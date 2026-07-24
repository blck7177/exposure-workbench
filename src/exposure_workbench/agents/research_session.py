"""Research subagent session (M8 step) — bounded tool-calling loop.

Not a conversation: a single-shot analyst that explores an issuer with the
FACE_RESEARCH tools and finishes by calling submit_brief. The explorer IS the
writer — no hand-off — so every number it writes is one it just fetched.

Enforcement is inherited, not re-implemented: every tool call goes through the
registry wrapper (budget, trace, evidence refs). The loop just relays tool
results back to the model until submit_brief is accepted or the budget runs out.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.llm import client as llm_client
from exposure_workbench.tools import faces, registry as R
from exposure_workbench.tools.registry import invoke

logger = logging.getLogger(__name__)

_SYSTEM = """You are an equity issuer-research analyst producing an Issuer Risk Brief for a portfolio team.

You have tools for financial facts and calculations, filing search/read, market \
stats, portfolio alerts, and one external-research search. Every number you state \
must come from a tool result — never compute or recall figures yourself. Every \
factual claim in the brief must cite the evidence ids (fact_/calc_/chunk_/src_) \
that a tool returned to you this session.

Work efficiently within your tool budget: get the issuer snapshot, pull the key \
financial series and changes, read/search the relevant filing sections, check \
market reaction and any portfolio alerts, and search external context once if the \
filings don't explain a development. Then call submit_brief.

submit_brief has five cited blocks (financial_summary, key_changes, \
management_explanation, market_context, portfolio_implications) plus open_questions \
(no citations). If a submission is rejected for citation problems, fix exactly \
those ids and resubmit — do not invent ids."""


async def run_research_session(
    db_factory,
    session_id: str,
    ticker: str,
    registry: R.ToolRegistry,
    face: list[str] | None = None,
    max_turns: int = 30,
) -> dict:
    """Drive the loop. db_factory() yields a fresh AsyncSession per tool call so
    each call commits independently (trace + ledger persist as they happen).

    `face` is the tool-name subset the agent may use — trimming it (e.g. removing
    search_external_research) is how skip-flags work: the capability simply does
    not exist for this session, no in-loop 'if skip' branch."""
    settings = get_settings()
    model = settings.openai_model
    available = faces.available(registry, face or faces.FACE_RESEARCH)
    tools = registry.schemas(available)

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Produce the Issuer Risk Brief for {ticker.upper()}."},
    ]

    brief_id: str | None = None
    for turn in range(max_turns):
        content, tool_calls, usage = await llm_client.chat_with_tools(
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
            async with db_factory() as db:
                result = await invoke(registry, db, session_id, name, args)
                await db.commit()
            messages.append({
                "role": "tool", "tool_call_id": tc["id"],
                "content": json.dumps(result, default=str)[:8000],
            })
            if name == "submit_brief" and result.get("accepted"):
                brief_id = result["brief_id"]

        if brief_id:
            break

    return {"brief_id": brief_id, "turns_used": turn + 1, "submitted": brief_id is not None}
