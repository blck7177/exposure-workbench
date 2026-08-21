"""Factor model — ONE multivariate OLS regression for portfolio return attribution.

The word that matters is "one". This file used to run eight separate univariate
regressions — `polyfit(x_k, y)` per factor — and then add their contributions
together as if the factors were orthogonal. Three of the eight are SPY, QQQ and
IWM, which correlate around 0.9: each univariate beta absorbs the WHOLE market
move, so summing three of them counts the same move three times. `total_explained`
routinely exceeded the return it was explaining, and `residual`, defined as
portfolio return minus that sum, was not a residual of any regression — it was
the arithmetic left over from double counting. The reported `r_squared` came from
a separate multivariate fit that shared none of the betas above it, so the one
number that looked like a goodness-of-fit measured a model the page did not show.

A single fit fixes all of that by construction: the betas are partial
coefficients, the contributions add up to the fitted value, and the residual is
the regression's own.

What a single fit does NOT fix is that those three factors are still nearly
collinear, which leaves each individual beta poorly determined even though their
sum is not. That is reported (`condition_number`, `collinear`) rather than
silently absorbed — shrinkage and factor orthogonalization are a later batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd


@dataclass
class FactorResult:
    factor_name: str
    factor_ticker: str
    beta: float            # PARTIAL coefficient: this factor holding the others fixed
    factor_return: float   # most recent day factor return
    contribution: float    # beta × factor_return (1-day attribution)
    r_squared: float       # this factor ALONE against the portfolio — a marginal
    #                        statistic, deliberately not the model's R² below


@dataclass
class FactorAttributionResult:
    factors: list[FactorResult] = field(default_factory=list)
    total_explained: float = 0.0   # sum of factor contributions = fitted - alpha
    residual: float = 0.0          # portfolio_return - alpha - total_explained
    r_squared: float = 0.0         # the one model's R²
    alpha: float = 0.0             # intercept: average daily return the factors miss
    observations: int = 0
    as_of: date | None = None      # the day the 1-day attribution describes
    max_vif: float | None = None
    collinear: bool = False

    def betas(self) -> dict[str, float]:
        """ticker -> partial beta. What a stress scenario propagates through."""
        return {f.factor_ticker: f.beta for f in self.factors}


# Variance inflation factor. VIF_k > 5 is the conventional line past which a
# single coefficient's standard error is inflated enough that the coefficient
# should not be quoted on its own.
#
# VIF and not the design matrix's condition number, because the question here is
# per-coefficient and so is the answer. Measured on the live book (2026-08-20,
# 58 observations): condition number 9.06, which reads as "mild" against the
# usual threshold of 30 — while SPY's VIF was 10.6 and QQQ's 7.8, and the fitted
# betas were SPY +1.39 against QQQ −0.67. The condition number was answering a
# question about the matrix; the flag is about the numbers on the page.
#
# What stays trustworthy under a firing flag is any SUM over the collinear set:
# the same run's betas sum to 0.54 and the portfolio's univariate beta to SPY is
# 0.53. That is why stress propagation — which shocks SPY, QQQ and IWM together
# and adds their contributions — is usable while "the book's beta to QQQ is
# −0.67" is not.
_VIF_THRESHOLD = 5.0


def calc_factor_attribution(
    portfolio_returns: pd.Series,
    factor_returns: pd.DataFrame,
    factor_config: dict,
    lookback: int = 60,
    min_observations: int = 30,
    include_intercept: bool = True,
) -> FactorAttributionResult:
    """
    Estimate factor betas with one OLS fit over the last `lookback` observations.

    portfolio_returns: pd.Series indexed by date, values = daily returns
    factor_returns: pd.DataFrame indexed by date, columns = factor_ticker
    factor_config: dict from factor_config.yaml, factors key
    lookback: number of trading days to use for the regression
    min_observations: refuse to fit below this; the caller reads it from config
    """
    if portfolio_returns.empty or factor_returns.empty:
        return FactorAttributionResult()

    combined = pd.concat(
        [portfolio_returns.rename("portfolio"), factor_returns],
        axis=1,
        join="inner",
    ).dropna()

    factor_cols = [c for c in combined.columns if c != "portfolio"]
    if not factor_cols:
        return FactorAttributionResult()

    # A regression needs more observations than coefficients before it is a fit
    # at all, quite apart from whether it is a good one. The config's floor and
    # this arithmetic one are both real; the binding one wins.
    floor = max(min_observations, len(factor_cols) + 2)
    if len(combined) < floor:
        return FactorAttributionResult(observations=len(combined))

    combined = combined.tail(lookback)
    y = combined["portfolio"].to_numpy(dtype=float)
    X = combined[factor_cols].to_numpy(dtype=float)

    design = np.column_stack([np.ones(len(X)), X]) if include_intercept else X
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    if include_intercept:
        alpha, betas = float(coeffs[0]), coeffs[1:]
    else:
        alpha, betas = 0.0, coeffs

    fitted = design @ coeffs
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    max_vif = _max_vif(X)

    name_by_ticker = {
        cfg.get("ticker"): name
        for name, cfg in factor_config.get("factors", {}).items()
        if cfg.get("ticker")
    }

    latest = combined.iloc[-1]
    results: list[FactorResult] = []
    for i, ticker in enumerate(factor_cols):
        x = X[:, i]
        factor_return = float(latest[ticker])
        results.append(FactorResult(
            factor_name=name_by_ticker.get(ticker, ticker),
            factor_ticker=ticker,
            beta=float(betas[i]),
            factor_return=factor_return,
            contribution=float(betas[i]) * factor_return,
            r_squared=_univariate_r2(x, y),
        ))

    results.sort(key=lambda r: abs(r.contribution), reverse=True)
    total_explained = float(sum(r.contribution for r in results))
    latest_port_return = float(y[-1])

    index_last = combined.index[-1]
    as_of = index_last.date() if hasattr(index_last, "date") else None

    return FactorAttributionResult(
        factors=results,
        total_explained=total_explained,
        # The regression's own residual for that day. Alpha is subtracted rather
        # than folded into total_explained: it is what the factors did NOT
        # explain on average, so putting it in the explained pile would be the
        # old double-count in a different disguise.
        residual=latest_port_return - alpha - total_explained,
        r_squared=max(0.0, min(1.0, r_squared)),
        alpha=alpha,
        observations=len(combined),
        as_of=as_of,
        max_vif=max_vif,
        collinear=max_vif > _VIF_THRESHOLD,
    )


def _max_vif(X: np.ndarray) -> float:
    """Worst variance inflation factor across the factors.

    VIF_k = 1 / (1 - R²_k), where R²_k is factor k regressed on all the others.
    A perfectly collinear factor gives R² = 1 and an infinite VIF, which is the
    right answer and is returned as such rather than clipped to a large number
    that would read as a measurement.
    """
    if X.shape[1] < 2:
        return 1.0

    scale = X.std(axis=0, ddof=1)
    scale[scale < 1e-12] = 1.0
    Z = (X - X.mean(axis=0)) / scale

    worst = 1.0
    for k in range(Z.shape[1]):
        others = np.delete(Z, k, axis=1)
        design = np.column_stack([np.ones(len(others)), others])
        coeffs, *_ = np.linalg.lstsq(design, Z[:, k], rcond=None)
        ss_res = float(np.sum((Z[:, k] - design @ coeffs) ** 2))
        ss_tot = float(np.sum((Z[:, k] - np.mean(Z[:, k])) ** 2))
        if ss_tot <= 0:
            continue
        unexplained = ss_res / ss_tot
        vif = float("inf") if unexplained < 1e-12 else 1.0 / unexplained
        worst = max(worst, vif)
    return worst


def _univariate_r2(x: np.ndarray, y: np.ndarray) -> float:
    """How much of the portfolio's variance this factor explains BY ITSELF.

    Reported per factor because "how much does the market alone account for" is a
    real question with a real answer. It is not a decomposition: these do not sum
    to the model's R², and for correlated factors they overlap heavily. That
    overlap is exactly what the old code summed.
    """
    if np.std(x) < 1e-12:
        return 0.0
    slope, intercept = np.polyfit(x, y, 1)
    ss_res = float(np.sum((y - (slope * x + intercept)) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot <= 0:
        return 0.0
    return max(0.0, 1.0 - ss_res / ss_tot)
