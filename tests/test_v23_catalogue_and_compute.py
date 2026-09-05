"""V23 — the catalogue, one compute, the skill registry, the budget's unit (offline).

WHY THIS FILE. The boss's division of labour (IMPLEMENTATION_PLAN_V23 §0):
get the catalogue right, then hand "what to look at, what to compare, what to
say" to agent intelligence plus skill. What that makes testable is not what
the agent decides but what it is handed: one catalogue in one format with
three kinds of absence; one compute whose methods are data with an authority
and a failure condition each; ten tools on the meta face, organised by data
domain; a description surface a third of what it was; a budget charged per
message. Each is pinned here as a property of the code, not a hope.
"""

from __future__ import annotations

import inspect
import json

import pytest

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import skill
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.services import catalogue_service as cat
from exposure_workbench.services import compute_service as cmp
from exposure_workbench.services import concept_mapping
from exposure_workbench.services import quantities as qn
from exposure_workbench.tools import definitions, faces
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


# ── the faces: data domains × verbs ─────────────────────────────────────────

def test_the_meta_face_is_ten_tools_by_domain_and_verb():
    assert faces.FACE_META_AGENT == [
        "describe", "read_fundamentals", "read_filings", "read_prices", "compute", "think",
        "read_book", "search_web", "start", "respond"]
    assert faces.FACE_RESEARCH == [
        "describe", "read_fundamentals", "read_filings", "read_prices", "compute", "think",
        "search_web", "submit_brief"]
    assert faces.resolve(build_meta_registry(), faces.FACE_META_AGENT) == faces.FACE_META_AGENT
    assert faces.resolve(build_research_registry(), faces.FACE_RESEARCH) == faces.FACE_RESEARCH


def test_no_tool_is_a_method_any_more():
    """Thirteen tools were methods with an entry point each. Every one is a
    registry method now, and no tool on either face names one."""
    retired = {"evaluate_formula", "get_fundamental_panel", "get_market_stats", "get_rolling_volatility",
               "get_beta", "get_momentum_12_1", "get_distance_from_52w_high", "get_adv", "get_drawdown",
               "get_drawdown_episodes", "explain_episode", "reconcile_move", "get_portfolio_analysis",
               "hypothetical_book"}
    assert not (retired & set(faces.FACE_META_AGENT))
    for name in ("issuer.panel", "price.volatility", "price.beta", "price.momentum_12_1",
                 "price.distance_from_52w_high", "price.adv", "price.drawdown", "price.window_return",
                 "book.drawdown_episodes", "book.explain_episode", "book.reconcile", "book.analysis",
                 "book.sell", "book.buy"):
        assert name in skill.METHODS, name


def test_the_description_surface_is_a_third_of_what_it_was():
    """31,003 characters of descriptions and schemas before V23 — ten times the
    system prompt — carried the 'when to use' that is the agent's judgement.
    The ceiling here is the plan's acceptance number, with respond's block
    grammar (the gate's contract) counted in."""
    reg = build_meta_registry()
    total = sum(len(reg.get(n).description) + len(json.dumps(reg.get(n).json_schema))
                for n in faces.FACE_META_AGENT)
    assert total < 12_000, total


def test_the_research_faces_compute_is_issuer_scoped():
    assert set(definitions.ISSUER_KINDS) == {"issuer", "price", "series"}
    assert "run" not in definitions.ISSUER_KINDS and "portfolio" not in definitions.ISSUER_KINDS


# ── the skill registry ──────────────────────────────────────────────────────

def test_every_method_states_an_authority_and_when_it_fails():
    for m in skill.METHODS.values():
        assert m.authority.strip() and m.fails_when.strip(), m.name
        assert m.params_schema.get("type") == "object", m.name


def test_every_formula_is_a_method_and_the_registry_adds_only_the_three_kinds():
    assert set(fm.FORMULAS) <= set(skill.METHODS)
    kinds = {m.subject_kind for m in skill.METHODS.values()}
    assert kinds <= set(skill.SUBJECT_KINDS)
    assert {m.executor for m in skill.METHODS.values()} <= set(skill.EXECUTORS)


def test_every_executor_the_registry_names_is_one_compute_dispatches():
    """The symmetry: a registry entry cannot name an executor compute does not
    have, and compute has no executor no entry uses."""
    used = {m.executor for m in skill.METHODS.values()}
    assert used == set(skill.EXECUTORS) == set(cmp.executors_dispatched())


