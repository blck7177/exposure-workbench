"""R5 — what a mount serves is physical, and a request may only narrow it (offline).

Two properties that have to hold together, driven through the real door and the
real transport (tests/mcp_mount.py).

The face is physical (N9). The research mount's registry registers eighteen
tools and its face names fourteen; the four meta-only reads are not hidden from
the model, they are not there. read_issuer_brief is the one that says why: a
brief-writing agent citing a previous brief's ids is a citation loop, not a
source, so the answer to calling it must be "no such tool", not "not allowed" —
a refusal is something a model retries.

deny narrows and can never widen (P6 as R4 expresses it). A skip flag used to
trim the face on the caller's side; now it travels in the token and the mount
computes face-minus-deny. The whole value of that is one direction: whatever a
token says, the request cannot end up with a tool the mount does not serve. So
the tests below are not only "deny removed the right name" but "no deny value
adds one".
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_research_registry
from tests.mcp_mount import RecordingDb, connected, mounted, use_secret

FACE = faces.FACE_NAME_RESEARCH
SKIPPED = "search_external_research"          # what skip_external_research removes
META_ONLY = "read_issuer_brief"               # registered, and outside this face


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    use_secret(monkeypatch)


async def _served(deny=()) -> list[str]:
    async with mounted(build_research_registry(), faces.FACE_RESEARCH, face_name=FACE) as door:
        async with connected(door, face_name=FACE, user_id="user_a",
                             session_id="sess_a", deny=deny) as client:
            return [t.name for t in (await client.list_tools()).tools]


async def _called(name: str, deny=()) -> tuple[dict, bool, list]:
    db = RecordingDb()
    async with mounted(build_research_registry(), faces.FACE_RESEARCH,
                       face_name=FACE, db_factory=lambda: db) as door:
        async with connected(door, face_name=FACE, user_id="user_a",
                             session_id="sess_a", deny=deny) as client:
            out = await client.call_tool(name, {})
    return json.loads(out.content[0].text), bool(out.isError), db.added


# ── the mount's face ─────────────────────────────────────────────────────────

async def test_the_mount_serves_its_face_and_not_its_registry():
    served = await _served()
    assert served == faces.FACE_RESEARCH
    assert META_ONLY in build_research_registry().tools, "the registry has it"
    assert META_ONLY not in served, "and the face is what the mount serves"


async def test_a_tool_outside_the_face_is_unknown_rather_than_forbidden():
    """Dispatch is against the face, not against the registry behind it. When it
    was against the registry the face only described what the model had been
    told about, and a research session offered fourteen tools could still call
    the four it was not."""
    payload, is_error, steps = await _called(META_ONLY)

    assert payload == {"error": "unknown_tool", "tool": META_ONLY}
    assert is_error
    # invoke() answers for a name it does not hold, so the refusal is the gate's
    # and it is recorded: the model is told, and the desk can see it was tried.
    assert [(s.tool_name, s.status) for s in steps] == [(META_ONLY, "error")]


# ── deny ─────────────────────────────────────────────────────────────────────

async def test_a_denied_tool_is_absent_from_the_face_it_was_denied_from():
    """skip_external_research, end to end as R4 sends it. The capability does
    not exist for this run rather than existing and refusing."""
    served = await _served(deny=(SKIPPED,))

    assert SKIPPED not in served
    assert served == [n for n in faces.FACE_RESEARCH if n != SKIPPED]
    assert len(served) == len(faces.FACE_RESEARCH) - 1


async def test_a_denied_tool_is_unknown_to_call_tool_and_not_only_unlisted():
    """The half that matters. A model does not have to read tools/list to try a
    name it saw in an earlier turn, so a deny that only hid the tool would be a
    skip flag that a persistent model can spend its way around."""
    payload, is_error, steps = await _called(SKIPPED, deny=(SKIPPED,))

    assert payload == {"error": "unknown_tool", "tool": SKIPPED}
    assert is_error
    assert [(s.tool_name, s.status) for s in steps] == [(SKIPPED, "error")]


async def test_a_deny_naming_a_tool_this_mount_never_offered_is_a_no_op():
    """A caller that skips a capability must be able to say so to a mount that
    never offered it. Refusing would turn the already-narrower request into the
    failing one, which is the wrong direction to fail in."""
    assert await _served(deny=(META_ONLY,)) == faces.FACE_RESEARCH


@pytest.mark.parametrize("deny", [
    (META_ONLY,),
    ("get_portfolio_snapshot", "get_task_status"),
    ("respond", "start_issuer_research"),
    ("no_such_tool_anywhere",),
    tuple(faces.FACE_META_AGENT),
], ids=["a registered tool outside the face", "two of them", "tools of the other face",
        "a name nobody registered", "the whole other face"])
async def test_no_deny_value_can_add_a_tool_to_the_face(deny):
    """The property, stated as the only direction that is allowed. Every entry
    here is a way a token could name something this mount does not serve, and
    none of them may produce a face larger than the mount's own.

    A blank entry is missing from the list because it cannot be minted and would
    not verify either (test_internal_token); everything reaching this layer is
    already a non-empty string, so the question left for the mount is only what
    it does with a name.
    """
    served = await _served(deny=deny)

    assert set(served) <= set(faces.FACE_RESEARCH)
    assert served == [n for n in faces.FACE_RESEARCH if n not in deny]


async def test_a_deny_does_not_outlive_the_request_that_carried_it():
    """Same mount, two connections. deny is per request; a mount that remembered
    one would be a skip flag leaking into the next run — and, since the mount
    outlives every run, into another tenant's."""
    async with mounted(build_research_registry(), faces.FACE_RESEARCH, face_name=FACE) as door:
        async with connected(door, face_name=FACE, user_id="user_a", session_id="sess_a",
                             deny=(SKIPPED,)) as narrowed:
            first = [t.name for t in (await narrowed.list_tools()).tools]
        async with connected(door, face_name=FACE, user_id="user_b",
                             session_id="sess_b") as plain:
            second = [t.name for t in (await plain.list_tools()).tools]

    assert SKIPPED not in first
    assert second == faces.FACE_RESEARCH
