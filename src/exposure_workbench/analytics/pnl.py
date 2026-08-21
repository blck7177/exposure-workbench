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


def _last_bar(prices_df: pd.DataFrame, ticker: str, on_or_before: pd.Timestamp):
    """(close, adj_close, bar_date) of the newest bar at or before a date.

    (None, None, None) when there is no such bar.

    The date comes back with the price because a daily move needs two DIFFERENT
    bars. Returning only the number made it impossible to tell "flat day" from
    "both lookups landed on the same bar", and those are not the same fact.

    Both prices come back because this function feeds two different questions:
    what the position is worth (close) and what it returned (adj_close).
    """
    sub = prices_df[(prices_df["ticker"] == ticker) & (prices_df["price_date"] <= on_or_before)]
    if sub.empty:
        return None, None, None
    last = sub.sort_values("price_date").iloc[-1]
    adj = last["adj_close"] if "adj_close" in sub.columns else None
    adj = float(adj) if adj is not None and adj == adj else None   # NaN -> None
    return float(last["close"]), adj, last["price_date"]


def calc_pnl(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    as_of_date: date,
) -> PnlResult:
    """
    Compute daily P&L for the portfolio.

    positions_df columns: ticker, quantity, sector [, market_value]
    prices_df columns: ticker, price_date, close, adj_close

    Market value is as-traded (close); the daily move is the adjusted return
    applied to yesterday's market value. The two prices answer two questions and
    mixing them up produces a specific, large error: on the day a stock splits
    4:1 the close falls 75% while nothing has happened to the holder, and a
    close-to-close P&L reports the book losing three quarters of that position.
    Dividends are the same error one order of magnitude smaller and far more
    often — every ex-date became a loss.

    What this does NOT fix: `positions.quantity` is a snapshot and is not
    split-adjusted either, so on a split day the market value is still computed
    from a pre-split share count. That is a holdings-data problem, not a price
    one, and it is named in docs/IMPLEMENTATION_PLAN_V5.md rather than papered
    over here.
    """
    as_of = pd.Timestamp(as_of_date)
    prev_date = as_of - pd.tseries.offsets.BDay(1)  # previous business day

    pos_pnl_list: list[PositionPnl] = []
    stale_tickers: list[str] = []
    total_pnl = 0.0

    # We need yesterday's MV to compute portfolio daily return properly
    prev_portfolio_mv = 0.0
    curr_portfolio_mv = 0.0

    for _, row in positions_df.iterrows():
        ticker = str(row["ticker"])
        qty = float(row["quantity"])
        sector = str(row.get("sector", "Unknown") or "Unknown")

        curr_price, curr_adj, curr_bar = _last_bar(prices_df, ticker, as_of)
        prev_price, prev_adj, prev_bar = _last_bar(prices_df, ticker, prev_date)

        if curr_price is None:
            # No fallback to the position's stored price or cost basis. That
            # fallback is why a single run could report a market value computed
            # one way and a daily return computed from a different, larger
            # denominator — the same portfolio priced in two universes. The
            # workflow's validate_inputs step now guarantees a current price
            # exists, so reaching here means a caller skipped it.
            raise ValueError(f"calc_pnl called with no price for {ticker} as of {as_of_date}")

        if curr_adj is None or (prev_price is not None and prev_adj is None):
            raise ValueError(
                f"calc_pnl called with no adjusted close for {ticker} as of "
                f"{as_of_date} — re-ingest market prices"
            )

        if prev_price is None:
            # Genuinely fine: nothing existed before this bar, e.g. a listing
            # younger than the comparison window. No prior close, no move.
            prev_price = curr_price
            prev_adj = curr_adj
        elif prev_bar == curr_bar:
            # Both lookups landed on the SAME bar, so there is no move to
            # measure — most often because as_of is today and today has not
            # closed yet. Counted, not silently reported as a flat day.
            stale_tickers.append(ticker)

        curr_mv = qty * curr_price
        prev_mv = qty * prev_price

        # The move is measured on the adjusted series and then applied to what
        # the position was actually worth yesterday. curr_mv - prev_mv would be
        # the close-to-close difference again, split and dividend included.
        ticker_return = (curr_adj / prev_adj - 1) if prev_adj > 0 else 0.0
        pnl = prev_mv * ticker_return
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

    # If EVERY holding priced off the same bar twice, there is no trading day
    # between the two sides of this comparison, and the "daily" figures would all
    # be exactly zero — a whole book reported as perfectly flat, which reads as a
    # calm day rather than as missing data. Measured on the live system before
    # this check existed: a run dated today, with the newest bar from yesterday,
    # reported daily_pnl 0.00 and daily_return 0.00000000 for a $10.4M portfolio.
    #
    # A subset being stale is left alone: one name that did not trade among many
    # that did is a real, measurable flat position.
    if stale_tickers and len(stale_tickers) == len(pos_pnl_list):
        raise ValueError(
            f"No daily move to report as of {as_of_date}: every holding's latest "
            f"price and its comparison price are the same bar, so no trading day "
            f"separates them. Run against the most recent completed session "
            f"instead — the newest available data predates {as_of_date}."
        )

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
