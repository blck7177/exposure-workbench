"""S1 regressions: complete recoverable context, no semantic completion claims."""
from __future__ import annotations

import copy
import json

import pytest

from exposure_workbench.agents import delegation as dl, meta_agent, sub_analyst
from exposure_workbench.services import analysis_state as S, fact_boundary
from tests.test_v2_state import BRIEFING, LEDGER, SETTLED, TASK, _result


def test_follow_up_preserves_the_previous_checked_result():
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    first = dl.Task("tsk_first", "risk", ("port_001",), ("weight",))
    S.merge_task(state, first, _result(SETTLED), LEDGER)
    follow = dl.Task("tsk_follow", "risk", ("port_001",), ("beta",), follow_up_of=first.task_id)
    S.start_tasks(state, [follow])
    assert state.accepted()[0]["text"] == SETTLED["finding"]
    assert state.accepted()[0]["task_id"] == first.task_id


def test_checked_caveats_and_follow_ups_survive_receipt_simplification():
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    brief = {"lines": [SETTLED], "caveats": [{"line": 1, "text": "as of the latest run"}],
             "follow_ups": ["Read the previous run before comparing."]}
    task = dl.Task("tsk_1", "risk", ("port_001",), ("weight",))
    verdict = dl.handoff_check(task, brief, LEDGER)
    assert verdict.ok
    result = dl.AnalystResult(task)
    sub_analyst._fill(result, brief, verdict)
    S.merge_task(state, task, result, LEDGER)
    view = S.view(state, LEDGER)
    assert view["findings"][0]["caveats"] == ["as of the latest run"]
    assert view["tasks"][0]["follow_ups"] == brief["follow_ups"]
    assert "caveats" not in dl.for_lead([result])["returns"][0]


def test_refused_caveat_cannot_reappear_in_state():
    task = dl.Task("tsk_1", "risk", ("port_001",), ("weight",))
    brief = {"lines": [SETTLED], "caveats": [{"line": 1, "text": "MSFT weighs 99.0% of the book."}]}
    verdict = dl.handoff_check(task, brief, LEDGER)
    assert not verdict.ok and not verdict.caveats_ok
    result = dl.AnalystResult(task)
    sub_analyst._fill(result, brief, verdict)
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(state, task, result, LEDGER)
    assert "99.0%" not in json.dumps(S.view(state, LEDGER))
    state.findings[0]["caveats"] = [brief["caveats"][0]["text"]]
    restored = S.new_turn("sess", "next", "q", BRIEFING, state, ledger=LEDGER)
    assert restored.accepted() == [], "restoring a checked finding must also recheck its caveats"


def test_every_card_is_reachable_without_silent_first_forty_cutoff():
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    for n in range(95):
        S.add_finding(state, SETTLED["finding"], refs=SETTLED["facts"], ledger=LEDGER, n=n)
    shown, offset = [], 0
    while True:
        page = S.view(state, LEDGER, offset=offset)
        assert page["total"] == 95 and page["question"] == "q"
        shown.extend(f["line"] for f in page["findings"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert shown == list(range(95))
    assert S.view(state, LEDGER, offset=95)["error"] == "invalid_offset"


def test_paging_keeps_a_caveat_with_its_finding_even_for_an_oversized_card():
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    text = "Context. " * S.VIEW_PAGE_CHARS
    finding = S.add_finding(state, text, refs=SETTLED["facts"], ledger=LEDGER)
    finding["caveats"] = ["as of the latest run"]
    S.add_finding(state, SETTLED["finding"], refs=SETTLED["facts"], ledger=LEDGER)
    page = S.view(state, LEDGER)
    assert page["oversized_card"] and page["next_offset"] == 1
    assert page["findings"][0]["text"] == text
    assert page["findings"][0]["caveats"] == finding["caveats"]


def test_newest_task_is_shown_before_older_findings():
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    for name in ["tsk_old", "tsk_new"]:
        task = dl.Task(name, "risk", ("port_001",), ("weight",))
        S.merge_task(state, task, _result(SETTLED), LEDGER)
    assert [f["task"] for f in S.view(state, LEDGER)["findings"]] == ["tsk_new", "tsk_old"]


@pytest.mark.asyncio
async def test_open_current_state_is_scoped_and_paged(monkeypatch):
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(state, TASK, _result(SETTLED), LEDGER)
    async def ledger(*_): return LEDGER
    monkeypatch.setattr(meta_agent, "_load_ledger", ledger)
    page = await meta_agent._open(None, "sess", state.id, [], state=state)
    assert page["findings"][0]["text"] == SETTLED["finding"]
    other = await meta_agent._open(None, "sess", "ast_foreign", [], state=state)
    assert other["error"] == "unknown_state"


@pytest.mark.asyncio
async def test_the_real_loop_delivers_opened_state_pages_and_records_their_ranges(monkeypatch):
    from tests.test_meta_agent_gate import _factory, _stub_desk, _stub_llm, _stub_tools, _W_MSFT
    from tests.test_v2_loop_state import _state_of, ROW
    tools = _stub_tools(monkeypatch, {})
    tools.records.append(dict(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    async def state_open(_, sid, mid, question, brief):
        state = S.new_turn(sid, mid, question, brief)
        from exposure_workbench.services.ledger import Ledger
        for n in range(70):
            S.add_finding(state, ROW, refs=[_W_MSFT["id"]], ledger=Ledger.of(tools.records), n=n)
        return state
    monkeypatch.setattr(meta_agent, "_open_state", state_open)
    calls = []
    async def chat(messages, note, **_):
        calls.append((copy.deepcopy(messages), note))
        if len(calls) == 1:
            page = _state_of(messages)
            return "", [{"id": "open_page", "function": {"name": "open", "arguments": json.dumps(
                {"id": page["id"], "offset": page["next_offset"]})}}]
        return ROW, None
    _stub_llm(monkeypatch, chat)
    out = await meta_agent.handle_message(_factory([]), "sess", "How big is MSFT?")
    page = json.loads(next(m["content"] for m in calls[1][0] if m["role"] == "tool"))
    assert page["shown"][0] > 0 and "truncated" not in page
    current_page = _state_of(calls[1][0])
    assert calls[1][1]["delivered"]["ranges"] == [
        {k: p[k] for k in ("id", "shown", "total")} for p in (current_page, page)]
    assert current_page["id"] != page["id"], "opening an older page must keep its snapshot id"
    assert out["meta"]["delivery"] == "answered" and out["meta"]["completion"] is None


@pytest.mark.asyncio
async def test_opening_a_snapshot_does_not_skip_cards_when_delivery_gaps_change(monkeypatch):
    state = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(state, TASK, _result(SETTLED), LEDGER)
    S.mark_delivery_missing(state, LEDGER, [])
    snapshot = copy.deepcopy(state)
    snapshot.id += "_view0"
    before = S.view(snapshot, LEDGER)
    S.mark_delivery_missing(state, LEDGER, list(LEDGER.by_id))
    assert S.view(state, LEDGER)["total"] < before["total"]
    page = await meta_agent._open(None, "sess", snapshot.id, [], state=state,
                                  work_views={snapshot.id: (snapshot, LEDGER)})
    assert page == before


def test_bad_numbers_do_not_become_valid_just_because_the_work_view_is_simpler():
    assert not fact_boundary.check_text("answer", "MSFT weighs 99.0% [f_w1a2b3c4d5e6].", LEDGER).ok
