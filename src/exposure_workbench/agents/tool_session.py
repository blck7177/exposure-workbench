"""The agents' connection to the resident tool face (MCP_PLAN P3/P4, R4).

Both loops reach their tools through an MCP client: same registry, same wrapper,
same trace, one hop of protocol in between. The point is not the hop. It is that
"the agent face is MCP" stops being a sentence in the architecture notes and
becomes the only way the agents can call anything — so the face cannot quietly
acquire a second definition, and a consumer that is not this repo's own loop is
served by construction rather than by intention.

Until R4 that hop was in-memory: a server built per turn in this process, handed
a registry, a db_factory and the turn's identity. That was the right first move,
because it made "agent path = MCP path" literally true before anything about the
topology changed. It is gone now, and its parameters went with it rather than
becoming optional. The face is a container (N6), so a client that still held a
registry would be holding the thing it is supposed to be reaching through, and
an in-memory helper left importable beside this would be a second production
transport — the two-track shape this plan exists to prevent. One path, over
HTTP, with an internal bearer on it (N7/N11). The helper survives only as a test
fixture, and R5's import guard is what keeps it there.

What a loop sees did not change: a tools list and a call verb. What changed is
that there is now a class of failure BELOW the tools — the connection itself —
and it deliberately does not wear a tool result's clothes. A tool that refuses
is a turn continuing; a face that cannot be reached is a turn over. Where each
of those surfaces is stated at ToolSession.call and was measured, not assumed.

The second one has a name now (S1). It surfaced as the ExceptionGroup anyio
raises when the stream's task group dies, which nobody above could catch by
name and nobody could read: a chat turn ended as a bare 500 with the quota
already spent, and a research run — a user has three a day — recorded
"unhandled errors in a TaskGroup (1 sub-exception)" as its error_message. In a
system whose whole claim is that every failure is explainable, that was the one
failure that explained nothing. ToolFaceUnavailable is the translation, and it
is made here because here is the only place that still knows it was HTTP.

The loops keep speaking OpenAI's function-calling dialect, so `tools` is
converted back into that shape here. A test asserts the conversion is
byte-identical to what registry.schemas() produced before, because a tool
description that changes on the way to the model is a behaviour change nobody
wrote.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Sequence

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth import internal_token

logger = logging.getLogger(__name__)

# httpx's own default is five seconds on every phase, which is a transport
# guessing how long a tool takes. These are the SDK's recommended figures
# instead (MCP_DEFAULT_TIMEOUT / MCP_DEFAULT_SSE_READ_TIMEOUT): the read budget
# covers a response that streams back while a tool reaches a provider —
# search_external_research through Tavily, search_filing_passages through an
# embedding — and outlasting five seconds is not a symptom of anything. What
# bounds a session is the registry's tool budget, not this.
_TIMEOUT = httpx.Timeout(30.0, read=300.0)


class ToolFaceUnavailable(RuntimeError):
    """The face itself could not be reached — the turn is over, with a name.

    Raised by tool_session() and never by ToolSession.call, which keeps its
    never-raises contract to the letter: a tool that refuses is a turn
    continuing, a face that is not there is a turn over.

    It lives in this module because this module is the only one that knows what
    counts as transport failure. Above it there is no httpx to test a leaf
    against, and below it there is no face name and no URL to name in the
    sentence — a tool handler does not know it was reached over a socket.

    The message IS that sentence, deliberately: apps/api turns this into a 503
    with wording of its own, but the worker writes str(exc) straight into
    research_runs.error_message (apps/worker/handlers/issuer_research.py), where
    the next reader is the user whose run died. It names the face and the URL
    and never the bearer — the token is a credential, and an error message is
    the most-copied text in any incident.
    """

    def __init__(self, face_name: str, url: str, reason: str):
        super().__init__(
            f"the {face_name} tool face at {url} could not be reached ({reason})"
        )
        self.face_name = face_name
        self.url = url
        self.reason = reason


def _as_openai_tool(tool) -> dict:
    """An MCP tool as an OpenAI function schema — the shape registry.schemas()
    produced when the loops read the registry directly."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.inputSchema,
        },
    }


class ToolSession:
    """What a loop holds for the length of a turn: the tool list and one verb."""

    def __init__(self, client, mcp_tools):
        self._client = client
        self.tools = [_as_openai_tool(t) for t in mcp_tools]

    async def call(self, name: str, args: dict) -> dict:
        """One tool call, returning what invoke() returned.

        Never raises on anything the server answers with, because invoke() does
        not and the loops are written to that contract: a tool failure is a
        result the model reads and adapts to, not an exception that ends the
        turn. Crossing a process boundary did not change that. An unknown tool,
        a refused argument and a handler that blew up all come back through the
        except below in the same shape they had in-process, next to the two ways
        a reply can be unreadable — an empty content list, and a payload that is
        not the JSON we serialised.

        What does NOT arrive here is the transport failing underneath, and it
        must not be made to. A refused connection or a 401 kills the stream's
        task group, so this await is cancelled — a BaseException, left uncaught
        deliberately — and the cause surfaces where the session was opened, as
        ToolFaceUnavailable. Measured against the real mount (R4), not assumed.

        That split is the right one. A 401 is not a tool that failed, it is the
        turn having lost the identity it was minted with; handing it to the
        model as a tool result would invite it to try something else against a
        face it can no longer reach, and it has no second identity to try. Same
        for a face that is down: thirty tool results reading "connection
        refused" is a loop burning its budget to arrive nowhere. The turn ends,
        loudly, at the caller.
        """
        try:
            out = await self._client.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.warning("tool session call %s failed: %s", name, exc, exc_info=True)
            return {"error": "tool_transport_error", "detail": str(exc)}

        text = next((c.text for c in out.content if getattr(c, "text", None)), None)
        if text is None:
            return {"error": "tool_transport_error", "detail": "no content in tool result"}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "tool_transport_error", "detail": text[:500]}


