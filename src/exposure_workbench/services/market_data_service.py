"""Market data service — fetch market and factor prices from the database."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import MarketPrice, FactorPrice


async def get_prices_df(
    db: AsyncSession,
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Return a DataFrame of close prices for the given tickers and date range.
    Columns: ticker, price_date, close
    """
    result = await db.execute(
        select(MarketPrice)
        .where(
            MarketPrice.ticker.in_(tickers),
            MarketPrice.price_date >= start_date,
            MarketPrice.price_date <= end_date,
        )
        .order_by(MarketPrice.price_date)
    )
    rows = result.scalars().all()
    if not rows:
        return pd.DataFrame(columns=["ticker", "price_date", "close"])

    return pd.DataFrame([
        {
            "ticker": r.ticker,
            "price_date": pd.Timestamp(r.price_date),
            "close": float(r.close),
        }
        for r in rows
    ])


async def get_factor_prices_df(
    db: AsyncSession,
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Return a DataFrame of factor close prices for the given tickers.
    Columns: ticker, price_date, close, daily_return
    """
    result = await db.execute(
        select(FactorPrice)
        .where(
            FactorPrice.ticker.in_(tickers),
            FactorPrice.price_date >= start_date,
            FactorPrice.price_date <= end_date,
        )
        .order_by(FactorPrice.price_date)
    )
    rows = result.scalars().all()
    if not rows:
        return pd.DataFrame(columns=["ticker", "price_date", "close", "daily_return"])

    return pd.DataFrame([
        {
            "ticker": r.ticker,
            "price_date": pd.Timestamp(r.price_date),
            "close": float(r.close),
            "daily_return": float(r.daily_return) if r.daily_return is not None else None,
        }
        for r in rows
    ])


def build_portfolio_returns(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> pd.Series:
    """
    Build a time series of daily portfolio returns from positions and prices.

    positions_df: columns ticker, quantity (snapshot weights are fixed)
    prices_df: columns ticker, price_date, close
    Returns: pd.Series indexed by date, values = daily portfolio return
    """
    if prices_df.empty or positions_df.empty:
        return pd.Series(dtype=float)

    # Pivot prices to wide format: date × ticker
    pivot = prices_df.pivot(index="price_date", columns="ticker", values="close").sort_index()
    pivot = pivot.ffill().dropna()

    if pivot.empty:
        return pd.Series(dtype=float)

    # Get tickers that exist in both positions and prices
    tickers = [t for t in positions_df["ticker"].tolist() if t in pivot.columns]
    if not tickers:
        return pd.Series(dtype=float)

    # Build quantity weights using latest prices (approximation for historical returns)
    last_prices = pivot[tickers].iloc[-1]
    quantities = positions_df.set_index("ticker")["quantity"].reindex(tickers).fillna(0)
    position_mv = quantities * last_prices
    total_mv = position_mv.sum()
    if total_mv <= 0:
        return pd.Series(dtype=float)
    weights = position_mv / total_mv

    # Compute daily price returns for each ticker
    ticker_returns = pivot[tickers].pct_change().dropna()

    # Portfolio return = weighted sum
    portfolio_returns = (ticker_returns * weights).sum(axis=1)
    return portfolio_returns


def build_factor_returns_df(factor_prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot factor prices into a date-indexed DataFrame of daily returns.
    Each column is a factor ticker.
    """
    if factor_prices_df.empty:
        return pd.DataFrame()

    pivot = factor_prices_df.pivot(index="price_date", columns="ticker", values="close").sort_index()
    returns = pivot.pct_change().dropna()
    return returns
