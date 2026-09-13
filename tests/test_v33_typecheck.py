"""V33 Phase 0/1 — the program language types itself before it runs (offline).

Read off the 20-question round (docs/spikes/v33/TRACE_V33.md): every program
the model wrote wrong was wrong in a way the dispatcher knew and the model
learned one node at a time. `typecheck` reports all of it at once, each with
the fix; SIGNATURES is the one table typecheck and signature_text read.
"""
from __future__ import annotations

import json
import re

import pytest

from exposure_workbench.analytics import skill
from exposure_workbench.services import program_service as ps


# ── the table and the parser agree ────────────────────────────────────────────

def test_every_primitive_has_a_signature_naming_its_arguments():
    assert set(ps.SIGNATURES) == set(ps.PRIMITIVES)
    for fn, (req, opt) in ps.PRIMITIVES.items():
        assert set(ps.SIGNATURES[fn].args) == set(req + opt), fn


def test_signature_text_names_every_primitive_method_and_boundary():
    text = ps.signature_text()
    for fn in ps.PRIMITIVES:
        assert f"  {fn}(" in text, fn
    for m in skill.METHODS.values():
        assert m.name in text, m.name
    for b in ps.BOUNDARIES:
        assert b in text
    assert "filter(" in text and "latest(" in text


# ── the shapes the round refused, each reported with its fix ──────────────────

def _problems(prog):
    return ps.typecheck(prog)


def test_q08_a_vector_of_series_names_latest_as_the_fix():
    prog = {"let": [
        {"name": "msft", "expression": {"fn": "method", "name": "capex_intensity", "subject": "MSFT", "params": {"last_n": 3}}},
        {"name": "amzn", "expression": {"fn": "method", "name": "capex_intensity", "subject": "AMZN", "params": {"last_n": 3}}},
        {"name": "capex_rank", "expression": {"fn": "rank", "of": {"fn": "vector", "entries": {"AMZN": "$amzn", "MSFT": "$msft"}}, "direction": "highest"}},
    ]}
    probs = _problems(prog)
    assert len(probs) == 1, probs                       # the rank depending on it is NOT reported again
    p = probs[0]
    assert p["reason"] == "type_mismatch" and p["got"] == ps.SERIES and "latest" in p["fix"]
    assert p["at"].startswith("_capex_rank_")            # the hoisted vector node


def test_q11_a_constant_operand_and_a_filter_are_well_typed():
    prog = {"let": [
        ["w", {"fn": "column", "run": {"fn": "run", "portfolio": "port_001"}, "table": "issuer_exposures", "col": "weight"}],
        ["over", {"fn": "sub", "a": "$w", "b": 0.08}],
        ["ranked", {"fn": "rank", "of": "$over", "direction": "highest"}],
        ["above", {"fn": "filter", "of": "$w", "op": ">", "level": 0.08}],
    ]}
    assert _problems(prog) == []


def test_q13_a_vector_of_constants_alone_is_refused_toward_filter():
    prog = {"let": [
        ["w", {"fn": "column", "run": {"fn": "run", "portfolio": "port_001"}, "table": "issuer_exposures", "col": "weight"}],
        ["caps", {"fn": "vector", "entries": {"AAPL": 0.08, "MSFT": 0.08}}],
        ["over", {"fn": "sub", "a": "$w", "b": "$caps"}],
    ]}
    probs = _problems(prog)
    assert [p["at"] for p in probs] == ["caps"]
    assert "filter" in probs[0]["fix"]


def test_q07_at_prev_is_refused_as_a_date_before_anything_runs():
    prog = {"let": [["ocf", {"fn": "method", "name": "ebit", "subject": ["AAPL", "MSFT"], "params": {"months": 12, "at": "prev"}}]]}
    probs = _problems(prog)
    assert len(probs) == 1 and probs[0]["reason"] == "invalid_date" and "YYYY-MM-DD" in probs[0]["fix"]


def test_q07_fundamentals_over_a_list_of_tickers_is_routed_to_method():
    prog = {"let": [["ocf", {"fn": "fundamentals", "ticker": ["AAPL", "MSFT"], "metric": "operating_cash_flow", "months": 12}]]}
    probs = _problems(prog)
    assert len(probs) == 1 and probs[0]["arg"] == "ticker" and "method over [tickers]" in probs[0]["fix"]


def test_a_panel_over_a_list_without_a_key_says_which():
    prog = {"let": [["p", {"fn": "method", "name": "issuer.panel", "subject": ["AAPL", "MSFT"]}]]}
    probs = _problems(prog)
    assert probs and probs[0]["reason"] == "several_figures" and "key=" in probs[0]["fix"]


def test_a_search_web_primitive_is_named_as_a_tool():
    prog = {"let": [["news", {"fn": "search_web", "ticker": "AAPL", "query": "x"}]]}
    probs = _problems(prog)
    assert probs[0]["reason"] == "unknown_primitive" and "tool" in probs[0]["fix"]


