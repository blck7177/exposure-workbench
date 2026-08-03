"""The thresholds now come from the table, and only from the table (offline).

test_limit_checks.py pins what the engine DOES with a threshold. This file pins
where it may get one: from a risk_limits row or not at all. The defect being
closed is not an arithmetic mistake — `check_limits` took a `db_limits` list,
never referenced it, and read every number from 16 literals in its own cfg()
closure, so the demo book's twelve per-entity rows were displayed to users as
policy in force while affecting nothing.

The tests that matter most here are the ones that would still be green under
the old bug. A drift pin that projects entity_id away is exactly that: it stays
green while every override in the system goes inert.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from exposure_workbench.analytics import limits as limits_mod
from exposure_workbench.analytics.limit_defaults import SEED_DEFAULTS
from exposure_workbench.analytics.limits import (
    LIMIT_SPECS, REQUIRED_LIMIT_TYPES, LimitBook, MissingLimit, check_limits,
)
from exposure_workbench.workflow.exposure_workflow import ExposureWorkflow

from tests.test_limit_checks import exposure, pnl, risk, stress

AS_OF = date(2026, 7, 24)


def row(limit_type: str, *, entity_id=None, warning=0.1, breach=0.2,
        unit="fraction", is_active=True) -> dict:
    return {"id": f"rl_{limit_type}_{entity_id or 'default'}", "limit_type": limit_type,
            "entity_id": entity_id, "warning_level": warning, "breach_level": breach,
            "unit": unit, "is_active": is_active}


def complete_rows(**over) -> list[dict]:
    return [row(lt, warning=w, breach=b, **over)
            for lt, (w, b) in SEED_DEFAULTS.items()]


def full_book() -> LimitBook:
    return LimitBook(complete_rows())


# ── the drift pin: every check reaches the table, at the right scope ──────────

def test_a_run_looks_up_every_required_limit_and_at_the_right_scope():
    """Both directions, and the scope as well as the name.

    Name-only is the version that would have stayed green through the original
    bug in its most likely repair: a single getter defaulting entity_id to None
    lets a future edit drop the entity argument, which makes every override in
    every portfolio inert — today's exact defect — while an assertion that
    projects entity_id away goes on passing.
    """
    book = full_book()
    check_limits(
        risk(vol_30d=0.2, var_95_1d=0.03, es_95=0.04),
        stress(("Rates +100bp", 0.05)),
        exposure(gross=1_000_000, sectors={"Technology": 0.3}, issuers={"AAPL": 0.1}),
        pnl(-0.01),
        book,
    )

    assert {lt for lt, _ in book.looked_up} == set(REQUIRED_LIMIT_TYPES)

    for limit_type, entity_id in book.looked_up:
        scope = LIMIT_SPECS[limit_type].scope
        if scope == "portfolio":
            assert entity_id is None, f"{limit_type} was looked up per entity"
        else:
            assert entity_id is not None, f"{limit_type} was looked up with no entity"


def test_every_check_in_the_source_names_a_spec():
    """A static pin over the source, for the branches one synthetic run cannot
    reach. Same technique as tests/test_v2_audit.py: read the code, not a trace."""
    source = Path(limits_mod.__file__).read_text()
    emitted = set(re.findall(r'_check_one\(\s*\n?\s*"([a-z_0-9]+)"', source))
    emitted |= set(re.findall(r'emit\(\s*"([a-z_0-9]+)"', source))
    assert emitted, "the check names could not be read out of limits.py"
    assert emitted <= set(LIMIT_SPECS), sorted(emitted - set(LIMIT_SPECS))


def test_the_evaluated_list_separates_a_check_that_ran_from_one_that_did_not():
    """Row presence is not check execution.

    A book with too little history gets var_95/es_95/vol_30d as None, and those
    three checks do not run — while the step completes and the UI reads "all
    limits within bounds". The alerts are identical either way; `evaluated` is
    the only thing that can tell the two runs apart.
    """
    book = full_book()
    _, evaluated = check_limits(risk(), None, None, pnl(-0.001), book)
    assert "daily_loss" in evaluated
    for never_ran in ("var_95", "expected_shortfall_95", "rolling_volatility_30d"):
        assert never_ran not in evaluated


def test_an_override_on_a_name_the_book_does_not_hold_is_reported_as_inert():
    book = LimitBook(complete_rows() + [
        row("issuer_concentration", entity_id="LLY", warning=0.12, breach=0.18),
        row("issuer_concentration", entity_id="AAPL", warning=0.12, breach=0.18),
    ])
    check_limits(None, None, exposure(gross=0, issuers={"AAPL": 0.05}), None, book)
    assert book.inert_overrides() == ["issuer_concentration:LLY"]


# ── the override actually wins, which is the whole point ──────────────────────

def test_a_per_entity_row_overrides_the_portfolio_wide_one():
    book = LimitBook(complete_rows() + [
        row("issuer_concentration", entity_id="LLY", warning=0.12, breach=0.18),
    ])
    alerts, _ = check_limits(
        None, None, exposure(gross=0, issuers={"LLY": 0.13809, "AAPL": 0.13809}), None, book)
    # Same weight, two names, one alert: LLY's tighter row is the difference.
    assert [(a.entity_id, a.severity, a.limit_value) for a in alerts] == \
           [("LLY", "warning", 0.12)]


def test_a_deactivated_required_row_is_indistinguishable_from_an_absent_one():
    rows = complete_rows()
    for r in rows:
        if r["limit_type"] == "var_95":
            r["is_active"] = False
    assert LimitBook(rows).missing_required() == ["var_95"]


def test_an_unknown_limit_type_is_reported_even_when_it_is_inactive():
    """Deactivation must not become the way to hide a typo.

    If the book only saw active rows, `UPDATE risk_limits SET is_active = false`
    would silence the completeness check about a limit_type nothing can run —
    the same silent path one level down.
    """
    book = LimitBook(complete_rows() + [row("stress_loss_tech", is_active=False)])
    assert book.unknown_types == ["stress_loss_tech"]


# ── the book refuses a row that cannot mean anything ──────────────────────────

@pytest.mark.parametrize("bad, why", [
    ({"warning": 0.2, "breach": 0.1}, "inverted tiers"),
    ({"warning": 0.2, "breach": 0.2}, "equal tiers kill the warning tier"),
    ({"warning": 0.0, "breach": 0.2}, "a non-positive warning alerts on everything"),
])
def test_a_row_that_could_never_fire_is_refused_at_construction(bad, why):
    with pytest.raises(ValueError, match="can never fire"):
        LimitBook([row("var_95", warning=bad["warning"], breach=bad["breach"])])


def test_a_row_on_another_scale_is_refused():
    with pytest.raises(ValueError, match="unit="):
        LimitBook([row("var_95", warning=2.5, breach=3.5, unit="percent")])


def test_two_portfolio_wide_rows_for_one_check_is_refused():
    with pytest.raises(ValueError, match="two default rows"):
        LimitBook([row("var_95"), row("var_95", warning=0.3, breach=0.4)])


# ── no fallback: the lookup raises rather than inventing a number ─────────────

def test_a_missing_row_raises_instead_of_returning_anything():
    book = LimitBook([])
    with pytest.raises(MissingLimit):
        book.get_portfolio("var_95")
    with pytest.raises(MissingLimit):
        book.get_entity("issuer_concentration", "AAPL")


def test_the_two_getters_cannot_be_used_for_each_other():
    """Two methods, not one with entity_id=None: forgetting the entity argument
    has to be an error at the call site, not a silent fall back to the default."""
    book = full_book()
    with pytest.raises(ValueError):
        book.get_entity("var_95", "AAPL")
    with pytest.raises(ValueError):
        book.get_portfolio("sector_concentration")
    with pytest.raises(TypeError):
        book.get_entity("issuer_concentration")        # type: ignore[call-arg]


def test_the_engine_takes_no_argument_that_could_carry_a_threshold():
    """`limits_config`, `db_limits` and the cfg() closure are gone, not emptied.

    A partial cutover that emptied limits_config while keeping cfg() would have
    been invisible: the API container has no /app/configs, so the loader's
    "file missing → warn and return {}" already fed every call the 16 literals.
    """
    import inspect
    params = set(inspect.signature(check_limits).parameters)
    assert params == {"risk_metrics_result", "stress_result", "exposure_result",
                      "pnl_result", "limits"}
    source = Path(limits_mod.__file__).read_text()
    assert "def cfg(" not in source
    assert not (Path(limits_mod.__file__).parents[3] / "configs" / "risk_limits.yaml").exists()


# ── _validate_inputs judges limits in the same raise as prices ────────────────

def _validate(limits: LimitBook, *, tickers=("AAPL",)):
    wf = ExposureWorkflow(configs_dir="/app/configs")
    positions_df = pd.DataFrame([{"ticker": t, "quantity": 10.0, "sector": "Tech",
                                  "asset_class": "equity"} for t in tickers])
    prices_df = pd.DataFrame([{"ticker": t, "price_date": pd.Timestamp(AS_OF),
                               "close": 100.0} for t in tickers])
    wf._validate_inputs(positions_df, prices_df, AS_OF, limits)


def test_a_complete_book_validates():
    _validate(full_book())


def test_every_missing_limit_is_named_not_just_the_first():
    rows = [r for r in complete_rows()
            if r["limit_type"] not in {"var_95", "stress_loss", "gross_exposure"}]
    with pytest.raises(ValueError) as e:
        _validate(LimitBook(rows))
    for name in ("gross_exposure", "stress_loss", "var_95"):
        assert name in str(e.value)


def test_a_price_problem_and_a_limit_problem_surface_in_the_same_raise():
    """One fix-and-rerun cycle, not two. The same argument that made the price
    check list every bad ticker instead of stopping at the first."""
    wf = ExposureWorkflow(configs_dir="/app/configs")
    positions_df = pd.DataFrame([{"ticker": "AAPL", "quantity": 10.0, "sector": "Tech",
                                  "asset_class": "equity"},
                                 {"ticker": "ZZZZ", "quantity": 10.0, "sector": "Tech",
                                  "asset_class": "equity"}])
    prices_df = pd.DataFrame([{"ticker": "AAPL", "price_date": pd.Timestamp(AS_OF),
                               "close": 100.0}])
    rows = [r for r in complete_rows() if r["limit_type"] != "var_95"]
    with pytest.raises(ValueError) as e:
        wf._validate_inputs(positions_df, prices_df, AS_OF, LimitBook(rows))
    message = str(e.value)
    assert "ZZZZ" in message
    assert "var_95" in message


def test_a_row_naming_a_check_that_does_not_exist_fails_the_run():
    with pytest.raises(ValueError, match="stress_loss_tech"):
        _validate(LimitBook(complete_rows() + [row("stress_loss_tech")]))
