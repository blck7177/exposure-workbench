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

from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import series_service as ss
from exposure_workbench.services import typed_calculator as tc

logger = logging.getLogger(__name__)

# v2 (V10-S3): the same baseline, composed from the interval engine's series
# primitives instead of the period ladder. What changed underneath each row:
# quarters are consecutive windows on the issuer's own grid (Q4 is a path, not a
# special case; a half-year filer's Q2 exists), every ratio went through the
# typed calculator's refusals, and each row records its type. What did not
# change: the set of labels, and the rule that an unavailable metric is an
# explicit entry with its reason.
RECIPE_VERSION = "v2"
OP_MANIFEST = "recipe.manifest"
BENCHMARK = "SPY"

# Growth is meaningful for flow metrics; balance-sheet levels get trend instead.
_GROWTH_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
_MARGIN_NUMERATORS = (("gross_margin", "gross_profit"),
                      ("operating_margin", "operating_income"),
                      ("net_margin", "net_income"))
_RETURN_WINDOWS = (("1m", 30), ("3m", 91), ("1y", 365))


def _unavailable(label: str, out: dict) -> dict:
    """Recipe steps are independent: one unavailable metric must not abort the rest.
    This is NOT a silent fallback — the failure is returned as an explicit
    'unavailable' entry with its reason, so the gap stays visible. The
    primitives return their refusals as dicts rather than raising, so this is a
    shape check, not an except clause."""
    logger.info("recipe: %s unavailable (%s)", label, out.get("error"))
    return {"unavailable": True, "reason": f"{out.get('error')}: {out.get('detail', '')}".strip(": ")}


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

    Ends with ONE manifest row naming every label's calc_id. The financials
    route reads the manifest rather than scanning the ledger by operation name:
    a scan keyed on `params.series.metric` was how the tab knew which row was
    which, and the new rows have no such key — a yoy row's `series` is the id
    of the series it was taken over, which is a different id every run.
    """
    out: dict[str, dict] = {}
    series: dict[str, dict] = {}

    async def flow(metric: str) -> dict:
        if metric not in series:
            series[metric] = await fs.get_flow(db, ticker, metric, months=3, last_n=12,
                                               invoked_by=invoked_by)
        return series[metric]

    async def balance(metric: str) -> dict:
        key = f"bal:{metric}"
        if key not in series:
            series[key] = await fs.get_balance_series(db, ticker, metric, last_n=12,
                                                      invoked_by=invoked_by)
        return series[key]

    async def ratio(label: str, num: dict, den: dict, op: str = "divide") -> None:
        if num.get("error"):
            out[label] = _unavailable(label, num)
            return
        if den.get("error"):
            out[label] = _unavailable(label, den)
            return
        got = await tc.calculate(db, op, num["calc_id"], den["calc_id"], invoked_by=invoked_by)
        out[label] = _unavailable(label, got) if got.get("error") else got

    # 1) growth (YoY on quarterly series; Q4 is a derived window like any other)
    for metric in _GROWTH_METRICS:
        s = await flow(metric)
        if s.get("error"):
            out[f"{metric}_yoy"] = _unavailable(f"{metric}_yoy", s)
            continue
        got = await ss.series_stat(db, s["calc_id"], "yoy", invoked_by=invoked_by)
        out[f"{metric}_yoy"] = _unavailable(f"{metric}_yoy", got) if got.get("error") else got

    # 2) margins — ratio of two reported series
    for label, numerator in _MARGIN_NUMERATORS:
        await ratio(label, await flow(numerator), await flow("revenue"))

    # 3) derived gross profit where the issuer omits GrossProfit but reports cost
    if out.get("gross_margin", {}).get("unavailable"):
        await ratio("gross_profit_derived", await flow("revenue"), await flow("cost_of_revenue"), "subtract")

    # 4) free cash flow = operating cash flow - capex
    await ratio("free_cash_flow", await flow("operating_cash_flow"), await flow("capex"), "subtract")

    # 5) liquidity / leverage — balances, at each reported instant
    await ratio("current_ratio", await balance("current_assets"), await balance("current_liabilities"))
    # V9-M1 renamed the denominator. `long_term_debt` accepted both LongTermDebt
    # (current maturities included) and LongTermDebtNoncurrent (excluded) and
    # served whichever was filed last, so this ratio silently changed base
    # between issuers and between quarters. It now names the noncurrent balance,
    # which is what "long-term debt" means on a balance sheet, and the key says
    # so — a reader of this number can no longer be wrong about which it is.
    await ratio("cash_to_long_term_debt_noncurrent",
                await balance("cash_and_equivalents"), await balance("long_term_debt_noncurrent"))

    # 6) market returns, absolute and benchmark-relative
    for label, days in _RETURN_WINDOWS:
        start = as_of - timedelta(days=days)
        out[f"return_{label}"] = await cs.window_return(
            db, ticker, start, as_of, invoked_by=invoked_by
        )
        out[f"return_{label}_vs_{BENCHMARK}"] = await cs.window_return(
            db, ticker, start, as_of, benchmark=BENCHMARK, invoked_by=invoked_by
        )

    labels = {label: (v["calc_id"] if "calc_id" in v else v) for label, v in out.items()}
    manifest_id = await cs._record(
        db, ticker, OP_MANIFEST,
        {"recipe_version": RECIPE_VERSION, "as_of": as_of.isoformat()},
        {"labels": labels},
        [v for v in labels.values() if isinstance(v, str)], {}, invoked_by,
    )
    out["_meta"] = {
        "recipe_version": RECIPE_VERSION, "ticker": ticker, "as_of": as_of.isoformat(),
        "manifest_id": manifest_id,
    }
    return out
