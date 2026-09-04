"""V21-S3 — a stated share count, carried to the date it is valued on.

`positions.quantity` is a snapshot: the number of shares the holder stated, as
of the date they stated it. A price is a fact about a date too, and a market
value is the product of the two ON THE SAME DATE. Between a position's
as_of_date and a run's date the issuer may have split its stock, and then the
stated count and the run-date close are on different bases: 100 shares stated
before a 4:1 split, priced after it, is a quarter of the position (V5 §5 left
this as the one thing the price convention did not fix — "a holdings-data
problem, not a price one").

So a quantity is carried through the splits between the two dates, exactly as
an adjusted close is carried through them the other way. `carry_quantity` is
that arithmetic and nothing else: multiply by each ratio whose ex-date lies in
(stated, valued] when valuing later, divide when valuing earlier. No split in
the interval means the stated count is the valued count.

Which basis the OTHER inputs are on decides where this applies:
  - close (as-traded) at the run date: the count carried to the run date;
  - adj_close (split-adjusted to the latest basis held): the count carried to
    the latest split held, which for a run at or after it is the same number.
The workflow carries every holding to the run date once, in `_load_inputs`,
and every consumer downstream reads the carried column.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Split:
    ticker: str
    ex_date: date
    ratio: float      # new shares per old share: 4.0 for a 4:1 split, 0.1 for a 1:10 reverse


@dataclass(frozen=True)
class Carried:
    ticker: str
    stated: float
    stated_as_of: date
    valued: float
    valued_as_of: date
    applied: tuple[Split, ...]

    @property
    def factor(self) -> float:
        return self.valued / self.stated if self.stated else 1.0


def carry_quantity(quantity: float, stated_as_of: date, valued_as_of: date,
                   splits: list[Split]) -> tuple[float, list[Split]]:
    """The share count on `valued_as_of` that `quantity` on `stated_as_of` is,
    with the splits it went through (in date order).

    A split's ex-date is the first session the new count trades, so a split
    ON the stated date is already in the stated count (excluded) and a split
    ON the valued date is in the valued count (included): the interval is
    (stated, valued]. Valuing before the stated date reverses both.
    """
    if valued_as_of == stated_as_of:
        return quantity, []
    forward = valued_as_of > stated_as_of
    lo, hi = (stated_as_of, valued_as_of) if forward else (valued_as_of, stated_as_of)
    hits = sorted((s for s in splits if lo < s.ex_date <= hi), key=lambda s: s.ex_date)
    carried = quantity
    for s in hits:
        if s.ratio <= 0:
            raise ValueError(f"split ratio must be positive: {s}")
        carried = carried * s.ratio if forward else carried / s.ratio
    return carried, hits


def carry(ticker: str, quantity: float, stated_as_of: date, valued_as_of: date,
          splits: list[Split]) -> Carried:
    valued, applied = carry_quantity(quantity, stated_as_of, valued_as_of, splits)
    return Carried(ticker=ticker, stated=quantity, stated_as_of=stated_as_of,
                   valued=valued, valued_as_of=valued_as_of, applied=tuple(applied))
