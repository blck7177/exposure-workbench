"""The book after a sale — a hypothetical run, as pure arithmetic (V22).

WHY THIS EXISTS. "Say I sell the one you landed on: where does that leave
concentration?" is not a figure the run holds and not a combination of two
figures it holds. Selling one name changes EVERY other weight, because each is
a share of a market value that just shrank — nine renormalisations and a set of
limit checks over the result. That is a new book, and the desk had no object
for one: the evidence stores what IS, and the one scenario machinery it had
(stress) was withheld in V20. C01#t3 of the conversation battery died on it
eight refusals deep (docs/spikes/V21_CONVERSATIONS.md §2).

So this is a PRIMITIVE, not a derivation: one parametric entry that mints a
run-shaped object, after which every reader that knows a run (the namer, the
table, the calculator's ref:name operands, the limit engine) works on it
unchanged. Nothing here reads a database or knows a threshold: the holdings
come in as rows the run already wrote, the thresholds are applied by
analytics/limits.check_limits on the result exactly as the workflow applies
them, and the proceeds LEAVE the book — no cash line is invented, because the
run has no cash line to renormalise against.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Holding:
    ticker: str
    sector: str | None
    market_value: float


@dataclass(frozen=True)
class Sale:
    ticker: str
    fraction: float = 1.0        # of the position, in (0, 1]; 1 is the whole of it


@dataclass(frozen=True)
class SoldLeg:
    ticker: str
    fraction: float
    market_value_sold: float
    exited: bool                 # nothing of the name remains


@dataclass(frozen=True)
class ScenarioBook:
    """The book that remains, with its own weights."""
    holdings: list[Holding]                       # post-sale, sold-out names dropped
    weights: dict[str, float]                     # ticker -> share of the remaining book
    sectors: dict[str, dict]                      # sector -> {market_value, weight}
    market_value: float
    proceeds: float
    sold: list[SoldLeg] = field(default_factory=list)


def _err(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


def without(holdings: list[Holding], sales: list[Sale]) -> ScenarioBook | dict:
    """The book after the sales, or a refusal.

    Refused: a name the book does not hold (a scenario about a position that
    does not exist), a fraction outside (0, 1], the same name sold twice (which
    of the two fractions is meant cannot be told), and a sale that empties the
    book (a weight over zero market value is not a number).
    """
    held = {h.ticker: h for h in holdings}
    seen: set[str] = set()
    for s in sales:
        if s.ticker in seen:
            return _err("duplicate_sale", f"{s.ticker} is sold twice; state one fraction per name")
        seen.add(s.ticker)
        if s.ticker not in held:
            return _err("not_held",
                        f"{s.ticker} is not a position of this book; the holdings are "
                        f"{', '.join(sorted(held))}")
        if not (0.0 < s.fraction <= 1.0):
            return _err("bad_fraction",
                        f"{s.ticker}: fraction {s.fraction!r} is not in (0, 1]; 1 sells the "
                        f"whole position")
    if any(h.market_value is None for h in holdings):
        unpriced = sorted(h.ticker for h in holdings if h.market_value is None)
        return _err("unpriced_holding",
                    f"{', '.join(unpriced)} carry no market value on this run, so no weight "
                    f"after a sale can be computed")

    by_ticker = {s.ticker: s for s in sales}
    remaining: list[Holding] = []
    sold: list[SoldLeg] = []
    proceeds = 0.0
    for h in holdings:
        s = by_ticker.get(h.ticker)
        if s is None:
            remaining.append(h)
            continue
        leg = float(h.market_value) * s.fraction
        proceeds += leg
        sold.append(SoldLeg(h.ticker, s.fraction, leg, exited=s.fraction >= 1.0))
        if s.fraction < 1.0:
            remaining.append(Holding(h.ticker, h.sector, float(h.market_value) - leg))

    total = sum(float(h.market_value) for h in remaining)
    if total <= 0.0:
        return _err("empty_book", "the sales leave nothing in the book; a weight over "
                                  "zero market value is not a number")
    weights = {h.ticker: float(h.market_value) / total for h in remaining}
    sectors: dict[str, dict] = {}
    for h in remaining:
        key = h.sector or "Unknown"
        row = sectors.setdefault(key, {"market_value": 0.0, "weight": 0.0})
        row["market_value"] += float(h.market_value)
    for row in sectors.values():
        row["weight"] = row["market_value"] / total
    return ScenarioBook(
        holdings=remaining, weights=weights, sectors=sectors,
        market_value=total, proceeds=proceeds, sold=sold,
    )


@dataclass(frozen=True)
class Buy:
    ticker: str
    weight: float                # target share of the book AFTER the purchase, in (0, 1)
    sector: str | None = None


def with_buys(holdings: list[Holding], buys: list[Buy]) -> ScenarioBook | dict:
    """The book after adding names at target weights of the NEW book (V23).

    Money comes from outside: the added market value is what makes each new
    name its target share of the enlarged book, mv_added_i = w_i × mv_old ÷
    (1 − Σ w). Every existing weight scales down by (1 − Σ w). Refused: a
    weight outside (0, 1), targets summing to one or more, a name already
    held (its weight is changed by selling or by buying more of it, which is a
    different arithmetic — say so rather than guess), a name bought twice, an
    unpriced holding.
    """
    held = {h.ticker: h for h in holdings}
    seen: set[str] = set()
    total_w = 0.0
    for b in buys:
        if b.ticker in seen:
            return _err("duplicate_buy", f"{b.ticker} is bought twice; state one target weight per name")
        seen.add(b.ticker)
        if b.ticker in held:
            return _err("already_held",
                        f"{b.ticker} is already a position of this book at its own weight; a "
                        f"scenario adds names the book does not hold")
        if not (0.0 < b.weight < 1.0):
            return _err("bad_weight", f"{b.ticker}: target weight {b.weight!r} is not in (0, 1)")
        total_w += b.weight
    if total_w >= 1.0:
        return _err("bad_weight", f"the target weights sum to {total_w:.4f}; the new names "
                                  f"cannot be the whole book")
    if any(h.market_value is None for h in holdings):
        unpriced = sorted(h.ticker for h in holdings if h.market_value is None)
        return _err("unpriced_holding",
                    f"{', '.join(unpriced)} carry no market value on this run, so no weight "
                    f"after a purchase can be computed")
    mv_old = sum(float(h.market_value) for h in holdings)
    if mv_old <= 0.0:
        return _err("empty_book", "the book has no market value to scale a purchase against")
    added = [Holding(b.ticker, b.sector, b.weight * mv_old / (1.0 - total_w)) for b in buys]
    remaining = list(holdings) + added
    total = sum(float(h.market_value) for h in remaining)
    weights = {h.ticker: float(h.market_value) / total for h in remaining}
    sectors: dict[str, dict] = {}
    for h in remaining:
        key = h.sector or "Unknown"
        row = sectors.setdefault(key, {"market_value": 0.0, "weight": 0.0})
        row["market_value"] += float(h.market_value)
    for row in sectors.values():
        row["weight"] = row["market_value"] / total
    return ScenarioBook(
        holdings=remaining, weights=weights, sectors=sectors,
        market_value=total, proceeds=-sum(float(h.market_value) for h in added),
        sold=[],
    )

