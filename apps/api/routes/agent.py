"""Agent conversation routes — the single meta-agent the user talks to.

POST messages runs the meta-agent loop and returns its reply synchronously.
Delegations inside the loop are non-blocking, so the turn stays responsive.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user, require_user
from exposure_workbench.agents.meta_agent import handle_message
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.models import AgentMessage, AgentSession, AgentStep
from exposure_workbench.db.session import get_db, get_session_factory
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import agent_session_service, context_budget, usage_service

router = APIRouter()


class SessionOut(BaseModel):
    id: str
    kind: str
    llm_model: str | None
    tools_used: int
    tool_budget: int | None

    model_config = {"from_attributes": True}


@router.post("/agent/sessions", response_model=SessionOut, status_code=201)
async def create_agent_session(
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    # Charged HERE and not in agent_session_service.create_session, which has two
    # other callers that must stay free: apps/mcp/server.py opens an ownerless
    # session (charge() raises on a None user by design), and
    # issuer_research_workflow opens a second session per research run, which has
    # already paid at enqueue. Shares the request transaction — this is one cheap
    # local INSERT, so rolling the charge back with a failed request is right.
    #
    # Not a ceiling on open sessions: agent_sessions.ended_at is never written
    # anywhere in this repo, so "at most N open" would lock a user out for good
    # after N. A daily pool is the only shape that actually works today.
    try:
        await usage_service.charge(db, user.user_id, "agent_session")
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    s = await agent_session_service.create_session(db, kind="meta", owner_id=user.user_id)
    await db.commit()
    return s


# One quota unit buys one TURN, so the turn itself has to be bounded. Without
# this a single charged action could carry a megabyte of text, which the agent
# loop then replays to the model on every one of up to 16 iterations — three
# orders of magnitude more spend for the same quota, which is the quota not
# doing its job. It also stops a single oversized message from bricking a
# session: once persisted, every later turn reloads it as history.
MAX_MESSAGE_CHARS = 8_000


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class MessageOut(BaseModel):
    session_id: str
    message_id: str
    text: str
    citations: list
    # {"gate": "exhausted"} when the loop ended without the gate accepting an
    # answer. The UI renders that message as a refusal rather than as an answer;
    # without it, "I could not produce an answer" is a paragraph the user has no
    # reason to read differently from any other.
    meta: dict = {}


def _is_provider_context_error(exc: Exception) -> bool:
    """Whether a provider error means "this prompt is too long".

    Matched on the message because neither SDK exposes a distinct type for it.
    Deliberately narrow: a false positive here would tell a user to start a new
    session over an unrelated outage, and every other error must keep its own
    shape rather than being absorbed into a tidy 413.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return ("context_length_exceeded" in text
            or "maximum context length" in text
            or ("too many tokens" in text and "context" in text))


