"""V8-C2 — the two criteria about what the turn did (offline).

Each criterion gets three tests, and the third is the one that matters: the
violation is refused, the compliant shape passes, and the refusal is reachable
from a turn with NO BUDGET LEFT. The third is V7-Q2's mirror. That incident was
not a degraded answer, it was a turn with no exit — a gate refusing to let the
model out unless it spent a budget it had already spent — and any new refusal
can reproduce it unless the way out costs nothing.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import trajectory_gate as tg


class _Step:
    def __init__(self, tool_name, status="completed", refs=None, seq=0):
        self.tool_name, self.status, self.evidence_refs, self.seq = tool_name, status, refs or [], seq


class _DB:
    """Returns a fixed step list for any query, and counts that it was asked."""

    def __init__(self, steps): self.steps, self.queries = steps, 0

    async def execute(self, *_a, **_k):
        self.queries += 1
        outer = self

        class _R:
            def scalars(self): return self
            def all(self): return outer.steps
        return _R()


async def _check(steps, text, citations, message_id="msg_1"):
    return await tg.check(_DB(steps), "sess_1", message_id, text, citations)


# ── R1: read the book before explaining it with a filing ─────────────────────

async def test_r1_refuses_a_portfolio_claim_supported_only_by_filings():
    """The incident shape. Every sentence individually true and cited; the causal
    link between them checked by nothing. A 10-K's risk factors were equally true
    on every day the book rose."""
    out = await _check([_Step("search_filing_passages")],
                       "The book fell because AAPL flagged supply concentration.",
                       ["run_1", "chunk_9"])
    assert out is not None and out["error"] == "attribution_not_read"


async def test_r1_passes_once_the_contributions_were_read():
    for tool in ("get_attribution", "reconcile_move", "get_portfolio_snapshot"):
        assert await _check([_Step(tool), _Step("search_filing_passages")],
                            "AAPL contributed most of the fall; its filing notes supply risk.",
                            ["run_1", "chunk_9"]) is None, tool


async def test_r1_does_not_fire_on_an_issuer_question():
    """A question about one company's filings cites chunk_ and nothing about the
    book. There is no causal claim joining two kinds of evidence, so there is
    nothing for this criterion to be about — and firing here would make every
    'how much debt does AAPL have' answer demand a portfolio tool."""
    assert await _check([_Step("search_filing_passages")],
                        "AAPL's 10-K describes supplier concentration.", ["chunk_9"]) is None


async def test_r1_does_not_fire_on_a_portfolio_only_answer():
    assert await _check([_Step("get_portfolio_snapshot")],
                        "The book fell 1.3%.", ["run_1"]) is None


async def test_r1_is_escapable_by_deleting_the_sentence():
    """DP4, on the criterion's own terms. The refusal names two exits and one of
    them is free: drop the filing citation. A turn with nothing left to spend
    must be able to take it."""
    steps = [_Step("search_filing_passages")]
    assert await _check(steps, "The book fell because AAPL flagged supply risk.",
                        ["run_1", "chunk_9"]) is not None
    assert await _check(steps, "The book fell 1.3%.", ["run_1"]) is None


# ── R2: say what you started ─────────────────────────────────────────────────

def _delegations(n):
    return [_Step("start_issuer_research", refs=[{"id": f"rrun_{i}", "type": "research_run"}])
            for i in range(n)]


async def test_r2_refuses_a_turn_that_enqueued_more_than_two_and_named_none():
    out = await _check(_delegations(6), "I have started some research for you.", [])
    assert out is not None and out["error"] == "delegated_work_unreported"
    assert len(out["problems"][0]["run_ids"]) == 6


async def test_r2_allows_two_unnamed():
    """Two is a turn that delegated and said which. The criterion is about the
    count disappearing into 'some research', which starts at three."""
    assert await _check(_delegations(2), "I have started some research.", []) is None


async def test_r2_passes_when_every_id_is_named():
    text = "Started: " + ", ".join(f"rrun_{i}" for i in range(4))
    assert await _check(_delegations(4), text, []) is None


async def test_r2_names_only_the_missing_ones():
    out = await _check(_delegations(4), "Started rrun_0 and rrun_1.", [])
    assert out["problems"][0]["run_ids"] == ["rrun_2", "rrun_3"]


async def test_r2_is_escapable_at_zero_tool_cost():
    """The ids are already in the model's context — they came back from the calls
    it just made. Satisfying this costs a longer sentence, not a tool call."""
    steps = _delegations(3)
    assert await _check(steps, "Started three runs.", []) is not None
    assert await _check(steps, "Started rrun_0, rrun_1, rrun_2.", []) is None


async def test_r2_ignores_a_delegation_that_failed():
    """A rejected or errored call enqueued nothing, so there is nothing to
    report. Counting it would demand the model name a run that does not exist."""
    steps = _delegations(3) + [_Step("start_issuer_research", status="error"),
                               _Step("start_issuer_research", status="rejected")]
    assert await _check(steps, "Started rrun_0, rrun_1, rrun_2.", []) is None


# ── scope ────────────────────────────────────────────────────────────────────

async def test_without_a_message_scope_there_is_nothing_to_judge():
    """A direct call, the recipe path. Scoping to the session instead would judge
    this answer against another turn's steps — and would then be satisfied
    forever by one old tool call, which is a criterion that has stopped
    criticising."""
    db = _DB(_delegations(6))
    assert await tg.check(db, "sess_1", None, "I started some research.", []) is None
    assert db.queries == 0, "no message scope means no query at all"