def test_sum_of_one_figure_and_yoy_of_a_scalar_each_name_the_fix():
    prog = {"let": [
        ["ebit", {"fn": "method", "name": "ebit", "subject": "MSFT"}],
        ["s", {"fn": "sum", "of": "$ebit"}],
        ["g", {"fn": "yoy", "of": "$ebit"}],
    ]}
    probs = {p["at"]: p for p in _problems(prog)}
    assert "vector" in probs["s"]["fix"] and "last_n" in probs["g"]["fix"]


def test_an_unknown_method_carries_its_nearest_names():
    prog = {"let": [["m", {"fn": "method", "name": "gross_margn", "subject": "MSFT"}]]}
    probs = _problems(prog)
    assert probs[0]["reason"] == "unknown_method" and "gross_margin" in probs[0]["nearest"]


def test_all_problems_come_at_once_and_blocked_nodes_are_not_repeated():
    prog = {"let": [
        ["a", {"fn": "method", "name": "ebit", "subject": "MSFT", "params": {"last_n": 4}}],
        ["v", {"fn": "vector", "entries": {"MSFT": "$a"}}],          # series into vector
        ["r", {"fn": "rank", "of": "$v"}],                            # blocked by v
        ["s", {"fn": "sum", "of": "$a"}],                             # fine: sum over a series
        ["z", {"fn": "yoy", "of": "$s"}],                             # scalar into yoy
    ]}
    probs = _problems(prog)
    assert [p["at"] for p in probs] == ["v", "z"]


def test_a_malformed_program_is_one_problem():
    probs = _problems({"let": []})
    assert len(probs) == 1 and probs[0]["reason"] == "malformed_program"


# ── every program the skill ships is well typed ───────────────────────────────

_FILLS = {"<T>": "MSFT", "<T1>": "MSFT", "<T2>": "AAPL", "<port>": "port_001", "<run>": "run_0000000000ab", "<N>": "KO"}


@pytest.mark.parametrize("name,title,prog", [(p.name, t, pr) for p in skill.PROCEDURES.values() for t, pr in p.programs])
def test_every_skill_program_typechecks_clean(name, title, prog):
    for k, v in _FILLS.items():
        prog = prog.replace(k, v)
    assert ps.typecheck(json.loads(prog)) == [], (name, title)


# ── the identity a node's facts carry (V33 Phase 1) ──────────────────────────

def test_a_nodes_declared_dates_reach_its_facts_and_make_a_window():
    n = ps.Node("explain", ps.TABLE, None)
    n.declared = {"params": {"peak": "2026-01-07", "trough": "2026-03-27"}}
    n.entries = [("portfolio.window_return", "calc_x:portfolio.window_return", -0.1196, "RATIO")]
    n.ref = "calc_x"
    facts = ps._facts_of(n)
    assert facts[0].params["peak"] == "2026-01-07" and facts[0].window == {"start": "2026-01-07", "end": "2026-03-27"}
    assert facts[0].as_of == "2026-03-27"


def test_a_scenario_row_names_a_labelled_measure_the_way_a_run_does():
    n = ps.Node("after", ps.TABLE, None)
    n.ref = "calc_scn"
    n.entries = [("sector_exposures.Technology.weight", "calc_scn:sector_exposures.Technology.weight", 0.3396, "RATIO"),
                 ("limit_checks.issuer_concentration:MSFT.current_value", "calc_scn:limit_checks.issuer_concentration:MSFT.current_value", 0.16, "RATIO"),
                 ("exposure_metrics.gross_exposure", "calc_scn:exposure_metrics.gross_exposure", 10.5e6, "MONEY"),
                 ("portfolio.reconcile.factor_share", "calc_scn:portfolio.reconcile.factor_share", -1.25, "RATIO")]
    by = {f.params["label"]: f for f in ps._facts_of(n)}
    assert (by["sector_exposures.Technology.weight"].measure, by["sector_exposures.Technology.weight"].subject) == ("sector_exposures.weight", "Technology")
    assert (by["limit_checks.issuer_concentration:MSFT.current_value"].measure, by["limit_checks.issuer_concentration:MSFT.current_value"].subject) == ("limit_checks.current_value", "issuer_concentration:MSFT")
    assert by["exposure_metrics.gross_exposure"].measure == "exposure_metrics.gross_exposure"
    assert by["portfolio.reconcile.factor_share"].measure == "portfolio.reconcile.factor_share"     # not a labelled table


def test_a_literal_node_is_shown_as_a_literal():
    n = ps.Node("peak", ps.TABLE, None, deps=["episodes"])
    n.payload = {"literal": "2026-01-07", "of": "calc_e", "key": "episodes[0].peak_date"}
    assert ps._note_of(n) == {"kind": "literal", "value": "2026-01-07", "deps": ["episodes"]}