def test_a_method_without_an_authority_cannot_be_constructed():
    with pytest.raises(ValueError):
        skill.Method(name="x", subject_kind="issuer", family="f", describes="d", procedure="p",
                     authority="   ", fails_when="never", executor="formula")
    with pytest.raises(ValueError):
        skill.Method(name="x", subject_kind="issuer", family="f", describes="d", procedure="p",
                     authority="a", fails_when="", executor="formula")
    with pytest.raises(ValueError):
        skill.Method(name="x", subject_kind="nowhere", family="f", describes="d", procedure="p",
                     authority="a", fails_when="n", executor="formula")


def test_no_method_reading_or_procedure_carries_a_threshold():
    """2026-08-24's rule, extended: a number that reads as a threshold must not
    appear in a method's procedure or a reading's text."""
    import re
    bands = re.compile(r"\b(above|below|over|under|at least|at most|more than|less than)\s+\d")
    for m in skill.METHODS.values():
        assert not bands.search(m.procedure), (m.name, m.procedure)
    for r in skill.READINGS.values():
        assert not bands.search(r.reads), (r.method, r.reads)


def test_every_reading_is_about_a_method_and_every_procedure_about_a_subject_kind():
    for r in skill.READINGS.values():
        assert r.method in skill.METHODS
    for p in skill.PROCEDURES.values():
        assert p.subject_kind in skill.SUBJECT_KINDS + ("desk",)
        assert p.gather and p.close and p.absent.strip() and p.authority.strip(), p.name


def test_the_battery_thirteen_angles_have_a_procedure_each():
    assert len(skill.PROCEDURES) >= 13
    assert {"cut_one_name", "bear_case_from_filings", "rates_scenario", "capital_allocation",
            "revenue_concentration", "news_to_position", "trigger_levels", "thesis_check",
            "peer_comparison"} <= set(skill.PROCEDURES)


def test_an_unknown_method_is_refused_with_near_names():
    assert skill.nearest("net_margn") and "net_margin" in skill.nearest("net_margn")


# ── compute ─────────────────────────────────────────────────────────────────

async def test_compute_takes_exactly_one_of_op_or_method():
    assert (await cmp.compute(None))["error"] == "op_or_method"
    assert (await cmp.compute(None, op="add", method="roe"))["error"] == "op_or_method"


async def test_compute_refuses_an_unknown_method_and_points_at_the_nearest():
    out = await cmp.compute(None, method="return_on_equity", subject="MSFT")
    assert out["error"] == "unknown_method" and "roe" in out["nearest"]["return_on_equity"] or out["known"]


async def test_compute_validates_params_against_the_methods_own_schema():
    out = await cmp.compute(None, method="price.volatility", subject="MSFT", params={"window_days": 7})
    assert out["error"] == "invalid_params" and out["problems"]


async def test_compute_requires_a_subject_for_a_method():
    assert (await cmp.compute(None, method="roe"))["error"] == "subject_required"


async def test_the_ops_are_the_calculators_and_the_series_modules_own():
    assert set(skill.SCALAR_OPS) == {"add", "subtract", "multiply", "divide"}
    from exposure_workbench.services import series_service as ss
    assert set(cmp.SERIES_OPS) == set(ss.OPS)
    assert (await cmp.compute(None, op="add", operands=["a"]))["error"] == "operands"
    assert (await cmp.compute(None, op="rank", operands=["a"]))["error"] == "operands"
    assert (await cmp.compute(None, op="yoy", operands=["a", "b"]))["error"] == "operands"


async def test_a_list_of_subjects_fans_out_to_one_row_each(monkeypatch):
    calls = []

    async def fake(db, spec, subject, params, invoked_by):
        calls.append(subject)
        return {"calc_id": f"calc_{subject}", "value": 1.0}
    monkeypatch.setattr(cmp, "_run_method", fake)
    out = await cmp.compute(None, method="net_margin", subject=["MSFT", "AAPL", "NVDA"])
    assert calls == ["MSFT", "AAPL", "NVDA"]
    assert out["count"] == 3 and [r["subject"] for r in out["results"]] == calls


# ── the catalogue ───────────────────────────────────────────────────────────

def test_the_subject_kind_is_read_off_the_id():
    assert cat.kind_of(None) == "desk" and cat.kind_of("") == "desk"
    assert cat.kind_of("run_x") == "run" and cat.kind_of("calc_x") == "scenario"
    assert cat.kind_of("port_1") == "portfolio" and cat.kind_of("MSFT") == "issuer"


def test_not_held_names_only_figure_kinds_the_concept_map_does_not_carry():
    """The catalogue may not claim a gap the ingest has closed: no mapped
    concept carries a dimension, and each not_held kind names a dimensional
    figure."""
    src = inspect.getsource(concept_mapping)
    assert "dimension" not in src.lower(), "the map has grown a dimensional axis: revisit NOT_HELD"
    for kind, where in cat.NOT_HELD.items():
        assert kind not in concept_mapping.SUPPORTED_METRICS, kind
        assert "read_filings" in where, kind


