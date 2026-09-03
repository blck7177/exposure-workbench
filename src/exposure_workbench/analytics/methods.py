"""What each published measure IS, said once beside the code that computes it (V20).

The page shows an ⓘ next to a measure and the text under it comes from here,
through the API, never typed into a component: a method statement that lives
in the UI drifts from the code the moment either changes, and the 9/2 audit
found `basis` strings on the tiles that nobody had checked against
risk_metrics.py. Each sentence below states the actual computation — the
estimator, the window, the annualisation — in the words a desk would use, and
test_v20_withheld pins the constants it quotes to the code's own.

Nothing here is a claim about a withheld measure (analytics/withheld.py):
a method statement for a number the desk does not publish would be an
advertisement.
"""

from __future__ import annotations

from exposure_workbench.analytics import risk_metrics as _rm

_ANNUALISE = f"√{_rm._TRADING_DAYS_PER_YEAR}"

METHODS: dict[str, str] = {
    "market_value": (
        "Sum of quantity × last close on or before the run date, for every holding; "
        "a holding with no recent price fails the run rather than being valued at zero."
    ),
    "day_pnl": (
        "Each holding's adjusted (total-return) daily return applied to its previous-session "
        "market value, summed; splits and dividends are therefore not counted as P&L. "
        "The book's day return is that P&L over the previous session's value."
    ),
    "value_path": (
        "Today's holdings, at fixed quantities, revalued at each session's adjusted close "
        "over the window; the benchmark is indexed to the same starting value. This is what "
        "this book would have been worth, not what it was — there is no holding history."
    ),
    "drawdown": (
        "Distance of the value path below its running maximum; an episode is a peak, the "
        "trough after it, and the recovery date if the peak was regained. Max drawdown is "
        "the deepest episode. Depth is not decomposed by holding or factor: a path "
        "statistic has no additive parts."
    ),
    "volatility": (
        f"Sample standard deviation (ddof=1) of the last N daily book returns, annualised by "
        f"{_ANNUALISE}; N is 30 or 60 sessions as labelled. A window the history cannot fill "
        f"is not reported."
    ),
    "attribution": (
        "One ordinary-least-squares regression of the book's daily return on the ETF factor "
        "returns over the run's regression window, with an intercept. A factor's day "
        "contribution is its partial beta × the factor's return that day; contributions plus "
        "alpha plus the residual equal the day's return. When the factors are collinear "
        "(max VIF above 5) their sum is reported and no single beta is shown."
    ),
    "factor_correlation": (
        "Pearson correlation of the factor daily-return series over the same window the "
        "regression used."
    ),
    "concentration": (
        "Each holding's and each sector's share of market value; a check compares the share "
        "with the tier this portfolio's own limit rows set."
    ),
}
