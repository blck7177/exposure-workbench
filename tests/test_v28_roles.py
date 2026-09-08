"""V28 — giving the work back to its role (offline).

Each test pins a boundary from IMPLEMENTATION_PLAN_V28: the tool executes the
intent it accepted (A1), an unwritable shape costs nothing (A2), comparability
is the identity's not the label's (B1), a run has one door (C1), a producer
declares its counts (C2), and the model is told validation's own rule (D1).
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

import pytest

from exposure_workbench.analytics.units import COUNT, MONEY, RATIO
from exposure_workbench.services import compute_service as cmp
from exposure_workbench.services import fact_adapters as fa
from exposure_workbench.services import gate, series_service
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.registries import build_meta_registry

SRC = Path(__file__).parent.parent / "src" / "exposure_workbench"


# ── A1: a series statistic runs over the resolved series, whatever id the model wrote ──

def _q(v, sid, quantity="revenue", unit=MONEY, issuer="MSFT", **kw):
    return tc.Typed(value=v, unit_class=unit, quantity=quantity, source_id=sid, issuers=(issuer,), **kw)


async def test_a_statistic_over_a_series_fact_id_is_computed_not_refused(monkeypatch):
    series = tc.TypedSeries(points=((date(2024, 12, 31), _q(10.0, "f_p1")), (date(2025, 12, 31), _q(14.0, "f_p2"))),
                            unit_class=MONEY, kind="flow", quantity="revenue", source_id="f_series")
    recorded = {}

    async def resolve(_db, ref):
        assert ref == "f_series"
        return series

    async def record(_db, _c, operation, params, result, inputs, flags, invoked_by):
        recorded.update(operation=operation, params=params, result=result, inputs=inputs)
        return "calc_new"
    monkeypatch.setattr(tc, "_resolve", resolve)
    monkeypatch.setattr(series_service.cs, "_record", record)
    out = await cmp._stat(None, "max", ["f_series"], None, "agent")
    assert out["calc_id"] == "calc_new" and out["value"] == 14.0 and out["unit_class"] == MONEY
    assert recorded["inputs"] == ["f_series"]
    out = await cmp._stat(None, "yoy", ["f_series"], None, "agent")
    assert out["calc_id"] == "calc_new" and out["points"][-1]["value"] == pytest.approx(0.4)


def test_compute_never_hands_a_series_op_an_id_to_reload():
    src = inspect.getsource(cmp)
    assert "series_service.series_stat(" not in src
    assert "series_service.stat_over(" in src


# ── A2: two shapes of one call are unwritable together, before any spend ──

def test_op_and_method_together_are_refused_by_the_schema_with_the_two_shapes_named():
    compute = build_meta_registry().tools["compute"].json_schema
    problems = validate_args(compute, {"op": "avg", "method": "price.beta", "subject": ["MSFT", "AAPL"]})
    assert problems and "two shapes" in problems[0]["problem"] and "two calls" in problems[0]["problem"]
    assert validate_args(compute, {"op": "avg", "method": None, "operands": ["f_a", "f_b"]}) == []
    assert validate_args(compute, {"method": "price.beta", "subject": "MSFT", "op": None}) == []
    filings = build_meta_registry().tools["read_filings"].json_schema
    assert "not both" in validate_args(filings, {"ticker": "MSFT", "query": "risk", "item": "1A"})[0]["problem"]
    assert validate_args(filings, {"ticker": "MSFT", "item": "1A", "query": None}) == []


# ── B1: what is comparable is the identity's, and the row is named by what varies ──

class _Desk:
    def __init__(self, monkeypatch, operands):
        async def resolve(_db, ref):
            return operands[ref]

        async def record(_db, _c, operation, params, result, inputs, flags, invoked_by):
            self.recorded = {"operation": operation, "params": params, "result": result}
            return "calc_rank"
        monkeypatch.setattr(tc, "_resolve", resolve)
        monkeypatch.setattr(tc.cs, "_record", record)

    async def rank(self, refs, **kw):
        return await tc.rank(None, refs, **kw)

    async def aggregate(self, op, refs, **kw):
        return await tc.aggregate(None, op, refs, **kw)


_YEAR = (date(2025, 1, 1), date(2025, 12, 31))


async def test_several_measures_of_one_holder_over_one_window_are_ordered_by_measure(monkeypatch):
    desk = _Desk(monkeypatch, {
        "capex": _q(30.0, "f_capex", "capex", interval=_YEAR),
        "buybacks": _q(45.0, "f_bb", "buybacks", interval=_YEAR),
        "dividends": _q(20.0, "f_div", "dividends_paid", interval=_YEAR),
    })
    out = await desk.rank(["capex", "buybacks", "dividends"], direction="highest")
    assert out["leader"] == "buybacks"
    assert [e["label"] for e in out["ordering"]] == ["buybacks", "capex", "dividends_paid"]
    assert out["type"]["axis"] == "quantity" and out["quantity"] == "MSFT.rank"
    out = await desk.aggregate("max", ["capex", "buybacks", "dividends"])
    assert out["value"] == 45.0


async def test_one_measure_across_holders_still_keeps_each_ones_own_window(monkeypatch):
    desk = _Desk(monkeypatch, {
        "m": _q(0.4, "f_m", "gross_margin", RATIO, "MSFT", interval=(date(2025, 7, 1), date(2026, 6, 30))),
        "a": _q(0.45, "f_a", "gross_margin", RATIO, "AAPL", interval=(date(2024, 9, 29), date(2025, 9, 27))),
    })
    out = await desk.rank(["m", "a"], direction="highest")
    assert out["leader"] == "AAPL" and out["type"]["axis"] == "issuer" and out["quantity"] == "gross_margin"


async def test_several_measures_over_different_windows_or_holders_are_refused(monkeypatch):
    desk = _Desk(monkeypatch, {
        "capex": _q(30.0, "f_capex", "capex", interval=_YEAR),
        "bb_prior": _q(45.0, "f_bb", "buybacks", interval=(date(2024, 1, 1), date(2024, 12, 31))),
        "aapl_bb": _q(50.0, "f_ab", "buybacks", issuer="AAPL", interval=_YEAR),
    })
    out = await desk.rank(["capex", "bb_prior"], direction="highest")
    assert out["error"] == "incomparable_quantities" and "window" in out["detail"]
    out = await desk.rank(["capex", "aapl_bb"], direction="highest")
    assert out["error"] == "incomparable_quantities"


# ── C1: a run has one door, and every reader uses it ──

_RUN_LOADER_ALLOWLIST = {
    "services/run_reads_service.py": "the loader itself",
    "services/exposure_run_service.py": "the writer: it creates and advances runs",
    "services/job_status_service.py": "the task door: it reports a run's status, which is the point",
    "services/evidence_resolver_service.py": "the drawer: renders evidence the gate already accepted from completed runs",
}


def _loads_run_by_id(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "where"):
            continue
        sel = node.func.value
        if not (isinstance(sel, ast.Call) and isinstance(sel.func, ast.Name) and sel.func.id == "select"
                and sel.args and isinstance(sel.args[0], ast.Name) and sel.args[0].id == "ExposureRun"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Compare) and isinstance(arg.left, ast.Attribute) and arg.left.attr == "id" \
                    and isinstance(arg.left.value, ast.Name) and arg.left.value.id == "ExposureRun":
                return True
    return False


def test_every_reader_of_a_run_goes_through_the_one_door():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC))
        if rel in _RUN_LOADER_ALLOWLIST:
            continue
        if _loads_run_by_id(ast.parse(path.read_text())):
            offenders.append(rel)
    assert offenders == [], f"load a run through run_reads_service.completed_run, not by id: {offenders}"


async def test_an_incomplete_run_is_task_state_not_figures(monkeypatch):
    from exposure_workbench.services import run_reads_service as rr

    class Run:
        id = "run_x"; status = "running"; task_id = "task_9"; portfolio_id = "port_001"

    async def loaded(_db, _rid):
        return Run()
    monkeypatch.setattr(rr, "_run_or_error", loaded)
    out = await rr.completed_run(None, "run_x")
    assert out["error"] == "run_not_completed" and out["status"] == "running"
    assert out["read"] == "read_book('task_9', names=['state'])"


# ── C2: a producer declares the unit of its counts; the adapter mints them ──

def test_a_container_that_declares_its_numeric_unit_is_minted_not_crashed():
    payload = {"subject": "MSFT", "kind": "issuer", "catalogue_as_of": "2026-09-08",
               "filings": {"items_detail": {"numeric_unit": "count", "Item 1A": 3, "Item 7": 2}}}
    facts, note = fa.describe({"subject": "MSFT", "expand": "filings"}, payload)
    minted = {f.measure.rsplit(".", 1)[-1]: f for f in facts}
    assert minted["Item 1A"].unit == COUNT.upper() and minted["Item 1A"].value == 3.0
    assert minted["Item 1A"].measure == "filings.items_detail.Item 1A"
    assert note["filings"]["items_detail"]["Item 7"] == minted["Item 7"].id
    with pytest.raises(fa.UnknownUnit):
        fa.describe({"subject": "MSFT"}, {"subject": "MSFT", "kind": "issuer", "catalogue_as_of": "2026-09-08",
                                          "filings": {"items_detail": {"Item 1A": 3}}})


# ── D1: the model is told validation's own sentence ──

def test_the_prose_rule_is_one_sentence_given_verbatim_to_the_model():
    from exposure_workbench.agents import meta_agent
    from exposure_workbench.tools import mcp_server
    assert gate.PROSE_RULE in meta_agent._SYSTEM
    assert gate.PROSE_RULE in mcp_server.INSTRUCTIONS
    assert gate.PROSE_RULE in build_meta_registry().tools["respond"].description
    assert gate._FIX.startswith(gate.PROSE_RULE)
    assert "never write a number" not in meta_agent._SYSTEM
