"""An absent COMPOSED input is scoped as its producer scoped it (offline).

evaluate_formula(debt_to_ebitda, AAPL, at=2026-08-20) said "this desk holds no
total_debt for AAPL at any date" — over an issuer whose total debt is 84.697B at
the last date it filed. total_debt is assembled by containment cover and is
never a filed line, so the coverage table has no row under that name, and the
sentence read a missing row as a missing fact. In the same payload `detail`
said "at this date"; the two halves contradicted each other and the model
transcribed the wrong one, which is what V11 asked of it — the wording is the
server's.

The second half of the fix is upstream: _total_debt's refusal dropped the date
it was refusing AT, so nothing downstream could have said it. Found by the
out-of-module battery, 2026-08-29.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import formula_service as fsvc

AAPL_LEAVES = {
    "net_income": {"periods": 23, "through": "2026-03-28"},
    "interest_expense": {"periods": 13, "through": "2023-09-30"},
    "income_tax_expense": {"periods": 23, "through": "2026-03-28"},
    "depreciation_amortization": {"periods": 23, "through": "2026-03-28"},
}


def _desk(monkeypatch, leaves: dict, latest: str = "2026-03-28") -> None:
    """The three things _unavailable asks the database for, held still."""
    async def coverage(_db, _ticker, metrics):
        return {m: leaves.get(m) for m in metrics}

    async def issuer_latest(_db, _ticker):
        return latest

    async def refuse(_db, error, *, statement, **kw):
        keep = ("missing", "detail", "formula")
        return {"error": error, "absence_id": "calc_absent", "statement": statement,
                **{k: v for k, v in kw.items() if k in keep}}

    monkeypatch.setattr(fsvc.ab, "coverage", coverage)
    monkeypatch.setattr(fsvc.ab, "issuer_latest", issuer_latest)
    monkeypatch.setattr(fsvc.ab, "refuse", refuse)


async def test_a_composed_input_is_not_reported_absent_at_any_date(monkeypatch):
    _desk(monkeypatch, AAPL_LEAVES)
    out = await fsvc._unavailable(
        None, "AAPL", "debt_to_ebitda", fm.FORMULAS["debt_to_ebitda"], "total_debt",
        "no debt component reported at this date (2026-08-20); "
        "debt components were last reported at 2026-03-28",
        12, "test")
    assert out["error"] == "input_unavailable"
    assert "at any date" not in out["statement"]
    assert "2026-08-20" in out["statement"] and "2026-03-28" in out["statement"]
    assert out["missing"] == "total_debt"
    # What the desk DOES hold is still listed — it is the same sentence for
    # every refusal — and it still shows the stale tag for what it is.
    assert "interest_expense through 2023-09-30" in out["statement"]


async def test_a_filed_line_the_desk_never_holds_is_still_absent_at_any_date(monkeypatch):
    """The branch that was right stays right: MSFT files depreciation and not
    the combined line EBITDA needs, and that IS an absence at every date."""
    _desk(monkeypatch, {k: v for k, v in AAPL_LEAVES.items() if k != "depreciation_amortization"},
          latest="2026-03-31")
    out = await fsvc._unavailable(
        None, "MSFT", "debt_to_ebitda", fm.FORMULAS["debt_to_ebitda"],
        "depreciation_amortization",
        "MSFT reports no depreciation_amortization with a period", 12, "test")
    assert "holds no depreciation_amortization for MSFT at any date" in out["statement"]


async def test_a_filed_line_that_stops_short_is_said_to_run_through_its_last_date(monkeypatch):
    _desk(monkeypatch, AAPL_LEAVES)
    out = await fsvc._unavailable(
        None, "AAPL", "ebit", fm.FORMULAS["ebit"], "interest_expense",
        "window not derivable", 12, "test")
    assert "interest_expense runs through 2023-09-30" in out["statement"]
    assert "at any date" not in out["statement"]


async def test_total_debt_names_the_date_it_was_refused_at_and_when_the_components_were_last_seen(monkeypatch):
    """Upstream half. get_balance_sheet(at=...) is exact-match, so a date with
    no filing has no balances and every line sits in not_reported_at_this_date
    with the date it was last reported — which is precisely the sentence the
    refusal needed and used to drop."""
    async def get_balance_sheet(_db, _ticker, *, at=None, invoked_by="test"):
        return {
            "ticker": "AAPL", "as_of": "2026-08-20", "balances": {},
            "not_reported_at_this_date": {
                "long_term_debt_total": {"last_reported": "2026-03-28", "value_then": 8.2e10},
                "current_portion_long_term_debt": {"last_reported": "2026-03-28", "value_then": 3.0e9},
                "commercial_paper": {"last_reported": "2025-12-27", "value_then": 2.0e9},
                "cash_and_equivalents": {"last_reported": "2026-03-28", "value_then": 4.5e10},
            },
            "basis": "balance sheet as of 2026-08-20; one instant, no substitution",
        }

    monkeypatch.setattr(fsvc.fs, "get_balance_sheet", get_balance_sheet)
    out = await fsvc._total_debt(None, "AAPL", "2026-08-20", "test")
    assert out["error"] == "not_reported" and out["metric"] == "total_debt"
    assert "(2026-08-20)" in out["detail"]
    assert "last reported at 2026-03-28" in out["detail"]
