"""The research run: an Issuer Risk Brief, written by the analyst who read the evidence.

A bounded loop over the research face — analyze, methods by name, the filings'
text, the web — that ends when the model writes the brief: six sections under
fixed headings, in prose. The observer reads every figure of it against the
analyses the run produced and the passages it read; the brief is stored with that
verification, section by section, and a figure that does not hold is sent back
once as business feedback. There is no submission form and no claims grammar: the
explorer is the writer, and what it writes is what is checked.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Sequence

from sqlalchemy import select

from exposure_workbench.agents import opening, tasks as T
from exposure_workbench.agents.llm_session import Conversation, LlmSession, ModelPolicy
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.analytics import handbook
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import IssuerBrief, ResearchRun
from exposure_workbench.llm import client as llm_client
from exposure_workbench.services import ledger as ledger_svc, method_index as mi, observer as ob, render as rd
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson
from exposure_workbench.utils.ids import new_brief_id

logger = logging.getLogger(__name__)

SECTIONS = ("financial_summary", "key_changes", "management_explanation",
            "market_context", "portfolio_implications", "open_questions")
HEADINGS = {s: s.replace("_", " ").title() for s in SECTIONS}
_HEADING = re.compile(r"^\s*#{1,3}\s*(" + "|".join(re.escape(h) for h in HEADINGS.values()) + r")\s*$", re.I | re.M)
TOOL_RESULT_LIMIT = 28_000
EVIDENCE_CALLS = 16

_ROLE = """You are an equity issuer-research analyst producing an Issuer Risk Brief for a portfolio team. \
The analysis is your job: decide what to look at, what to compare it against, and what the evidence means for a team \
that holds this name — what changed, why, and what would change your reading.

Your tools: `analyze` runs one analysis as an aligned table — measures over the issuer (and peers you name), each at \
its latest period and, with `compare`, against the comparable period before on the issuer's own calendar, with changes \
in percentage points; `metric` takes a registry method by name; the text tools quote filings and the web; `list` shows \
what the desk holds; `open` re-reads anything on the record. You never compute a date or copy an id: the desk binds, \
pairs, computes and records.