# Between a class name and the word for it: ConnectError -> connect_error.
_WORD_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _leaves(exc: BaseException):
    """Every non-group exception inside `exc`, at whatever depth.

    Recursive because a task group whose child is a task group raises a group of
    groups, and the httpx error is at the bottom of it. Nothing here inspects
    the group itself: a group is a shape, not a cause.
    """
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            yield from _leaves(sub)
    else:
        yield exc


def _transport_reason(exc: BaseException) -> str | None:
    """The word for why the face was not reached, or None if this is not that.

    Two branches because httpx's tree has two, and the split is easy to get
    wrong: HTTPStatusError is NOT a TransportError, it is the sibling meaning
    the door answered and said no — the 401 a mount returns for a bearer it
    refuses. Both end the turn, so both belong here, but they must stay
    distinguishable in the sentence: one is fixed by starting a container, the
    other by fixing MCP_INTERNAL_SECRET or the face a token was minted for.

    The word for a transport leaf is httpx's own name for it rather than a
    lookup table of the kinds seen so far. A table has to be extended by
    whoever first meets the kind it is missing, and what it returns until then
    is an unnamed failure — the exact thing ToolFaceUnavailable exists to end.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        # The status, not the door's own {"error": ..., "reason": ...} body.
        # Measured: the SDK calls raise_for_status() inside `client.stream(...)`,
        # so by the time this runs the response is closed with its body unread
        # and .text raises ResponseNotRead. The reason is not lost — the mount
        # logged it on its own side, where the token it rejected also is.
        return f"http_{exc.response.status_code}"
    if isinstance(exc, httpx.TransportError):
        return _WORD_BOUNDARY.sub("_", type(exc).__name__).lower()
    return None


@asynccontextmanager
async def tool_session(
    face_name: str,
    *,
    session_id: str,
    user_id: str,
    message_id: str | None = None,
    deny: Sequence[str] = (),
):
    """A connected client for one turn, or for one research run.

    `face_name` is a mount name (faces.FACE_NAME_META / FACE_NAME_RESEARCH) and
    it is the whole of what this side chooses: it picks the URL and it is the
    face claim in the token, which the mount checks against its own name. There
    is no registry argument and no db_factory, because the tools and the
    database are behind the door now — a client holding either was holding the
    thing it was supposed to be reaching through.

    user_id is required, where it used to default to None. A token has to name
    somebody, so an anonymous tool session cannot be minted at all; the only
    caller that ever passed None was a test, and what it was testing was a face,
    not a tenant.

    `deny` removes names from that face for this connection alone, which is how
    a skip flag travels now (P6): the capability is absent from tools/list, not
    present and refused. It can only narrow — see mcp_server._served.
    """
    settings = get_settings()
    # rstrip because MCP_URL is the one part of this an operator writes by hand,
    # and a trailing slash builds //mcp/meta — a path Starlette's Route does not
    # match, reported as a 404 from a server that is up and healthy, which is
    # the least informative failure this hop can produce.
    url = f"{settings.mcp_url.rstrip('/')}/mcp/{face_name}"

    # Minted once per session, not per call: the turn's identity is fixed when
    # the turn starts, and a token re-minted mid-loop would be a second place
    # deciding whose work this is. Nothing here can recover from a rejection —
    # see ToolSession.call.
    token = internal_token.mint(
        user_id=user_id,
        session_id=session_id,
        face=face_name,
        message_id=message_id,
        deny=deny,
    )

    # ONE catch for both ways this hop dies, because both arrive at the same
    # place. streamable_http_client runs the stream in a task group: a face that
    # is not there when the session opens fails inside it, and a face that dies
    # mid-run cancels the await in ToolSession.call and fails inside it too — so
    # either way what escapes is the group raised as these with-blocks unwind,
    # never the httpx error itself. Both paths were measured against the real
    # mount before this was written; neither was assumed.
    try:
        # No follow_redirects: each face answers on its own exact path (R2
        # mounted them with Route rather than Mount for that reason), so a
        # redirect arriving here would mean the URL is not the one this build
        # believes in, and quietly following it would send a bearer somewhere
        # nobody chose.
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT,
        ) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (
                read_stream, write_stream, _get_session_id,
            ):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
                    listed = await client.list_tools()
                    yield ToolSession(client, listed.tools)
    except BaseExceptionGroup as group:
        reason = next((r for r in map(_transport_reason, _leaves(group)) if r), None)
        if reason is None:
            # Not this module's failure. Everything the loops raise passes
            # through here too — the provider refusing a prompt, a bug in a
            # handler — and swallowing an exception you cannot name is how a bug
            # becomes a silence. A group is exactly where one would hide.
            raise
        # Logged as well as raised: the api answers a 503 whose body names
        # neither the URL nor the reason, because an internal hostname is not
        # the user's business, so this line is the only place an operator learns
        # which face was unreachable and why.
        logger.warning("tool face %s unreachable at %s: %s", face_name, url, reason)
        raise ToolFaceUnavailable(face_name, url, reason) from group
