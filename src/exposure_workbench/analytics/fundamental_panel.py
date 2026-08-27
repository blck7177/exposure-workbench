"""Panel line types. Pure: no database, no clock, no network.

The arithmetic that used to live here — a TTM with a fiscal-year fallback and
eight hand-written debt recipes — encoded how particular issuers file rather
than what is true of accounting, and is gone (V9 plan §0). What remains is the
shape a line is reported in: a value with the formula and period basis that make
it checkable, or an absence with a reason, and no third state.

Everything here exists because the corpus proved it necessary.

**A total is composed from a non-overlapping set.** `LongTermDebt` already
contains the current maturities — AAPL at 2026-03-28 reports 74.404 noncurrent,
8.310 current and 82.700 total — so a recipe that adds the current portion to
the total double-counts 8.31bn. Whichever recipe runs, it names itself in the
formula, because "total debt" is a term whose composition varies by issuer and
by what they tagged.

**Every component of one total comes from one as-of date.** Taking the latest
fact for each metric independently produced, for GOOGL, a long-term debt total
of 49.085bn under a noncurrent balance of 98.165bn. The facts were six months
apart. The caller selects the date; this module only ever sees one balance set.

**TTM is four consecutive quarters and says which four.** Three quarters summed
is not a year, and a sum across a gap is a number that looks like a year while
hiding the hole that is the interesting part.

Definitions and sources: docs/spikes/V9_FORMULA_BASIS.md. In particular EBIT and
EBITDA start from NET INCOME (SEC C&DI 103.01) — an operating-income lookalike
may not carry those names — and free cash flow must travel with its formula
because, in the SEC's own words, "its title does not describe how it is
calculated" (C&DI 102.07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

@dataclass(frozen=True)
class Q:
    """One quarterly observation, carrying the facts it came from."""
    period_end: date
    value: float
    fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Amount:
    """A number the panel is prepared to state, with what it means.

    `formula` and `basis` are not decoration: a ratio of a balance to a flow is
    two period conventions in one number, and a reader who cannot see both
    cannot check it.
    """
    value: float
    formula: str
    basis: str
    fact_ids: tuple[str, ...] = ()
    quarters: tuple[str, ...] = ()


@dataclass(frozen=True)
class Missing:
    """Why a line is not there. Deliberately carries no value field: a payload
    that could hold both would eventually hold both."""
    missing: tuple[str, ...]
    reason: str
    alternatives: tuple[str, ...] = field(default_factory=tuple)


Line = Amount | Missing


def ratio(numerator: Line, denominator: Line, *, name: str, formula: str) -> Line:
    """A ratio is available only when both sides are, and it inherits both bases
    — a balance over a flow is two period conventions and both have to show."""
    for side, label in ((numerator, "numerator"), (denominator, "denominator")):
        if isinstance(side, Missing):
            return Missing(missing=side.missing,
                           reason=f"{name}: {label} unavailable — {side.reason}")
    assert isinstance(numerator, Amount) and isinstance(denominator, Amount)
    if denominator.value == 0:
        return Missing(missing=(), reason=f"{name}: denominator is zero")
    bases = [b for b in (numerator.basis, denominator.basis) if b]
    return Amount(
        value=numerator.value / denominator.value,
        formula=formula,
        basis=" / ".join(dict.fromkeys(bases)),
        fact_ids=numerator.fact_ids + denominator.fact_ids,
        quarters=numerator.quarters or denominator.quarters,
    )


def add(parts: dict[str, Line], *, formula: str, basis: str = "") -> Line:
    """Sum several lines, refusing if any is missing and saying which."""
    absent = {k: v for k, v in parts.items() if isinstance(v, Missing)}
    if absent:
        return Missing(
            missing=tuple(sorted(absent)),
            reason="; ".join(f"{k}: {v.reason}" for k, v in sorted(absent.items())),
        )
    amounts: list[Amount] = [v for v in parts.values()]  # type: ignore[misc]
    return Amount(
        value=sum(a.value for a in amounts),
        formula=formula,
        basis=basis or next((a.basis for a in amounts if a.basis), ""),
        fact_ids=tuple(fid for a in amounts for fid in a.fact_ids),
        quarters=next((a.quarters for a in amounts if a.quarters), ()),
    )


