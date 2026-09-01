"""Citable columns are declared once (V15-S1).

"Which numbers may an answer point at" had four descriptions inside the gate and
no mechanism making them agree. A column added to a table was citable only if
somebody remembered _RUN_CHILDREN; a new ledger operation was typed correctly
only if somebody remembered _CALC_RATIO_OPS — a set whose own comment admitted
it mirrored typed_calculator._result_type.

These hold the derivation, so the four cannot drift back apart, and they hold the
two directions the drift actually took: a column that exists and is not citable,
and a unit decided by a name instead of by the row.
"""

from __future__ import annotations

import inspect

import pytest

from exposure_workbench.analytics import resources as R
from exposure_workbench.services import numeric_verification as nv


def test_the_gate_derives_its_lists_rather_than_keeping_them():
    src = inspect.getsource(nv)
    for name in ("_RUN_CHILDREN", "_RUN_COUNTS", "_CALC_RESULT_KEYS", "_CALC_RATIO_OPS"):
        block = src[src.index(f"{name}"):]
        block = block[:block.index("\n\n")]
        assert "resources." in block, f"{name} is a second copy again, not a derivation"


def test_every_declared_column_exists_on_its_table():
    """The direction that fails silently: a citable column naming a field the
    table does not have contributes nothing and says nothing."""
    missing = [
        f"{r.table}.{c.name}"
        for r in R.RUN_CHILDREN for c in r.columns
        if c.name not in r.model.__table__.columns
    ]
    assert missing == [], f"declared but absent: {missing}"
    bad_labels = [r.table for r in R.RUN_CHILDREN
                  if r.label_column and r.label_column not in r.model.__table__.columns]
    assert bad_labels == []


def test_every_numeric_column_of_a_run_child_is_declared_or_deliberately_not():
    """The other direction, and the one V13-S5 fell into: limit_checks gained
    three measured columns and stayed unciteable for a batch because the list in
    the gate was not revisited. A numeric column that is not citable is a
    decision; it is named here so it is a decision somebody made."""
    from sqlalchemy import Numeric, Float, Integer

    # Numeric columns that are deliberately not evidence, with the reason.
    NOT_EVIDENCE = {
        # identity and bookkeeping, not measurements
        "exposure_metrics.id", "issuer_exposures.id", "sector_exposures.id",
        "stress_results.id", "factor_attributions.id", "risk_alerts.id",
        "limit_checks.id",
        # V14-A's ordering key: a rank is a position in a list, not a quantity
        # the desk measured.
        "stress_results.rank",
    }
    undeclared = []
    for r in R.RUN_CHILDREN:
        declared = {c.name for c in r.columns}
        for col in r.model.__table__.columns:
            if not isinstance(col.type, (Numeric, Float, Integer)):
                continue
            key = f"{r.table}.{col.name}"
            if col.name in declared or key in NOT_EVIDENCE:
                continue
            undeclared.append(key)
    assert undeclared == [], (
        f"numeric columns neither citable nor named as deliberately not: {undeclared}. "
        "Add them to resources.RUN_CHILDREN with a unit, or to NOT_EVIDENCE with a reason"
    )


def test_the_unit_of_a_calculation_comes_from_the_row_not_its_name():
    """calc_ledger.unit_class is the promoted form of what typed producers have
    always stated. The operation-name set is transitional and may not grow —
    every entry in it predates the column."""
    from exposure_workbench.db.models import CalcLedger

    assert "unit_class" in CalcLedger.__table__.columns

    src = inspect.getsource(nv._from_calc)
    assert "row.unit_class" in src
    assert src.index("row.unit_class") < src.index("_CALC_RATIO_OPS"), (
        "the row's own unit must be preferred over the operation-name table"
    )

    # The frozen size. Raising this number is the edit that says a NEW operation
    # was typed by its name instead of by its row — which is the thing retired.
    assert len(R.LEGACY_RATIO_OPS) == 14, (
        "the transitional set changed size. A new operation types itself: pass "
        "unit_class to calc_service._record, or state result_type in params"
    )


def test_the_writer_stores_the_unit_it_was_given_or_could_read():
    src = inspect.getsource(__import__(
        "exposure_workbench.services.calc_service", fromlist=["_record"])._record)
    assert "unit_class=unit" in src
    assert 'result_type' in src, "a row that already states its type must not need a caller to repeat it"


def test_unit_class_strings_agree_across_the_two_modules():
    """resources names them without importing the gate; the gate must mean the
    same strings or the derivation types everything wrong and nothing fails."""
    assert (R.MONEY, R.RATIO, R.COUNT) == (nv.MONEY, nv.RATIO, nv.COUNT)
