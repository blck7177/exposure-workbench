"""Price analytics (V16 Lane C) — single-name quantities from daily bars.

Two design rules govern every function here.

CLOSE AND ADJ_CLOSE ARE TWO QUANTITIES. `close` is what the position is worth
— as-traded, ties to a statement; `adj_close` is what the position RETURNED —
split- and dividend-adjusted (market_data_service.get_prices_df says why at
length). Each carries its own name (`{ticker}.close`, `{ticker}.adj_close`),
market value and display read the first, every return-derived estimator here
reads the second, and neither ever stands in for the other: a bar whose
adj_close is absent yields no return, not an unadjusted one.

AN UNCERTAIN QUANTITY DOES NOT REACH THE TABLE (M3). Every estimator carries
the number of observations it rests on, and each producer declares its own
minimum below which the estimate is not minted — the constants below, which are
PRODUCER parameters (what this estimator needs to mean anything), not gate
thresholds (what a reader is allowed to see). Too few observations produces a
loud, citable refusal through absence_service — an absence row with the
parameter's name and both numbers (needs / have) — and NEVER a silently
shortened window: a 30-day vol computed over the 25 returns we happen to hold
is a different quantity wearing the requested one's name.

Return convention, stated once: SIMPLE daily total returns from adj_close
(r = P_t/P_{t-1} − 1). Simple returns are the cross-sectionally additive
convention the desk's portfolio side already uses, and beta against a
benchmark must be estimated on the same definition of return on both sides
(research_scratch/C-price-analytics.md §1). A return spanning a data gap of
more than `_MAX_RETURN_SPAN_DAYS` calendar days is dropped and counted — the
same rule market_data_service applies, for the same reason: a multi-day move
wearing a one-day label enlarges every tail downstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import units as u
from exposure_workbench.analytics.units import POINT_PERIOD_KEY
from exposure_workbench.db.models import CalcLedger, FactorPrice, MarketPrice
from exposure_workbench.services import absence_service as ab
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services.market_data_service import _MAX_RETURN_SPAN_DAYS

# 252 trading sessions per year is the convention for daily data; using 365
# overstates annualised vol by ~20% (C-price-analytics.md §4).
TRADING_DAYS_PER_YEAR = 252

# ── minimum observations — PRODUCER parameters, not gate thresholds ──────────
#
# Each constant is what its estimator needs before the number means anything,
# with the desk convention it comes from. Sources: the C-lane research notes,
# /home/ubuntu/dev_note/portfolio-demo/analyst-skills/research_scratch/
# C-price-analytics.md (sections cited per constant).
#
# VOL_MIN_OBS = 20: the shortest window desks quote at all is ~1 month of
#   sessions (21d in §11's convention table; risk_metrics.py has used a 20-obs
#   floor since V1). The relative standard error of a vol estimate is ≈1/√(2n)
#   (§11), so n=20 is already ±16% — anything shorter is noise with a label.
VOL_MIN_OBS = 20
# BETA_MIN_OBS = 60: the classic estimation windows are 60 monthly or ~250
#   daily observations; §12's standard-error rule (SE(β) ≈ 1.56/√n for typical
#   R²) gives SE ≈ 0.32 at n=24 ("useless") and ≈ 0.20 at n=60, and states the
#   practical floor verbatim: "do not report a beta on fewer than ~60
#   observations".
BETA_MIN_OBS = 60
# ADV_MIN_OBS = 20: n = 20, 30 or 60 are the common desk windows for average
#   daily volume (§8); 20 sessions ≈ 1 month is the shortest of them.
ADV_MIN_OBS = 20
# MOMENTUM_MIN_OBS = 200: 12-1 momentum's formation window is months t−12
#   through t−2 (§5, Ken French's construction — the latest month is SKIPPED
#   because it carries short-term reversal), so the estimator needs close to a
#   year of history; the 52-week-high distance likewise reads a 252-session
#   window (§16). 200 sessions ≈ 9.5 months is the floor below which either
#   quantity would be a fresh listing's few weeks dressed as a year.
MOMENTUM_MIN_OBS = 200

# Trading sessions skipped at the near end of the 12-1 formation window (§5:
# the omitted month carries bid-ask bounce and short-term reversal, which
# contaminate the signal with the opposite sign). 21 sessions ≈ 1 month.
MOMENTUM_SKIP_DAYS = 21
# Nominal formation depth: ~12 months of sessions.
_MOMENTUM_FORMATION_DAYS = 252
_52W_WINDOW_DAYS = 252

# Named spans, the drawdown_service pattern: an arbitrary day count invites
# "last 37 days", a window chosen after seeing the answer.
_WINDOWS = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "3y": 1096}
_DEFAULT_WINDOW = "1y"

OP_PRICE_POINT = "price.point"
OP_PRICE_SERIES = "price.series"
OP_RETURNS_SERIES = "price.returns.series"
OP_VOL = "price.vol"
OP_REGRESS = "price.regress"           # rows are OP_REGRESS + ".beta" / ".alpha" / ".r2"
OP_MOMENTUM = "price.momentum_12_1"
OP_52W = "price.distance_from_52w_high"
OP_ADV = "price.adv"                   # rows are OP_ADV + ".shares" / ".dollars"


@dataclass(frozen=True)
class Bar:
    """One daily bar. `adj_close` is None when the provider has not written it
    — a fact the consumer must face, never paper over with `close`."""
    date: date
    close: float
    adj_close: float | None
    volume: int | None = None


# ── the two fetch seams ──────────────────────────────────────────────────────

async def _bars(db: AsyncSession, ticker: str,
                start: date | None = None, end: date | None = None) -> list[Bar]:
    """A ticker's bars from the store that tracks it — the same rule as
    market_data_service.price_points (factor sync wins), because for SPY the
    two stores disagree by 500+ sessions and the store IS part of the answer.
    The factor store carries no volume; ADV reads `_market_bars` instead."""
    is_factor = (await db.execute(
        select(FactorPrice.ticker).where(FactorPrice.ticker == ticker).limit(1)
    )).scalar_one_or_none() is not None
    model = FactorPrice if is_factor else MarketPrice
    stmt = select(model.price_date, model.close, model.adj_close).where(model.ticker == ticker)
    if start is not None:
        stmt = stmt.where(model.price_date >= start)
    if end is not None:
        stmt = stmt.where(model.price_date <= end)
    rows = (await db.execute(stmt.order_by(model.price_date))).all()
    return [Bar(d, float(c), float(a) if a is not None else None) for d, c, a in rows]


async def _market_bars(db: AsyncSession, ticker: str) -> list[Bar]:
    """Bars with volume, from market_prices only — the one store that records
    it. A ticker the desk tracks only as a factor has no volume history here,
    and ADV says so rather than substituting a store without the column."""
    rows = (await db.execute(
        select(MarketPrice.price_date, MarketPrice.close, MarketPrice.adj_close,
               MarketPrice.volume)
        .where(MarketPrice.ticker == ticker)
        .order_by(MarketPrice.price_date))).all()
    return [Bar(d, float(c), float(a) if a is not None else None,
                int(v) if v is not None else None) for d, c, a, v in rows]


# ── refusals (M3): loud, citable, carrying needs/have and the parameter ──────

async def _too_few(db: AsyncSession, *, ticker: str | None, quantity: str,
                   parameter: str, needs: int, have: int, window_desc: str,
                   invoked_by: str, **tried) -> dict:
    """The one refusal for an under-observed estimator. The statement names the
    producer parameter and both numbers, so the model can transcribe rather
    than author it (the V11-A lesson), and the absence row makes the refusal
    citable. The window is NEVER silently shortened to make the number exist."""
    statement = (
        f"{quantity} was not computed: the estimator needs at least {needs} "
        f"observations ({parameter} = {needs}, a producer parameter of this "
        f"estimator) and this desk holds {have} ({window_desc}). An estimate "
        f"from fewer observations would carry a precision it does not have, so "
        f"none is reported and the window is never silently shortened. This is "
        f"a statement about this desk's price history, not about the market."
    )
    return await ab.refuse(
        db, "insufficient_observations", kind="insufficient_observations",
        ticker=ticker, statement=statement,
        tried={"quantity": quantity, **tried},
        stopped_at={"parameter": parameter, "needs": needs, "have": have},
        invoked_by=invoked_by,
        needs=needs, have=have, parameter=parameter,
    )


async def _no_history(db: AsyncSession, *, ticker: str, quantity: str,
                      detail: str, invoked_by: str, **tried) -> dict:
    statement = (f"{quantity} was not computed: {detail} This is a statement "
                 f"about this desk's price history, not about the market.")
    return await ab.refuse(
        db, "no_price_history", kind="no_price_history", ticker=ticker,
        statement=statement, tried={"quantity": quantity, **tried},
        invoked_by=invoked_by,
    )


# ── returns (one convention, stated in the module docstring) ─────────────────

def _simple_returns(bars: list[Bar]) -> tuple[list[tuple[date, float]], dict]:
    """Simple daily returns on adj_close, with the two drop rules made loud:
    bars without adj_close yield no return (counted, never read from close),
    and a return spanning more than _MAX_RETURN_SPAN_DAYS calendar days is a
    hole in the panel, not a market closure pattern (counted, dropped)."""
    priced = [b for b in bars if b.adj_close is not None]
    flags: dict = {}
    if len(priced) != len(bars):
        flags["bars_without_adj_close"] = len(bars) - len(priced)
    out: list[tuple[date, float]] = []
    gapped = 0
    for prev, cur in zip(priced, priced[1:]):
        if (cur.date - prev.date).days > _MAX_RETURN_SPAN_DAYS:
            gapped += 1
            continue
        out.append((cur.date, cur.adj_close / prev.adj_close - 1.0))
    if gapped:
        flags["returns_dropped_over_gaps"] = gapped
    return out, flags


# ── 1. the price itself — two quantities, two rows ───────────────────────────

async def get_price(db: AsyncSession, ticker: str, as_of: str | None = None,
                    invoked_by: str = "agent") -> dict:
    """The most recent (or as-of) close AND adj_close, as two named quantities.

    Two ledger rows, because they are two different numbers about the same bar
    and an answer must cite the one it used: `{ticker}.close` (market value,
    display, ties to a statement) and `{ticker}.adj_close` (the level the
    return series is measured on). Both are money_per_share.
    """
    ticker = ticker.upper()
    try:
        cutoff = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        return {"error": "invalid_date", "detail": "as_of is YYYY-MM-DD"}
    bars = await _bars(db, ticker, end=cutoff)
    if not bars:
        return await _no_history(
            db, ticker=ticker, quantity=f"{ticker}.close",
            detail=(f"this desk holds no price for {ticker}"
                    + (f" on or before {as_of}." if as_of else ".")),
            invoked_by=invoked_by, as_of=as_of)
    bar = bars[-1]

    out: dict = {"ticker": ticker, "as_of": bar.date.isoformat(),
                 "convention": (
                     "close is the as-traded price (market value, display); "
                     "adj_close is the split- and dividend-adjusted level returns "
                     "are measured on. They are two quantities; cite the one you use.")}
    for column, value in (("close", bar.close), ("adj_close", bar.adj_close)):
        quantity = f"{ticker}.{column}"
        if value is None:
            # Distinct from "no bar": the bar exists and this column of it does
            # not. Reading `close` here would silently change convention on
            # exactly the rows old enough to contain a split.
            out[column] = await _no_history(
                db, ticker=ticker, quantity=quantity,
                detail=(f"{ticker}'s bar at {bar.date.isoformat()} has no adjusted "
                        f"close — re-ingest market prices before measuring returns."),
                invoked_by=invoked_by, as_of=as_of)
            continue
        calc_id = await cs._record(
            db, ticker, OP_PRICE_POINT,
            {"ticker": ticker, "column": column, "as_of": bar.date.isoformat(),
             "result_type": {"unit_class": u.MONEY_PER_SHARE, "kind": "scalar",
                             "quantity": quantity,
                             "basis": {"instant": bar.date.isoformat()}}},
            {"value": value}, [f"price:{ticker}:{bar.date.isoformat()}"], {},
            invoked_by, unit_class="MONEY_PER_SHARE",
        )
        out[column] = {"value": value, "calc_id": calc_id, "quantity": quantity,
                       "unit_class": u.MONEY_PER_SHARE}
    return out


# ── 2. the adjusted price series ─────────────────────────────────────────────

async def get_price_series(db: AsyncSession, ticker: str,
                           window: str = _DEFAULT_WINDOW,
                           invoked_by: str = "agent") -> dict:
    """adj_close daily series over a named window, as one citable series row.

    adj_close and only adj_close: this series exists to feed return work, and
    a level series that silently mixed conventions would poison every
    estimator built on it. Points carry POINT_PERIOD_KEY, the one key a series
    producer writes (analytics/units.py).
    """
    ticker = ticker.upper()
    if window not in _WINDOWS:
        return {"error": "unknown_window", "window": window, "known": sorted(_WINDOWS)}
    bars = await _bars(db, ticker)
    if not bars:
        return await _no_history(
            db, ticker=ticker, quantity=f"{ticker}.adj_close",
            detail=f"this desk holds no price history for {ticker}.",
            invoked_by=invoked_by, window=window)
    start = bars[-1].date - timedelta(days=_WINDOWS[window])
    priced = [b for b in bars if b.date >= start and b.adj_close is not None]
    unadjusted = sum(1 for b in bars if b.date >= start and b.adj_close is None)
    if not priced:
        return await _no_history(
            db, ticker=ticker, quantity=f"{ticker}.adj_close",
            detail=(f"{ticker}'s bars over the last {window} have no adjusted close "
                    f"— re-ingest market prices before measuring returns."),
            invoked_by=invoked_by, window=window)
    points = [{POINT_PERIOD_KEY: b.date.isoformat(), "value": b.adj_close,
               "fact_ids": []} for b in priced]
    flags = {"n": len(points)}
    if unadjusted:
        flags["bars_without_adj_close"] = unadjusted
    calc_id = await cs._record(
        db, ticker, OP_PRICE_SERIES,
        {"ticker": ticker, "window": window,
         "result_type": {"unit_class": u.MONEY_PER_SHARE, "kind": "series",
                         "quantity": f"{ticker}.adj_close"}},
        {"points": points},
        [f"price:{ticker}:{priced[0].date.isoformat()}:{priced[-1].date.isoformat()}"],
        flags, invoked_by, unit_class="MONEY_PER_SHARE",
    )
    return {"calc_id": calc_id, "ticker": ticker, "window": window,
            "n": len(points), "points": points,
            "from": points[0][POINT_PERIOD_KEY], "to": points[-1][POINT_PERIOD_KEY],
            "quantity": f"{ticker}.adj_close", "unit_class": u.MONEY_PER_SHARE,
            "basis": f"adjusted daily closes, {points[0][POINT_PERIOD_KEY]}..{points[-1][POINT_PERIOD_KEY]}"}


async def _record_returns_series(db: AsyncSession, ticker: str, bars: list[Bar],
                                 window: str, invoked_by: str) -> dict:
    """Ledger the simple daily return series `{ticker}.returns` — the citable
    input regress() aligns on. Returns the same shape get_price_series does."""
    returns, flags = _simple_returns(bars)
    if not returns:
        return await _no_history(
            db, ticker=ticker, quantity=f"{ticker}.returns",
            detail=f"no two consecutively-priced adjusted closes for {ticker}.",
            invoked_by=invoked_by, window=window)
    points = [{POINT_PERIOD_KEY: d.isoformat(), "value": r, "fact_ids": []}
              for d, r in returns]
    calc_id = await cs._record(
        db, ticker, OP_RETURNS_SERIES,
        {"ticker": ticker, "window": window,
         "result_type": {"unit_class": u.RATIO, "kind": "series",
                         "quantity": f"{ticker}.returns"}},
        {"points": points},
        [f"price:{ticker}:{returns[0][0].isoformat()}:{returns[-1][0].isoformat()}"],
        {"n": len(points), **flags}, invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "n": len(points),
            "points": points, "quantity": f"{ticker}.returns",
            "unit_class": u.RATIO}


# ── 3. rolling volatility ────────────────────────────────────────────────────

async def rolling_volatility(db: AsyncSession, ticker: str, window_days: int = 30,
                             invoked_by: str = "agent") -> dict:
    """Annualised vol of the last `window_days` daily returns, with its n.

    Sample std (ddof=1) of simple daily adj_close returns × √252 (§4, §11).
    Refused, never shrunk: a window below VOL_MIN_OBS is refused as asked-for
    noise, and a window the history cannot fill is refused rather than filled
    with the returns we happen to hold — a 30-day vol over 25 returns is a
    25-day vol wearing the wrong name.
    """
    ticker = ticker.upper()
    quantity = f"{ticker}.vol.{window_days}d"
    if window_days < VOL_MIN_OBS:
        return await _too_few(
            db, ticker=ticker, quantity=quantity, parameter="VOL_MIN_OBS",
            needs=VOL_MIN_OBS, have=window_days,
            window_desc=f"the request itself asks for a {window_days}-observation window",
            invoked_by=invoked_by, window_days=window_days)
    bars = await _bars(db, ticker)
    returns, flags = _simple_returns(bars)
    if len(returns) < window_days:
        return await _too_few(
            db, ticker=ticker, quantity=quantity, parameter="window_days",
            needs=window_days, have=len(returns),
            window_desc=f"{len(returns)} usable daily returns for {ticker}",
            invoked_by=invoked_by, window_days=window_days)
    tail = returns[-window_days:]
    values = [r for _, r in tail]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    vol = math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR)
    n = len(values)
    calc_id = await cs._record(
        db, ticker, OP_VOL,
        {"ticker": ticker, "window_days": window_days,
         "result_type": {"unit_class": u.RATIO, "kind": "scalar", "quantity": quantity,
                         "basis": {"interval": [tail[0][0].isoformat(),
                                                tail[-1][0].isoformat()]}}},
        {"value": vol},
        [f"price:{ticker}:{tail[0][0].isoformat()}:{tail[-1][0].isoformat()}"],
        {"n": n, **flags}, invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "value": vol, "n": n,
            "quantity": quantity, "unit_class": u.RATIO,
            "window": {"from": tail[0][0].isoformat(), "to": tail[-1][0].isoformat()},
            "basis": (f"sample std (ddof=1) of {n} daily simple adj_close returns, "
                      f"annualised by √{TRADING_DAYS_PER_YEAR}")}


# ── 5. the generic regression primitive (listed before beta, which uses it) ──

def _series_points(row: CalcLedger) -> list[tuple[str, float]] | dict:
    points = (row.result or {}).get("points")
    if not isinstance(points, list):
        return {"error": "not_a_series", "series_id": row.id,
                "detail": f"{row.id} ({row.operation}) holds one value, not a series"}
    out: list[tuple[str, float]] = []
    for p in points:
        # Writers here use POINT_PERIOD_KEY and only it; the legacy keys are
        # read so rows minted by older producers stay regressable.
        key = p.get(POINT_PERIOD_KEY) or p.get("end") or p.get("as_of")
        v = p.get("value")
        if key is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((str(key), float(v)))
    return out


async def regress(db: AsyncSession, series_x: str, series_y: str, *,
                  min_obs: int = 3, min_obs_param: str = "min_obs",
                  quantity_names: dict[str, str] | None = None,
                  ticker: str | None = None,
                  invoked_by: str = "agent") -> dict:
    """OLS of one ledgered series on another: y = alpha + beta·x, plus r².

    A general primitive over two calc_ids whose rows hold points. Alignment is
    by period key (the typed_calculator._align rule): only points whose keys
    match on both sides enter the fit; unmatched points are DROPPED FROM THE
    RESULT AND COUNTED in its quality flags — an unmatched day is not a wrong
    number, it is a day only one side priced, and the result says how many.

    `min_obs` is the CALLER's producer parameter (beta passes BETA_MIN_OBS);
    the default of 3 is the arithmetic floor below which r² is not an estimate
    of anything. Each of beta / alpha / r2 is minted as its own row, because
    each is its own quantity and an answer cites the one it used.
    """
    loaded: list[list[tuple[str, float]]] = []
    for sid in (series_x, series_y):
        row = await db.get(CalcLedger, sid)
        if row is None:
            return {"error": "unknown_series", "series_id": sid,
                    "detail": f"{sid} is not a calculation this desk holds"}
        pts = _series_points(row)
        if isinstance(pts, dict):
            return pts
        if not (row.params or {}).get("result_type"):
            return {"error": "untyped_series", "series_id": sid,
                    "detail": f"{sid} was recorded before series carried their type; "
                              f"recompute it with a typed producer"}
        loaded.append(pts)
    xs, ys = dict(loaded[0]), dict(loaded[1])
    shared = sorted(set(xs) & set(ys))
    unmatched = (len(xs) - len(shared)) + (len(ys) - len(shared))
    if not shared:
        return {"error": "misaligned_series",
                "detail": (f"{series_x} and {series_y} share no period key; "
                           f"they cover different dates")}
    n = len(shared)
    names = {"beta": (quantity_names or {}).get("beta", f"regress({series_y}~{series_x}).beta"),
             "alpha": (quantity_names or {}).get("alpha", f"regress({series_y}~{series_x}).alpha"),
             "r2": (quantity_names or {}).get("r2", f"regress({series_y}~{series_x}).r2")}
    if n < min_obs:
        return await _too_few(
            db, ticker=ticker, quantity=names["beta"], parameter=min_obs_param,
            needs=min_obs, have=n,
            window_desc=(f"{n} aligned observations between {series_x} and "
                         f"{series_y} ({unmatched} unmatched dropped)"),
            invoked_by=invoked_by, series_x=series_x, series_y=series_y)

    x = [xs[k] for k in shared]
    y = [ys[k] for k in shared]
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx == 0.0:
        return {"error": "degenerate_regressor",
                "detail": f"{series_x} has zero variance over the {n} aligned points; "
                          f"no slope is determined by it"}
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    syy = sum((v - my) ** 2 for v in y)
    beta_hat = sxy / sxx
    alpha_hat = my - beta_hat * mx
    r2 = 0.0 if syy == 0.0 else (sxy * sxy) / (sxx * syy)

    window = {"from": shared[0], "to": shared[-1]}
    flags = {"n": n, "unmatched_points": unmatched}
    out: dict = {"n": n, "unmatched_points": unmatched, "window": window,
                 "basis": (f"OLS of {series_y} on {series_x} over {n} observations "
                           f"aligned by period key; {unmatched} unmatched points "
                           f"dropped and counted")}
    for key, value in (("beta", beta_hat), ("alpha", alpha_hat), ("r2", r2)):
        calc_id = await cs._record(
            db, ticker, f"{OP_REGRESS}.{key}",
            {"series_x": series_x, "series_y": series_y, "n": n,
             "unmatched_points": unmatched,
             "result_type": {"unit_class": u.RATIO, "kind": "scalar",
                             "quantity": names[key],
                             "basis": {"interval": [window["from"], window["to"]]}}},
            {"value": value}, [series_x, series_y], flags, invoked_by,
        )
        out[key] = {"value": value, "calc_id": calc_id, "quantity": names[key],
                    "unit_class": u.RATIO}
    return out


# ── 4. beta against a benchmark, through regress ─────────────────────────────

async def beta(db: AsyncSession, ticker: str, benchmark: str = "SPY",
               window: str = _DEFAULT_WINDOW, invoked_by: str = "agent") -> dict:
    """OLS beta/alpha/r² of a name's daily returns on a benchmark's, with n.

    Both sides are simple daily adj_close total returns (a beta of adjusted
    against unadjusted returns is biased by exactly the distributions — the
    market_data_service.get_factor_prices_df argument). The two return series
    are ledgered first, then fitted by regress(), so the estimate's inputs are
    citable rows, not private arrays. n below BETA_MIN_OBS refuses (§12).
    Alpha is per trading day, not annualised.
    """
    ticker, benchmark = ticker.upper(), benchmark.upper()
    if window not in _WINDOWS:
        return {"error": "unknown_window", "window": window, "known": sorted(_WINDOWS)}
    if ticker == benchmark:
        return {"error": "self_regression",
                "detail": f"{ticker} against itself is 1.0 by construction"}
    series = {}
    for name in (benchmark, ticker):
        bars = await _bars(db, name)
        if bars:
            start = bars[-1].date - timedelta(days=_WINDOWS[window])
            bars = [b for b in bars if b.date >= start]
        if not bars:
            return await _no_history(
                db, ticker=ticker, quantity=f"{ticker}.beta.{benchmark}",
                detail=f"this desk holds no price history for {name} over the last {window}.",
                invoked_by=invoked_by, benchmark=benchmark, window=window)
        rec = await _record_returns_series(db, name, bars, window, invoked_by)
        if rec.get("error"):
            return rec
        series[name] = rec
    res = await regress(
        db, series[benchmark]["calc_id"], series[ticker]["calc_id"],
        min_obs=BETA_MIN_OBS, min_obs_param="BETA_MIN_OBS",
        quantity_names={"beta": f"{ticker}.beta.{benchmark}",
                        "alpha": f"{ticker}.alpha.{benchmark}",
                        "r2": f"{ticker}.r2.{benchmark}"},
        ticker=ticker, invoked_by=invoked_by)
    if res.get("error"):
        return res
    return {**res, "ticker": ticker, "benchmark": benchmark, "window": window,
            "returns_series": {ticker: series[ticker]["calc_id"],
                               benchmark: series[benchmark]["calc_id"]},
            "convention": ("simple daily adj_close total returns on both sides; "
                           "alpha is per trading day")}


# ── 6a. 12-1 momentum ────────────────────────────────────────────────────────

async def momentum_12_1(db: AsyncSession, ticker: str,
                        invoked_by: str = "agent") -> dict:
    """Cumulative adj_close return from ~12 months back through 21 sessions
    back — the Ken French prior-(2,12) construction (§5): the most recent
    month is SKIPPED because it carries short-term reversal, which would
    contaminate the signal with the opposite sign.

    n below MOMENTUM_MIN_OBS refuses. A history between 200 and 252 sessions
    starts the formation window at the oldest bar held and SAYS SO — the
    actual formation dates are in the row and a quality flag counts the
    shortfall; nothing is shortened silently.
    """
    ticker = ticker.upper()
    quantity = f"{ticker}.momentum_12_1"
    bars = [b for b in await _bars(db, ticker) if b.adj_close is not None]
    n = len(bars)
    if n < MOMENTUM_MIN_OBS:
        return await _too_few(
            db, ticker=ticker, quantity=quantity, parameter="MOMENTUM_MIN_OBS",
            needs=MOMENTUM_MIN_OBS, have=n,
            window_desc=f"{n} adjusted daily closes for {ticker}",
            invoked_by=invoked_by)
    end_bar = bars[-(MOMENTUM_SKIP_DAYS + 1)]
    start_bar = bars[-_MOMENTUM_FORMATION_DAYS] if n >= _MOMENTUM_FORMATION_DAYS else bars[0]
    value = end_bar.adj_close / start_bar.adj_close - 1.0
    formation_days = len(bars) - MOMENTUM_SKIP_DAYS - 1 if n < _MOMENTUM_FORMATION_DAYS \
        else _MOMENTUM_FORMATION_DAYS - MOMENTUM_SKIP_DAYS - 1
    flags: dict = {"n": n}
    if n < _MOMENTUM_FORMATION_DAYS:
        flags["formation_short_of_252"] = formation_days
    calc_id = await cs._record(
        db, ticker, OP_MOMENTUM,
        {"ticker": ticker, "skip_trading_days": MOMENTUM_SKIP_DAYS,
         "formation_from": start_bar.date.isoformat(),
         "formation_to": end_bar.date.isoformat(),
         "result_type": {"unit_class": u.RATIO, "kind": "scalar", "quantity": quantity,
                         "basis": {"interval": [start_bar.date.isoformat(),
                                                end_bar.date.isoformat()]}}},
        {"value": value},
        [f"price:{ticker}:{start_bar.date.isoformat()}:{end_bar.date.isoformat()}"],
        flags, invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "value": value, "n": n,
            "quantity": quantity, "unit_class": u.RATIO,
            "formation": {"from": start_bar.date.isoformat(),
                          "to": end_bar.date.isoformat()},
            "skipped_recent_sessions": MOMENTUM_SKIP_DAYS,
            "basis": (f"adj_close return {start_bar.date.isoformat()}.."
                      f"{end_bar.date.isoformat()}; the most recent "
                      f"{MOMENTUM_SKIP_DAYS} sessions are excluded (short-term reversal)")}


# ── 6b. distance from the 52-week high ───────────────────────────────────────

async def distance_from_52w_high(db: AsyncSession, ticker: str,
                                 invoked_by: str = "agent") -> dict:
    """adj_close today relative to its 252-session high, as a ratio ≤ 0.

    Adjusted closes, per §16's pitfall: on unadjusted prices every post-split
    stock looks permanently far from its high. The DATE of the high travels
    with the number — a high 3 sessions old and one 300 sessions old are the
    same ratio and very different facts. Shares MOMENTUM_MIN_OBS as its floor:
    both quantities read a one-year formation window, and a "52-week high"
    over a few weeks of history is a different quantity under that name.
    """
    ticker = ticker.upper()
    quantity = f"{ticker}.distance_from_52w_high"
    bars = [b for b in await _bars(db, ticker) if b.adj_close is not None]
    n = len(bars)
    if n < MOMENTUM_MIN_OBS:
        return await _too_few(
            db, ticker=ticker, quantity=quantity, parameter="MOMENTUM_MIN_OBS",
            needs=MOMENTUM_MIN_OBS, have=n,
            window_desc=f"{n} adjusted daily closes for {ticker}",
            invoked_by=invoked_by)
    window_bars = bars[-_52W_WINDOW_DAYS:]
    high_bar = max(window_bars, key=lambda b: b.adj_close)
    last = window_bars[-1]
    value = last.adj_close / high_bar.adj_close - 1.0
    flags: dict = {"n": len(window_bars)}
    if len(window_bars) < _52W_WINDOW_DAYS:
        flags["window_short_of_252"] = len(window_bars)
    calc_id = await cs._record(
        db, ticker, OP_52W,
        {"ticker": ticker, "high_date": high_bar.date.isoformat(),
         "as_of": last.date.isoformat(),
         "result_type": {"unit_class": u.RATIO, "kind": "scalar", "quantity": quantity,
                         "basis": {"interval": [window_bars[0].date.isoformat(),
                                                last.date.isoformat()]}}},
        {"value": value, "high_date": high_bar.date.isoformat()},
        [f"price:{ticker}:{window_bars[0].date.isoformat()}:{last.date.isoformat()}"],
        flags, invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "value": value,
            "n": len(window_bars), "quantity": quantity, "unit_class": u.RATIO,
            "high_date": high_bar.date.isoformat(), "as_of": last.date.isoformat(),
            "basis": (f"adj_close at {last.date.isoformat()} against its high of the "
                      f"trailing {len(window_bars)} sessions, set {high_bar.date.isoformat()}")}


# ── 6c. average daily volume — two quantities ────────────────────────────────

async def adv(db: AsyncSession, ticker: str, window_days: int = 20,
              invoked_by: str = "agent") -> dict:
    """Average daily volume over the last `window_days` sessions: shares
    (count) and dollars (money), two rows, because days-to-liquidate divides
    a share count and a limit divides a dollar figure.

    Dollar ADV is as-traded close × as-traded volume — the dollar value that
    actually crossed the tape, invariant to splits, so neither side is read
    from the adjusted series. Sessions without a recorded volume yield no
    observation (counted); a window the history cannot fill is refused, never
    filled with what happens to be there.
    """
    ticker = ticker.upper()
    if window_days < ADV_MIN_OBS:
        return await _too_few(
            db, ticker=ticker, quantity=f"{ticker}.adv_shares.{window_days}d",
            parameter="ADV_MIN_OBS", needs=ADV_MIN_OBS, have=window_days,
            window_desc=f"the request itself asks for a {window_days}-session window",
            invoked_by=invoked_by, window_days=window_days)
    bars = await _market_bars(db, ticker)
    with_volume = [b for b in bars if b.volume is not None]
    if not bars:
        return await _no_history(
            db, ticker=ticker, quantity=f"{ticker}.adv_shares.{window_days}d",
            detail=(f"this desk's holdings store (market_prices, the one store that "
                    f"records volume) holds no bars for {ticker}."),
            invoked_by=invoked_by, window_days=window_days)
    if len(with_volume) < window_days:
        return await _too_few(
            db, ticker=ticker, quantity=f"{ticker}.adv_shares.{window_days}d",
            parameter="window_days", needs=window_days, have=len(with_volume),
            window_desc=f"{len(with_volume)} sessions with a recorded volume for {ticker}",
            invoked_by=invoked_by, window_days=window_days)
    tail = with_volume[-window_days:]
    n = len(tail)
    shares = sum(b.volume for b in tail) / n
    dollars = sum(b.volume * b.close for b in tail) / n
    flags: dict = {"n": n}
    skipped = len(bars) - len(with_volume)
    if skipped:
        flags["bars_without_volume"] = skipped
    span = [tail[0].date.isoformat(), tail[-1].date.isoformat()]
    refs = [f"price:{ticker}:{span[0]}:{span[1]}"]
    out: dict = {"ticker": ticker, "n": n,
                 "window": {"from": span[0], "to": span[1]},
                 "basis": (f"mean over the last {n} sessions with recorded volume; "
                           f"dollar ADV is as-traded close × as-traded volume")}
    for key, value, unit, col in (("adv_shares", shares, u.COUNT, "shares"),
                                  ("adv_dollars", dollars, u.MONEY, "dollars")):
        quantity = f"{ticker}.{key}.{window_days}d"
        calc_id = await cs._record(
            db, ticker, f"{OP_ADV}.{col}",
            {"ticker": ticker, "window_days": window_days,
             "result_type": {"unit_class": unit, "kind": "scalar", "quantity": quantity,
                             "basis": {"interval": span}}},
            {"value": value}, refs, flags, invoked_by,
        )
        out[key] = {"value": value, "calc_id": calc_id, "quantity": quantity,
                    "unit_class": unit}
    return out


# ── tool specs (DATA — not registered here) ──────────────────────────────────
# The Wave-2 coordinator registers these on the tool face; nothing in this
# module touches the registry. Shapes mirror tools/definitions.py: name /
# display / description / json_schema / evidence, plus the service function
# each wraps. `evidence: {}` means a plain Evidence() — the calc_ids and
# absence_ids in results go on the table by the default rule.

_TICKER_ARG = {"type": "string", "description": "ticker symbol"}
_WINDOW_ARG = {"type": ["string", "null"], "enum": [*sorted(_WINDOWS), None],
               "description": "named span (default 1y)"}

_TOOL_SPECS: list[dict] = [
    {
        "name": "get_price",
        "service_fn": "get_price",
        "display": "Reading {ticker}'s price",
        "description": (
            "The most recent (or as-of) price of one name, as TWO quantities with two "
            "calc_ids: close (as-traded — market value, display, ties to a statement) "
            "and adj_close (split- and dividend-adjusted — the level returns are "
            "measured on). Cite the one you use; neither stands in for the other."),
        "json_schema": {"type": "object", "properties": {
            "ticker": _TICKER_ARG,
            "as_of": {"type": ["string", "null"],
                      "description": "YYYY-MM-DD; the last session on or before it. "
                                     "Defaults to the latest session held."},
        }, "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "get_price_series",
        "service_fn": "get_price_series",
        "display": "Reading {ticker}'s adjusted price series",
        "description": (
            "One name's adjusted daily closes over a named span, as one citable series. "
            "This is the series every return-derived figure is measured on; for what a "
            "position is WORTH on a day, use get_price's close instead."),
        "json_schema": {"type": "object", "properties": {
            "ticker": _TICKER_ARG, "window": _WINDOW_ARG,
        }, "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "get_rolling_volatility",
        "service_fn": "rolling_volatility",
        "display": "Measuring {ticker}'s rolling volatility",
        "description": (
            "Annualised volatility of one name's last N daily returns, with the number "
            "of observations it rests on. Desk windows: 21d ≈ 1 month (fast, noisy), "
            "63d ≈ 1 quarter, 252d ≈ 1 year (stable, slow). A window the history "
            "cannot fill is refused with the counts, never quietly shortened."),
        "json_schema": {"type": "object", "properties": {
            "ticker": _TICKER_ARG,
            "window_days": {"type": ["integer", "null"], "enum": [21, 30, 63, 126, 252, None],
                            "description": "sessions in the window (default 30)"},
        }, "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "get_beta",
        "service_fn": "beta",
        "display": "Estimating {ticker}'s beta",
        "description": (
            "OLS beta, alpha and R² of one name's daily returns on a benchmark's "
            "(default SPY), each as its own citable quantity, with n — the aligned "
            "observation count the fit rests on. Both sides are adjusted total returns; "
            "alpha is per trading day. Fewer than 60 aligned observations is refused "
            "with the counts rather than estimated."),
        "json_schema": {"type": "object", "properties": {
            "ticker": _TICKER_ARG,
            "benchmark": {"type": ["string", "null"], "default": "SPY",
                          "description": "benchmark ticker (default SPY)"},
            "window": _WINDOW_ARG,
        }, "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "regress_series",
        "service_fn": "regress",
        "display": "Regressing {series_y} on {series_x}",
        "description": (
            "OLS of one ledgered series on another, by their calc_ids: slope, intercept "
            "and R², each citable, plus the aligned n. Points are matched by period "
            "key; unmatched points are dropped from the fit and counted in the result. "
            "Series on disjoint dates are refused, not interpolated."),
        "json_schema": {"type": "object", "properties": {
            "series_x": {"type": "string", "description": "calc_… id of the regressor series"},
            "series_y": {"type": "string", "description": "calc_… id of the dependent series"},
        }, "required": ["series_x", "series_y"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "get_momentum_12_1",
        "service_fn": "momentum_12_1",
        "display": "Measuring {ticker}'s 12-1 momentum",
        "description": (
            "The academically standard momentum measure: cumulative adjusted return from "
            "~12 months back through 21 sessions back — the most recent month is skipped "
            "on purpose (it carries short-term reversal, which points the other way). "
            "Less than ~a year of history is refused with the counts; a formation window "
            "shorter than 252 sessions is flagged, never hidden."),
        "json_schema": {"type": "object", "properties": {"ticker": _TICKER_ARG},
                        "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "get_distance_from_52w_high",
        "service_fn": "distance_from_52w_high",
        "display": "Locating {ticker} against its 52-week high",
        "description": (
            "How far one name's adjusted close sits below its trailing-year high, as a "
            "ratio ≤ 0, with the DATE the high was set — a high 3 sessions old and "
            "one 300 sessions old are the same ratio and different facts, so say the "
            "date when you quote the distance."),
        "json_schema": {"type": "object", "properties": {"ticker": _TICKER_ARG},
                        "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
    {
        "name": "get_adv",
        "service_fn": "adv",
        "display": "Measuring {ticker}'s average daily volume",
        "description": (
            "Average daily volume over the last N sessions, as TWO quantities with two "
            "calc_ids: shares (for days-to-liquidate arithmetic) and dollars (as-traded "
            "close × volume — the value that actually crossed the tape, invariant "
            "to splits). Sessions without recorded volume are dropped and counted; a "
            "window the history cannot fill is refused with the counts."),
        "json_schema": {"type": "object", "properties": {
            "ticker": _TICKER_ARG,
            "window_days": {"type": ["integer", "null"], "enum": [20, 30, 60, None],
                            "description": "sessions in the window (default 20)"},
        }, "required": ["ticker"], "additionalProperties": False},
        "evidence": {},
    },
]
