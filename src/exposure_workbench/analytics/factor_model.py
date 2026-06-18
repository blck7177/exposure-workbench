"""Factor model — rolling OLS regression for portfolio return attribution."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class FactorResult:
    factor_name: str
    factor_ticker: str
    beta: float
    factor_return: float   # most recent day factor return
    contribution: float    # beta × factor_return (1-day attribution)
    r_squared: float       # R² of the regression


@dataclass
class FactorAttributionResult:
    factors: list[FactorResult] = field(default_factory=list)
    total_explained: float = 0.0   # sum of factor contributions
    residual: float = 0.0          # portfolio_return - total_explained
    r_squared: float = 0.0         # overall model R²


def calc_factor_attribution(
    portfolio_returns: pd.Series,
    factor_returns: pd.DataFrame,
    factor_config: dict,
    lookback: int = 60,
) -> FactorAttributionResult:
    """
    Estimate factor betas via OLS using the last `lookback` observations.

    portfolio_returns: pd.Series indexed by date, values = daily returns
    factor_returns: pd.DataFrame indexed by date, columns = factor_ticker
    factor_config: dict from factor_config.yaml, factors key
    lookback: number of trading days to use for regression
    """
    if portfolio_returns.empty or factor_returns.empty:
        return FactorAttributionResult()

    # Align and trim to lookback
    combined = pd.concat(
        [portfolio_returns.rename("portfolio"), factor_returns],
        axis=1,
        join="inner",
    ).dropna()

    if len(combined) < max(10, lookback // 3):
        return FactorAttributionResult()

    combined = combined.tail(lookback)

    y = combined["portfolio"].values
    factor_cols = [c for c in combined.columns if c != "portfolio"]

    results: list[FactorResult] = []
    explained_return = 0.0

    # Most recent day return for each factor (for 1-day attribution)
    latest_factor_returns: dict[str, float] = {}
    for col in factor_cols:
        last = combined[col].iloc[-1]
        latest_factor_returns[col] = float(last) if not np.isnan(last) else 0.0

    # Latest portfolio return
    latest_port_return = float(y[-1]) if len(y) > 0 else 0.0

    for factor_ticker in factor_cols:
        x = combined[factor_ticker].values

        if np.std(x) < 1e-10:
            beta, r2 = 0.0, 0.0
        else:
            # OLS: y = alpha + beta * x  (use polyfit for simplicity)
            coeffs = np.polyfit(x, y, 1)
            beta = float(coeffs[0])

            # R² for this single factor
            y_pred = coeffs[0] * x + coeffs[1]
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        factor_return_today = latest_factor_returns.get(factor_ticker, 0.0)
        contribution = beta * factor_return_today

        # Map ticker to factor name from config
        factor_name = factor_ticker
        for name, cfg in factor_config.get("factors", {}).items():
            if cfg.get("ticker") == factor_ticker:
                factor_name = name
                break

        results.append(FactorResult(
            factor_name=factor_name,
            factor_ticker=factor_ticker,
            beta=beta,
            factor_return=factor_return_today,
            contribution=contribution,
            r_squared=max(0.0, r2),
        ))
        explained_return += contribution

    # Sort by abs contribution descending
    results.sort(key=lambda r: abs(r.contribution), reverse=True)

    # Overall R² using multi-factor OLS
    overall_r2 = 0.0
    if len(factor_cols) > 0:
        X = np.column_stack([combined[c].values for c in factor_cols])
        X_with_intercept = np.column_stack([np.ones(len(X)), X])
        try:
            coeffs_multi, _, _, _ = np.linalg.lstsq(X_with_intercept, y, rcond=None)
            y_pred_multi = X_with_intercept @ coeffs_multi
            ss_res_m = np.sum((y - y_pred_multi) ** 2)
            ss_tot_m = np.sum((y - np.mean(y)) ** 2)
            overall_r2 = float(1.0 - ss_res_m / ss_tot_m) if ss_tot_m > 0 else 0.0
        except Exception:
            overall_r2 = 0.0

    return FactorAttributionResult(
        factors=results,
        total_explained=explained_return,
        residual=latest_port_return - explained_return,
        r_squared=max(0.0, min(1.0, overall_r2)),
    )
