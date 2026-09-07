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
# Flows per trading session (V25). Every class above is a STOCK — a balance, a
# count, a price — and stock ÷ stock is dimensionless, which is right for
# margins and wrong for a position over its daily turnover: $1.6M held ÷ $16B
# traded a day is 0.0001 DAYS, and the 2026-09-06 battery rendered it "0.01%"
# because the algebra had no row that could say otherwise. Average daily
# volume is money (or shares) PER SESSION, and a stock over a flow is a time —
# the only way "how many days to get out" can come from the algebra rather
# than from a caller's declaration.
MONEY_PER_DAY = "money_per_day"
COUNT_PER_DAY = "count_per_day"

UNIT_CLASSES = (MONEY, RATIO, COUNT, MONEY_PER_SHARE, MULTIPLE, MONEY_PER_DAY, COUNT_PER_DAY)

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
    # A flow scaled by a share is a flow: 20% participation of a day's dollar
    # volume is the dollars that can be sold a day. And price × shares a day is
    # the dollars a day — how dollar ADV is made from share ADV.
    frozenset((MONEY_PER_DAY, RATIO)): MONEY_PER_DAY,
    frozenset((COUNT_PER_DAY, RATIO)): COUNT_PER_DAY,
    frozenset((MONEY_PER_SHARE, COUNT_PER_DAY)): MONEY_PER_DAY,
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
    # A stock over a flow is a time, in the flow's own period: a position over
    # its daily turnover is days to liquidate; shares held over shares a day
    # likewise. Two like flows compared are a share; a flow over a share is a
    # flow; dollars a day over shares a day is a price; dollars a day over a
    # price is shares a day.
    (MONEY, MONEY_PER_DAY): COUNT,
    (COUNT, COUNT_PER_DAY): COUNT,
    (MONEY_PER_DAY, MONEY_PER_DAY): RATIO,
    (COUNT_PER_DAY, COUNT_PER_DAY): RATIO,
    (MONEY_PER_DAY, RATIO): MONEY_PER_DAY,
    (COUNT_PER_DAY, RATIO): COUNT_PER_DAY,
    (MONEY_PER_DAY, COUNT_PER_DAY): MONEY_PER_SHARE,
    (MONEY_PER_DAY, MONEY_PER_SHARE): COUNT_PER_DAY,
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
