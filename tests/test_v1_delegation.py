"""V1 step 4 (docs/IMPLEMENTATION_PLAN_V1.md §2.4): what crosses between the lead
and an analyst — `ask` down, a Return up, `open` back — and the check at the
boundary. No loop runs here: the protocol is read and tested on its own.
"""

from __future__ import annotations

import re

import pytest

from exposure_workbench.agents import delegation as dl, meta_agent
from exposure_workbench.analytics import registry as R
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.tools import primitives as P
from exposure_workbench.utils.ids import new_id

WEIGHT = {"id": "f_w1a2b3c4d5e6", "kind": "scalar", "measure": "issuer_exposures.weight", "subject": "MSFT", "unit": "RATIO",
          "value": 0.16, "as_of": "2026-09-10", "window": None, "params": {"pull": "r_1", "of": "run_x"},
          "standalone": True, "sources": ["run_x"], "group": "composition", "means": {}}
REFUSED = {"id": "f_no1a2b3c4d5e", "kind": "absence", "measure": "price.beta", "subject": "MSFT", "unit": None, "value": None,
           "text": "metric: fewer than 60 aligned observations", "as_of": "n/a", "window": None,
           "params": {"pull": "r_2", "error": "insufficient_history"}, "standalone": False, "sources": [],
           "group": "boundary", "means": {"reason": "not_held"}}
LEDGER = Ledger.of([WEIGHT, REFUSED])
TASK = dl.Task("tsk_1", "risk", ("port_001",), ("how big MSFT is in the book", "MSFT's beta to the market",
                                                   "where MSFT's weight will be next year"))


# ── down: ask ────────────────────────────────────────────────────────────────

def test_the_lead_asks_one_of_three_analysts_in_financial_language():
    task = dl.ASK_TOOL["function"]["parameters"]["properties"]["tasks"]["items"]
    assert task["properties"]["analyst"]["enum"] == ["issuer", "market", "risk"]
    # S1: work requests, without a requirement mapping or low-level tool schema
    assert set(task["properties"]) == {"analyst", "subjects", "lines", "context", "follow_up_of"}
    # no field invites arithmetic in words, a measure's name or a window to be parsed
    assert not {"facts_to_derive", "constraints", "measures", "window"} & set(task["properties"])


def test_an_ask_names_a_real_analyst_and_does_not_ask_it_twice_about_the_same_names():
    ok = dl.parse_tasks({"tasks": [{"analyst": "issuer", "subjects": ["XOM"], "lines": ["how levered"]},
                                   {"analyst": "issuer", "subjects": ["CVX"], "lines": ["how levered"]}]}, new_id)
    assert [t.subjects for t in ok] == [("XOM",), ("CVX",)]          # several issuers in depth: one task each
    with pytest.raises(dl.BadDelegation, match="issuer, market, risk"):
        dl.parse_tasks({"tasks": [{"analyst": "credit", "subjects": ["XOM"], "lines": ["x"]}]}, new_id)
    with pytest.raises(dl.BadDelegation, match="asked twice"):
        dl.parse_tasks({"tasks": [{"analyst": "issuer", "subjects": ["XOM"], "lines": ["a"]},
                                  {"analyst": "issuer", "subjects": ["xom"], "lines": ["b"]}]}, new_id)
    with pytest.raises(dl.BadDelegation):
        dl.parse_tasks({"tasks": [{"analyst": "issuer", "subjects": ["XOM"], "lines": ["x"] * (dl.MAX_LINES + 1)}]}, new_id)


def test_what_the_record_calls_the_asked_party_is_the_analyst():
    assert TASK.domain == "risk" and TASK.as_dict()["lines"][0] == "1. how big MSFT is in the book"


# ── the brief has no third state, and the door says so ───────────────────────

SETTLED = {"n": 1, "settled": True, "finding": "MSFT weighs 16.0% [f_w1a2b3c4d5e6] of the book.", "facts": ["f_w1a2b3c4d5e6"]}
UNSETTLED = {"n": 2, "settled": False, "why": "too little price history", "boundary": "f_no1a2b3c4d5e"}
POLICY = {"n": 3, "settled": False, "why": "the desk does not forecast", "boundary": "f_policy_no_forecast"}


@pytest.mark.parametrize("entry", [
    {"n": 1, "settled": True, "finding": "MSFT weighs 16.0% [f_w1a2b3c4d5e6]."},                           # settled, no facts
    {"n": 1, "settled": True, "facts": ["f_w1a2b3c4d5e6"]},                                                # settled, no finding
    {**SETTLED, "why": "also could not"},                                                        # both
    {"n": 2, "settled": False, "why": "too little history"},                                     # no boundary
    {"n": 2, "settled": False, "boundary": "f_no1a2b3c4d5e"},                                             # no why
    {**UNSETTLED, "finding": "roughly 1.1×"},                                                    # both, the other way
    {"n": 1, "finding": "MSFT weighs 16.0% [f_w1a2b3c4d5e6].", "facts": ["f_w1a2b3c4d5e6"]},                         # does not say which
])
def test_an_entry_that_is_neither_state_never_reaches_the_check(entry):
    with pytest.raises(dl.BadDelegation):
        dl.parse_submission({"lines": [entry]})


def test_the_historical_schema_keeps_its_two_state_contract():
    one_of = dl.LEGACY_SUBMIT_TOOL["function"]["parameters"]["properties"]["lines"]["items"]["oneOf"]
    assert [sorted(x["required"]) for x in one_of] == [["facts", "finding", "n", "settled"],
                                                       ["boundary", "n", "settled", "why"]]
    assert "report" not in dl.SUBMIT_TOOL["function"]["parameters"]["properties"]     # the log is not written


