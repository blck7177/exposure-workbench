"""A step can record WHAT it did, not just that it finished (offline: no DB).

The timeline's only output per step used to be a prose message, and prose is
where this project's worst defect hid: check_limits skips any check whose input
is None, so a run can execute three of eight checks and still print "All limits
within bounds". Step 8 is about to start recording which checks it evaluated,
and it needs somewhere to put that. `payload` is that somewhere — the step body
assigns or mutates it, __aexit__ writes it to workflow_events.payload_summary.

There are TWO step wrappers in this codebase: ExposureWorkflow._StepContext and
workflow.step_context.step (used by the readiness and issuer-research
workflows). Nearly every test here runs against both, on purpose. They must not
disagree about whether a step can record evidence, because of the shape of the
disagreement rather than its untidiness: on a wrapper without the attribute,
`ctx.payload = {...}` succeeds, is never read, and the event lands with '{}' —
a green step that hides what it did, which is the exact failure this attribute
exists to end.

These tests pin the two halves of "deliberately free": a step that records a
payload gets it persisted, and a step that records nothing lands exactly the
payload_summary it landed before this attribute existed. They also pin the
boundary between those two, because it is where the same defect reappears one
layer down: {} means "recorded nothing" and is legal, while anything that is
not a dict is a bug in the step body and fails loudly instead of being
normalised into the first.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics.limits import LIMIT_SPECS, MissingLimit
from exposure_workbench.services import workflow_event_service
from exposure_workbench.workflow.exposure_workflow import _StepContext
from exposure_workbench.workflow.step_context import mark_skipped, step

# A check name inside a payload is a LIMIT_SPECS key or it is nothing: the
# completeness signal this payload is being built to carry will be produced by
# joining checks_evaluated against REQUIRED_LIMIT_TYPES, so a name that is not a
# key there will read as a check that permanently never ran — a false alarm on
# the very signal. Neither side of that join exists yet: check_limits does not
# populate checks_evaluated and nothing reads it, both of which arrive when the
# engine is switched over to risk_limits. The names have to be real keys before
# then, because this file is where the next author copies them from. This file
# describes itself as the spec for step 8, which makes every
# string in it vocabulary the next author copies, and it previously demonstrated
# the shape with "es_95" and "concentration_single_name", neither of which is a
# check. Deriving instead of typing does not make these names track a rename in
# limits.py — the unpacking would just pick three other real keys — it makes
# them incapable of being anything but real keys, so there is no string here
# that can quietly stop being one. (Too few keys to unpack is an import error,
# which is loud.)
_CHECK_A, _CHECK_B, _CHECK_C = sorted(LIMIT_SPECS)[:3]

# The two wrappers, run through the same expectations. A payload feature that
# exists on only one of them is how a step body ends up silently recording
# nothing (see the module docstring).
both_wrappers = pytest.mark.parametrize(
    "make_ctx", [_StepContext, step], ids=["exposure_StepContext", "step_context_step"]
)


class _FakeDB:
    """Enough AsyncSession for either wrapper; records the ordering of commits."""

    def __init__(self):
        self.calls: list[str] = []

    async def commit(self):
        self.calls.append("commit")

    async def rollback(self):
        self.calls.append("rollback")


class _CaptureDB:
    """Enough AsyncSession for the REAL log_event: keeps the model objects."""

    def __init__(self):
        self.added = []
        self.calls: list[str] = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.calls.append("commit")

    async def rollback(self):
        self.calls.append("rollback")


@pytest.fixture
def logged(monkeypatch):
    """Capture log_event's kwargs instead of writing rows.

    Patched on the service module itself, which both wrappers import by module
    and call by attribute, so one fixture covers both.
    """
    calls: list[dict] = []

    async def _fake_log_event(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(workflow_event_service, "log_event", _fake_log_event)
    return calls


@both_wrappers
async def test_a_step_that_records_nothing_writes_an_empty_payload(make_ctx, logged):
    ctx = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    await ctx.__aexit__(None, None, None)

    start, end = logged
    # The start event is written before the body has run, so there is by
    # definition nothing to record — it must not acquire a payload argument.
    assert "payload_summary" not in start
    assert end["payload_summary"] == {}
    assert end["status"] == "completed"


@both_wrappers
async def test_a_step_that_records_nothing_stores_what_omitting_the_argument_stored(make_ctx):
    """The no-payload path must be behaviour-preserving, not merely similar.

    Every step in every workflow is on this path today, so the attribute has to
    be invisible to all of them: the value a bare `async with` lands in
    payload_summary must be the value log_event writes when no caller mentions
    the argument at all. This one drives the real log_event rather than the
    fixture's stand-in, because the question is what reaches the column.

    What that catches is the two defaults drifting apart: a starting payload
    that is not empty, or log_event's default for an argument nobody mentions
    ceasing to be {}. Read it no wider than that. In particular it does not
    bless log_event's `payload_summary or {}`, which is the coercion that let a
    lost payload land as an event identical to this one — the wrappers now
    refuse a non-dict payload before log_event can see it (see the loud-failure
    tests below), so the only value that reaches the coercion from here is
    already {}. It does NOT prove __aexit__ forwards the payload either; the
    tests that assign one prove that.
    """
    baseline = _CaptureDB()
    await workflow_event_service.log_event(baseline, "run_1", "check_limits", status="completed")

    via_ctx = _CaptureDB()
    ctx = make_ctx(via_ctx, "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    await ctx.__aexit__(None, None, None)

    assert via_ctx.added[-1].payload_summary == baseline.added[-1].payload_summary == {}


@both_wrappers
async def test_an_assigned_payload_reaches_the_event(make_ctx, logged):
    ctx = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    ctx.payload = {"checks_evaluated": [_CHECK_A, _CHECK_B],
                   "checks_skipped": [_CHECK_C]}
    await ctx.__aexit__(None, None, None)

    assert logged[-1]["payload_summary"] == {
        "checks_evaluated": [_CHECK_A, _CHECK_B],
        "checks_skipped": [_CHECK_C],
    }


@both_wrappers
async def test_a_mutated_payload_reaches_the_event(make_ctx, logged):
    # A step body accumulating as it goes (ctx.payload[...] = ...) must work as
    # well as one assignment at the end; __aexit__ reads the attribute late.
    ctx = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    ctx.payload["checks_evaluated"] = [_CHECK_A]
    ctx.payload["checks_evaluated"].append(_CHECK_B)
    await ctx.__aexit__(None, None, None)

    assert logged[-1]["payload_summary"] == {"checks_evaluated": [_CHECK_A, _CHECK_B]}


@both_wrappers
async def test_a_failed_step_still_carries_what_it_recorded(make_ctx, logged):
    """Consistent with the message, which __aexit__ also still writes on failure.

    "It ran two checks and then blew up" and "it blew up before running any" are
    different diagnoses, and this event is the only place either one survives.
    """
    ctx = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    ctx.payload["checks_evaluated"] = [_CHECK_A]
    err = MissingLimit(_CHECK_B, None)
    await ctx.__aexit__(type(err), err, None)

    end = logged[-1]
    assert end["status"] == "failed"
    assert end["payload_summary"] == {"checks_evaluated": [_CHECK_A]}


@both_wrappers
@pytest.mark.parametrize("lost", [None, [], "", 0], ids=["None", "list", "str", "zero"])
async def test_a_non_dict_payload_fails_loudly_instead_of_becoming_empty(make_ctx, lost, logged):
    """`ctx.payload = None` is a bug in the step body, not a step with nothing to say.

    It is what a helper that returns None on an early-return branch leaves
    behind. Normalised — which is what log_event's `payload_summary or {}` does
    to every falsy value — the event is byte-identical to the one a step that
    recorded nothing writes, so "lost what it recorded" and "had nothing to
    record" become indistinguishable after the fact. That is the same green
    step hiding what it did that this attribute exists to end, one layer down,
    so the assignment has to fail rather than the reader having to guess. {}
    stays legal and keeps meaning "recorded nothing" — pinned by the tests
    above.
    """
    ctx = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    ctx.payload = lost

    with pytest.raises(TypeError, match="non-dict payload"):
        await ctx.__aexit__(None, None, None)

    # And no closing event on the way out: a step whose evidence is malformed
    # has not been certified as completed, and an event written from the
    # malformed value is the very thing being refused.
    assert [c["status"] for c in logged] == ["running"]


@both_wrappers
async def test_a_non_dict_payload_is_recorded_not_raised_when_the_body_also_failed(make_ctx, logged):
    """Deliberate asymmetry: on the failure path the malformation is recorded.

    Both wrappers already treat "the body's real cause must reach the timeline"
    as the thing worth protecting — _StepContext rolls the session back before
    writing precisely so the write cannot die of PendingRollbackError and
    replace that cause with plumbing. Raising a TypeError about the evidence
    field while the body's own exception is in flight is that same
    substitution, and a lost payload is the smaller loss of the two. So this
    path records the malformation instead, which also keeps the event
    distinguishable from a step that recorded nothing.
    """
    ctx = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    ctx.payload = None
    err = MissingLimit(_CHECK_A, None)

    assert await ctx.__aexit__(type(err), err, None) is False   # never suppress

    end = logged[-1]
    assert end["status"] == "failed"
    assert str(err) in end["message"], "the body's own cause still reaches the timeline"
    assert end["payload_summary"] == {"payload_error": "None"}
    assert end["payload_summary"] != {}, "not the event a step with no evidence writes"


async def test_the_exposure_wrappers_rollback_does_not_take_the_payload_with_it(logged):
    """_StepContext alone rolls the session back before writing the failure event.

    Its comment claims the payload survives that because it is in-process state.
    Pinned here so the claim stays true: the rollback and the recorded evidence
    have to appear on the same failure.
    """
    db = _FakeDB()
    ctx = _StepContext(db, "run_1", "check_limits", "Checking risk limits")
    await ctx.__aenter__()
    ctx.payload["checks_evaluated"] = [_CHECK_A]
    err = MissingLimit(_CHECK_B, None)
    await ctx.__aexit__(type(err), err, None)

    assert "rollback" in db.calls
    assert logged[-1]["payload_summary"] == {"checks_evaluated": [_CHECK_A]}


@both_wrappers
async def test_each_step_gets_its_own_payload(make_ctx):
    # A class-level dict would make every step of every run share one object:
    # calculate_risk's payload would show up on generate_report's event, and
    # under the same process it would leak across runs.
    a = make_ctx(_FakeDB(), "run_1", "calculate_risk", "Computing VaR")
    b = make_ctx(_FakeDB(), "run_1", "check_limits", "Checking risk limits")
    a.payload[_CHECK_A] = 0.031

    assert b.payload == {}


async def test_mark_skipped_refuses_a_payload_instead_of_dropping_it(logged):
    """mark_skipped is the one place allowed to have no payload — loudly.

    A skipped step has no body, so it has no work to describe; status='skipped'
    plus the reason is the whole honest record. That divergence from `step` is
    only safe while a caller who tries anyway is told at the call site. Give
    this function a **kwargs or an ignored parameter and the divergence becomes
    the same silent drop `step` just had to fix.
    """
    db = _FakeDB()
    with pytest.raises(TypeError):
        await mark_skipped(
            db, "run_1", "refresh_market_data", "skipped by request",
            payload={"prices_refreshed": 0},  # type: ignore[call-arg]
        )

    await mark_skipped(db, "run_1", "refresh_market_data", "skipped by request")
    assert logged[-1]["status"] == "skipped"
    assert "payload_summary" not in logged[-1]