@router.post("/agent/sessions/{session_id}/messages", response_model=MessageOut)
async def post_message(
    session_id: str, body: MessageIn,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """One turn of the meta-agent.

    Status order is fixed: 401 (require_user) -> 404 (precheck) -> 409 (a turn is
    already in flight) -> 413 (the session's context is spent) -> 429 (daily
    quota). 413 sits before 429 deliberately: a turn that cannot run must not
    cost a quota unit. Deliberately no 403: agent_sessions
    has a FOR ALL policy, so another tenant's session is invisible to both the
    SELECT and the UPDATE — the precheck below is what keeps "not yours" (404)
    distinguishable from "busy" (409); drop it and the two collapse into one
    indistinguishable 0-row answer.
    """
    s = await agent_session_service.get_session(db, session_id)
    if s is None:
        raise HTTPException(404, "unknown session")

    factory = get_session_factory()

    # Claim the turn and charge the quota in ONE short transaction, committed
    # before any LLM call. Over-quota rolls the claim back with it, so there is
    # no "release on the rejection path" case to get wrong. It must not use the
    # request-scoped db: get_db holds its transaction open until the route
    # returns, and reserve() runs on a different connection once per tool call,
    # so an uncommitted claim would hang the request on its own row lock.
    #
    # It must also land BEFORE handle_message, which commits the user's message
    # before entering the LLM loop — claim later and a rejected turn would still
    # leave that message in the database.
    async with factory() as gate_db, gate_db.begin():
        claimed_at = await agent_session_service.claim_turn(gate_db, session_id)
        if claimed_at is None:
            raise HTTPException(409, {"error": "turn_in_flight", "session_id": session_id})

        # Before the charge, never after: a turn that cannot run must not cost a
        # quota unit. Raising here rolls the claim_turn UPDATE back with the
        # transaction, and THAT is the release — the 429 below has always worked
        # this way. Calling release_turn explicitly would open a second
        # connection onto the row lock this one still holds and hang the request
        # with its exception swallowed.
        projected = (s.last_prompt_tokens or 0) + context_budget.count_tokens(body.text)
        if projected > get_settings().context_soft_limit_tokens:
            raise HTTPException(413, {
                "error": "session_context_exhausted",
                "projected_tokens": projected,
                "limit": get_settings().context_soft_limit_tokens,
                "detail": "this conversation has grown past what one turn can carry; "
                          "start a new session to continue",
            })

        try:
            await usage_service.charge(gate_db, user.user_id, "chat_turn")
        except usage_service.QuotaExceeded as e:
            raise HTTPException(429, e.as_dict()) from e

    try:
        return await handle_message(factory, session_id, body.text)
    except Exception as e:      # noqa: BLE001 — narrowed immediately below
        # Defence in depth for the case the pre-check cannot see: the FIRST turn
        # of a session has no measurement to project from, and a single 8k-char
        # message plus a large tool result can still overrun. Same error shape,
        # but the quota is NOT refunded — it was charged and committed before the
        # loop, the provider call really happened, and V2-H's rule is that a
        # charge shares its caller's transaction only when the money is spent
        # later on the worker.
        if _is_provider_context_error(e):
            raise HTTPException(413, {
                "error": "session_context_exhausted",
                "detail": "the provider refused this turn as too long; start a new session",
            }) from e
        raise
    finally:
        # finally, not a happy-path call: chat_with_tools raises outright when no
        # API key is configured, OpenAI network errors pass straight through, and
        # reserve's ValueError("unknown session") is outside the only except
        # clause in registry.invoke. Every one of those must still free the slot.
        # Fenced on the stamp we claimed: if this turn outlived its lease and was
        # superseded, releasing unconditionally would free the REPLACEMENT's slot.
        await agent_session_service.release_turn(session_id, claimed_at)


class StepOut(BaseModel):
    seq: int
    step_type: str
    tool_name: str | None
    status: str
    result_summary: str | None
    evidence_refs: list
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetailOut(BaseModel):
    id: str
    kind: str
    tools_used: int
    messages: list
    steps: list[StepOut]


class SessionSummaryOut(BaseModel):
    id: str
    kind: str
    started_at: datetime
    ended_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("/agent/sessions", response_model=list[SessionSummaryOut])
async def list_agent_sessions(
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    # RLS scopes this to the caller's own sessions (owner_id = tenant).
    #
    # 'mcp' is the stdio debug door, which opens a session of its own under a
    # real user. Excluding it would make the one surface built for watching a
    # tool call land the one surface the monitor cannot show. 'research' stays
    # out: a run's session is reached through the run, not this list.
    rows = (await db.execute(
        select(AgentSession).where(AgentSession.kind.in_(("meta", "mcp")))
        .order_by(AgentSession.started_at.desc()).limit(50)
    )).scalars().all()
    return rows


@router.get("/agent/sessions/{session_id}", response_model=SessionDetailOut)
async def get_agent_session(
    session_id: str,
    user: UserClaims | None = Depends(optional_user),   # sets tenant so the owner (only) can read it
    db: AsyncSession = Depends(get_db),
):
    s = await agent_session_service.get_session(db, session_id)
    if s is None:
        raise HTTPException(404, "unknown session")
    msgs = (await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.created_at)
    )).scalars().all()
    steps = (await db.execute(
        select(AgentStep).where(AgentStep.session_id == session_id).order_by(AgentStep.seq)
    )).scalars().all()
    return SessionDetailOut(
        id=s.id, kind=s.kind, tools_used=s.tools_used,
        messages=[{"id": m.id, "role": m.role, "content": m.content,
                   "citations": m.citations, "meta": m.meta or {}} for m in msgs],
        steps=steps,
    )
