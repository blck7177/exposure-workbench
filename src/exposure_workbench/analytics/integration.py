"""V14-A. The arithmetic an analyst does before the analysis starts.

Ordering a list of losses, netting two legs that point opposite ways, measuring
how far a weight sits from the limit it must not cross — none of these is a
judgement. They are arithmetic, and Law D puts arithmetic in code. Leaving them
to the model cost twice over: budget spent re-deriving what a query already
knows, and a transcription of every derived figure for the gate to check.

The round-4 battery measured what their absence looks like. A macro question
answered with seven exposures in the order they were fetched; a rates question
that listed a duration long and a credit short side by side as if they added
up; a concentration question that said which limits were warning without saying
how much room was left. All three are answers to the arithmetic, not to the
question, and all three are deterministic.

Pure functions over rows that already exist. Nothing here reads a database,
computes a beta, or invents a threshold: the regression happened in
factor_model, the scenarios in stress, the thresholds live in risk_limits. This
module rearranges what those produced, which is why every number it returns can
name the row it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Which way a factor's exposure points for the book, in the language of the
# thing the reader is worried about rather than the sign of a beta.
#
# A beta is signed against the factor's OWN return, and two of this model's
# factors move opposite to the risk they proxy for: TLT rises when long rates
# fall, HYG falls when credit spreads widen. So a positive TLT beta is a book
# that GAINS from falling rates — a duration long — and reporting it as
# "positive rates exposure" is how a hedge gets read as an exposure. The mapping
# is a property of the instrument, not of any issuer, so it belongs here beside
# the arithmetic and not in a rule about a company.
_RISK_SENSE = {
    # factor_ticker -> (risk being asked about, sign of the risk's effect on the
    # book when beta is positive)
    "TLT": ("rates_up", -1.0),   # long duration: rates up hurts
    "HYG": ("credit_spreads_widen", -1.0),
    "SPY": ("equity_down", -1.0),
    "QQQ": ("equity_down", -1.0),
    "IWM": ("equity_down", -1.0),
}


@dataclass(frozen=True)
class RankedItem:
    """One row of an ordered table, carrying where it came from."""
    name: str
    value: float
    unit_class: str
    source_id: str
    label: str
    note: str | None = None


def rank_by_magnitude(items: list[RankedItem]) -> list[RankedItem]:
    """Largest first, by absolute size.

    Ties keep their incoming order, which for a query ordered by name means the
    output is stable across runs: an ordering that changes between two identical
    calls would make "the largest" a different scenario on a page refresh.
    """
    return sorted(items, key=lambda i: (-abs(i.value), i.name))


@dataclass(frozen=True)
class NetLeg:
    """One side of an exposure that has two."""
    name: str
    beta: float
    signed_contribution: float
    source_id: str
    label: str


@dataclass(frozen=True)
class NetExposure:
    """The legs, and what they come to.

    `legs` is the whole set, always: a net of -0.4 that hides a +1.1 against a
    -1.5 is a different book from one with a single -0.4 leg, and a reader who
    sees only the net cannot tell them apart. `gross` says how much is being
    offset — the size of the disagreement between the legs.
    """
    risk: str
    net: float
    gross: float
    legs: list[NetLeg]
    quotable_individually: bool | None

    @property
    def direction(self) -> str:
        """Which way the book moves if this risk materialises.

        The word, not the sign: "the book is short rates" reads as an opinion
        about rates, while "loses if rates rise" cannot be misread. Zero is
        neither — reported as flat rather than rounded into one of the two.
        """
        if self.net == 0.0:
            return "flat"
        return "loses" if self.net < 0 else "gains"


def net_factor_exposure(
    factors: list[dict],
    risk: str,
    collinear: bool | None,
) -> NetExposure | None:
    """Net the legs of one risk across the factors that speak to it.

    Returns None when the model has no factor for this risk — a risk nothing in
    the regression measures has no net, and reporting 0.0 would say the book is
    flat to something that was never looked at. Same rule as stress: a scenario
    whose factors have no beta is unevaluated, not harmless.

    `quotable_individually` travels through unchanged. When the regression is
    collinear the individual legs may not be quoted, but their SUM is well
    determined — which is exactly what this function returns, so the net stays
    quotable while the legs it is made of do not.
    """
    legs: list[NetLeg] = []
    for f in factors:
        sense = _RISK_SENSE.get(f.get("factor_ticker") or "")
        if sense is None or sense[0] != risk:
            continue
        beta = f.get("beta")
        if beta is None:
            continue
        legs.append(NetLeg(
            name=f["factor_name"],
            beta=float(beta),
            signed_contribution=float(beta) * sense[1],
            source_id=f.get("source_id") or "",
            label=f"factor_attributions.{f['factor_name']}.beta",
        ))
    if not legs:
        return None
    net = sum(l.signed_contribution for l in legs)
    gross = sum(abs(l.signed_contribution) for l in legs)
    return NetExposure(
        risk=risk,
        net=net,
        gross=gross,
        legs=legs,
        quotable_individually=(None if collinear is None else not collinear),
    )


@dataclass(frozen=True)
class Headroom:
    """How far a measured value sits from the level it must not cross.

    Both distances, not one. "6.2% from the breach" and "already 1.4% past the
    warning" are the same row, and a reader deciding whether to act needs the
    nearer of the two — which is not always the same one.
    """
    check: str
    entity: str | None
    current: float
    warning_level: float
    breach_level: float
    to_warning: float
    to_breach: float
    status: str
    source_id: str


def headroom(checks: list[dict]) -> list[Headroom]:
    """Distance to each threshold, for every check that was actually evaluated.

    Checks that did not run are skipped rather than shown at zero distance. V7-U4
    is the same lesson one layer up: a check that never ran must not look like a
    check that passed, and here it must not look like one with room to spare.
    """
    out: list[Headroom] = []
    for c in checks:
        if not c.get("evaluated"):
            continue
        cur, warn, brch = c.get("current_value"), c.get("warning_level"), c.get("breach_level")
        if cur is None or warn is None or brch is None:
            continue
        cur, warn, brch = float(cur), float(warn), float(brch)
        out.append(Headroom(
            check=c["limit_type"], entity=c.get("entity_id"), current=cur,
            warning_level=warn, breach_level=brch,
            to_warning=warn - cur, to_breach=brch - cur,
            status=("breach" if cur >= brch else "warning" if cur >= warn else "clear"),
            source_id=c.get("source_id") or "",
        ))
    return sorted(out, key=lambda h: h.to_breach)


@dataclass(frozen=True)
class MatrixRow:
    """One holding, seen from both directions at once.

    The battery's clearest structural finding was that the two halves of the
    system never met: a turn discussing what ten businesses do had the factor
    loadings of all ten sitting unread in the same run. This row is that join,
    and it is a join — every field is a column of a row that already existed.
    """
    ticker: str
    sector: str | None
    weight: float | None
    contribution: float | None
    market_value: float | None
    measures_available: list[str] = field(default_factory=list)
    source_id: str = ""


def integration_matrix(
    positions: list[dict],
    coverage: dict[str, list[str]] | None = None,
) -> list[MatrixRow]:
    """Positions with what can be measured about each, ordered by weight.

    `coverage` maps ticker -> the named measures that issuer's filings support.
    Absent, the rows carry an empty list, which reads as "not asked" rather than
    "nothing available" — the caller decides whether to look it up, because
    doing it here would make a pure function reach for a database.
    """
    rows = [
        MatrixRow(
            ticker=p["ticker"], sector=p.get("sector"),
            weight=None if p.get("weight") is None else float(p["weight"]),
            contribution=(None if p.get("contribution") is None
                          else float(p["contribution"])),
            market_value=(None if p.get("market_value") is None
                          else float(p["market_value"])),
            measures_available=sorted((coverage or {}).get(p["ticker"], [])),
            source_id=p.get("source_id") or "",
        )
        for p in positions
    ]
    return sorted(rows, key=lambda r: (-(r.weight or 0.0), r.ticker))
