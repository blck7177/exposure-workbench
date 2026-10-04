"""The contracts under the new loops, offline: value semantics and display, the
comparable period, the ask protocol, the method index, the work view's projection,
the provider contract."""

from __future__ import annotations

import json
from datetime import date

import pytest

from exposure_workbench.agents import tasks as T, work_view as wvm
from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.analytics import value_semantics as vs
from exposure_workbench.services import method_index as mi, period_semantics as ps
from tests import provider_contract
from tests.agent_fakes import view_fixture


def test_display_says_what_kind_of_number_a_figure_is():
    assert dc.display(-0.19297793726071044, "RATIO") == "-19.3%"
    assert dc.display(-0.19297793726071044, "RATIO", vs.ABSOLUTE_CHANGE) == "-19.3 pp"
    assert dc.display(0.017938616431574683, "RATIO", vs.ABSOLUTE_CHANGE) == "+1.79 pp"
    assert dc.display(-0.21693140044091308, "RATIO", vs.RELATIVE_CHANGE) == "-21.7%"
    assert dc.display(1_250_000, "MONEY", vs.ABSOLUTE_CHANGE) == "+$1.25M"


def test_semantics_round_trip_through_params_and_default_to_a_level():
    s = vs.Semantics(kind=vs.ABSOLUTE_CHANGE, measure="cash_conversion", current="calc_a", baseline="calc_b",
                     current_period={"start": "2025-03-30", "end": "2026-03-28"})
    assert vs.of({vs.KEY: s.as_params()}) == s
    assert vs.of({}).kind == vs.LEVEL and vs.of(None).kind == vs.LEVEL
    with pytest.raises(ValueError):
        vs.Semantics(kind="delta")


def _calendar() -> ps.FiscalCalendar:
    y = lambda fy, s, e: ps.FiscalPeriod(fy, None, date.fromisoformat(s), date.fromisoformat(e))
    q = lambda fy, n, s, e: ps.FiscalPeriod(fy, n, date.fromisoformat(s), date.fromisoformat(e))
    return ps.FiscalCalendar(
        years=(y(2024, "2023-10-01", "2024-09-28"), y(2025, "2024-09-29", "2025-09-27")),
        quarters=(q(2025, 1, "2024-09-29", "2024-12-28"), q(2025, 2, "2024-12-29", "2025-03-29"),
                  q(2025, 3, "2025-03-30", "2025-06-28"), q(2026, 1, "2025-09-28", "2025-12-27"),
                  q(2026, 2, "2025-12-28", "2026-03-28")))


def test_the_comparable_period_is_the_same_fiscal_period_a_year_earlier():
    cal = _calendar()
    assert ps.prior_comparable(cal, date(2026, 3, 28), "previous_ttm").end == date(2025, 3, 29)
    assert ps.prior_comparable(cal, date(2025, 9, 27), "previous_fy").end == date(2024, 9, 28)
    assert ps.prior_comparable(cal, date(2026, 3, 28), "previous_quarter").end == date(2025, 12, 27)
    assert ps.prior_comparable(cal, date(2024, 12, 28), "previous_ttm") is None     # FY2024 Q1 is not filed here
    assert ps.prior_comparable(cal, date(2026, 3, 30), "previous_ttm").end == date(2025, 3, 29)   # within the snap
    assert ps.prior_comparable(cal, date(2026, 5, 1), "previous_ttm") is None
    with pytest.raises(ValueError):
        ps.prior_comparable(cal, date(2026, 3, 28), "previous_run")


def test_two_asks_of_one_specialist_over_one_scope_are_one_task():
    tasks = T.parse_tasks({"tasks": [
        {"analyst": "issuer", "scope": {"subjects": ["aapl", "MSFT"]}, "lines": ["cash conversion, latest TTM"]},
        {"analyst": "issuer", "scope": {"subjects": ["MSFT", "AAPL"]}, "lines": ["the change against the prior TTM"]},
        {"analyst": "risk", "scope": {"book": "port_001", "sector": "Technology"}, "lines": ["weights, both runs"]},
    ]})
    assert [t.analyst for t in tasks] == ["issuer", "risk"]
    assert tasks[0].scope["subjects"] == ["AAPL", "MSFT"]
    assert tasks[0].lines == ("cash conversion, latest TTM", "the change against the prior TTM")
    assert tasks[0].as_dict()["lines"][1].startswith("2. ")
    with pytest.raises(T.BadAsk):
        T.parse_tasks({"tasks": [{"analyst": "issuer", "scope": {}, "lines": ["x"]}]})
    with pytest.raises(T.BadAsk):
        T.parse_tasks({"tasks": [{"analyst": "quant", "scope": {"subjects": ["AAPL"]}, "lines": ["x"]}]})


def test_the_method_index_says_what_each_measure_compares_against():
    assert mi.compares_for("cash_conversion") == mi.ISSUER_COMPARES
    assert mi.compares_for("book.weight") == ("previous_run",)
    assert mi.compares_for("price.beta") == ()
    assert mi.family_of("operating_cash_flow") == mi.FILED_LINE
    assert mi.family_of("not_a_measure") is None
    text = mi.index_text("risk")
    assert "book.weight" in text and "cash_conversion" not in text
    assert "cash_conversion" in mi.index_text(None)
    assert mi.detail("cash_conversion")["expression"] == "operating cash flow ÷ net income"
    assert mi.detail("nope")["error"] == "unknown_method"


def test_the_work_view_hands_a_view_whole_once_and_then_as_an_index_line():
    wv = wvm.WorkView(session_id="sess", message_id="msg", question="q")
    view = view_fixture()
    wv.add_view(view, by="sub:issuer")
    first = wv.projection()
    assert first["analyses"] and first["analyses"][0]["view"] == view["view"]
    assert "_facts" not in first["analyses"][0]
    assert first["scope_decisions"][0]["status"] == "mismatch"
    wv.mark_seen()
    second = wv.projection()
    assert second["analyses"] == [] and second["analyses_seen"][0]["measures"] == ["cash_conversion", "book.weight"]
    tail = wv.tail_text()
    assert tail.startswith("<state ") and tail.endswith("</state>")
    assert json.loads(tail.split("\n", 1)[1].rsplit("\n", 1)[0])["question"] == "q"
    st = wv.start("tsk_1", "sub:issuer")
    st.status, st.stop_reason = "returned", "finished"
    assert wv.projection()["execution"][0] == {"task_id": "tsk_1", "actor": "sub:issuer", "status": "returned",
                                                "stop_reason": "finished"}


def test_the_provider_contract_refuses_an_unanswered_function_call():
    call = {"type": "function_call", "call_id": "c1", "name": "analyze", "arguments": "{}"}
    out = {"type": "function_call_output", "call_id": "c1", "output": "{}"}
    provider_contract.check([{"role": "user", "content": "q"}, call, out])
    with pytest.raises(AssertionError):
        provider_contract.check([{"role": "user", "content": "q"}, call])
    with pytest.raises(AssertionError):
        provider_contract.check([out])
