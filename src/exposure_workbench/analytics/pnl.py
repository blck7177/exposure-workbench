"""P&L calculation — daily portfolio return and per-position contribution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd


@dataclass
class PositionPnl:
    ticker: str
    sector: str
    daily_pnl: float
    daily_return: float      # price return for this ticker
    contribution: float      # contribution to portfolio return (weight × ticker_return)
    prev_price: float | None
    curr_price: float | None


@dataclass
class PnlResult:
    daily_pnl: float
    daily_return: float
    position_pnl: list[PositionPnl] = field(default_factory=list)
    top_contributors: list[PositionPnl] = field(default_factory=list)
    top_detractors: list[PositionPnl] = field(default_factory=list)


def _last_price(prices_df: pd.DataFrame, ticker: str, on_or_before: pd.Timestamp) -> float | None:
    sub = prices_df[(prices_df["ticker"] == ticker) & (prices_df["price_date"] <= on_or_before)]
    if sub.empty:
        return None
    return float(sub.sort_values("price_date").iloc[-1]["close"])


def calc_pnl(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    as_of_date: date,
) -> PnlResult:
    """
    Compute daily P&L for the portfolio.

    positions_df columns: ticker, quantity, sector [, market_value]
    prices_df columns: ticker, price_date, close
    """
    as_of = pd.Timestamp(as_of_date)
    prev_date = as_of - pd.tseries.offsets.BDay(1)  # previous business day

    pos_pnl_list: list[PositionPnl] = []
    total_pnl = 0.0

    # We need yesterday's MV to compute portfolio daily return properly
    prev_portfolio_mv = 0.0
    curr_portfolio_mv = 0.0

    for _, row in positions_df.iterrows():
        ticker = str(row["ticker"])
        qty = float(row["quantity"])
        sector = str(row.get("sector", "Unknown") or "Unknown")

        curr_price = _last_price(prices_df, ticker, as_of)
        prev_price = _last_price(prices_df, ticker, prev_date)

        if curr_price is None:
            curr_price = float(row.get("price", 0) or row.get("cost_basis", 0) or 0)
        if prev_price is None:
            prev_price = curr_price  # no change if no history

        curr_mv = qty * curr_price
        prev_mv = qty * prev_price
        pnl = curr_mv - prev_mv

        ticker_return = (curr_price / prev_price - 1) if prev_price > 0 else 0.0
        total_pnl += pnl
        curr_portfolio_mv += curr_mv
        prev_portfolio_mv += prev_mv

        pos_pnl_list.append(PositionPnl(
            ticker=ticker,
            sector=sector,
            daily_pnl=pnl,
            daily_return=ticker_return,
            contribution=0.0,  # filled below after total MV is known
            prev_price=prev_price,
            curr_price=curr_price,
        ))

    # Compute contribution = position_weight_yesterday × ticker_return
    for p in pos_pnl_list:
        prev_mv_pos = p.prev_price * positions_df.loc[
            positions_df["ticker"] == p.ticker, "quantity"
        ].iloc[0] if p.prev_price else 0.0
        p.contribution = (prev_mv_pos / prev_portfolio_mv) * p.daily_return if prev_portfolio_mv > 0 else 0.0

    portfolio_return = total_pnl / prev_portfolio_mv if prev_portfolio_mv > 0 else 0.0

    sorted_by_contribution = sorted(pos_pnl_list, key=lambda x: x.contribution, reverse=True)
    top_contributors = sorted_by_contribution[:3]
    top_detractors = sorted(pos_pnl_list, key=lambda x: x.contribution)[:3]

    return PnlResult(
        daily_pnl=total_pnl,
        daily_return=portfolio_return,
        position_pnl=pos_pnl_list,
        top_contributors=top_contributors,
        top_detractors=top_detractors,
    )
