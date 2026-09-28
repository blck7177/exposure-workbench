"""V21-S1 — a batch of tool calls stops at its first refusal per tool (offline).

The class: one assistant message carrying ten calls composed under one wrong
belief. The wrapper refuses each on its own, correctly, and the model reads
the ten refusals after ten budget units are gone (V19 round 1: ten
`evaluate_formula("net_income")`, five units left, no rank). Only the loop
holds the batch, so agents/batch.py dispatches in order and holds the rest of
a refused tool's calls — returned as `not_attempted`, costing nothing — while
a refusal WITH a table (an absence row: a finding about the world) holds
nothing, and an empty evidence pool holds everything but the pause and exit.
"""

from __future__ import annotations

import inspect
import json

import pytest

from exposure_workbench.agents import batch, meta_agent, research_session


class _Session:
    """A tool face that answers by name, and remembers what reached it."""

    def __init__(self, by_name: dict, default: dict | None = None):
        self.by_name = by_name
        self.default = default or {"ok": True, "table": {"x": 1}}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, name, args, *, actor=None, task_id=None):
        self.calls.append((name, args))
        answer = self.by_name.get(name, self.default)
        return answer(args) if callable(answer) else answer


def _tc(i: int, name: str, **args) -> dict:
    return {"id": f"c{i}", "function": {"name": name, "arguments": json.dumps(args)}}


TEN = [_tc(i, "evaluate_formula", ticker=t, formula="net_income")
       for i, t in enumerate("MSFT AAPL GOOGL AMZN NVDA META TSLA JPM XOM KO".split())]

UNKNOWN_FORMULA = {"error": "unknown_formula", "formula": "net_income",
                   "detail": "net_income is a filed metric: read it with get_flow"}
ABSENT = {"error": "absent", "absence_id": "absence_1", "statement": "not filed",
          "table": {"absence_1": {"statement": "not filed"}}}


@pytest.mark.asyncio
async def test_a_refused_tool_holds_the_rest_of_its_calls_in_the_batch():
    face = _Session({"evaluate_formula": UNKNOWN_FORMULA})
    out = await batch.dispatch(face, TEN, free=("think", "respond"))

    assert len(face.calls) == 1, "only the first call reached the face"
    assert len(out) == 10, "every call still gets its result"
    assert out[0][2] == UNKNOWN_FORMULA
    held = [r for _, _, r in out[1:]]
    assert all(r["error"] == batch.NOT_ATTEMPTED for r in held)
    assert all(r["held_behind"]["error"] == "unknown_formula" for r in held)
    # The held result carries the refusal's own sentence, so the model reads
    # what to do without scrolling back to the first result.
    assert all(r["held_behind"]["detail"] == UNKNOWN_FORMULA["detail"] for r in held)
    assert all(r["tool"] == "evaluate_formula" for r in held)


@pytest.mark.asyncio
async def test_a_refusal_that_put_an_absence_on_the_table_holds_nothing():
    """`get_flow` for a metric the issuer never filed is a finding, and the
    model may want the same read for the other nine names."""
    calls = [_tc(i, "get_flow", ticker=t, metric="research_expense") for i, t in enumerate("ABCDE")]
    face = _Session({"get_flow": ABSENT})
    out = await batch.dispatch(face, calls, free=("think", "respond"))

    assert len(face.calls) == 5
    assert all(r == ABSENT for _, _, r in out)


@pytest.mark.asyncio
async def test_the_hold_is_by_tool_name_and_other_tools_in_the_batch_still_go():
    calls = [_tc(0, "evaluate_formula", ticker="MSFT", formula="net_income"),
             _tc(1, "describe_issuer", ticker="AAPL"),
             _tc(2, "evaluate_formula", ticker="AAPL", formula="net_income"),
             _tc(3, "get_flow", ticker="AAPL", metric="net_income")]
    face = _Session({"evaluate_formula": UNKNOWN_FORMULA})
    out = await batch.dispatch(face, calls, free=("think", "respond"))

    assert [n for n, _ in face.calls] == ["evaluate_formula", "describe_issuer", "get_flow"]
    assert out[2][2]["error"] == batch.NOT_ATTEMPTED
    assert out[1][2]["ok"] and out[3][2]["ok"]


@pytest.mark.asyncio
async def test_calls_before_the_refusal_are_unaffected_and_order_is_kept():
    """The first two names succeed, the third is refused, the rest are held:
    a refusal reaches back over nothing."""
    answers = iter([{"ok": 1, "table": {}}, {"ok": 2, "table": {}}, UNKNOWN_FORMULA])
    face = _Session({"evaluate_formula": lambda _a: next(answers)})
    out = await batch.dispatch(face, TEN[:6], free=("think", "respond"))

    assert [tc["id"] for tc, _, _ in out] == [f"c{i}" for i in range(6)]
    assert out[0][2]["ok"] == 1 and out[1][2]["ok"] == 2
    assert out[2][2] == UNKNOWN_FORMULA
    assert all(r["error"] == batch.NOT_ATTEMPTED for _, _, r in out[3:])
    assert len(face.calls) == 3


