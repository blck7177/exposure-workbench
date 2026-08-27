"""V8-B — one call that reconciles a day's move (M17).

The question "why did the book move" was costing fifteen tool calls and ending
in filings, because the pieces of the answer lived in four places and nothing
put them together. This does, once, and records that it did.

Two identities, and what each one is for:

  A  Σ position contribution  ==  daily_return
     The book's return is its positions' returns weighted by yesterday's
     weights. If this does not hold the attribution is not describing this
     portfolio, and NO share of the move may be quoted — which is why the share
     fields are absent from the payload rather than null when it fails. A null
     invites "unknown share"; an absent key cannot be read at all.

  B  attribution_portfolio_return − Σ factor contribution  ==  alpha + residual
     What the factor model does not explain, named for what it is.

Identity B's left side is `attribution_portfolio_return` and NOT `daily_return`,
which is a correction to the V8 plan made by running it. The two differ by
however much dividend history the holdings carry — measured 2.4e-6 on the demo
book, all of it MSFT, the one holding whose adjusted close differs from its
close. The regression was fitted against total-return prices, so the residual
closes against the total-return revaluation and against nothing else. Written
the plan's way the identity misses by that gap and the "unexplained" figure
silently absorbs a valuation convention.

The unexplained remainder is called `alpha_plus_residual` and may not be called
`specific_return`. This system has no security-specific return: alpha is the
average daily return the factor set misses over the whole window, and residual
is this one day's miss. Adding them gives the part of today the model does not
account for, which is a statement about the MODEL. "Specific return" names it as
a property of the holdings and licenses a sentence about stock-picking that
nothing here measured.

There is no permission field (DP2). Whether a move is best described as
systematic or idiosyncratic is a judgement about wording, and this returns the
numbers that judgement would be made from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import run_reads_service as rr
from exposure_workbench.tools.registry import current_session_id

# The calc ledger operation this records under. Registered in
# numeric_verification._CALC_RATIO_OPS, without which the gate types this row's
# result as MONEY and refuses the share figures it just produced — reporting the
# refusal as the model's fault.
OP_RECONCILE = "portfolio.reconcile"

# Every quantity in these identities is stored as Numeric(12, 8), so one ulp is
# 1e-8 and each stored term carries at most half of that in rounding. Summing n
# terms and comparing against one more stored value admits (n + 1) halves.
#
# Derived from the schema rather than chosen: a fixed epsilon is a number
# somebody picked, and it goes stale the moment a column's scale changes. A
# relative tolerance is the other wrong answer — V3 established that rtol errs in
# both directions at once, accepting a tampered last digit on a large number
# while rejecting a correctly rounded small one.
_STORED_ULP = 1e-8


def _tolerance(n_terms: int) -> float:
    return (n_terms + 1) * 0.5 * _STORED_ULP


@dataclass(frozen=True)
class _Shares:
    """Only constructible when identity A holds.

    A dataclass rather than dict keys, so that "we could not verify the
    attribution" and "here is the share of the move" are mutually exclusive by
    construction rather than by a caller remembering to check a flag.
    """

    factor_share: float
    unexplained_share: float


def _sum(rows: list[dict], key: str) -> tuple[float, int]:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals), len(vals)


async def reconcile_move(db: AsyncSession, run_id: str) -> dict[str, Any]:
    """Both identities, the largest single contributors, and one ledger row."""
    attribution = await rr.get_attribution(db, run_id)
    if attribution.get("error"):
        return attribution

    meta = attribution.get("metadata")
    daily_return = attribution.get("daily_return")
    attr_return = attribution.get("attribution_portfolio_return")
    positions = attribution["positions"]
    factors = attribution["factors"]

    if daily_return is None or attr_return is None or meta is None:
        # An older run, or one whose attribution step did not complete. Saying
        # which is missing beats a bare failure: the caller can still read the
        # rows through get_attribution.
        return {"error": "run_not_reconcilable", "run_id": run_id,
                "missing": [name for name, v in (("daily_return", daily_return),
                                                 ("attribution_portfolio_return", attr_return),
                                                 ("regression_metadata", meta)) if v is None],
                "detail": "this run did not record everything the identities need; "
                          "get_attribution still returns the rows it does have"}

    sum_positions, n_pos = _sum(positions, "contribution")
    sum_factors, n_fac = _sum(factors, "contribution")

    gap_a = abs(sum_positions - daily_return)
    tol_a = _tolerance(n_pos)
    holds_a = gap_a <= tol_a

    unexplained = attr_return - sum_factors
    stated_unexplained = (meta.get("alpha") or 0.0) + (meta.get("residual") or 0.0)
    gap_b = abs(unexplained - stated_unexplained)
    tol_b = _tolerance(n_fac)
    holds_b = gap_b <= tol_b

    largest_factor = max(factors, key=lambda f: abs(f["contribution"] or 0.0), default=None)
    largest_position = max(positions, key=lambda p: abs(p["contribution"] or 0.0), default=None)

    out: dict[str, Any] = {
        "run_id": run_id,
        "portfolio_id": attribution["portfolio_id"],
        "as_of": attribution["as_of"],
        "reconciles": holds_a,
        "identity_positions": {
            "statement": "sum of position contributions == daily_return",
            "sum_of_contributions": sum_positions,
            "daily_return": daily_return,
            "gap": gap_a, "tolerance": tol_a, "holds": holds_a, "terms": n_pos,
        },
        "identity_factors": {
            "statement": ("attribution_portfolio_return - sum of factor contributions "
                          "== alpha + residual"),
            "attribution_portfolio_return": attr_return,
            "sum_of_factor_contributions": sum_factors,
            "alpha_plus_residual": unexplained,
            "recorded_alpha_plus_residual": stated_unexplained,
            "gap": gap_b, "tolerance": tol_b, "holds": holds_b, "terms": n_fac,
        },
        # The one place the two return conventions meet, named so a reader who
        # notices they differ finds the reason rather than a discrepancy.
        "return_conventions": {
            "daily_return": daily_return,
            "attribution_portfolio_return": attr_return,
            "difference": attr_return - daily_return,
            "why": ("daily_return applies each holding's adjusted return to yesterday's "
                    "as-traded market value; attribution_portfolio_return revalues the book "
                    "at total-return prices on both days, which is what the betas were "
                    "fitted against. They differ by the holdings' dividend history."),
        },
        "largest_factor_contribution": largest_factor and {
            "factor_name": largest_factor["factor_name"],
            "factor_ticker": largest_factor["factor_ticker"],
            "contribution": largest_factor["contribution"],
            "quotable_individually": largest_factor["quotable_individually"],
        },
        "largest_position_contribution": largest_position and {
            "ticker": largest_position["ticker"],
            "contribution": largest_position["contribution"],
            "weight": largest_position["weight"],
            "daily_return": largest_position["daily_return"],
        },
        "observations": meta.get("observations"),
        "regression_window_days": meta.get("regression_window_days"),
        "collinear": meta.get("collinear"),
        "factor_note": attribution.get("factor_note"),
    }

    if holds_a and holds_b and attr_return != 0.0:
        shares = _Shares(
            factor_share=sum_factors / attr_return,
            unexplained_share=unexplained / attr_return,
        )
        out |= asdict(shares)
    else:
        # Not null. There is no share to report and no key to read one out of.
        out["shares_note"] = (
            "the share of the move attributable to factors is not reported: "
            + ("the position contributions do not sum to the day's return, so this "
               "attribution does not describe this portfolio" if not holds_a
               else "the factor identity does not close" if not holds_b
               else "the day's return is zero, so a share of it is undefined"))

    # What this operation COMPUTED, at the top level where the resolver reads it.
    # The keys are declared in numeric_verification._CALC_RESULT_KEYS with a unit
    # each; a quantity recorded here and not declared there is a number the tool
    # produced and the gate will refuse.
    #
    # daily_return, alpha, residual and the observation count are deliberately
    # NOT repeated: they are columns of the run's own children and already
    # resolve through the run_ id. Recording them twice would create a second,
    # weaker path to the same evidence.
    recorded = {
        "sum_of_position_contributions": sum_positions,
        "sum_of_factor_contributions": sum_factors,
        "alpha_plus_residual": unexplained,
    }
    if holds_a and holds_b and attr_return != 0.0:
        recorded["factor_share"] = out["factor_share"]
        recorded["unexplained_share"] = out["unexplained_share"]
    out["calc_id"] = await cs._record(
        db, None, OP_RECONCILE,
        {"run_id": run_id, "terms_positions": n_pos, "terms_factors": n_fac},
        recorded,
        [run_id], {"identity_positions_holds": holds_a, "identity_factors_holds": holds_b},
        current_session_id(),
    )
    return out
