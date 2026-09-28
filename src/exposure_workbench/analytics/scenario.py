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
class BoughtLeg:
    ticker: str
    weight: float                # its share of the book right after the purchase
    market_value_added: float


@dataclass(frozen=True)
class ScenarioBook:
    """The book that remains, with its own weights."""
    holdings: list[Holding]                       # post-sale, sold-out names dropped
    weights: dict[str, float]                     # ticker -> share of the remaining book
    sectors: dict[str, dict]                      # sector -> {market_value, weight}
    market_value: float
    proceeds: float
    sold: list[SoldLeg] = field(default_factory=list)
    bought: list[BoughtLeg] = field(default_factory=list)


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


FUNDING = ("external", "proceeds")


def with_buys(holdings: list[Holding], buys: list[Buy], *, funding: str = "external",
              pool: float = 0.0) -> ScenarioBook | dict:
    """The book after buying names at target weights of the NEW book (V23; V2 P4).

    `funding="external"` (the default, and the engine as it has been): money comes
    from outside the book. The added market value is what makes each new name its
    target share of the enlarged book, mv_added_i = w_i × mv_old ÷ (1 − Σ w), and
    every existing weight scales down by (1 − Σ w). A name already held is
    refused: its weight is changed by selling or by adding to it, and adding is
    the other mode.

    `funding="proceeds"` (V2 P4, design v0.4 §09 "Q13 再配置"): the purchases are
    paid out of `pool`, the money the trade's sales freed. A held name may be
    bought — the purchase ADDS to it, so its target weight is the weight of the
    whole position afterwards. With existing_i the market value already held of
    each bought name, the book after is T1 = (T0 − Σ existing_i) ÷ (1 − Σ w), and
    what is spent is T1 − T0; it may not exceed the pool (insufficient_proceeds:
    the sales must free it), and every added_i = w_i × T1 − existing_i must be
    positive (already_above_target: the name is already more than that weight).

    Refused in both modes: a weight outside (0, 1), targets summing to one or
    more, a name bought twice, an unpriced holding.
    """
    if funding not in FUNDING:
        return _err("bad_funding", f"funding is one of {', '.join(FUNDING)}")
    held = {h.ticker: h for h in holdings}
    seen: set[str] = set()
    total_w = 0.0
    for b in buys:
        if b.ticker in seen:
            return _err("duplicate_buy", f"{b.ticker} is bought twice; state one target weight per name")
        seen.add(b.ticker)
        if b.ticker in held and funding == "external":
            return _err("already_held",
                        f"{b.ticker} is already a position of this book at its own weight; with outside money a "
                        f"scenario adds names the book does not hold — to add to a held name, fund the purchase "
                        f"from the sales' proceeds")
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

    if funding == "external":
        added = [Holding(b.ticker, b.sector, b.weight * mv_old / (1.0 - total_w)) for b in buys]
        remaining = list(holdings) + added
        spent = sum(float(h.market_value) for h in added)
        bought_legs = [(h.ticker, float(h.market_value)) for h in added]
    else:
        existing = {b.ticker: float(held[b.ticker].market_value) for b in buys if b.ticker in held}
        total_after = (mv_old - sum(existing.values())) / (1.0 - total_w)
        spent = total_after - mv_old
        if spent > pool + 1e-9:
            return _err("insufficient_proceeds",
                        f"the purchases need {spent:,.2f} and the sales in this trade freed {pool:,.2f}: sell more, "
                        f"or buy less")
        added_mv = {b.ticker: b.weight * total_after - existing.get(b.ticker, 0.0) for b in buys}
        under = [t for t, mv in added_mv.items() if mv <= 0.0]
        if under:
            return _err("already_above_target",
                        f"{', '.join(under)} already weigh more than the target after the sales; a purchase adds "
                        f"to a position, it does not cut one — sell instead")
        by_ticker = {b.ticker: b for b in buys}
        remaining = [Holding(h.ticker, h.sector, float(h.market_value) + added_mv[h.ticker]) if h.ticker in added_mv else h
                     for h in holdings]
        remaining += [Holding(b.ticker, b.sector, added_mv[b.ticker]) for b in buys if b.ticker not in held]
        bought_legs = [(t, added_mv[t]) for t in by_ticker]
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
        market_value=total, proceeds=-spent,
        sold=[], bought=[BoughtLeg(t, weights[t], mv) for t, mv in bought_legs],
    )


def traded(holdings: list[Holding], groups: list[tuple[str, list]], *, funding: str = "external") -> ScenarioBook | dict:
    """The book after a list of trades, applied IN THE ORDER GIVEN (V1: the plan's
    `scenario(run, trades)`). `groups` is that list with neighbouring sales put
    together and neighbouring purchases put together, so each group is exactly
    what `without` or `with_buys` has always taken and every refusal of theirs
    still fires on the group it belongs to.

    `funding` (V2 P4) says where a purchase's money comes from. `external`, the
    default and the engine as it has been: a sale's proceeds LEAVE the book, a
    purchase is paid with money from OUTSIDE it, and the two only happen to the
    same book one after the other. `proceeds`: the sales in this trade fund the
    purchases after them — a purchase may add to a held name — and what they did
    not spend leaves the book. `proceeds` on the result is the net of what left
    and what came in."""
    if funding not in FUNDING:
        return _err("bad_funding", f"funding is one of {', '.join(FUNDING)}")
    book: ScenarioBook | dict | None = None
    sold: list[SoldLeg] = []
    bought: list[BoughtLeg] = []
    proceeds = 0.0
    for side, legs in groups:
        book = (without(holdings, legs) if side == "sell"
                else with_buys(holdings, legs, funding=funding, pool=max(0.0, proceeds) if funding == "proceeds" else 0.0))
        if isinstance(book, dict):
            return book
        sold += book.sold
        bought += book.bought
        proceeds += book.proceeds
        holdings = book.holdings
    if book is None:
        return _err("no_trades", "at least one trade is needed")
    # a name bought early and diluted by a later purchase holds its FINAL weight
    bought = [BoughtLeg(b.ticker, book.weights.get(b.ticker, b.weight), b.market_value_added) for b in bought]
    return ScenarioBook(holdings=book.holdings, weights=book.weights, sectors=book.sectors,
                        market_value=book.market_value, proceeds=proceeds, sold=sold, bought=bought)