def test_cannot_is_about_methods_the_registry_lacks():
    """per-name factor sensitivity: no method yields a per-holding beta over
    the book; the sentence points at the method that gives it per name."""
    yields = " ".join(y for m in skill.METHODS.values() for y in m.yields)
    assert "per_name" not in yields
    assert "price.beta" in cat.CANNOT["per_name_factor_sensitivity"]


def test_the_catalogue_carries_three_kinds_of_absence_in_one_format():
    src = inspect.getsource(cat)
    for key in ('"not_held"', '"cannot"', "methods_not_computable"):
        assert key in src, key
    assert cat.DEFAULT_CEILING == 8_000


def test_describe_lists_methods_and_procedures_by_the_subjects_kind():
    assert cat._methods("run", False) == {"run": [m.name for m in skill.methods_for("run")]}
    assert [p["name"] for p in cat._procedures("issuer", False)] == \
        [p.name for p in skill.procedures_for("issuer")]
    full = cat._methods("price", True)["price"]
    assert all({"name", "authority", "fails_when", "params", "yields"} <= set(m) for m in full)


def test_the_factoring_is_the_v15_compression():
    names = [f"limit_checks.{c}.{col}" for c in ("a", "b", "c", "d") for col in ("current_value", "warning_level")]
    out = cat._factored(names)
    assert out["patterns"][0]["labels"] == ["a", "b", "c", "d"]
    assert set(out["patterns"][0]["patterns"]) == {"limit_checks.<label>.current_value",
                                                   "limit_checks.<label>.warning_level"}


# ── the budget's unit is the message ────────────────────────────────────────

def test_the_turn_budget_is_charged_per_message():
    src = inspect.getsource(sess.reserve)
    assert "charged_message_id" in src and "same_message" in src
    from exposure_workbench.db.models import AgentSession
    assert hasattr(AgentSession, "charged_message_id")
    from exposure_workbench.tools import registry
    assert "message_id=message_id" in inspect.getsource(registry.invoke)


# ── read_book: one spelling for the desk's own work ─────────────────────────

def test_read_book_is_the_one_read_of_the_desks_own_work():
    src = inspect.getsource(definitions._read_book)
    for prefix in ('"task_"', '"port_"', '"run_"', '"calc_"'):
        assert prefix in src
    assert set(definitions._PORTFOLIO_SECTIONS) == {"positions", "limits", "alerts", "freshness", "runs"}
    assert set(definitions._RUN_SECTIONS) == {"alerts", "attribution", "risk_state"}


def test_read_fundamentals_decides_instant_or_flow_from_the_facts_not_a_list():
    src = inspect.getsource(definitions._metric_is_instant)
    assert "period_start" in src and "FinancialFact" in src


# ── what the first live turns taught (2026-09-05, deployed stack) ──────────

def test_the_desk_is_the_desk_under_the_spellings_a_model_writes():
    """Live turn 4 wrote subject="null" (the schema said null) and got
    company_not_found, then guessed "port_"."""
    for spelled in (None, "", "null", "None", "desk", "portfolios"):
        assert cat.kind_of(spelled) == "desk", spelled


def test_a_held_issuers_catalogue_puts_the_books_market_value_and_its_tiers_on_the_table():
    """Live turn 2 could not price a trim: describe(MSFT) had put three names on
    the table and the book's market value was not one of them."""
    src = inspect.getsource(cat._in_book)
    assert '"exposure_metrics.portfolio_market_value"' in src
    assert '"warning_level", "breach_level"' in src
    assert "methods_on_this_run" in src and 'skill.methods_for("run")' in src


def test_the_fundamentals_layer_lists_the_metric_names_by_default():
    """Live turn 3 guessed `capital_expenditures`; the desk's name is `capex`."""
    src = inspect.getsource(cat._fundamentals)
    assert '"names": sorted(have)' in src


def test_a_metric_refusal_lists_what_is_held_and_names_its_argument():
    src = inspect.getsource(definitions._read_fundamentals)
    assert '"available": have' in src and '"held_on": {"metric": metric}' in src


def test_a_refusal_about_one_argument_holds_only_calls_that_repeat_it():
    """The V21 §7 residual: live turn 3's first refusal (a wrong metric name)
    held seven reads of OTHER metrics, twice."""
    from exposure_workbench.agents import batch
    about_capex = {"error": "metric_not_filed", "held_on": {"metric": "capital_expenditures"}}
    assert batch.holds(about_capex, {"ticker": "AMZN", "metric": "capital_expenditures"})
    assert not batch.holds(about_capex, {"ticker": "AMZN", "metric": "buybacks"})
    assert batch.holds({"error": "unknown_run"}, {"anything": 1}), "no argument named: held by tool, as V21"


