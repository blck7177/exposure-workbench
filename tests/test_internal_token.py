"""R1/N7 — every way an internal bearer can be wrong, one test each (offline).

The price of residency is stated in MCP_PLAN §4: v2's "identity is a constructor
argument, so it is physically impossible to get wrong" is traded for "the door
must be correct". This file is one third of what was promised in exchange — the
negative matrix. The other two are the ASGI door itself (test_mcp_middleware)
and two tenants proved concurrent through the real transport
(test_mcp_identity_binding).

One property per test, named for it, because the reason string is what an
operator reads at 3am and a matrix that asserts "it raised" would let two of
these collapse into each other without anyone noticing.

Nothing here reads .env: the secret is set on the settings object, so a machine
with no .env and a machine with a real deployment's .env run the same tests.
"""

from __future__ import annotations

import time

import jwt
import pytest

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.internal_token import InternalAuthError, mint, verify
from exposure_workbench.tools import faces
from tests.mcp_mount import TEST_SECRET, use_secret

FACE = faces.FACE_NAME_META


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    use_secret(monkeypatch)


def _claims(**overrides) -> dict:
    now = int(time.time())
    payload = {
        "sub": "user_a", "sid": "sess_a", "face": FACE, "deny": [],
        "iat": now, "exp": now + 1800,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _ABSENT}


class _Absent:
    """A sentinel, so a test can say 'this claim is not there' as an override."""


_ABSENT = _Absent()


def _token(secret: str = TEST_SECRET, algorithm: str = "HS256", **overrides) -> str:
    return jwt.encode(_claims(**overrides), secret, algorithm=algorithm)


def _reason(token: str, expected_face: str = FACE) -> str:
    with pytest.raises(InternalAuthError) as exc:
        verify(token, expected_face=expected_face)
    return exc.value.reason


# ── the positive case, so the negatives mean something ───────────────────────

def test_a_minted_token_verifies_to_exactly_what_was_minted():
    claims = verify(
        mint(user_id="user_a", session_id="sess_a", face=FACE,
             message_id="msg_1", deny=["think"]),
        expected_face=FACE,
    )
    assert (claims.user_id, claims.session_id, claims.face) == ("user_a", "sess_a", FACE)
    assert (claims.message_id, claims.deny) == ("msg_1", ("think",))


def test_a_turn_with_no_message_carries_no_message_claim():
    """mid is the one optional claim. A research run has no message to attribute
    a step to, and writing an empty one would make trace_service store a
    message_id that resolves to nothing."""
    assert verify(mint(user_id="user_a", session_id="sess_a", face=FACE),
                  expected_face=FACE).message_id is None


# ── signature ────────────────────────────────────────────────────────────────

def test_a_token_signed_with_another_secret_does_not_verify():
    """The whole mechanism: api, worker and exposure-mcp share one key, and a
    bearer that did not come from that key came from somebody else."""
    assert _reason(_token(secret="a-different-secret-of-adequate-length")).startswith(
        "invalid_token:"
    )


def test_an_unsigned_token_does_not_verify():
    """alg=none is a signature the caller chose not to apply. pyjwt will honour
    it if 'none' is in algorithms, so the one-element list in verify() is the
    only thing standing between this token and a served tool face."""
    assert _reason(_token(secret=None, algorithm="none")).startswith("invalid_token:")


