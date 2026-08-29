"""Market data service — fetch market and factor prices from the database."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import MarketPrice, FactorPrice


async def latest_session_date(db: AsyncSession) -> date | None:
    """The newest session we actually hold prices for, or None if we hold none.

    This is what "daily" means for a report: the last completed trading session,
    not the wall-clock date. Asking for today before today has closed produces a
    run whose two comparison prices are the same bar — measured on the live
    system, a $10.4M book reporting daily P&L of exactly 0.00, which reads as a
    calm day rather than as absent data.
    """
    return (await db.execute(select(func.max(MarketPrice.price_date)))).scalar_one_or_none()


async def get_prices_df(
    db: AsyncSession,
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Return a DataFrame of prices for the given tickers and date range.
    Columns: ticker, price_date, close, adj_close

    BOTH price columns travel together, and each consumer names the one it means.
    They answer different questions and the system needs both:

      close      — what the position is worth. Market value, gross/net exposure,
                   concentration. As-traded, ties to a statement.
      adj_close  — what the position RETURNED. Volatility, VaR, ES, drawdown,
                   betas, P&L. Split- and dividend-adjusted.

    Returning only `close` was not a simplification, it was a silent choice of
    convention for every consumer at once — and the wrong one for all the return
    consumers. A 4:1 split is a −75% close-to-close move; fed to a 60-observation
    VaR it becomes the tail. The calc ledger had already chosen adj_close for its
    own price series (calc_service.load_price_series), so the two halves of one
    system were measuring different returns for the same stock.
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
        return pd.DataFrame(columns=["ticker", "price_date", "close", "adj_close"])

    return pd.DataFrame([
        {
            "ticker": r.ticker,
            "price_date": pd.Timestamp(r.price_date),
            "close": float(r.close),
            "adj_close": float(r.adj_close) if r.adj_close is not None else float("nan"),
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
    Return a DataFrame of factor prices for the given tickers.
    Columns: ticker, price_date, close, adj_close, daily_return

    Same two-column convention as get_prices_df, for the same reason. It matters
    more here than it looks: two of the eight factors are TLT and HYG, which
    distribute several percent a year. On close alone their measured returns are
    short by exactly those distributions, so every beta estimated against them is
    biased — and the portfolio side is now on a total-return basis, which would
    make the regression a comparison between two different definitions of return.
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
        return pd.DataFrame(
            columns=["ticker", "price_date", "close", "adj_close", "daily_return"]
        )

    return pd.DataFrame([
        {
            "ticker": r.ticker,
            "price_date": pd.Timestamp(r.price_date),
            "close": float(r.close),
            "adj_close": float(r.adj_close) if r.adj_close is not None else float("nan"),
            "daily_return": float(r.daily_return) if r.daily_return is not None else None,
        }
        for r in rows
    ])


# A return is a ONE-day return or it is not usable. Weekends span 3 calendar
# days and a holiday-extended weekend 4, so anything past 5 is a hole in the
# panel, not a market closure pattern.
_MAX_RETURN_SPAN_DAYS = 5


def total_return_panel(prices_df: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """date × ticker adjusted closes, for exactly `tickers`, no fabricated cells.

    Every return series in the system is built from this one function, so
    "which price, and what happens to a missing bar" has a single answer.

    A missing bar leaves a hole and the whole date is dropped, because a
    portfolio return needs every leg priced on the same day. What it must NEVER
    do is carry the previous close forward: ffill() does not fill a gap, it
    manufactures a day on which the stock did not move. Those synthetic zeros
    are indistinguishable from real flat days to every estimator downstream, and
    they all read the same way — variance computed over a sample padded with
    zeros is biased down, so a book with a patchy price feed reports itself
    calmer than it is, and reports it through VaR into the limit checks.
    """
    if "adj_close" not in prices_df.columns:
        raise ValueError(
            "price frame has no adj_close column — returns are measured on the "
            "adjusted series and there is no second convention to fall back to"
        )

    panel = (
        prices_df.pivot(index="price_date", columns="ticker", values="adj_close")
        .sort_index()
    )
    panel.columns = [str(c) for c in panel.columns]

    absent = sorted(set(tickers) - set(panel.columns))
    if absent:
        raise ValueError(
            "Cannot build a return series without every holding: "
            f"no usable price history for {', '.join(absent)}"
        )

    panel = panel[list(tickers)]
    unadjusted = sorted(t for t in tickers if panel[t].isna().all())
    if unadjusted:
        # Distinct from "absent": the bars are there, they just predate the
        # provider writing adj_close. Silently reading `close` instead would put
        # the unadjusted convention back, on exactly the rows most likely to be
        # old enough to contain a split.
        raise ValueError(
            f"No adjusted close for {', '.join(unadjusted)} — re-ingest market "
            "prices before measuring returns"
        )
    return panel.dropna()


def build_portfolio_returns(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> pd.Series:
    """
    Daily total return of the book, valued at fixed quantities.

    positions_df: columns ticker, quantity
    prices_df: columns ticker, price_date, close, adj_close
    Returns: pd.Series indexed by date, values = daily portfolio return

    The book is revalued each day and the return is the change in its value.
    That is equivalent to weighting each name's return by its share of YESTERDAY's
    value, which is the only weighting a return series can honestly use.

    What it replaces: weights computed from the LAST close in the window and then
    applied to every day of it. Those weights are unknowable on any day but the
    last one, so the series described a book assembled with hindsight — the
    winners were held in the proportion they grew INTO, not the proportion they
    were held at. The bias is systematic and one-directional: it overweights
    whatever went up. Measured on the two-name case in the tests, a book that
    genuinely returned 0.0% reported +1.0%.

    Fixed quantities remain an assumption — `positions` holds one snapshot per
    portfolio, so there is no holding history to replay and no way to know the
    book was ever different. That assumption is stated, not hidden, and it is the
    same one calc_pnl makes. The look-ahead was neither.
    """
    if prices_df.empty or positions_df.empty:
        return pd.Series(dtype=float)

    held = [str(t) for t in positions_df["ticker"].tolist()]
    if not held:
        return pd.Series(dtype=float)

    panel = total_return_panel(prices_df, held)
    if len(panel) < 2:
        return pd.Series(dtype=float)

    quantities = positions_df.set_index("ticker")["quantity"].reindex(held).astype(float)
    if quantities.isna().any():
        missing = ", ".join(sorted(quantities[quantities.isna()].index.astype(str)))
        raise ValueError(f"Holdings with no quantity: {missing}")

    book_value = panel.mul(quantities.values, axis=1).sum(axis=1)
    if (book_value <= 0).any():
        # pct_change across a zero or a sign flip produces a number with no
        # meaning as a return, and it would flow straight into VaR.
        raise ValueError(
            "Portfolio value is zero or negative on at least one day in the "
            "window — a return series cannot be built from it"
        )

    returns = book_value.pct_change()
    span = book_value.index.to_series().diff().dt.days
    # A return over a gap is a multi-day move wearing a one-day label: it
    # enlarges the tail of a VaR whose every other observation is one day long.
    return returns[span <= _MAX_RETURN_SPAN_DAYS].dropna()


def build_portfolio_values(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
) -> pd.Series:
    """The book's value each day, on the SAME panel the return series uses (V13-S5).

    Extracted from build_portfolio_returns rather than written beside it: the
    chart of the book's value and the VaR tile above it are about to be read
    together, and two valuation conventions in one screen is how a page comes to
    disagree with itself. This is the identical panel — adjusted closes, fixed
    quantities, no forward fill — and the returns are literally this series'
    percentage change.

    The fixed-quantity assumption is the one build_portfolio_returns documents at
    length: `positions` holds one snapshot per portfolio, so there is no holding
    history to replay. A chart of it is therefore "today's book at historical
    prices", which is a real and useful thing and is not the book's actual past.
    The endpoint that serves it says so in those words.
    """
    if prices_df.empty or positions_df.empty:
        return pd.Series(dtype=float)
    held = [str(t) for t in positions_df["ticker"].tolist()]
    if not held:
        return pd.Series(dtype=float)
    panel = total_return_panel(prices_df, held)
    if panel.empty:
        return pd.Series(dtype=float)
    quantities = positions_df.set_index("ticker")["quantity"].reindex(held).astype(float)
    if quantities.isna().any():
        missing = ", ".join(sorted(quantities[quantities.isna()].index.astype(str)))
        raise ValueError(f"Holdings with no quantity: {missing}")
    return panel.mul(quantities.values, axis=1).sum(axis=1)


def build_factor_returns_df(factor_prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot factor prices into a date-indexed DataFrame of daily total returns.
    Each column is a factor ticker.

    Same panel rules as the portfolio side — adjusted closes, no ffill, no
    return spanning a gap — because these two series are regressed against each
    other and a difference in convention between them lands entirely in the betas.
    """
    if factor_prices_df.empty:
        return pd.DataFrame()

    tickers = sorted({str(t) for t in factor_prices_df["ticker"].tolist()})
    panel = total_return_panel(factor_prices_df, tickers)
    if len(panel) < 2:
        return pd.DataFrame()

    returns = panel.pct_change()
    span = panel.index.to_series().diff().dt.days
    return returns[span <= _MAX_RETURN_SPAN_DAYS].dropna()


