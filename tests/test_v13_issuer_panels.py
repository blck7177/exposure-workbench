"""V13-S6 — the containment view and the margins panel read what already
happened (offline).

Two endpoints, and the same two ways their claim could quietly stop being true
that test_v13_read_endpoints.py guards for the S5 panels. FIRST: a panel that
recomputes is a second opinion — the containment view must ask the engine the
formula path asks, over the balance sheet the formula path reads, and the
margins panel must serve the points the recipe's manifest rows already hold, or
the page disagrees with the answer it sits beside. SECOND: a read that mints a
ledger row turns the calculation count into a page-view count.

What the offline half can see: the handlers, called directly with the services
held still, and the relationship each endpoint's source keeps with its source
of truth — the registry's set of cover-composed formulas, the producer's own
family, the absence of any minting entry point in the handler bodies. What it
cannot see is whether the live ledger actually stays put across requests; that
half is tests/test_v13_issuer_panels_live.py, which counts it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from apps.api.routes import issuers
from exposure_workbench.analytics import containment as ct
from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import formula_service as fsvc

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "apps" / "api" / "routes" / "issuers.py").read_text()
CONTAINMENT = SRC[SRC.index("async def containment_view"):SRC.index("async def panel_series")]
PANEL = SRC[SRC.index("async def panel_series"):SRC.index("# ── filings tab")]


class _Co:
    ticker = "TEST"


def _hold_still(monkeypatch, bs: dict) -> None:
    """The two things the containment view asks the database for."""
    async def company(_db, _ticker):
        return _Co()

    async def balance_sheet(_db, _ticker, **_kw):
        return bs

    monkeypatch.setattr(issuers, "_company", company)
    monkeypatch.setattr(issuers.fundamentals_service, "get_balance_sheet", balance_sheet)


def _bs(balances: dict[str, float], absent: dict[str, str] | None = None) -> dict:
    return {
        "ticker": "TEST", "as_of": "2026-04-26",
        "balances": {m: {"value": v, "fact_id": f"fact_{m}", "as_of": "2026-04-26"}
                     for m, v in balances.items()},
        "not_reported_at_this_date": {
            m: {"last_reported": d, "value_then": 1.0, "note": ""}
            for m, d in (absent or {}).items()},
        "basis": "balance sheet as of 2026-04-26; one instant, no substitution",
    }


# ── the family map is pinned to its two sources ──────────────────────────────

def test_the_cover_formula_set_is_the_registrys_and_the_family_is_the_producers():
    """The route's map is two claims, each with an owner. WHICH measures are
    composed by cover is the formula registry's (op == "cover"); WHICH family
    each one sums is written where the summing happens, in
    formula_service._total_debt. A cover formula added without a row here, or a
    producer moved to a different family, should go red rather than serve the
    wrong tree under the right name."""
    composed = {n for n, f in fm.FORMULAS.items() if f.op == "cover"}
    assert set(issuers._FAMILY_OF_COVER_FORMULA) == composed, (
        "the route serves a different set of cover-composed measures than the "
        "registry declares"
    )
    src = inspect.getsource(fsvc._total_debt)
    assert f'family="{issuers._FAMILY_OF_COVER_FORMULA["total_debt"]}"' in src, (
        "the route's family for total_debt is not the one its producer passes"
    )
    unknown = {f for f in issuers._FAMILY_OF_COVER_FORMULA.values()
               if f not in ct.FAMILIES}
    assert unknown == set(), f"families the engine does not know: {sorted(unknown)}"


# ── the view is the engine's answer, not a second one ────────────────────────

def test_the_view_reads_the_balance_sheet_the_formula_path_reads():
    assert "fundamentals_service.get_balance_sheet(" in CONTAINMENT
    assert "ct.cover(" in CONTAINMENT, (
        "the tree must be the engine's own cover, or the view and the total it "
        "explains can describe different assemblies"
    )


@pytest.mark.parametrize("segment,name", [(CONTAINMENT, "containment_view"),
                                          (PANEL, "panel_series")])
@pytest.mark.parametrize("minting", ["get_flow(", "get_balance_series(",
                                     "tc.calculate(", "_record(", "refuse(",
                                     "db.commit"])
def test_neither_handler_reaches_a_minting_entry_point(segment, name, minting):
    """Every recording path this codebase has, absent from both bodies. The
    live half — the ledger count actually holding still — is
    tests/test_v13_issuer_panels_live.py."""
    assert minting not in segment, f"{name} reaches {minting}, which records"


def test_the_panel_is_a_filter_over_the_financials_read():
    assert "await financials(" in PANEL, (
        "the panel must serve the manifest rows the Financials tab serves, or "
        "the two views can disagree about the same issuer"
    )


def test_the_default_set_is_derived_from_the_rows_own_type():
    """A margin is a share of revenue, and that is written in each row's
    result_type. A list of labels here would drift the day the recipe adds
    one — which is exactly how the display-name guard's regex predecessor came
    to pin four labels of sixteen."""
    assert "derived_from" in PANEL
    for label in ('"gross_margin"', '"operating_margin"', '"net_margin"',
                  '"revenue_yoy"'):
        assert label not in PANEL, f"the default set hard-codes {label}"


# ── the containment view, behaviourally ──────────────────────────────────────

async def test_an_overlapping_line_is_explained_by_the_engines_own_edges(monkeypatch):
    """The NVDA shape: debt_current_total is reported and real, and its current
    portion of long-term debt is already inside the taken long_term_debt_total.
    The view must say that from EDGES, per request — not from a hand-kept map."""
    _hold_still(monkeypatch, _bs({"long_term_debt_total": 8.463e9,
                                  "debt_current_total": 1.0e9}))
    out = await issuers.containment_view("TEST", db=None)
    assert out["definition"] == "long_term_debt_total"
    assert [t["metric"] for t in out["taken"]] == ["long_term_debt_total"]
    assert out["taken"][0]["fact_id"] == "fact_long_term_debt_total"
    (overlap,) = out["overlapping_not_added"]
    assert overlap["metric"] == "debt_current_total"
    assert overlap["value"] == 1.0e9
    assert overlap["because"] == [{
        "part": "current_portion_long_term_debt",
        "part_label": "Long-term debt, current portion",
        "already_in": "long_term_debt_total",
        "already_in_label": "Long-term debt, total",
    }], "the shared part and the wider node holding it, from the edges"


async def test_the_two_kinds_of_leftover_stay_distinct_and_the_tree_is_present_only(monkeypatch):
    """`missing_at_this_date` is a claim about the total; `no_facts_for_issuer`
    is a claim about this desk's coverage. The cover draws that line (V11-U)
    and the view must not blur it back."""
    _hold_still(monkeypatch, _bs(
        {"long_term_debt_total": 100.0, "long_term_debt_noncurrent": 90.0,
         "current_portion_long_term_debt": 10.0,
         "total_assets": 500.0, "current_assets": 200.0},
        absent={"commercial_paper": "2025-12-27"}))
    out = await issuers.containment_view("TEST", db=None)
    assert [t["metric"] for t in out["taken"]] == ["long_term_debt_total"]
    assert out["overlapping_not_added"] == []
    assert out["missing_at_this_date"] == [
        {"metric": "commercial_paper", "label": "Commercial paper",
         "last_reported": "2025-12-27"}]
    assert {m["metric"] for m in out["no_facts_for_issuer"]} == {
        "debt_current_total", "short_term_borrowings"}
    assert [m["metric"] for m in out["outside_family"]] == [
        "current_assets", "total_assets"]
    assert {(e["parent"], e["child"]) for e in out["edges"]} == {
        ("long_term_debt_total", "long_term_debt_noncurrent"),
        ("long_term_debt_total", "current_portion_long_term_debt"),
    }, "edges are drawn among the metrics on this instant's sheet"
    assert all(e["observed"] > 0 for e in out["edges"]), (
        "the corpus count travels with each edge, as it does in the module"
    )


async def test_no_balance_sheet_is_the_honest_empty_shape(monkeypatch):
    _hold_still(monkeypatch, {"error": "no_balance_sheet_data", "ticker": "TEST"})
    out = await issuers.containment_view("TEST", db=None)
    assert out["detail"] == "this desk holds no balance sheet for TEST"
    for key in ("taken", "overlapping_not_added", "missing_at_this_date",
                "no_facts_for_issuer", "outside_family", "edges"):
        assert out[key] == [], f"{key} must be present and empty, not absent"


async def test_a_family_is_served_under_its_own_name(monkeypatch):
    _hold_still(monkeypatch, _bs({"stockholders_equity": 50.0,
                                  "noncontrolling_interest": 5.0}))
    out = await issuers.containment_view("TEST", formula="equity", db=None)
    assert out["family"] == "equity"
    assert {t["metric"] for t in out["taken"]} == {
        "stockholders_equity", "noncontrolling_interest"}


async def test_an_unknown_formula_names_what_is_known(monkeypatch):
    _hold_still(monkeypatch, _bs({}))
    with pytest.raises(HTTPException) as exc:
        await issuers.containment_view("TEST", formula="ebitda", db=None)
    assert exc.value.status_code == 422
    assert exc.value.detail["known"] == sorted(
        set(ct.FAMILIES) | {"total_debt"}), (
        "the known set is derived from the two sources, so it stays true"
    )


# ── the margins panel, behaviourally ─────────────────────────────────────────

def _row(label, operation, derived_from, points=None, value=None):
    result = ({"points": points, "quality_flags": {}} if points is not None
              else {"value": value, "quality_flags": {}})
    return {"label": label, "display": label.replace("_", " "),
            "calc_id": f"calc_{label}", "operation": operation,
            "params": {"result_type": {"kind": "series", "unit_class": "ratio",
                                       "derived_from": derived_from}},
            "result": result, "primitive_version": "v2"}


_POINTS = [{"end": "2026-03-28", "value": 0.49, "fact_ids": []}]


def _manifest(monkeypatch) -> None:
    async def financials(_ticker, _db):
        return {"ticker": "TEST", "recipe_version": "v2", "as_of": "2026-08-20",
                "calcs": [
                    _row("gross_margin", "calc.series.divide",
                         ["gross_profit", "revenue"], points=_POINTS),
                    _row("return_1m", "window_return", None, value=-0.05),
                    _row("current_ratio", "calc.series.divide",
                         ["current_assets", "current_liabilities"],
                         points=[{"end": "2026-03-28", "value": 1.07, "fact_ids": []}]),
                    _row("revenue_yoy", "change.yoy", "revenue",
                         points=[{"end": "2026-03-28", "value": 0.16,
                                  "fact_ids": ["fact_a", "fact_b"]}]),
                ]}
    monkeypatch.setattr(issuers, "financials", financials)


async def test_the_default_is_every_series_derived_from_revenue(monkeypatch):
    """The three margins and revenue year-on-year on the live manifest — here,
    the two of those this stub carries, and NOT the current ratio, which is a
    series and not a share of revenue."""
    _manifest(monkeypatch)
    out = await issuers.panel_series("TEST", db=None)
    assert [s["metric"] for s in out["series"]] == ["gross_margin", "revenue_yoy"]
    assert "unavailable" not in out


async def test_the_series_carries_the_ledger_rows_own_id_and_points(monkeypatch):
    _manifest(monkeypatch)
    out = await issuers.panel_series("TEST", metrics="gross_margin", db=None)
    (s,) = out["series"]
    assert s["calc_id"] == "calc_gross_margin", (
        "the id is the ledger row that computed the series — one per series, "
        "none fabricated per point"
    )
    assert s["points"] == _POINTS, "the stored points, verbatim"
    assert out["as_of"] == "2026-08-20" and out["recipe_version"] == "v2"


async def test_a_name_the_manifest_cannot_chart_is_answered_in_the_body(monkeypatch):
    _manifest(monkeypatch)
    out = await issuers.panel_series(
        "TEST", metrics="net_margin,return_1m,current_ratio", db=None)
    assert [s["metric"] for s in out["series"]] == ["current_ratio"]
    reasons = {u["metric"]: u["detail"] for u in out["unavailable"]}
    assert reasons["return_1m"] == "a single figure in the manifest, not a series"
    assert reasons["net_margin"] == "not a row this issuer's recipe produced"
    assert out["chartable"] == ["current_ratio", "gross_margin", "revenue_yoy"], (
        "what IS chartable rides along, so the caller can correct itself"
    )


async def test_no_manifest_passes_the_financials_reads_own_reason_through(monkeypatch):
    async def financials(_ticker, _db):
        return {"ticker": "TEST", "calcs": [],
                "note": "no baseline computed by the current recipe yet — run readiness"}
    monkeypatch.setattr(issuers, "financials", financials)
    out = await issuers.panel_series("TEST", db=None)
    assert out["series"] == []
    assert "run readiness" in out["note"]
