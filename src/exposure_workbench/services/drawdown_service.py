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
from exposure_workbench.db.models import Portfolio, Position
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
    """The benchmark's prices from the store that tracks it — the rule is
    market_data_service.price_points, which was written here first (V8-D) and
    moved there when window_return turned out to need the same rule."""
    from exposure_workbench.services import market_data_service as mds
    return await mds.price_points(db, ticker, start, end)


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
    # One path: window_return reads through the same store rule now.
    _points, store = await _benchmark_series(db, benchmark, start, end)
    bench = await cs.window_return(db, benchmark, start, end, invoked_by=current_session_id())

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
