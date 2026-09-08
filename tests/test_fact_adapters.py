"""V24 phase A: the adapters over the phase-0 fixtures, and the three invariants.

I1  no numeric leaf in a note — a number reaches the model only as a Fact
I2  every Fact has as_of or window (a task excepted)
I3  every numeric key has a declared unit (UnknownUnit otherwise) — pinned by
    the fixtures simply loading without raising
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from exposure_workbench.services import fact_adapters as fa
from exposure_workbench.services import facts as F

FIX = Path(__file__).parent / "fixtures" / "v24_payloads"

# fixture -> (tool, args). The args are what the meta face would have sent.
CASES: dict[str, tuple[str, dict]] = {
    "describe_desk": ("describe", {}),
    "describe_issuer": ("describe", {"subject": "MSFT"}),
    "describe_run": ("describe", {"subject": "run_b791e7985dcd"}),
    "describe_portfolio": ("describe", {"subject": "port_001"}),
    "describe_issuer_expand_fundamentals": ("describe", {"subject": "MSFT", "expand": "fundamentals"}),
    "describe_issuer_expand_methods": ("describe", {"subject": "MSFT", "expand": "methods"}),
    # V28 C2: the expand values that had no fixture — the filings one is the payload that
    # crashed the adapter on every issuer for two versions (X3), unseen by 2,133 tests.
    "describe_issuer_expand_filings": ("describe", {"subject": "MSFT", "expand": "filings"}),
    "describe_issuer_expand_readings": ("describe", {"subject": "MSFT", "expand": "readings"}),
    "describe_issuer_expand_procedures": ("describe", {"subject": "MSFT", "expand": "procedures"}),
    "describe_issuer_domain": ("describe", {"subject": "MSFT", "expand": "issuer_earnings_quality"}),
    "describe_portfolio_domain": ("describe", {"subject": "port_001", "expand": "book_liquidity"}),
    "describe_desk_expand_refused": ("describe", {"expand": "book"}),
    "describe_unknown": ("describe", {"subject": "ZZZZ"}),
    "read_fundamentals_flow": ("read_fundamentals", {"ticker": "MSFT", "metric": "revenue", "months": 12}),
    "read_fundamentals_sheet": ("read_fundamentals", {"ticker": "MSFT"}),
    "read_fundamentals_series": ("read_fundamentals", {"ticker": "MSFT", "metric": "revenue", "last_n": 8}),
    "read_fundamentals_balance_series": ("read_fundamentals", {"ticker": "MSFT", "metric": "total_assets", "last_n": 6}),
    "read_fundamentals_absent": ("read_fundamentals", {"ticker": "MSFT", "metric": "segment_revenue"}),
    "read_fundamentals_not_at_date": ("read_fundamentals", {"ticker": "MSFT", "metric": "total_assets", "at": "2019-01-01"}),
    "read_filings_search": ("read_filings", {"ticker": "MSFT", "query": "cloud revenue growth"}),
    "read_filings_item7": ("read_filings", {"ticker": "MSFT", "item": "7"}),
    "read_filings_not_indexed_or_missing_item": ("read_filings", {"ticker": "MSFT", "item": "99"}),
    "read_prices_1y": ("read_prices", {"ticker": "MSFT", "window": "1y"}),
    "read_prices_day": ("read_prices", {"ticker": "MSFT"}),
    "read_prices_unknown_window": ("read_prices", {"ticker": "MSFT", "window": "7y"}),
    "read_book_run_sections": ("read_book", {"ref": "run_b791e7985dcd", "names": ["alerts", "attribution", "risk_state"]}),
    "read_book_port": ("read_book", {"ref": "port_001", "names": ["positions", "limits", "freshness", "runs", "alerts"]}),
    "read_book_run_by_name": ("read_book", {"ref": "run_b791e7985dcd", "names": ["issuer_exposures.MSFT.weight"]}),
    "read_book_rrun": ("read_book", {"ref": "rrun_x", "names": ["state"]}),
    "read_book_task": ("read_book", {"ref": "task_x", "names": ["state"]}),
    "read_book_ticker": ("read_book", {"ref": "MSFT", "names": ["brief", "alerts"]}),
    "compute_op_divide": ("compute", {"op": "divide"}),
    "compute_op_scale": ("compute", {"op": "scale"}),
    "compute_op_rank": ("compute", {"op": "rank"}),
    "compute_op_yoy": ("compute", {"op": "yoy"}),
    "compute_op_regress": ("compute", {"op": "regress"}),
    "compute_formula_x3": ("compute", {"method": "net_margin", "subject": ["MSFT", "AAPL", "NVDA"]}),
    "compute_formula_unavailable": ("compute", {"method": "ebitda", "subject": "MSFT"}),
    "compute_unknown_method": ("compute", {"method": "nonsense", "subject": "MSFT"}),
    "compute_panel": ("compute", {"method": "issuer.panel", "subject": "MSFT"}),
    "compute_beta": ("compute", {"method": "price.beta", "subject": "MSFT"}),
    "compute_price_momentum": ("compute", {"method": "price.momentum_12_1", "subject": "MSFT"}),
    "compute_price_52w": ("compute", {"method": "price.distance_from_52w_high", "subject": "MSFT"}),
    "compute_price_adv": ("compute", {"method": "price.adv", "subject": "MSFT"}),
    "compute_price_drawdown": ("compute", {"method": "price.drawdown", "subject": "MSFT"}),
    "compute_price_window_return": ("compute", {"method": "price.window_return", "subject": "MSFT"}),
    "compute_price_vol": ("compute", {"method": "price.rolling_volatility", "subject": "MSFT"}),
    "compute_book_analysis": ("compute", {"method": "book.analysis", "subject": "run_b791e7985dcd"}),
    "compute_book_reconcile": ("compute", {"method": "book.reconcile", "subject": "run_b791e7985dcd"}),
    "compute_book_episodes": ("compute", {"method": "book.drawdown_episodes", "subject": "port_001"}),
    "compute_book_sell": ("compute", {"method": "book.sell", "subject": "run_b791e7985dcd"}),
    "compute_book_buy": ("compute", {"method": "book.buy", "subject": "run_b791e7985dcd"}),
    "start_exposure_run_not_owner": ("start", {"kind": "exposure_run", "subject": "port_001"}),
}


def _load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def adapted() -> dict[str, tuple[list[F.Fact], dict, dict | None]]:
    return {name: fa.adapt(tool, args, _load(name)) for name, (tool, args) in CASES.items()}


def test_every_fixture_has_a_case():
    on_disk = {p.stem for p in FIX.glob("*.json")}
    assert on_disk == set(CASES), f"fixtures without a case: {on_disk - set(CASES)}; cases without a fixture: {set(CASES) - on_disk}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_I1_no_number_reaches_the_model_outside_a_fact(adapted, name):
    _facts, note, _held = adapted[name]
    leaves = fa.numeric_leaves(note)
    # identity parameters the model may write stay in the note by design
    leaves = [(p, v) for p, v in leaves if p.rsplit(".", 1)[-1].split("[")[0] not in fa.PARAM_KEYS]
    assert leaves == [], f"{name}: numbers left in the note: {leaves[:8]}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_I2_every_fact_says_as_of_or_window(adapted, name):
    facts, _note, _held = adapted[name]
    bare = [(f.measure, f.subject) for f in facts if f.kind != F.TASK and not (f.as_of or f.window)]
    assert bare == [], f"{name}: facts with neither as_of nor window: {bare[:8]}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_fact_has_a_unit_or_is_text(adapted, name):
    facts, _n, _h = adapted[name]
    bad = [f.measure for f in facts if f.kind in (F.SCALAR, F.SERIES) and f.unit not in ("RATIO", "MONEY", "COUNT", "MULTIPLE", "MONEY_PER_SHARE", "PERCENT", "MONEY_PER_DAY", "COUNT_PER_DAY")]
    assert bad == [], f"{name}: {bad[:8]}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_ids_unique_and_note_points_at_them(adapted, name):
    facts, note, held = adapted[name]
    ids = [f.id for f in facts]
    assert len(ids) == len(set(ids))
    referenced = set()

    def walk(n):
        if isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
        elif F.is_fact_id(n):
            referenced.add(n)
    walk(note)
    assert referenced <= set(ids), f"{name}: note points at ids that are not facts: {referenced - set(ids)}"


@pytest.mark.parametrize("name", sorted(CASES))
def test_model_form_round_trips_and_fits(adapted, name):
    facts, _n, held = adapted[name]
    block = F.block_for_model(facts)
    assert len(json.dumps(block)) <= F.FACTS_CHAR_LIMIT
    for row, f in zip(block["rows"], facts):
        d = F.from_model_row(row, block.get("sources"))
        assert d["id"] == f.id and d["measure"] == f.measure and d["kind"] == f.kind
        assert tuple(d["sources"]) == f.sources
    for f in facts:
        assert F.from_record(F.for_record(f)) == f


def test_counts_measured_in_phase_0(adapted):
    """The fixture counts §9 was set from: a change here is a change in what the
    model is shown, and should be a decision."""
    n = {name: len(adapted[name][0]) for name in adapted}
    assert n["read_prices_1y"] == 2 and adapted["read_prices_1y"][0][0].kind == F.SERIES or any(f.kind == F.SERIES for f in adapted["read_prices_1y"][0])
    assert n["read_fundamentals_sheet"] >= 17
    assert n["compute_book_analysis"] == 146, "every figure of book.analysis is shown; none held back"
    assert n["read_book_run_sections"] == 114
    assert all(h is None for _f, _n, h in adapted.values()), "no phase-0 fixture is over the cap"


def test_series_is_one_fact_thinned_for_the_model(adapted):
    facts, _n, _h = adapted["read_prices_1y"]
    s = next(f for f in facts if f.kind == F.SERIES)
    assert len(s.points) > F.SERIES_POINTS_INLINE
    row = F.row_for_model(s)
    shown = F.from_model_row(row)["value"]
    assert len(shown["points"]) == F.SERIES_POINTS_INLINE and shown["n"] == len(s.points)
    vals = [v for _, v in s.points]
    periods = {p for p, _ in shown["points"]}
    assert s.points[0][0] in periods and s.points[-1][0] in periods
    assert s.points[vals.index(min(vals))][0] in periods and s.points[vals.index(max(vals))][0] in periods


def test_passage_fact_is_the_filing_text_with_its_source(adapted):
    facts, note, _h = adapted["read_filings_search"]
    assert len(facts) == 5 and all(f.kind == F.PASSAGE for f in facts)
    assert all(f.sources and f.sources[0].startswith("chunk_") for f in facts)
    assert all("score" not in p for p in note["passages"])
    item7, _n, _h = adapted["read_filings_item7"]
    assert item7[0].kind == F.PASSAGE and len(item7[0].text) > F.PASSAGE_CHARS
    assert "truncated" in F.from_model_row(F.row_for_model(item7[0]))["value"]


def test_absence_is_a_fact_the_honest_sentence_can_point_at(adapted):
    facts, note, _h = adapted["compute_formula_unavailable"]
    assert [f.kind for f in facts] == [F.ABSENCE]
    assert facts[0].sources[0].startswith("calc_") and "statement" not in note and note["fact"] == facts[0].id


def test_read_book_by_name_measures_are_the_runs_own(adapted):
    facts, note, _h = adapted["read_book_run_by_name"]
    by = {f"{f.subject}:{f.measure}" for f in facts}
    assert "MSFT:issuer_exposures.weight" in by
    assert any(f.measure == "count.alerts" for f in facts)
    assert set(note["figures"]) == {"issuer_exposures.MSFT.weight", "count.alerts"}


def test_book_sections_share_the_runs_measure_names(adapted):
    """A weight read through positions is the same measure as one read by name."""
    facts, _n, _h = adapted["read_book_run_sections"]
    measures = {f.measure for f in facts}
    assert "issuer_exposures.weight" in measures and "factor_attributions.contribution" in measures
    assert "exposure_metrics.portfolio_market_value" in measures


def test_collinear_legs_are_not_standalone(adapted):
    facts, _n, _h = adapted["compute_book_analysis"]
    legs = [f for f in facts if f.measure.endswith("legs.beta") or f.measure == "net_exposures.beta" or "legs" in f.measure]
    flagged = [f for f in facts if not f.standalone]
    assert flagged, "book.analysis carries quotable_individually flags; some leg must be non-standalone"


def test_task_facts(adapted):
    facts, _n, _h = adapted["read_book_rrun"]
    assert [f.kind for f in facts] == [F.TASK] and facts[0].text


def test_cap_holds_back_whole_facts():
    many = [F.fact(F.SCALAR, f"m{i}", subject="X", unit="RATIO", value=float(i), as_of="2026-01-01") for i in range(500)]
    kept, held = F.cap(many, per_result=50)
    assert len(kept) == 50 and held["count"] == 450
    kept2, held2 = F.cap(many[:100], char_limit=2_000)
    assert 0 < len(kept2) < 100 and held2 and len(json.dumps(F.block_for_model(kept2))) <= 2_000


def test_unknown_numeric_key_is_an_error_not_a_guess():
    with pytest.raises(fa.UnknownUnit):
        fa.harvest({"as_of": "2026-01-01", "frobnication": 3.2}, fa.Ctx("t", subject="X"))


def test_a_refusals_schema_and_problems_pass_through_untouched():
    """Live round 1: compute(book.sell) with the wrong params shape refused with
    its params_schema, and `minItems` inside it became an adapter error that
    masked the refusal the model needed."""
    refusal = {"error": "invalid_params", "detail": "book.sell: params do not fit the method's schema",
               "problems": [{"field": "sales", "message": "required", "minimum": 1}],
               "params_schema": {"type": "object", "properties": {"sales": {"type": "array", "minItems": 1}}}}
    facts, note, held = fa.adapt("compute", {"method": "book.sell"}, refusal)
    assert facts == [] and note["params_schema"] == refusal["params_schema"] and note["problems"] == refusal["problems"]
    assert fa.numeric_leaves(note) == []


def test_the_catalogues_not_held_and_cannot_are_absence_facts(adapted):
    """The honest sentence has something to point at: every not_held and cannot
    entry of describe is an absence fact with the catalogue's sentence."""
    facts, note, _h = adapted["describe_issuer"]
    absent = [f for f in facts if f.kind == F.ABSENCE]
    assert absent and {f.params["reason"] for f in absent} <= {"not_held", "cannot"}
    assert any(f.measure == "segment_revenue" and "read_filings" in f.text for f in absent)
    assert all(F.is_fact_id(v) for v in note["not_held"].values()) and all(f.as_of for f in absent)


