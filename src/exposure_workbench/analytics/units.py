"""The unit vocabulary and the algebra over it — one table, no guessing.

V16. Two findings force this module into existence. First: multiply and
divide used to skip the unit check entirely, and the result's unit came from
the operand ORDER (money x ratio was money, ratio x money was ratio) — the
algebra below is a lookup, so the answer cannot depend on who was written
first. Second: the same fact's unit was judged twice with two answers
(quantities said COUNT for anything non-USD, typed_calculator said RATIO) —
fact_unit is now the one judgement, and both modules import it.

A product or quotient missing from the table is not "unknown, default to
something": it is undefined on this desk, and the calculator refuses it
loudly (money x money has no meaning here). Adding a row is adding a claim
about the world, and takes a case in test_unit_algebra.py.
"""

from __future__ import annotations

MONEY = "money"
RATIO = "ratio"
COUNT = "count"
MONEY_PER_SHARE = "money_per_share"

UNIT_CLASSES = (MONEY, RATIO, COUNT, MONEY_PER_SHARE)

# Products are commutative, so the key is a frozenset — order independence
# is by construction, not by discipline.
PRODUCTS: dict[frozenset[str], str] = {
    frozenset((MONEY_PER_SHARE, COUNT)): MONEY,  # price x shares = market cap
    frozenset((MONEY, RATIO)): MONEY,
    frozenset((COUNT, RATIO)): COUNT,
    frozenset((MONEY_PER_SHARE, RATIO)): MONEY_PER_SHARE,
    frozenset((RATIO,)): RATIO,  # ratio x ratio (frozenset collapses the pair)
}

# Quotients are ordered: (numerator, denominator) -> unit of the result.
QUOTIENTS: dict[tuple[str, str], str] = {
    (MONEY, MONEY): RATIO,
    (MONEY, COUNT): MONEY_PER_SHARE,
    (MONEY, MONEY_PER_SHARE): COUNT,
    (MONEY, RATIO): MONEY,
    (MONEY_PER_SHARE, MONEY_PER_SHARE): RATIO,  # P/E
    (MONEY_PER_SHARE, RATIO): MONEY_PER_SHARE,
    (COUNT, COUNT): RATIO,
    (COUNT, RATIO): COUNT,
    (RATIO, RATIO): RATIO,
}


def product_unit(a: str, b: str) -> str | None:
    """The unit of a x b, or None: None means undefined, and the caller
    refuses — it never guesses."""
    return PRODUCTS.get(frozenset((a, b)))


def quotient_unit(numerator: str, denominator: str) -> str | None:
    return QUOTIENTS.get((numerator, denominator))


# The one judgement of a stored fact's unit. Keys are the exact strings the
# ingest writes (case-folded); everything else — segment counts, MWh, jobs —
# is a disclosure count the desk cannot do algebra on, and fact_unit says so
# by returning None.
_FACT_UNITS: dict[str, str] = {
    "USD": MONEY,
    "SHARES": COUNT,
    "USD PER SHARE": MONEY_PER_SHARE,
    "NUMBER": COUNT,
}


def fact_unit(unit: str | None) -> str | None:
    return _FACT_UNITS.get((unit or "").strip().upper())


# The one key a series producer writes for a point's period. Three producers
# used to write three keys (period_end / end / as_of) and the namer guessed;
# readers keep a frozen legacy tuple for rows written before V16, writers use
# this and only this.
POINT_PERIOD_KEY = "period_end"
