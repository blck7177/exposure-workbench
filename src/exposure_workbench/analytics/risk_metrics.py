"""Risk metrics — rolling volatility, VaR, Expected Shortfall, drawdown."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class RiskResult:
    vol_30d: float | None      # annualised 30-day rolling vol
    vol_60d: float | None      # annualised 60-day rolling vol
    var_95_1d: float | None    # 1-day 95% historical VaR (positive = loss)
    es_95: float | None        # 1-day 95% Expected Shortfall (positive = loss)
    max_drawdown: float | None # max peak-to-trough drawdown (positive = loss magnitude)


_TRADING_DAYS_PER_YEAR = 252


def calc_risk_metrics(
    portfolio_returns: pd.Series,
    min_obs: int = 20,
) -> RiskResult:
    """
    Compute risk metrics from a series of daily portfolio returns.

    portfolio_returns: pd.Series of float (daily %, e.g. 0.01 = +1%)
    """
    returns = portfolio_returns.dropna()

    if len(returns) < min_obs:
        return RiskResult(None, None, None, None, None)

    arr = returns.values.astype(float)

    # Rolling volatility (annualised)
    vol_30d: float | None = None
    vol_60d: float | None = None
    if len(arr) >= 30:
        vol_30d = float(np.std(arr[-30:], ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR))
    if len(arr) >= 60:
        vol_60d = float(np.std(arr[-60:], ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR))
    if vol_60d is None and len(arr) >= min_obs:
        vol_60d = float(np.std(arr, ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR))

    # Historical VaR (95%) — negative 5th percentile expressed as positive loss
    var_95: float | None = None
    es_95: float | None = None
    if len(arr) >= min_obs:
        sorted_returns = np.sort(arr)
        cutoff_idx = int(math.floor(len(sorted_returns) * 0.05))
        cutoff_idx = max(1, cutoff_idx)
        var_95_raw = float(sorted_returns[cutoff_idx - 1])
        var_95 = -var_95_raw  # convert to positive loss measure

        tail = sorted_returns[:cutoff_idx]
        es_95_raw = float(np.mean(tail)) if len(tail) > 0 else var_95_raw
        es_95 = -es_95_raw

    # Maximum drawdown from cumulative return series
    max_dd: float | None = None
    if len(arr) >= min_obs:
        cum = (1 + returns).cumprod()
        rolling_max = cum.cummax()
        drawdown = (cum - rolling_max) / rolling_max
        max_dd = float(abs(drawdown.min()))

    return RiskResult(
        vol_30d=vol_30d,
        vol_60d=vol_60d,
        var_95_1d=max(0.0, var_95) if var_95 is not None else None,
        es_95=max(0.0, es_95) if es_95 is not None else None,
        max_drawdown=max_dd,
    )