def test_a_token_signed_with_rs256_does_not_verify():
    """Algorithm confusion, the other half: a verifier that accepts a family it
    was never given a key for lets the header decide how it is checked."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _reason(jwt.encode(_claims(), key, algorithm="RS256")).startswith("invalid_token:")


def test_exactly_one_algorithm_is_ever_accepted():
    """The two tests above cannot fail on their own, and that is the point.

    pyjwt refuses alg=none while a key is present, and it cannot check an RS256
    signature against an HMAC string, so widening `algorithms` does not by
    itself let either token through today. What it does is arm the confusion for
    the day the shared secret is something a header can name — a PEM, a JWKS
    entry, anything a second deployment decides to reuse here. So the list is
    pinned as it is written, next to the tokens that probe it, rather than
    inferred from the fact that two attacks happen to bounce off pyjwt first.
    """
    import inspect

    from exposure_workbench.auth import internal_token

    assert internal_token._ALGORITHM == "HS256"
    assert "algorithms=[_ALGORITHM]" in inspect.getsource(internal_token.verify)


# ── lifetime ─────────────────────────────────────────────────────────────────

def test_an_expired_token_does_not_verify():
    now = int(time.time())
    assert _reason(_token(iat=now - 3600, exp=now - 1800)) == "expired"


def test_a_token_a_few_seconds_past_expiry_is_still_taken():
    """N8's 60s leeway. Both ends run on the same host, so this is slack against
    a container's clock stepping, not against a real difference — and without it
    a research run would lose its tools to a leap second."""
    now = int(time.time())
    claims = verify(_token(iat=now - 1830, exp=now - 30), expected_face=FACE)
    assert claims.user_id == "user_a"


def test_the_leeway_is_slack_and_not_a_second_lifetime():
    now = int(time.time())
    assert _reason(_token(iat=now - 1920, exp=now - 120)) == "expired"


# ── required claims ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "sid", "face"])
def test_a_token_missing_a_required_claim_does_not_verify(claim):
    """Absent, not merely falsy: pyjwt refuses before any value check runs, so a
    token minted by something that is not mint() is a rejection rather than a
    KeyError deeper in."""
    assert _reason(_token(**{claim: _ABSENT})) == f"missing_claim:{claim}"


@pytest.mark.parametrize("claim, reason", [("sub", "no_sub"), ("sid", "no_sid"),
                                           ("face", "no_face")])
def test_a_present_but_empty_identifier_is_not_an_identity(claim, reason):
    """require= only proves a claim is there. An empty sub is an anonymous tool
    call with a valid signature on it, which is precisely the pre-P1.3 state."""
    assert _reason(_token(**{claim: ""})) == reason


@pytest.mark.parametrize("mid", ["", 7, ["msg_1"]], ids=["empty", "a number", "a list"])
def test_a_message_id_that_is_not_one_does_not_verify(mid):
    """mid names the agent_messages row a trace step is attributed to. A token
    carrying something else there is a step filed under an id that resolves to
    nothing."""
    assert _reason(_token(mid=mid)) == "bad_mid"


# ── deny ─────────────────────────────────────────────────────────────────────

def test_a_token_with_no_deny_claim_is_refused_rather_than_read_as_empty():
    """The one that is easy to get wrong in the safe-looking direction.

    mint() always writes deny, so its absence means something other than mint()
    produced this token. Reading absence as 'nothing denied' would hand a
    research run started with skip_external_research the exact tool the flag
    exists to remove — a widening, arriving as a default.
    """
    assert _reason(_token(deny=_ABSENT)) == "bad_deny"


@pytest.mark.parametrize("deny", ["search_external_research", {"tool": "think"}, 7],
                         ids=["a bare string", "an object", "a number"])
def test_a_deny_that_is_not_a_list_does_not_verify(deny):
    """A bare string is the dangerous one: it is iterable, so a verifier that
    only checked membership would deny every tool whose name is a substring of
    it and nothing else."""
    assert _reason(_token(deny=deny)) == "bad_deny"


@pytest.mark.parametrize("deny", [["think", 7], ["think", None], ["think", ""]],
                         ids=["a number", "a null", "an empty name"])
def test_a_deny_entry_that_is_not_a_tool_name_does_not_verify(deny):
    assert _reason(_token(deny=deny)) == "bad_deny"


# ── the mount's own name ─────────────────────────────────────────────────────

def test_a_token_for_another_face_does_not_verify_at_this_mount():
    """N9's second lock. The mount has already decided which face it serves, so
    this can only fire when the two disagree — a mistyped MCP_URL, or a swapped
    mount table. Without it the research run's token would be served the meta
    face and nothing would say so."""
    token = mint(user_id="user_a", session_id="sess_a", face=faces.FACE_NAME_RESEARCH)
    assert _reason(token, expected_face=faces.FACE_NAME_META) == "face_mismatch:token=research"


# ── mint refuses what it cannot attribute ────────────────────────────────────

@pytest.mark.parametrize("field, kwargs", [
    ("blank_user_id", {"user_id": "   "}),
    ("blank_user_id", {"user_id": None}),
    ("blank_session_id", {"session_id": ""}),
    ("blank_face", {"face": ""}),
    ("blank_message_id", {"message_id": " "}),
    ("blank_deny_entry", {"deny": ["think", ""]}),
])
def test_mint_refuses_an_argument_it_could_not_attribute_later(field, kwargs):
    """Checked at mint rather than only at verify, because a token minted with an
    empty sub is a 401 half an hour later, in another container, attributed to
    whichever request happened to spend it."""
    args = {"user_id": "user_a", "session_id": "sess_a", "face": FACE, **kwargs}
    with pytest.raises(InternalAuthError) as exc:
        mint(**args)
    assert exc.value.reason == field


# ── the key itself ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", ["mint", "verify"])
def test_without_a_secret_neither_end_pretends_to_work(monkeypatch, call):
    """.env.example promises an empty MCP_INTERNAL_SECRET stops api, worker and
    exposure-mcp from coming up. An unsigned internal bearer is not a degraded
    tool face, it is an open one."""
    token = mint(user_id="user_a", session_id="sess_a", face=FACE)
    monkeypatch.setattr(get_settings(), "mcp_internal_secret", "")

    with pytest.raises(InternalAuthError) as exc:
        if call == "mint":
            mint(user_id="user_a", session_id="sess_a", face=FACE)
        else:
            verify(token, expected_face=FACE)
    assert exc.value.reason.startswith("mcp_internal_secret_unset:")
    assert "MCP_INTERNAL_SECRET" in exc.value.reason


# ── the lifetime is sized against the run it has to outlive ──────────────────

def test_a_token_outlives_the_longest_run_it_could_be_minted_for():
    """N8, and load-bearing since R4: run_research_session mints ONCE for the
    whole run. A ttl under the task lease means a run still inside its lease
    loses its tool face halfway — every remaining call 401s, the loop has no way
    to re-mint, and (tool_session.call) a 401 ends the turn rather than
    degrading it. The other direction is a settings decision, not this test's:
    a token much longer-lived than the lease would still be working after the
    run it belongs to was handed to somebody else.
    """
    settings = get_settings()
    assert settings.mcp_token_ttl_seconds >= settings.task_lease_seconds
