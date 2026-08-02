"""Meta-agent (M10) — the single conversational entity the user talks to.

A thin tool-calling loop: it answers directly with the read tools when data is
ready, delegates heavy/unready work (non-blocking) and reports the run id, and
exits by calling respond. The system prompt states the role and the evidence
discipline's WHY — it is not a rulebook, because the architecture (ids required
to cite, wrapper-enforced budget/trace) is what actually constrains behaviour.

History is persisted as agent_messages so a session survives across turns.
"""

from __future__ import annotations

import json
import logging

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import AgentMessage
from exposure_workbench.llm import client as llm_client
from exposure_workbench.tools import faces, registry as R
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.meta_tools import register_meta_tools
from exposure_workbench.tools.registry import invoke
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
brief, call start_issuer_research and give the user the run id to follow. These \
return immediately; never block waiting for them.

Finish every turn by calling respond. A reply with no numbers in it — a greeting, \
a clarifying question — needs no citations; any reply that states a number must \
cite the evidence that number came from. If respond rejects a citation, fix that \
id — never invent one. If it says citations_required, you stated a number you did \
not fetch: call the tool that produces it, then cite what comes back."""


def build_meta_registry() -> R.ToolRegistry:
    return register_meta_tools(build_read_registry())


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
    registry: R.ToolRegistry | None = None,
    max_turns: int = 16,
) -> dict:
    """Run one user turn. Persists the user + assistant messages; returns the reply."""
    registry = registry or build_meta_registry()
    settings = get_settings()
    face = faces.available(registry, faces.FACE_META_AGENT)
    tools = registry.schemas(face)

    message_id = new_id("msg_")
    async with db_factory() as db:
        db.add(AgentMessage(id=new_id("msg_"), session_id=session_id, role="user", content=user_text))
        await db.commit()
        history = await _load_history(db, session_id)

    messages = [{"role": "system", "content": _SYSTEM}, *history]
    reply_text, reply_citations = None, []

    for turn in range(max_turns):
        content, tool_calls, _usage = await llm_client.chat_with_tools(messages=messages, tools=tools)
        assistant_msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            if turn >= max_turns - 1:
                reply_text = content or ""
                break
            messages.append({"role": "user", "content": "Call respond to reply to the user."})
            continue

        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            async with db_factory() as db:
                result = await invoke(registry, db, session_id, name, args, message_id=message_id)
                await db.commit()
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps(result, default=str)[:6000]})
            if name == "respond" and result.get("responded"):
                reply_text, reply_citations = result["text"], result.get("citations", [])

        if reply_text is not None:
            break

    reply_text = reply_text if reply_text is not None else "(no response produced)"
    async with db_factory() as db:
        db.add(AgentMessage(id=message_id, session_id=session_id, role="assistant",
                            content=reply_text, citations=reply_citations))
        await db.commit()

    return {"session_id": session_id, "message_id": message_id,
            "text": reply_text, "citations": reply_citations}
