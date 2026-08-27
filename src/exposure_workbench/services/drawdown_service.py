"""V8-D2 — drawdown episodes for a real book, and what an episode is made of.

`build_portfolio_returns` already produces the series these read; the exposure
workflow computes it, hands it to the regression and to the risk metrics, and
drops it. So the episodes have always been derivable and never derived.

`explain_episode` returns three things about the window between a peak and a
trough: the book's cumulative return over it, the benchmark's over the same
window, and each holding's contribution to it. All three are quantities about a
FIXED WINDOW. None of them is a decomposition of the drawdown's depth, which
does not exist (see analytics/drawdown), and the payload says so in a field
rather than a footnote — `fixed_window_caveat` is always present, because a
caveat that appears only when someone remembers it is a caveat that is absent
when it matters.

What this deliberately does not return is a per-day factor contribution summed
across the window. Betas are estimated on a rolling window, so a factor's daily
contribution is measured against a different model on each day, and adding them
is arithmetic across incompatible fits. The shape is not offered rather than
refused: there is no field to ask for.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import drawdown as dd
from exposure_workbench.db.models import FactorPrice, Portfolio, Position
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import market_data_service
from exposure_workbench.tools.registry import current_session_id

# Spans a caller may ask for, as sessions of history to load. Named rather than
# free-form: an arbitrary day count invites "last 37 days", which is a window
# chosen after seeing the answer.
_SPANS = {"3m": 92, "6m": 183, "1y": 366, "3y": 1096}
_DEFAULT_SPAN = "1y"
_BENCHMARK_FALLBACK = "SPY"


async def _benchmark_series(db: AsyncSession, ticker: str, start: date, end: date):
    """The benchmark's prices, from the store that tracks this ticker.

    Prices live in two tables. `market_prices` is filled by holdings — a ticker
    enters it when somebody's portfolio contains it, and gets whatever history
    that upload backfilled. `factor_prices` is filled by the factor sync, which
    maintains full history because the regression needs it. The same ticker can
    be in both, and for SPY on this deployment the difference is decisive:
    277 sessions from 2025-06-18 in the holdings store against 825 from
    2023-05-08 in the factor store. Asking the holdings store for SPY's return
    across a drawdown in early 2025 returns nothing at all.

    So the store is chosen by what the ticker IS to this desk, not by what
    happens to be present: a ticker with rows in `factor_prices` is one of the
    desk's factors, because that table is populated by the factor sync for
    exactly the configured set. That question is answered from the database and
    not from factor_config.yaml on purpose — the api container has no
    /app/configs mount, so a tool reading YAML returns the full answer in the
    mcp container and an empty one in the api container, which is V2-H4's bug
    exactly.

    The underlying flaw is that two tables hold one kind of fact and every
    consumer has to know which. Measured while writing this: they agree exactly
    on `close` across all 1,927 overlapping rows, and differ on `adj_close` for
    38 SPY rows by at most 2e-4 — two ingests of one series rounding at the
    fourth decimal. Unifying them is a migration and belongs in its own batch;
    what is here is one rule, stated, rather than each caller guessing.
    """
    is_factor = (await db.execute(
        select(FactorPrice.ticker).where(FactorPrice.ticker == ticker).limit(1)
    )).scalar_one_or_none() is not None
    if not is_factor:
        return None, "market_prices"
    rows = (await db.execute(
        select(FactorPrice.price_date, FactorPrice.adj_close, FactorPrice.close)
        .where(FactorPrice.ticker == ticker,
               FactorPrice.price_date >= start, FactorPrice.price_date <= end)
        .order_by(FactorPrice.price_date))).all()
    from exposure_workbench.analytics import series_ops as so
    return [so.PricePoint(d, float(a if a is not None else c)) for d, a, c in rows], "factor_prices"


async def _book(db: AsyncSession, portfolio_id: str):
    pf = (await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id))).scalar_one_or_none()
    if pf is None:
        return None, None
    rows = list((await db.execute(
        select(Position).where(Position.portfolio_id == portfolio_id))).scalars().all())
    return pf, rows


async def _returns(db: AsyncSession, positions, start: date, end: date) -> pd.Series:
    positions_df = pd.DataFrame([
        {"ticker": p.ticker, "quantity": float(p.quantity)}
        for p in positions if p.quantity is not None
    ])
    if positions_df.empty:
        return pd.Series(dtype=float)
    prices_df = await market_data_service.get_prices_df(
        db, positions_df["ticker"].tolist(), start, end)
    return market_data_service.build_portfolio_returns(positions_df, prices_df)


async def get_drawdown_episodes(db: AsyncSession, portfolio_id: str,
                                span: str = _DEFAULT_SPAN) -> dict:
    """Every episode at least 5% deep in the span, deepest first."""
    if span not in _SPANS:
        return {"error": "unknown_span", "span": span, "known": sorted(_SPANS)}
    pf, positions = await _book(db, portfolio_id)
    if pf is None:
        return {"error": "unknown_portfolio", "portfolio_id": portfolio_id}
    if not positions:
        return {"error": "no_positions", "portfolio_id": portfolio_id}

    end = await market_data_service.latest_session_date(db)
    if end is None:
        return {"error": "no_price_data", "portfolio_id": portfolio_id}
    start = end - timedelta(days=_SPANS[span])

    returns = await _returns(db, positions, start, end)
    if len(returns) < 2:
        return {"error": "insufficient_history", "portfolio_id": portfolio_id,
                "span": span, "sessions": int(len(returns))}

    episodes = dd.find_episodes(returns)
    deepest = dd.deepest(returns)
    # The depths need an id, or nothing can support them. Before this the tool
    # returned numbers a citation could not reach — the same gap V8-A closed for
    # the run's children, one layer out.
    calc_id = await cs._record(
        db, None, "portfolio.drawdown_episodes",
        {"portfolio_id": portfolio_id, "span": span, "sessions": int(len(returns)),
         "floor": 0.05},
        {"deepest_depth": None if deepest is None else deepest.depth,
         "episode_depths": [e.depth for e in episodes]},
        [portfolio_id], {"episodes": len(episodes)}, current_session_id(),
    )
    return {
        "calc_id": calc_id,
        "portfolio_id": portfolio_id,
        "span": span,
        "window": {"from": str(returns.index[0].date()), "to": str(returns.index[-1].date())},
        "sessions": int(len(returns)),
        "episodes": [
            {"peak_date": e.peak_date.isoformat(), "trough_date": e.trough_date.isoformat(),
             "depth": e.depth, "recovery_date": e.recovery_date.isoformat() if e.recovery_date else None,
             "trough_days": e.trough_days, "recovery_days": e.recovery_days,
             "recovered": e.recovery_date is not None}
            for e in episodes
        ],
        "deepest": None if deepest is None else {
            "peak_date": deepest.peak_date.isoformat(),
            "trough_date": deepest.trough_date.isoformat(),
            "depth": deepest.depth,
            "recovered": deepest.recovery_date is not None,
        },
        "reported_floor": 0.05,
        "valuation_assumption": (
            "quantities are held fixed at today's holdings for the whole span — "
            "the book has one position snapshot and no holding history to replay"
        ),
    }


async def explain_episode(db: AsyncSession, portfolio_id: str, peak: str, trough: str) -> dict:
    """What happened between two dates: the book, the benchmark, each holding.

    Every figure is a cumulative return over the FIXED window [peak, trough].
    None of them decomposes the drawdown's depth — that quantity is not additive
    and no set of per-name numbers sums to it.
    """
    try:
        start, end = date.fromisoformat(peak), date.fromisoformat(trough)
    except ValueError:
        return {"error": "invalid_date", "detail": "peak and trough are YYYY-MM-DD"}
    if end <= start:
        return {"error": "invalid_window", "detail": "trough must be after peak"}

    pf, positions = await _book(db, portfolio_id)
    if pf is None:
        return {"error": "unknown_portfolio", "portfolio_id": portfolio_id}
    if not positions:
        return {"error": "no_positions", "portfolio_id": portfolio_id}

    returns = await _returns(db, positions, start, end)
    if len(returns) < 2:
        return {"error": "insufficient_history", "portfolio_id": portfolio_id,
                "window": {"from": peak, "to": trough}, "sessions": int(len(returns))}

    book_return = float((1.0 + returns).prod() - 1.0)

    benchmark = pf.benchmark or _BENCHMARK_FALLBACK
    factor_points, store = await _benchmark_series(db, benchmark, start, end)
    if factor_points is None:
        bench = await cs.window_return(db, benchmark, start, end,
                                       invoked_by=current_session_id())
    else:
        from exposure_workbench.analytics import series_ops as so
        res = so.compute_window_return(factor_points, start, end)
        bench = {"value": res.value, "quality_flags": res.quality_flags,
                 "calc_id": await cs._record(
                     db, benchmark, res.operation,
                     {"ticker": benchmark, "start": peak, "end": trough, "store": store},
                     {"value": res.value}, [f"price:{benchmark}:{peak}:{trough}"],
                     res.quality_flags, current_session_id())}

    holdings = []
    for p in positions:
        if p.quantity is None:
            continue
        one = await cs.window_return(db, p.ticker, start, end,
                                     invoked_by=current_session_id())
        holdings.append({"ticker": p.ticker, "window_return": one.get("value"),
                         "calc_id": one.get("calc_id")})

    calc_id = await cs._record(
        db, None, "portfolio.window_return",
        {"portfolio_id": portfolio_id, "start": peak, "end": trough,
         "sessions": int(len(returns))},
        {"value": book_return}, [portfolio_id], {}, current_session_id(),
    )

    return {
        "portfolio_id": portfolio_id,
        "window": {"from": str(returns.index[0].date()), "to": str(returns.index[-1].date())},
        "sessions": int(len(returns)),
        "portfolio_window_return": book_return,
        "calc_id": calc_id,
        "benchmark": {
            "ticker": benchmark, "window_return": bench.get("value"),
            "calc_id": bench.get("calc_id"), "price_store": store,
            # Unavailable with a reason, never a bare null: a benchmark whose
            # series does not cover the window is a fact about coverage, and a
            # reader seeing only `null` cannot tell it from a broken lookup.
            "unavailable_reason": (None if bench.get("value") is not None else
                                   f"{benchmark} has no price on or before one bound of this "
                                   f"window in {store}"),
        },
        "holdings": holdings,
        # Always present. A caveat that appears only when someone remembers it is
        # a caveat that is absent exactly when it matters.
        "fixed_window_caveat": (
            "these are cumulative returns over the fixed window between the two dates. "
            "They do not decompose the drawdown's DEPTH: depth depends on the order of "
            "the returns and on endpoints the data chose, so it is not additive and no "
            "set of per-holding numbers sums to it. Quantities are held fixed at today's "
            "holdings throughout."
        ),
    }
