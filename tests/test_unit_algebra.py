"""V16 — the unit algebra is a lookup, and the ledger refuses rows it cannot type.

Two findings forced analytics/units.py into existence, and this file holds them
red. First: multiply and divide skipped the unit check entirely, and the result's
unit came from the operand ORDER — money × ratio was money, ratio × money was
ratio, and money × money was "money". Second: a fact's unit was judged twice
with two answers (typed_calculator said RATIO for anything non-USD, quantities
said COUNT). Now PRODUCTS/QUOTIENTS answer the first and fact_unit the second,
each in exactly one place.

Adding a row to either table is adding a claim about the world; the coverage
tests below fail until the claim has a case here.
"""

from __future__ import annotations

import inspect
from datetime import date
from itertools import product as iproduct

import pytest

from exposure_workbench.analytics import units
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import typed_calculator as tc

MONEY, RATIO, COUNT, MPS = units.MONEY, units.RATIO, units.COUNT, units.MONEY_PER_SHARE


def q(unit: str, v: float = 2.0, sid: str = "x", on: str | None = None,
      quantity: str | None = None, issuer: str = "AAPL") -> tc.Typed:
    return tc.Typed(value=v, unit_class=unit, quantity=quantity, source_id=sid,
                    instant=date.fromisoformat(on) if on else None,
                    issuers=(issuer,))


# ── (a) every row of the two tables, through the calculator ──────────────────

PRODUCT_CASES = [
    (MPS, COUNT, MONEY),        # price × shares = market cap
    (MONEY, RATIO, MONEY),      # revenue × margin
    (COUNT, RATIO, COUNT),      # shares × a fraction of them
    (MPS, RATIO, MPS),          # a per-share figure, scaled
    (RATIO, RATIO, RATIO),      # margin × turnover
]

QUOTIENT_CASES = [
    (MONEY, MONEY, RATIO),      # net income / revenue = margin
    (MONEY, COUNT, MPS),        # net income / shares = EPS
    (MONEY, MPS, COUNT),        # market cap / price = implied shares
    (MONEY, RATIO, MONEY),
    (MPS, MPS, RATIO),          # price / EPS = P/E
    (MPS, RATIO, MPS),
    (COUNT, COUNT, RATIO),
    (COUNT, RATIO, COUNT),
    (RATIO, RATIO, RATIO),
]


@pytest.mark.parametrize("a,b,expected", PRODUCT_CASES)
def test_every_products_row_multiplies_the_same_in_both_orders(a, b, expected):
    for x, y in ((a, b), (b, a)):
        left, right = q(x, sid="l"), q(y, sid="r")
        assert tc._check("multiply", left, right) is None
        assert tc._result_type("multiply", left, right, 1.0).unit_class == expected


@pytest.mark.parametrize("num,den,expected", QUOTIENT_CASES)
def test_every_quotients_row_divides_to_the_tables_answer(num, den, expected):
    left, right = q(num, sid="l"), q(den, sid="r")
    assert tc._check("divide", left, right) is None
    assert tc._result_type("divide", left, right, 1.0).unit_class == expected


def test_the_cases_above_cover_both_tables_whole():
    """A new table row without a case here is a claim without evidence."""
    assert {frozenset((a, b)) for a, b, _ in PRODUCT_CASES} == set(units.PRODUCTS)
    assert {(n, d) for n, d, _ in QUOTIENT_CASES} == set(units.QUOTIENTS)


# ── (b) what is not in the table is undefined, not defaulted ─────────────────

@pytest.mark.parametrize("a,b", [(MONEY, MONEY), (MPS, MPS), (MONEY, COUNT),
                                 (MONEY, MPS), (COUNT, COUNT)])
def test_an_undefined_product_is_refused_naming_both_units(a, b):
    r = tc._check("multiply", q(a, sid="l"), q(b, sid="r"))
    assert r["error"] == "undefined_product"
    assert a in r["detail"] and b in r["detail"] and "PRODUCTS" in r["detail"]


@pytest.mark.parametrize("num,den", [(RATIO, MONEY), (COUNT, MONEY), (RATIO, COUNT),
                                     (COUNT, MPS), (MPS, COUNT), (RATIO, MPS),
                                     (MPS, MONEY)])
