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
# A dimensionless number that is read as "so many times", not as a share of a
# whole. Both RATIO and MULTIPLE are money ÷ money; what separates them is the
# reader, and the reader is not a detail — displayed as a percent, a coverage
# of 12.5× reads "1250.0%" and a current ratio of 1.85 reads "185.0%". The
# algebra cannot tell the two apart (see REFINEMENTS below): the registry
# declares which one a named measure is, and this class is what it declares.
MULTIPLE = "multiple"

UNIT_CLASSES = (MONEY, RATIO, COUNT, MONEY_PER_SHARE, MULTIPLE)

# The dimensionless classes: pure numbers, distinguished only by how they read.
DIMENSIONLESS = (RATIO, MULTIPLE)

# Products are commutative, so the key is a frozenset — order independence
# is by construction, not by discipline.
PRODUCTS: dict[frozenset[str], str] = {
    frozenset((MONEY_PER_SHARE, COUNT)): MONEY,  # price x shares = market cap
    frozenset((MONEY, RATIO)): MONEY,
    frozenset((COUNT, RATIO)): COUNT,
    frozenset((MONEY_PER_SHARE, RATIO)): MONEY_PER_SHARE,
    frozenset((RATIO,)): RATIO,  # ratio x ratio (frozenset collapses the pair)
    # A multiple undoes the division that made it: EBITDA x (debt/EBITDA) = debt,
    # EPS x P/E = price. And DuPont is why the two dimensionless rows exist —
    # net_margin x asset_turnover = ROA (a share), asset_turnover x
    # equity_multiplier = revenue/equity (a multiple) — so the three-term chain
    # lands on RATIO whichever pair is multiplied first.
    frozenset((MONEY, MULTIPLE)): MONEY,
    frozenset((MONEY_PER_SHARE, MULTIPLE)): MONEY_PER_SHARE,
    frozenset((RATIO, MULTIPLE)): RATIO,
    frozenset((MULTIPLE,)): MULTIPLE,
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
    # Dividing BY a multiple recovers the denominator it was built over: debt ÷
    # (debt/EBITDA) = EBITDA, price ÷ (P/E) = EPS.
    (MONEY, MULTIPLE): MONEY,
    (MONEY_PER_SHARE, MULTIPLE): MONEY_PER_SHARE,
    # Two like multiples compared — this year's leverage against last year's —
    # is a share of one by the other, which reads as a percent.
    (MULTIPLE, MULTIPLE): RATIO,
}

# What the ALGEBRA computes, refined by what the REGISTRY declares. The algebra
# sees money ÷ money and answers RATIO, which is all it can know: debt/EBITDA
# and net margin are the same operation on the same units. A named measure may
# therefore declare the reading — but only within the dimensionless family, so
# a declaration can never turn a quotient into money, or a sum of dollars into
# a percent. One row, and adding another is a claim that two classes are the
# same dimension.
REFINEMENTS: dict[tuple[str, str], str] = {
    (RATIO, MULTIPLE): MULTIPLE,
}


def product_unit(a: str, b: str) -> str | None:
    """The unit of a x b, or None: None means undefined, and the caller
    refuses — it never guesses."""
    return PRODUCTS.get(frozenset((a, b)))


def quotient_unit(numerator: str, denominator: str) -> str | None:
    return QUOTIENTS.get((numerator, denominator))


def refine(computed: str, declared: str | None) -> str | None:
    """The unit a caller's declaration may impose on an algebra result.

    Returns the unit to record, or None: None means the declaration contradicts
    the algebra and the caller refuses. Declaring nothing keeps the computed
    unit, and declaring what was computed changes nothing — the only real work
    is a row in REFINEMENTS, which is the registry saying "this quotient is
    read as a multiple, not as a share".
    """
    if declared is None or declared == computed:
        return computed
    return REFINEMENTS.get((computed, declared))


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
