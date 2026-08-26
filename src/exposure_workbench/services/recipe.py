"""Standard analysis recipe (M3 consumer #1) — the deterministic baseline.

This file is deliberately the ONLY place the baseline metric list lives, so
changing what the Financials tab shows is a change here and nowhere else.

The recipe composes the closed algebra; it adds no new maths. Metrics an issuer
does not report simply do not appear — the recipe never substitutes a proxy
(e.g. it will not pass pre-tax income off as operating income), and derived
gross profit is computed only where the issuer omits GrossProfit but reports
cost_of_revenue.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import period_ladder as pl
from exposure_workbench.services import calc_service as cs

logger = logging.getLogger(__name__)

RECIPE_VERSION = "v1"
BENCHMARK = "SPY"

# Growth is meaningful for flow metrics; balance-sheet levels get trend instead.
_GROWTH_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
_MARGIN_NUMERATORS = (("gross_margin", "gross_profit"),
                      ("operating_margin", "operating_income"),
                      ("net_margin", "net_income"))
_RETURN_WINDOWS = (("1m", 30), ("3m", 91), ("1y", 365))


async def _try(label: str, coro):
    """Recipe steps are independent: one unavailable metric must not abort the rest.

    This is NOT a silent fallback — the failure is returned as an explicit
    'unavailable' entry with its reason, so the gap stays visible.
    """
    try:
        return await coro
    except cs.UnknownMetric as e:
        logger.info("recipe: %s unavailable (%s)", label, e)
        return {"unavailable": True, "reason": str(e)}


async def run_standard_recipe(
    db: AsyncSession, ticker: str, as_of: date, invoked_by: str = "recipe"
) -> dict:
    """Compute the baseline set for one issuer. Returns {label: result-or-unavailable}.

    `as_of` anchors the return windows and has no default. The ledger's whole
    claim is that a calc_id can be replayed to the same number, and date.today()
    broke that for the six return rows: the same ticker recomputed a day later
    wrote a different 1m return under the same recipe version, with nothing in
    `params` to say the window had moved. A default here would be the clock
    again, one layer down.
    """
    out: dict[str, dict] = {}
    # Flow metrics (revenue, income, cash flow) are DURATION facts -> quarterly.
    # Balance-sheet metrics (assets, cash, debt) are INSTANT facts with no
    # period_start; asking for them as "quarterly" matches nothing.
    q = lambda m: cs.SeriesSpec(ticker=ticker, metric=m, period_type=pl.QUARTERLY, last_n=12)
    bal = lambda m: cs.SeriesSpec(ticker=ticker, metric=m, period_type=pl.INSTANT, last_n=12)

    # 1) growth (YoY on quarterly series, which include the derived Q4)
    for metric in _GROWTH_METRICS:
        out[f"{metric}_yoy"] = await _try(
            f"{metric}_yoy", cs.change(db, q(metric), "yoy", invoked_by=invoked_by)
        )

    # 2) margins — ratio of two reported series
    for label, numerator in _MARGIN_NUMERATORS:
        out[label] = await _try(
            label, cs.combine(db, q(numerator), q("revenue"), "divide", invoked_by=invoked_by)
        )

    # 3) derived gross profit where the issuer omits GrossProfit but reports cost
    if out.get("gross_margin", {}).get("unavailable"):
        derived = await _try(
            "gross_profit_derived",
            cs.combine(db, q("revenue"), q("cost_of_revenue"), "sub", invoked_by=invoked_by),
        )
        out["gross_profit_derived"] = derived

    # 4) free cash flow = operating cash flow - capex
    out["free_cash_flow"] = await _try(
        "free_cash_flow",
        cs.combine(db, q("operating_cash_flow"), q("capex"), "sub", invoked_by=invoked_by),
    )

    # 5) liquidity / leverage
    out["current_ratio"] = await _try(
        "current_ratio",
        cs.combine(db, bal("current_assets"), bal("current_liabilities"), "divide", invoked_by=invoked_by),
    )
    # V9-M1 renamed the denominator. `long_term_debt` accepted both LongTermDebt
    # (current maturities included) and LongTermDebtNoncurrent (excluded) and
    # served whichever was filed last, so this ratio silently changed base
    # between issuers and between quarters. It now names the noncurrent balance,
    # which is what "long-term debt" means on a balance sheet, and the key says
    # so — a reader of this number can no longer be wrong about which it is.
    out["cash_to_long_term_debt_noncurrent"] = await _try(
        "cash_to_long_term_debt_noncurrent",
        cs.combine(db, bal("cash_and_equivalents"), bal("long_term_debt_noncurrent"),
                   "divide", invoked_by=invoked_by),
    )

    # 6) market returns, absolute and benchmark-relative
    for label, days in _RETURN_WINDOWS:
        start = as_of - timedelta(days=days)
        out[f"return_{label}"] = await cs.window_return(
            db, ticker, start, as_of, invoked_by=invoked_by
        )
        out[f"return_{label}_vs_{BENCHMARK}"] = await cs.window_return(
            db, ticker, start, as_of, benchmark=BENCHMARK, invoked_by=invoked_by
        )

    out["_meta"] = {
        "recipe_version": RECIPE_VERSION, "ticker": ticker, "as_of": as_of.isoformat(),
    }
    return out