def test_an_undefined_quotient_is_refused_naming_both_units(num, den):
    r = tc._check("divide", q(num, sid="l"), q(den, sid="r"))
    assert r["error"] == "undefined_quotient"
    assert num in r["detail"] and den in r["detail"] and "QUOTIENTS" in r["detail"]


def test_a_quotient_is_ordered_where_a_product_is_not():
    """money ÷ count is a per-share figure; count ÷ money means nothing here."""
    assert units.quotient_unit(MONEY, COUNT) == MPS
    assert units.quotient_unit(COUNT, MONEY) is None


# ── (c) order independence by construction, over the whole vocabulary ────────

def test_product_unit_is_commutative_over_every_pair():
    for a, b in iproduct(units.UNIT_CLASSES, repeat=2):
        assert units.product_unit(a, b) == units.product_unit(b, a), (a, b)


def test_money_per_share_is_in_the_vocabulary_and_adds_only_to_itself():
    assert MPS in units.UNIT_CLASSES
    a = q(MPS, 1.5, sid="a", on="2026-03-28", quantity="eps_basic")
    b = q(MPS, 0.5, sid="b", on="2026-03-28", quantity="dividends_per_share")
    assert tc._check("add", a, b) is None
    assert tc._result_type("add", a, b, 2.0).unit_class == MPS
    assert tc._check("add", a, q(MONEY, sid="m", on="2026-03-28"))["error"] == "incompatible_units"


# ── (d) the ledger refuses a valued row it cannot type ───────────────────────

class _Db:
    """Just enough of a session for _record: rows go in, nothing comes back."""

    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        pass


async def test_a_valued_row_without_a_unit_raises():
    with pytest.raises(ValueError, match="unit"):
        await cs._record(_Db(), None, "calc.scalar.divide",
                         {"result_type": {"quantity": "net_margin"}},
                         {"value": 0.25}, [], {}, "test")


async def test_a_valued_row_without_a_quantity_raises():
    with pytest.raises(ValueError, match="quantity"):
        await cs._record(_Db(), None, "calc.scalar.divide",
                         {"result_type": {"unit_class": "ratio"}},
                         {"value": 0.25}, [], {}, "test")


async def test_a_series_row_is_held_to_the_same_two_statements():
    with pytest.raises(ValueError):
        await cs._record(_Db(), None, "flow.series", {},
                         {"points": [{"period_end": "2026-03-28", "value": 1.0}]},
                         [], {}, "test")


async def test_money_per_share_reaches_the_unit_column():
    db = _Db()
    await cs._record(db, None, "derive.interval",
                     {"result_type": {"unit_class": "money_per_share",
                                      "quantity": "eps_basic"}},
                     {"value": 1.57}, [], {}, "test")
    assert db.rows[0].unit_class == "MONEY_PER_SHARE"


async def test_an_absence_row_carries_no_value_and_stays_exempt():
    """A refusal records that nothing was produced; there is no number to type."""
    db = _Db()
    await cs._record(db, None, "absence.not_reported", {"tried": {}},
                     {"statement": "not held"}, [], {}, "test")
    assert db.rows[0].unit_class is None


# ── (e) one fact, one unit judgement ─────────────────────────────────────────

def test_the_fact_unit_judgement_has_one_home():
    """typed_calculator and fundamentals_service both ask units.fact_unit;
    neither re-judges a unit string itself. The 'USD' literal disappearing from
    _resolve is the point — that literal WAS the second judgement."""
    src = inspect.getsource(tc._resolve)
    assert "units.fact_unit" in src
    assert "USD" not in src
    assert "units.fact_unit" in inspect.getsource(fs._facts_unit)


def test_fact_unit_speaks_the_ingest_vocabulary_and_refuses_the_rest():
    assert units.fact_unit("USD") == MONEY
    assert units.fact_unit(" usd ") == MONEY
    assert units.fact_unit("shares") == COUNT
    assert units.fact_unit("USD per share") == MPS
    assert units.fact_unit("segments") is None
    assert units.fact_unit(None) is None


def test_series_writers_write_the_one_period_key():
    """Three producers used to write three keys and the namer guessed."""
    src = inspect.getsource(fs._slot)
    assert "units.POINT_PERIOD_KEY" in src
    assert '"end"' not in src