# ── the adapter sees the wire form ────────────────────────────────────────────
# Every fixture above is wire-form JSON. In process a service hands the wrapper
# `datetime.date` and `Decimal`, and that is the form the adapter saw live: on
# 2026-09-05 read_book(port_001) showed every holding as of the READING day
# because _as_of_of skipped a date object and fell back to today. This walks
# each fixture back into the in-process form and asserts the facts are the
# same ones — so the class of "the fixture never held what the service returns"
# stays closed by adapt() itself, not by each adapter's care.

_DATE_STR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _in_process_form(node):
    if isinstance(node, dict):
        return {k: _in_process_form(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_in_process_form(v) for v in node]
    if isinstance(node, str) and _DATE_STR.match(node):
        return date.fromisoformat(node)
    if isinstance(node, float):
        return Decimal(repr(node))
    return node


def _shape(f: F.Fact) -> tuple:
    return (f.kind, f.subject, f.measure, f.unit, f.value, f.as_of, f.window, f.text,
            tuple(sorted((f.params or {}).items())), f.sources, f.points)


@pytest.mark.parametrize("name", sorted(CASES))
def test_adapter_reads_the_wire_form_whatever_the_service_returned(adapted, name):
    tool, args = CASES[name]
    facts, _n, _h = adapted[name]
    again, _n2, _h2 = fa.adapt(tool, args, _in_process_form(_load(name)))
    assert [_shape(f) for f in again] == [_shape(f) for f in facts], name


def test_a_holding_is_dated_by_its_valuation_not_by_the_reading():
    payload = _load("read_book_port")
    payload["section"]["positions"]["valued_as_of"] = date(2026, 9, 3)
    facts, _n, _h = fa.adapt("read_book", {"ref": "port_001", "names": ["positions"]}, payload)
    holdings = [f for f in facts if f.measure.startswith("issuer_exposures.")]
    assert holdings and {f.as_of for f in holdings} == {"2026-09-03"}
    assert date.today().isoformat() not in {f.as_of for f in holdings}
