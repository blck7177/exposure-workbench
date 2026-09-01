"""V8-P1 — the regression that produced the betas is a row, not a log line (offline).

`calc_factor_attribution` computes alpha, the model's R², the residual, the
observation count and the collinearity flag, and the workflow puts them in
`workflow_events.payload`. A JSONB blob on an event is not a citable place: the
evidence resolver reads run CHILDREN, and `workflow_events` is not one, so the
one set of numbers that says how much of the day the factors actually explain
could not be stated by the agent at all.

`residual` had it worse — `FactorAttributionResult` computes it and NOTHING
persisted it anywhere, so the honest answer to "how much of this move do you
not explain" existed for the duration of one function call.

These are columns on `exposure_metrics` because that table is already the run's
one-row-per-run scalar record (it carries `UniqueConstraint("run_id")`), and
adding a table for eight scalars would give the same row two homes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from exposure_workbench.db.models import ExposureMetrics
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import numeric_verification as nv

ROOT = Path(__file__).resolve().parents[1]
INIT_SQL = ROOT / "infra" / "init.sql"
MIGRATION = ROOT / "infra" / "migrations" / "v8_skill_reads.sql"

# (column, is_numeric) — the eight facts about the regression behind a run.
NEW_COLUMNS = [
    ("attribution_portfolio_return", True),
    ("alpha", True),
    ("residual", True),
    ("model_r_squared", True),
    ("observations", True),
    ("regression_window_days", True),
    ("max_vif", True),
    ("collinear", False),
    ("attribution_date", False),
]


@pytest.mark.parametrize("column, _numeric", NEW_COLUMNS)
def test_the_run_records_what_its_regression_was(column, _numeric):
    assert column in ExposureMetrics.__table__.columns, (
        f"{column} is computed by factor_model and reaches only workflow_events.payload"
    )


@pytest.mark.parametrize("column, _numeric", NEW_COLUMNS)
def test_all_three_schemas_carry_it(column, _numeric):
    """models.py, init.sql and the migration are hand-written and must agree —
    the same discipline test_rls_parity enforces for policies. A fresh database
    and a migrated one must not differ."""
    assert re.search(rf"\b{column}\b", INIT_SQL.read_text()), f"init.sql missing {column}"
    assert MIGRATION.exists(), "v8_skill_reads.sql not written"
    assert re.search(rf"\b{column}\b", MIGRATION.read_text()), f"migration missing {column}"


def test_the_migration_is_idempotent():
    """It will be replayed against a live database that already has some of
    this. Every statement has to survive a second run — the same property
    v2_multiuser.sql and v6_report_gate.sql already hold."""
    body = MIGRATION.read_text()
    for stmt in re.findall(r"ALTER TABLE\s+\w+\s+ADD COLUMN[^;]*;", body, re.I):
        assert "IF NOT EXISTS" in stmt.upper(), f"not idempotent: {stmt[:80]}"


def test_the_numeric_metadata_is_citable_under_the_run():
    """The whole point. A number the agent may state has to resolve to a value
    the cited evidence holds, and `run_` resolves through _RUN_CHILDREN. Left
    out of that table these columns would be readable and unquotable, which is
    the same as absent.

    They go in the RATIO slot rather than MONEY because none of them is an
    amount of money. A bare figure is written as COUNT, and _COMPATIBLE lets a
    written COUNT meet a stored RATIO, so "58 observations" verifies while
    "58%" correctly does not.
    """
    ratio_cols = next(
        ratio for model, _money, ratio, _label, _qual in qn._RUN_CHILDREN
        if model is ExposureMetrics
    )
    for column, numeric in NEW_COLUMNS:
        if numeric:
            assert column in ratio_cols, f"{column} is not resolvable under run_"


def test_the_result_object_carries_the_window_it_was_fitted_over():
    """`lookback` is an argument, and an argument is not a record. A writer that
    takes the window from config while the fit took it from somewhere else can
    record a window the regression never used — so the number rides home on the
    result, and the persister has nowhere else to read it from."""
    from exposure_workbench.analytics.factor_model import FactorAttributionResult
    assert "window_days" in FactorAttributionResult.__dataclass_fields__


def test_the_regression_records_the_return_it_explained():
    """Measured on the live book (run_dcf950fa270d, 2026-08-20): the day's
    return is TWO numbers, and both are right.

      -0.0129178907   pnl: the adjusted return applied to yesterday's AS-TRADED
                      market value — what the book, valued as it actually is,
                      moved
      -0.0129202861   attribution: the book revalued at TOTAL-RETURN prices on
                      both days — the only convention a return SERIES can use,
                      and the one the betas were fitted against

    They differ by 2.4e-6 here, and the whole difference comes from MSFT, the
    one holding whose adj_close is not its close. It is not an error and it is
    not rounding: it scales with how much dividend history the book carries.

    So `residual` closes exactly against the attribution return and does NOT
    close against `daily_return`. Without this column a reconciliation has two
    options — report an `unexplained` quietly contaminated by a valuation
    convention, or hide the gap — and this codebase has removed that shape
    twice already (v5 adj_close, v6 contribution). The third quantity gets a
    name instead.
    """
    from exposure_workbench.analytics.factor_model import FactorAttributionResult
    assert "portfolio_return" in FactorAttributionResult.__dataclass_fields__
    assert "attribution_portfolio_return" in ExposureMetrics.__table__.columns