When you have read enough, write the brief in prose under exactly these six headings, each on its own line:
{headings}
State figures as the tables show them, with the period they are over, saying which are levels and which are changes \
in percentage points. A figure the desk does not hold is said to be absent, never estimated. Every section but Open \
Questions rests on evidence you read this run. The desk checks your figures against its record and tells you only \
when one does not hold."""


def instructions() -> str:
    return (_ROLE.format(headings="\n".join(f"## {HEADINGS[s]}" for s in SECTIONS)) + "\n\n" + mi.index_text(None)
            + "\n\nYOUR CHAPTER OF THE DESK'S HANDBOOK, IN SHORT\n" + handbook.guidance_text("issuer"))


def split_sections(text: str) -> dict[str, str] | None:
    """The six sections by heading, or None when a heading is missing."""
    found = list(_HEADING.finditer(text or ""))
    by_name: dict[str, str] = {}
    for i, m in enumerate(found):
        name = next(s for s, h in HEADINGS.items() if h.lower() == m.group(1).strip().lower())
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        by_name[name] = text[m.end():end].strip()
    return by_name if all(s in by_name for s in SECTIONS) else None


async def run_research_session(db_factory, session_id: str, ticker: str, deny: Sequence[str] = (),
                               max_turns: int = 30) -> dict:
    """Drive the loop; the brief is stored when the observer has read it."""
    settings = get_settings()
    ticker = ticker.upper()
    policy = ModelPolicy.for_role("research")
    llm = LlmSession(db_factory, session_id, None, policy=policy, actor="research")
    conv = Conversation()
    conv.say("user", f"Produce the Issuer Risk Brief for {ticker}.")
    views: list[dict] = []
    evidence_calls = completions = feedback_rounds = 0
    brief_id: str | None = None
    text: str | None = None
    verdict: ob.Verdict | None = None
    scope = {"subjects": [ticker], "basis": "the issuer of the brief"}

    async with tool_session(faces.FACE_NAME_RESEARCH, session_id=session_id, user_id=current_user_id(),
                            deny=deny) as tools_session:
        face_tools = list(tools_session.tools)
        verbs = {t["name"] for t in face_tools}
        for _ in range(max_turns):
            exhausted = evidence_calls >= EVIDENCE_CALLS
            tools = ([T.OPEN_TOOL] if exhausted else face_tools + [T.OPEN_TOOL])
            tail = [llm_client.message("developer", f"Budget: {max(0, EVIDENCE_CALLS - evidence_calls)} analyses or reads left"
                                                    + ("; none left — write the brief." if exhausted else "."))]
            turn = await llm.next(conv, instructions=instructions(), tools=tools, tail=tail)
            completions += 1
            if turn.tool_calls:
                for call in turn.tool_calls:
                    try:
                        args = json.loads(call.arguments or "{}")
                    except json.JSONDecodeError:
                        args = None
                    if args is None:
                        res: dict = {"error": "malformed_arguments", "detail": "the arguments were not JSON"}
                    elif call.name == T.OPEN_TOOL_NAME:
                        res = await opening.open_ref(db_factory, session_id, str(args.get("id") or ""),
                                                     offset=int(args.get("offset") or 0))
                    elif call.name in verbs:
                        if call.name == "analyze" and not args.get("scope"):
                            args["scope"] = scope
                        if call.name != "list" and evidence_calls >= EVIDENCE_CALLS:
                            res = {"error": "budget_exhausted", "detail": "this run's analyses and reads are used; write the brief"}
                        else:
                            evidence_calls += int(call.name != "list")
                            res = await tools_session.call(call.name, args)
                            res = res if isinstance(res, dict) else {"error": "tool_transport_error"}
                            if call.name == "analyze" and isinstance(res.get("view"), str):
                                views.append({k: v for k, v in res.items() if k != "_facts"})
                    else:
                        res = {"error": "unknown_tool", "detail": f"your tools are {', '.join(sorted(verbs))} and open"}
                    conv.tool_output(call.call_id, ejson.dumps_capped(res, TOOL_RESULT_LIMIT, keep=("rows", "view")))
                continue
            draft = (turn.text or "").strip()
            if not draft:
                conv.say("developer", "Write the brief under the six headings.")
                continue
            sections = split_sections(draft)
            if sections is None:
                conv.say("developer", "The brief needs all six headings, each on its own line: "
                                      + "; ".join(f"## {HEADINGS[s]}" for s in SECTIONS))
                continue
            async with db_factory() as db:
                led = await ledger_svc.load(db, session_id)
            verdict = ob.observe(draft, question=f"Produce the Issuer Risk Brief for {ticker}.", views=views,
                                 passages=led.passages)
            text = draft
            if verdict.ok or feedback_rounds >= settings.observer_feedback_rounds:
                break
            feedback_rounds += 1
            conv.say("developer", verdict.feedback() or "")

    if text and verdict is not None:
        sections = split_sections(text) or {}
        async with db_factory() as db:
            led = await ledger_svc.load(db, session_id)
            run = (await db.execute(select(ResearchRun).where(ResearchRun.agent_session_id == session_id))).scalar_one_or_none()
            if run is None:
                raise RuntimeError(f"session {session_id} belongs to no research run")
            per_section = {name: rd.render(body, ob.observe(body, question="", views=views, passages=led.passages), views, led.by_id)
                           for name, body in sections.items()}
            brief_id = new_brief_id()
            db.add(IssuerBrief(
                id=brief_id, research_run_id=run.id, company_id=run.company_id, owner_id=run.owner_id,
                **{name: sections[name] for name in SECTIONS},
                blocks={name: per_section[name]["blocks"] for name in SECTIONS},
                claims_by_section={name: per_section[name]["validation"] for name in SECTIONS},
                citations=sorted({c for r in per_section.values() for c in r["citations"]}),
                block_citations={name: per_section[name]["citations"] for name in SECTIONS},
            ))
            await db.commit()
    return {"brief_id": brief_id, "turns_used": completions, "submitted": brief_id is not None,
            "verification": verdict.summary() if verdict else None}
