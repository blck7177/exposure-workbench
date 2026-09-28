"""V2 P2b: the analysis state (design v0.4 §07) and its one door. Offline: the
check, the ledger and the row renderer are real; the database is a fake that
remembers what was added or reports how many rows an UPDATE touched.

A3: a rejected proposal is a trace row and never a finding, never in the view.
A4: a scope change marks what fell outside stale, and stale is not projected.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.services import analysis_state as S, trace_service
from exposure_workbench.services.ledger import Ledger

WEIGHT = {"id": "f_w1a2b3c4d5e6", "kind": "scalar", "measure": "issuer_exposures.weight", "subject": "MSFT", "unit": "RATIO",
          "value": 0.16, "as_of": "2026-09-10", "window": None, "params": {"pull": "r_1", "of": "run_x"},
          "standalone": True, "sources": ["run_x"], "group": "composition", "means": {}}
WEIGHT_AGAIN = {**WEIGHT, "id": "f_w2b3c4d5e6f7", "value": 0.18, "params": {"pull": "r_2", "of": "run_x"}}
UNREAD = {**WEIGHT, "id": "f_u3c4d5e6f7a8", "subject": "AAPL", "value": 0.12, "params": {"pull": "r_3", "of": "run_x"}}
NO_BETA = {"id": "f_no1a2b3c4d5e", "kind": "absence", "measure": "price.beta", "subject": "MSFT", "unit": None, "value": None,
           "text": "metric: fewer than 60 aligned observations", "as_of": "n/a", "window": None,
           "params": {"pull": "r_2", "error": "insufficient_history"}, "standalone": False, "sources": [],
           "group": "boundary", "means": {"reason": "not_held"}}
LEDGER = Ledger.of([WEIGHT, WEIGHT_AGAIN, UNREAD, NO_BETA])
BRIEFING = {"subjects": {"tickers": ["MSFT"], "portfolios": ["port_001"], "runs": []},
            "portfolios": {"port_001": {"runs": {"latest": {"id": "run_x", "as_of": "2026-09-10"}}}}}
TASK = dl.Task("tsk_1", "risk", ("port_001",), ("how big MSFT is", "MSFT's beta", "MSFT next year"))


def _result(*lines, refused=()):
    return SimpleNamespace(lines=list(lines), refused=[{"n": n} for n in refused], status="partial",
                           coverage={"asked": 3}, made=[])


SETTLED = {"n": 1, "settled": True, "finding": "MSFT weighs 16.0% [f_w1a2b3c4d5e6] of the book.", "facts": ["f_w1a2b3c4d5e6"]}
NOT_HELD = {"n": 2, "settled": False, "why": "too little price history", "boundary": "f_no1a2b3c4d5e"}
POLICY = {"n": 3, "settled": False, "why": "the desk does not forecast", "boundary": "f_policy_no_forecast"}


def test_a_turn_opens_with_the_scope_the_runtime_fixed():
    st = S.new_turn("sess", "msg", "how big is MSFT?", BRIEFING)
    assert st.version == 0 and st.scope == S.scope_of(BRIEFING, "how big is MSFT?")
    assert st.findings == [] and st.gaps == [] and S.completion_of(st) is None


def test_merge_task_types_a_gap_by_the_boundary_rows_reason_and_skips_refused_lines():
    st = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(st, TASK, _result(SETTLED, NOT_HELD, POLICY, {"n": 4, "settled": True, "finding": "x", "facts": []}, refused=(4,)), LEDGER)
    assert [f["text"] for f in st.findings] == [SETTLED["finding"]] and st.findings[0]["subjects"] == ["MSFT"]
    assert [(g["type"], g["boundary"]) for g in st.gaps] == [("data_missing", "f_no1a2b3c4d5e"), ("policy_boundary", "f_policy_no_forecast")]
    assert st.tasks[0]["task_id"] == "tsk_1"


@pytest.mark.asyncio
async def test_a_proposal_that_fails_the_check_is_a_trace_row_and_never_a_finding(monkeypatch):
    rows: list = []

    async def _record(db, session_id, **kw):
        rows.append(kw)
        return "step_1"

    class _Db:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def commit(self): pass

    monkeypatch.setattr(trace_service, "record_step", _record)
    st = S.new_turn("sess", "msg", "q", BRIEFING)
    v = await S.propose(_Db, st, "hypothesis", "MSFT weighs 23.4% of the book.", LEDGER)
    assert not v.ok and st.findings == []
    assert rows[0]["step_type"] == "state_proposal" and rows[0]["status"] == "rejected"
    assert rows[0]["args"]["channel"] == "hypothesis" and rows[0]["args"]["problems"][0]["reason"] == "unsourced_figure"
    assert S.view(st, LEDGER)["findings"] == [], "A3: not in the view either"
    ok = await S.propose(_Db, st, "hypothesis", "MSFT weighs 16.0% [f_w1a2b3c4d5e6] of the book.", LEDGER)
    assert ok.ok and st.findings[0]["refs"] == ["f_w1a2b3c4d5e6"] and st.findings[0]["source"] == "hypothesis"
    assert len(rows) == 1, "a passing proposal leaves no rejected row"


def test_a_scope_change_marks_what_fell_outside_stale_and_the_view_drops_it():
    st = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(st, TASK, _result(SETTLED), LEDGER)
    assert len(S.view(st, LEDGER)["findings"]) == 1
    stale = S.invalidate(st, {"subjects": ["AAPL"], "books": ["port_001"], "as_of": "2026-09-10"})
    assert [f["status"] for f in stale] == ["stale"]
    assert S.view(st, LEDGER)["findings"] == [], "A4: a stale finding is on the record and not in the view"


def test_a_new_turn_inherits_only_what_is_inside_its_scope():
    first = S.new_turn("sess", "m1", "q1", BRIEFING)
    S.merge_task(first, TASK, _result(SETTLED), LEDGER)
    same_scope = S.new_turn("sess", "m2", "q1", BRIEFING, previous=first, ledger=LEDGER)
    assert [f["status"] for f in same_scope.findings] == ["inherited"] and same_scope.gaps == []
    other = S.new_turn("sess", "m3", "what about AAPL?", {"subjects": {"tickers": ["AAPL"], "portfolios": [], "runs": []}},
                       previous=first)
    assert other.findings == []


def test_undelivered_rows_become_one_gap_per_call_and_conflicts_are_found_by_lookup():
    st = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(st, TASK, _result(SETTLED), LEDGER)
    gaps = S.mark_delivery_missing(st, LEDGER, delivered={"f_w1a2b3c4d5e6"})
    assert {(g["pull"], g["count"]) for g in gaps} == {("r_2", 1), ("r_3", 1)}
    assert S.mark_delivery_missing(st, LEDGER, delivered={"f_w1a2b3c4d5e6", "f_w2b3c4d5e6f7", "f_u3c4d5e6f7a8"}) == []
    st.findings.append({"text": "MSFT weighs 18.0% [f_w2b3c4d5e6f7] of the book.", "refs": ["f_w2b3c4d5e6f7"],
                        "subjects": ["MSFT"], "requirement_ids": [], "status": "accepted"})
    [conflict] = S.conflicts(st, LEDGER)
    assert conflict["type"] == "evidence_conflict" and conflict["refs"] == ["f_w1a2b3c4d5e6", "f_w2b3c4d5e6f7"]
    shown = S.view(st, LEDGER)
    assert next(g for g in shown["gaps"] if g["type"] == "evidence_conflict")["rows"][0].startswith("[f_w1a2b3c4d5e6]")


def test_requirement_status_and_completion_are_counts():
    st = S.new_turn("sess", "msg", "q", BRIEFING)
    st.requirements = [{"id": "R1", "anchor": "how big MSFT is"}, {"id": "R2", "anchor": "its beta"}, {"id": "R3", "anchor": "next year"}]
    task = dl.Task("tsk_1", "risk", ("port_001",), ("a",), requirements=(("R1", "how big MSFT is"),))
    S.merge_task(st, task, _result(SETTLED), LEDGER)
    assert [r["status"] for r in st.requirements] == ["covered", "unresolved", "unresolved"] and S.completion_of(st) == "partial"
    st.gaps.append({"type": "policy_boundary", "requirement_ids": ["R2", "R3"], "boundary": "f_policy_no_forecast"})
    S._recompute_requirements(st)
    assert S.completion_of(st) == "completed_with_boundaries"


@pytest.mark.asyncio
async def test_save_inserts_once_and_then_fences_on_the_version():
    added: list = []
    rowcount = {"n": 1}

    class _Db:
        def add(self, row): added.append(row)
        async def flush(self): pass
        async def execute(self, stmt): return SimpleNamespace(rowcount=rowcount["n"])

    st = S.new_turn("sess", "msg", "q", BRIEFING)
    await S.save(_Db(), st)
    assert st.version == 1 and added[0].version == 1 and added[0].session_id == "sess"
    await S.save(_Db(), st)
    assert st.version == 2
    rowcount["n"] = 0
    with pytest.raises(S.StaleState):
        await S.save(_Db(), st)
    assert st.version == 2, "a lost race leaves the caller's version where it was, to re-read"


def test_the_view_carries_rows_and_no_refused_text():
    st = S.new_turn("sess", "msg", "q", BRIEFING)
    S.merge_task(st, TASK, _result(SETTLED, NOT_HELD), LEDGER)
    v = S.view(st, LEDGER)
    assert v["findings"][0]["rows"][0].startswith("[f_w1a2b3c4d5e6] issuer exposures: weight, MSFT")
    assert v["gaps"][0]["boundary"].startswith("[f_no1a2b3c4d5e] absent:")
    assert v["completion"] is None and v["state_version"] == 0
