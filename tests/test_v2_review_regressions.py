"""Regressions from review of desk-v2-wip@afcce47. Real state/check/loop code;
only persistence transport, provider and tool faces are replaced where named.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from exposure_workbench.agents import delegation as dl, delivery, meta_agent, sub_analyst
from exposure_workbench.services import analysis_state as S, facts as F
from exposure_workbench.services.ledger import Ledger
from tests.test_v2_state import BRIEFING, LEDGER, SETTLED, WEIGHT, WEIGHT_AGAIN, _result


def state():
    st = S.new_turn("sess", "msg", "how big is MSFT?", BRIEFING)
    st.requirements = [{"id": "R1", "anchor": "how big is MSFT?"}]
    return st


def task(task_id="tsk_1", lines=("weight",), **kw):
    return dl.Task(task_id, "risk", ("port_001",), lines,
                   requirements=(("R1", "how big is MSFT?"),), **kw)


@pytest.mark.parametrize("change", ["book", "run", "as_of", "period", "request", "row", "legacy", "text"])
def test_restore_rejects_stale_or_unchecked_text_for_the_same_issuer(change):
    st = state()
    S.merge_task(st, task(), _result(SETTLED), LEDGER)
    brief, question, records = copy.deepcopy(BRIEFING), st.question, [copy.deepcopy(WEIGHT)]
    if change == "book":
        brief["subjects"]["portfolios"] = ["port_other"]
    elif change == "run":
        brief["portfolios"]["port_001"]["runs"]["latest"]["id"] = "run_new"
    elif change == "as_of":
        brief["portfolios"]["port_001"]["runs"]["latest"]["as_of"] = "2026-09-11"
    elif change == "period":
        brief["issuers"] = {"MSFT": {"latest_period_end": "2026-06-30"}}
    elif change == "request":
        question = "how big was MSFT in 2025?"
    elif change == "row":
        records[0]["value"] = 0.18
    elif change == "legacy":
        st.findings[0].pop("validation")
    else:
        st.findings[0]["text"] = "MSFT weighs 99.0% of the book."
    restored = S.new_turn("sess", "next", question, brief, st, ledger=Ledger.of(records))
    assert restored.accepted() == []


def test_unchanged_scope_rechecks_and_copies_the_prior_finding():
    st = state()
    S.merge_task(st, task(), _result(SETTLED), LEDGER)
    restored = S.new_turn("sess", "next", st.question, BRIEFING, st, ledger=LEDGER)
    assert restored.findings[0]["status"] == "inherited"
    assert restored.findings[0]["requirement_ids"] == []
    restored.findings[0]["validation"]["facts"].clear()
    assert st.findings[0]["validation"]["facts"]


@pytest.mark.parametrize("failure", ["cannot", "param_out_of_range", "not_on_this_face", "refused", "missing"])
def test_one_success_cannot_hide_an_unfinished_line_of_the_same_requirement(failure):
    st = state()
    bad = {"id": "f_failed0001", "kind": "absence", "means": {"reason": failure}}
    led = Ledger.of([WEIGHT, bad])
    result = _result(SETTLED)
    if failure != "missing":
        result.lines.append({"n": 2, "settled": False, "why": "cannot read", "boundary": bad["id"]})
    if failure == "refused":
        result.refused = [{"n": 2}]
    S.merge_task(st, task(lines=("weight", "beta")), result, led)
    assert st.requirements[0]["status"] == "unresolved"
    assert S.completion_of(st) == "partial"
    assert S.unaddressed(st, [WEIGHT["id"], bad["id"]])
    assert st.tasks[0]["lines"][1]["status"] == "unresolved"


def test_explicit_follow_up_replaces_only_its_predecessors_named_requirements():
    st = state()
    st.requirements.append({"id": "R2", "anchor": "beta"})
    prior = dl.Task("tsk_1", "risk", ("port_001",), ("weight", "beta"),
                    requirements=(("R1", "weight"), ("R2", "beta")),
                    line_requirements=(("R1",), ("R2",)))
    S.merge_task(st, prior, _result(), LEDGER)
    follow = task("tsk_2", follow_up_of="tsk_1")
    S.start_tasks(st, [follow])
    assert [r["status"] for r in st.requirements] == ["unresolved", "unresolved"]
    S.merge_task(st, follow, _result(SETTLED), LEDGER)
    assert [r["status"] for r in st.requirements] == ["covered", "unresolved"]
    assert S.completion_of(st) == "partial"
    repair_beta = dl.Task("tsk_3", "risk", ("port_001",), ("beta",), follow_up_of="tsk_1",
                          requirements=(("R2", "beta"),))
    S.merge_task(st, repair_beta, _result({"n": 1, "settled": False, "why": "no forecast",
                                          "boundary": "f_policy_no_forecast"}), LEDGER)
    assert S.completion_of(st) == "completed_with_boundaries"


def test_scope_change_invalidates_boundaries_as_well_as_findings():
    st = state()
    S.merge_task(st, task(), _result({"n": 1, "settled": False, "why": "no forecast",
                                    "boundary": "f_policy_no_forecast"}), LEDGER)
    assert S.completion_of(st) == "completed_with_boundaries"
    S.invalidate(st, {**st.scope, "request": "different question"})
    assert S.completion_of(st) == "partial" and not S.active_gaps(st)


def test_conflicts_block_completion_but_different_books_are_not_conflicts():
    st = state()
    S.merge_task(st, task(), _result(SETTLED), LEDGER)
    S.add_finding(st, "other", refs=[WEIGHT_AGAIN["id"]], ledger=LEDGER, requirement_ids=["R1"])
    assert S.conflicts(st, LEDGER) and S.completion_of(st) == "partial"
    different_book = Ledger.of([WEIGHT, {**WEIGHT_AGAIN, "params": {"of": "run_other"}}])
    assert not S.conflicts(st, different_book) and S.completion_of(st) == "completed"


def test_all_mapped_results_must_be_reached_by_the_reply():
    st = state()
    other = {**SETTLED, "n": 2, "facts": [WEIGHT_AGAIN["id"]]}
    S.merge_task(st, task(lines=("first", "second")), _result(SETTLED, other), LEDGER)
    assert S.completion_of(st) == "completed"
    assert S.unaddressed(st, [WEIGHT["id"]])
    assert not S.unaddressed(st, [WEIGHT["id"], WEIGHT_AGAIN["id"]])


def test_final_partial_survives_persistence_reload_and_projection():
    st = state()
    S.merge_task(st, task(), _result(SETTLED), LEDGER)
    assert S.completion_of(st) == "completed"
    st.completion = "partial"  # evidence was collected, but the final reply omitted it
    saved = S._fields(st)
    restored = S._from_row(SimpleNamespace(id=st.id, version=2, **saved))
    assert saved["completion"] == restored.completion == S.view(restored, LEDGER)["completion"] == "partial"


@pytest.mark.asyncio
async def test_save_conflict_never_borrows_a_new_version_to_overwrite(monkeypatch):
    st, calls = state(), []
    st.version = 3
    class Db:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def commit(self): calls.append("commit")
    async def fail_save(db, candidate):
        calls.append(("save", candidate.version))
        raise S.StaleState("newer state exists")
    async def load(db, sid):
        calls.append("load")
        return SimpleNamespace(version=4)
    monkeypatch.setattr(S, "save", fail_save)
    monkeypatch.setattr(S, "load", load)
    with pytest.raises(S.StaleState):
        await meta_agent._save_state(Db, st)
    assert calls == [("save", 3)] and st.version == 3


@pytest.mark.parametrize("args", [{}, {"requirements": None}, {"requirements": []}])
def test_first_ask_cannot_bypass_requirements(args):
    with pytest.raises(dl.BadDelegation, match="first ask"):
        dl.parse_requirements(args, "how big is MSFT?")


def test_delivery_counts_state_prior_rows_and_page_ranges_separately_from_mentions():
    d = delivery.Delivered()
    page = {"id": "r_12345678", "shown": [20, 39], "total": 120, "rows": [F.line(WEIGHT)]}
    messages = [{"role": "system", "content": "<state>" + json.dumps({"rows": [F.line(WEIGHT_AGAIN)]})},
                {"role": "user", "content": "<prior>\n" + F.line(WEIGHT)},
                {"role": "assistant", "content": "[f_invented0001] 1.0%"},
                {"role": "tool", "content": json.dumps(page)}]
    d.project(messages)
    shown = d.note()["delivered"]
    assert shown["facts"] == sorted([WEIGHT["id"], WEIGHT_AGAIN["id"]])
    assert "f_invented0001" in shown["mentioned"]
    assert shown["ranges"] == [{k: page[k] for k in ("id", "shown", "total")}]


@pytest.mark.asyncio
async def test_legacy_or_changed_scope_reports_are_not_prior_context(monkeypatch):
    from tests.test_v1_analyst import _Tools, _ctx, _read, _submit
    from tests.test_v2_follow_up import PRIOR, FOLLOW
    tools = _Tools()
    ctx, _, _, _ = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED))], tools)
    tools.records.append(dict(WEIGHT))
    prior = copy.deepcopy(PRIOR)
    async def load(*_): return prior
    monkeypatch.setattr(sub_analyst.analyst_reports, "load_by_task", load)
    assert await sub_analyst._prior_block(FOLLOW, ctx) == ""
    for entry in prior["accepted_lines"]:
        entry["validation"] = S.validation_context(S.scope_of(ctx.briefing, "earlier question"),
                                                   entry.get("facts") or [entry["boundary"]], LEDGER)
    assert await sub_analyst._prior_block(FOLLOW, ctx) == ""


@pytest.mark.asyncio
async def test_final_reply_partial_is_saved_even_when_all_evidence_is_collected(monkeypatch):
    from tests.test_meta_agent_gate import _delegate, _factory, _run, _run_result, _stub_desk, _stub_llm, _stub_tools, _submit, _two_loops, _W_MSFT
    chat, lead, _ = _two_loops(
        [("", _delegate()), ("The desk has checked the book.", None)],
        [("", _run()), ("", _submit((["f_wmsft0001"], "MSFT weighs 16.0% [f_wmsft0001] of the book.")))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    saved = []
    async def save(_, st): saved.append(copy.deepcopy(S._fields(st)))
    monkeypatch.setattr(meta_agent, "_save_state", save)
    out = await meta_agent.handle_message(_factory([]), "sess", "how big is MSFT?")
    assert out["meta"]["requirements"][0]["status"] == "covered"
    assert out["meta"]["completion"] == saved[-1]["completion"] == "partial"
    assert "Still open" in out["text"]
    assert saved[-1]["budget"]["lead_completions_used"] == len(lead)


@pytest.mark.asyncio
async def test_prior_ledger_can_be_opened_before_the_first_ask(monkeypatch):
    from tests.test_meta_agent_gate import _factory, _stub_desk, _stub_llm, _stub_tools, _W_MSFT
    tools = _stub_tools(monkeypatch, {})
    tools.records.append(dict(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    calls = []
    async def chat(messages, tools, **_):
        calls.append(copy.deepcopy(messages))
        assert dl.OPEN_TOOL_NAME in [t["function"]["name"] for t in tools]
        if len(calls) == 1:
            return "", [{"id": "o1", "function": {"name": dl.OPEN_TOOL_NAME,
                           "arguments": json.dumps({"id": _W_MSFT["id"]})}}]
        return "MSFT weighs 16.0% [f_wmsft0001] of the book.", None
    _stub_llm(monkeypatch, chat)
    out = await meta_agent.handle_message(_factory([]), "sess", "show that MSFT row again")
    assert out["citations"] == [_W_MSFT["id"]]
    opened = json.loads(next(m["content"] for m in calls[1] if m["role"] == "tool"))
    assert opened["row"] == F.line(_W_MSFT) and not tools.calls