@pytest.mark.asyncio
async def test_an_empty_evidence_pool_holds_every_later_read_but_not_the_pause_or_exit():
    """sess_1c71b5fb7f79: 69 calls in one message, 65 refused one round trip
    at a time. After the pool's refusal nothing else reaches the face except
    think and respond."""
    spent = {"error": "budget_exceeded", "kind": "turn_tool", "used": 15, "limit": 15}
    calls = [_tc(0, "get_flow", ticker="A", metric="revenue"),
             _tc(1, "describe_issuer", ticker="B"),
             _tc(2, "think", note="hm"),
             _tc(3, "get_beta", ticker="C"),
             _tc(4, "respond", blocks=[])]
    face = _Session({"get_flow": spent, "think": {"noted": True}, "respond": {"responded": True}})
    out = await batch.dispatch(face, calls, free=("think", "respond"))

    assert [n for n, _ in face.calls] == ["get_flow", "think", "respond"]
    assert out[1][2]["held_behind"]["error"] == "budget_exceeded"
    assert out[1][2]["held_behind"]["used"] == 15
    assert out[3][2]["error"] == batch.NOT_ATTEMPTED
    assert out[2][2] == {"noted": True} and out[4][2] == {"responded": True}


@pytest.mark.asyncio
async def test_a_search_pool_running_dry_holds_only_the_search_tool():
    """external_search is a sub-pool; its refusal says nothing about a filing
    read. It is a call-shaped refusal for ITS tool and nothing more."""
    dry = {"error": "budget_exceeded", "kind": "external_search", "used": 5, "limit": 5}
    calls = [_tc(0, "search_external_research", query="a"),
             _tc(1, "get_flow", ticker="A", metric="revenue"),
             _tc(2, "search_external_research", query="b")]
    face = _Session({"search_external_research": dry})
    out = await batch.dispatch(face, calls, free=("think", "respond"))

    assert [n for n, _ in face.calls] == ["search_external_research", "get_flow"]
    assert out[2][2]["error"] == batch.NOT_ATTEMPTED


@pytest.mark.asyncio
async def test_a_refused_exit_holds_nothing_and_is_never_held():
    """respond's refusals are the gate's, and they say nothing about reads.
    Two respond attempts in one message both reach the gate."""
    gate = {"error": "not_on_table", "problems": []}
    calls = [_tc(0, "respond", blocks=[]), _tc(1, "get_flow", ticker="A", metric="revenue"),
             _tc(2, "respond", blocks=[])]
    face = _Session({"respond": gate})
    out = await batch.dispatch(face, calls, free=("think", "respond"))

    assert [n for n, _ in face.calls] == ["respond", "get_flow", "respond"]
    assert out[2][2] == gate


@pytest.mark.asyncio
async def test_held_calls_are_recorded_and_sent_calls_are_not():
    """The wrapper traces what reaches it; the loop traces what it held, so a
    turn's steps still account for every call the model made."""
    recorded: list[tuple[str, dict, dict]] = []

    async def _record(name, args, result):
        recorded.append((name, args, result))

    face = _Session({"evaluate_formula": UNKNOWN_FORMULA})
    await batch.dispatch(face, TEN[:4], free=("think", "respond"), record=_record)

    assert [n for n, _, _ in recorded] == ["evaluate_formula"] * 3
    assert [a["ticker"] for _, a, _ in recorded] == ["AAPL", "GOOGL", "AMZN"]
    assert all(r["error"] == batch.NOT_ATTEMPTED for _, _, r in recorded)


@pytest.mark.asyncio
async def test_a_recorder_that_fails_does_not_cost_the_turn():
    async def _boom(*_a):
        raise RuntimeError("audit store down")

    face = _Session({"evaluate_formula": UNKNOWN_FORMULA})
    out = await batch.dispatch(face, TEN[:3], free=(), record=_boom)
    assert [r["error"] for _, _, r in out] == ["unknown_formula", batch.NOT_ATTEMPTED, batch.NOT_ATTEMPTED]


def test_unparseable_arguments_are_an_empty_dict_not_a_crash():
    assert batch.parse_args({"id": "x", "function": {"name": "f", "arguments": "{not json"}}) == {}
    assert batch.parse_args({"id": "x", "function": {"name": "f", "arguments": ""}}) == {}


# ── the loops use it ──────────────────────────────────────────────────────────

def test_the_research_loop_dispatches_through_the_one_module_and_the_analyst_dispatches_nothing():
    """V36: the research loop still batches its own tool calls through this
    module. The lead analyst makes no tool calls at all — both of its tools are
    in-process — and the domain analyst that calls the face on its behalf does
    so one call at a time, through the transport (tools_session.call), never
    through invoke()."""
    from exposure_workbench.agents import sub_analyst
    src = inspect.getsource(research_session)
    assert "batch.dispatch(" in src
    assert "tools_session.call(" not in src
    meta_src = inspect.getsource(meta_agent)
    assert "batch.dispatch(" not in meta_src and "tools_session.call(" not in meta_src
    assert "tools_session.call(" in inspect.getsource(sub_analyst)


def test_the_free_names_each_loop_spells_are_its_faces_budget_free_classes():
    from exposure_workbench.tools import faces, registry as R
    from exposure_workbench.tools.registries import build_meta_registry, build_research_registry

    reg, face, spelled = build_research_registry(), faces.FACE_RESEARCH, research_session._BUDGET_FREE_TOOLS
    free = sorted(n for n in face if reg.tools[n].tool_class in R.BUDGET_FREE_CLASSES)
    assert free == sorted(spelled)
    # the analyst's one tool is on no face: nothing it calls is budgeted, because it calls nothing
    assert meta_agent._BUDGET_FREE_TOOLS[0] not in build_meta_registry().tools