async def test_a_batch_holds_by_argument_when_the_refusal_names_one():
    from exposure_workbench.agents import batch

    class _Face:
        def __init__(self):
            self.calls = []

        async def call(self, name, args):
            self.calls.append((name, args))
            if args.get("metric") == "capital_expenditures":
                return {"error": "metric_not_filed", "held_on": {"metric": "capital_expenditures"}}
            return {"calc_id": "calc_1", "table": {"quantities": {}}}

    def _tc(i, **args):
        return {"id": f"c{i}", "function": {"name": "read_fundamentals", "arguments": json.dumps(args)}}
    face = _Face()
    out = await batch.dispatch(face, [_tc(1, ticker="AMZN", metric="capital_expenditures"),
                                      _tc(2, ticker="AMZN", metric="buybacks"),
                                      _tc(3, ticker="MSFT", metric="capital_expenditures")],
                               free=("think", "respond"))
    assert [a["metric"] for _, a in face.calls] == ["capital_expenditures", "buybacks"]
    assert out[2][2]["error"] == batch.NOT_ATTEMPTED


async def test_scale_is_an_op_with_a_factor_not_an_operand():
    """Live turn 2 wrote "book_market_value*0.15" as an operand."""
    assert "scale" in cmp.OPS
    out = await cmp.compute(None, op="scale", operands=["a", "b"], params={"factor": 0.15})
    assert out["error"] == "operands"
    out = await cmp.compute(None, op="scale", operands=["a"])
    assert out["error"] == "operands"


async def test_a_bare_run_name_as_an_operand_is_told_its_row():
    from exposure_workbench.services import typed_calculator as tc
    out = await tc._resolve(None, "issuer_exposures.MSFT.market_value")
    assert out["error"] == "unknown_operand" and "run_<id>:issuer_exposures.MSFT.market_value" in out["detail"]


# ── the second live round (2026-09-05) ──────────────────────────────────────

def test_a_scenario_row_publishes_the_trades_money():
    """Live turn 2 sized a trim with book.sell and could not slot the proceeds."""
    from exposure_workbench.services.typed_calculator import SCENARIO_OP
    row = type("Row", (), {"id": "calc_s", "operation": SCENARIO_OP,
                           "params": {"run_id": "run_x", "as_of": "2026-09-03", "sales": [{"ticker": "MSFT", "fraction": 0.08}]},
                           "result": {"issuer_exposures": [], "sector_exposures": [], "exposure_metrics": {},
                                      "limit_checks": [], "alerts": [], "proceeds": 135_000.0,
                                      "sold": [{"ticker": "MSFT", "fraction": 0.08, "market_value_sold": 135_000.0, "exited": False}]}})()
    held = {q.label: q for q in qn._from_scenario(row, "calc_s").quantities}
    assert held["trade.proceeds"].value == 135_000.0 and held["trade.proceeds"].unit_class == qn.MONEY
    assert held["trade.sold.MSFT.market_value"].unit_class == qn.MONEY
    assert held["trade.sold.MSFT.fraction"].value == 0.08


async def test_an_unknown_name_on_a_row_is_told_the_nearest_names(monkeypatch):
    """Live turn 2 wrote `limit_checks.issuer_concentration:MSFT.limit_value`;
    the column is warning_level, and the refusal said only 'describe lists them'."""
    from exposure_workbench.services import typed_calculator as tc

    async def quantities(_db, rid):
        return qn.Resolved((qn.Quantity(0.15, qn.RATIO, "limit_checks.issuer_concentration:MSFT.warning_level", rid),
                            qn.Quantity(0.16, qn.RATIO, "limit_checks.issuer_concentration:MSFT.current_value", rid)),
                           frozenset(), "run")
    monkeypatch.setattr(tc, "_named_quantities", quantities)
    out = await tc._resolve(None, "run_x:limit_checks.issuer_concentration:MSFT.limit_value")
    assert out["error"] == "unknown_name" and "warning_level" in out["detail"]


def test_a_series_point_is_an_operand_with_its_own_period():
    """Live turn 3 wrote `calc_…:capex@2025-12-31` and was refused undated: a
    point is the most dated thing on the desk."""
    from exposure_workbench.services import typed_calculator as tc
    src = inspect.getsource(tc._resolve_named)
    assert 'resolved.kind == "series" and "@" in name' in src
    assert "_resolve_point" in src