# ── one rule for which store holds a ticker's prices (V10 side item) ─────────

async def price_points(db: AsyncSession, ticker: str, start: date, end: date):
    """A ticker's price series, from the store that tracks it, and which one.

    Prices live in two tables. `market_prices` is filled by holdings — a ticker
    enters it when somebody's portfolio contains it, with whatever history that
    upload backfilled. `factor_prices` is filled by the factor sync, which keeps
    full history because the regression needs it. The same ticker can be in
    both, and for SPY on this deployment the difference decides the answer:
    277 sessions from 2025-06-18 in the holdings store against 825 from
    2023-05-08 in the factor store.

    So the store is chosen by what the ticker IS to this desk — rows in
    `factor_prices` mean the factor sync tracks it — and that is decided from
    the database rather than from factor_config.yaml, because the api container
    has no /app/configs mount and a tool reading YAML there answers with an
    empty set (V2-H4's bug). This function is the only place the rule lives;
    calc_service.window_return and drawdown_service both call it. Before V10
    the rule sat in drawdown_service and window_return read the holdings store
    unconditionally, so get_market_stats on a benchmark returned nothing for
    any window older than the newest upload.

    Returns (points, store_name). Prefers adj_close, as every consumer here does.
    """
    from exposure_workbench.analytics import series_ops as so
    is_factor = (await db.execute(
        select(FactorPrice.ticker).where(FactorPrice.ticker == ticker).limit(1)
    )).scalar_one_or_none() is not None
    model = FactorPrice if is_factor else MarketPrice
    rows = (await db.execute(
        select(model.price_date, model.adj_close, model.close)
        .where(model.ticker == ticker, model.price_date >= start, model.price_date <= end)
        .order_by(model.price_date))).all()
    return ([so.PricePoint(d, float(a if a is not None else c)) for d, a, c in rows],
            model.__tablename__)