def test_a_line_appears_once_and_a_caveat_names_its_line():
    with pytest.raises(dl.BadDelegation, match="twice"):
        dl.parse_submission({"lines": [SETTLED, SETTLED]})
    with pytest.raises(dl.BadDelegation, match="caveat"):
        dl.parse_submission({"lines": [SETTLED], "caveats": ["weights are as of the prior run"]})
    brief = dl.parse_submission({"lines": [SETTLED], "caveats": [{"line": 1, "text": "as of the latest run"}]})
    assert brief["caveats"] == [{"line": 1, "text": "as of the latest run"}]


# ── the check at the boundary ────────────────────────────────────────────────

def _check(*entries, caveats=()):
    return dl.handoff_check(TASK, dl.parse_submission({"lines": list(entries), "caveats": list(caveats)}), LEDGER)


def test_every_line_is_settled_or_explained_and_a_policy_is_a_boundary():
    v = _check(SETTLED, UNSETTLED, POLICY)
    assert v.ok and v.coverage == {"asked": 3, "settled": 1, "unsettled": 2, "refused": 0}


def test_a_line_left_out_a_boundary_that_is_not_one_and_a_figure_nothing_backs_are_each_named():
    v = _check(SETTLED)
    assert {p["reason"] for p in v.problems} == {"uncovered_line"} and len(v.problems) == 2
    v = _check(SETTLED, {**UNSETTLED, "boundary": "f_w1a2b3c4d5e6"}, POLICY)
    assert [p["reason"] for p in v.problems] == ["not_a_boundary"]
    v = _check({**SETTLED, "finding": "MSFT weighs 23.4% of the book.", "facts": ["f_w1a2b3c4d5e6", "f_never"]}, UNSETTLED, POLICY)
    assert {"unsourced_figure", "not_on_ledger"} <= {p["reason"] for p in v.problems}
    assert v.rejected[0]["n"] == 1 and not v.accepted
    v = _check(SETTLED, UNSETTLED, POLICY, caveats=[{"line": 9, "text": "x"}])
    assert [(p["reason"], p["rule"]) for p in v.problems] == [("caveat_without_a_line", 7)]     # the style guide's seventh


# ── up: the Return ───────────────────────────────────────────────────────────

def _result(**kw):
    return dl.AnalystResult(task=TASK, status="partial", lines=[SETTLED, UNSETTLED, POLICY], **kw)


def test_receipt_and_work_view_separate_execution_from_checked_content():
    from exposure_workbench.services import analysis_state as S
    result = _result(caveats=[{"line": 1, "text": "as of the latest run"}], made=["calc_after"])
    receipt = dl.for_lead([result], LEDGER)["returns"][0]
    assert receipt == {"task_id": "tsk_1", "analyst": "risk", "brief_status": "partial",
                       "accepted_findings": 1, "made": ["calc_after"]}
    state = S.new_turn("sess", "msg", "q", {})
    S.merge_task(state, TASK, result, LEDGER)
    view = S.view(state, LEDGER)
    assert view["findings"][0]["rows"] == [F.line(WEIGHT)]
    assert view["findings"][0]["caveats"] == ["as of the latest run"]
    assert view["gaps"][0]["boundary"] == F.line(REFUSED)


def test_a_refused_finding_is_not_copied_into_the_receipt():
    r = _result(refused=[{"n": 1, "finding": "invented prose", "problems": [{"reason": "mark_mismatch"}]}])
    receipt = dl.for_lead([r], LEDGER)["returns"][0]
    assert receipt["accepted_findings"] == 0 and "invented prose" not in str(receipt)


def test_the_log_is_the_calls_in_order_each_with_why():
    r = _result(log=[{"step": 1, "tool": "book_read", "asked": 'book="port_001", table="issuer_exposures"',
                      "why": "line 1 asks the weight", "got": "1 row"},
                     {"step": 2, "tool": "metric", "asked": 'name="price.beta"', "why": "line 2 asks the beta",
                      "got": "not_held: too little history"}])
    text = dl.log_text(r).splitlines()
    assert text[0].startswith("tsk_1 — the risk analyst, asked about port_001: 1. how big MSFT is in the book")
    assert text[1] == '1. book_read(book="port_001", table="issuer_exposures") — why: line 1 asks the weight → 1 row'
    assert text[-1] == "brief: partial"


# ── the lead's own text ──────────────────────────────────────────────────────

LEAD_TEXT = meta_agent._SYSTEM + meta_agent.BRIEFING_TAG + meta_agent.ROSTER_TAG + meta_agent.READINGS_TAG


def test_the_lead_speaks_none_of_the_desks_vocabulary():
    verbs = [v for face in P.FACES for v in P.FACE_TOOLS[face] if v not in ("list", "start", "metric", "calc", "scenario")]   # words of plain English too
    assert not [v for v in verbs if v in LEAD_TEXT]
    keys = [k for k in R.METHODS if "_" in k or "." in k]
    assert not [k for k in keys if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w.])", LEAD_TEXT)]
    assert "program" not in LEAD_TEXT and "delegate" not in LEAD_TEXT


def test_the_lead_is_told_its_three_moves_and_the_premise_rule_once():
    for word in ("`ask`", "`open`", "repair_answer"):
        assert word in meta_agent._SYSTEM
    assert meta_agent._SYSTEM.count("neither agreed with nor denied") == 1
    assert [t["function"]["name"] for t in (dl.ASK_TOOL, dl.OPEN_TOOL, meta_agent.REPAIR_TOOL)] == [
        "ask", "open", "repair_answer"]
