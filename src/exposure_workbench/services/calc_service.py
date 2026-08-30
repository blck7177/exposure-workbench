"""Calc service (M3) — data primitives + ledgered calculation primitives.

Every calculation writes ONE append-only row to calc_ledger and returns its
calc_id. That is what makes "the LLM may not do arithmetic" enforceable rather
than aspirational: an agent can only quote a number that some named, replayable
operation actually produced, and the ledger records the inputs it came from.

Series specs are STATELESS (each call carries its full data spec), per the M3
decision; calc_id chaining is a later evolution.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import series_ops as so
from exposure_workbench.db.models import CalcLedger, Company, Filing, FinancialFact, MarketPrice
from exposure_workbench.utils.ids import new_calc_id

logger = logging.getLogger(__name__)



class UnknownMetric(Exception):
    def __init__(self, metric: str):
        super().__init__(f"No facts for metric {metric!r}")
        self.metric = metric



async def _company_id(db: AsyncSession, ticker: str) -> str:
    row = await db.execute(select(Company.id).where(Company.ticker == ticker))
    cid = row.scalar_one_or_none()
    if cid is None:
        raise UnknownMetric(f"ticker {ticker}")
    return cid


async def load_price_series(
    db: AsyncSession, ticker: str, start: date, end: date
) -> list[so.PricePoint]:
    """The store rule lives in market_data_service.price_points (V10); this is
    the name window_return has always called."""
    from exposure_workbench.services import market_data_service as mds
    points, _store = await mds.price_points(db, ticker, start, end)
    return points


# ── Ledger ─────────────────────────────────────────────────────────────────────

async def _record(
    db: AsyncSession,
    company_ticker: str | None,
    operation: str,
    params: dict,
    result: dict,
    input_refs: list[str],
    quality_flags: dict,
    invoked_by: str,
) -> str:
    calc_id = new_calc_id()
    db.add(
        CalcLedger(
            id=calc_id,
            company_id=company_ticker,
            operation=operation,
            params=params,
            result={**result, "quality_flags": quality_flags},
            input_refs=input_refs,
            primitive_version=so.PRIMITIVE_VERSION,
            invoked_by=invoked_by,
        )
    )
    await db.flush()
    return calc_id


async def find_recorded(
    db: AsyncSession, operation: str, params: dict,
) -> CalcLedger | None:
    """The most recent ledger row for exactly this call, if there is one (V13-S5).

    WHY THIS EXISTS. The ledger's contract is one row per calculation, and it is
    what makes a number citable. A read endpoint that recomputes on every page
    load keeps that contract in letter and destroys it in spirit: the chart panel
    for one book would mint a row every time somebody refreshed, and "25,119
    calculations this desk has performed" would become "how many times a browser
    asked".

    So a read that would derive something asks here first. A hit is not a cache —
    it is the same calculation, already performed and already citable, and
    handing back its id is what lets the chart's points click through to a row
    that a previous answer may also have cited.

    WHAT `params` MUST BE, and why this is containment and not equality.

    The first version compared for JSONB EQUALITY, on the argument that "the
    params ARE the call". They are not, quite: an operation is free to record
    beside its arguments what the call turned out to involve — reconcile stores
    `terms_positions` and `terms_factors` — and a caller looking a row up cannot
    know those before making the call. So equality never matched, every read fell
    through to the recording path, and the one endpoint using this minted a row
    per request. It shipped that way; the ledger's own row count found it.

    Containment keeps the guarantee the equality argument was protecting, and the
    obligation moves to the caller: pass EVERY argument that distinguishes this
    call from another of the same operation. Two reconciliations of different
    runs differ in `run_id`; two drawdown scans differ in their span; pass those
    and they can never resolve to each other. Pass a proper subset of what
    identifies a call and this will hand back the wrong row, which is why each
    operation exports the identifying set (reconcile_service.identifying_params)
    rather than each caller composing one by hand.
    """
    row = (await db.execute(
        select(CalcLedger)
        .where(CalcLedger.operation == operation, CalcLedger.params.contains(params))
        .order_by(CalcLedger.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return row


async def window_return(
    db: AsyncSession,
    ticker: str,
    start: date,
    end: date,
    benchmark: str | None = None,
    invoked_by: str = "recipe",
) -> dict:
    prices = await load_price_series(db, ticker, start, end)
    bench = await load_price_series(db, benchmark, start, end) if benchmark else None
    res = so.compute_window_return(prices, start, end, benchmark=bench)
    params = {"ticker": ticker, "start": start.isoformat(), "end": end.isoformat(),
              "benchmark": benchmark}
    refs = [f"price:{ticker}:{start.isoformat()}:{end.isoformat()}"]
    if benchmark:
        refs.append(f"price:{benchmark}:{start.isoformat()}:{end.isoformat()}")
    calc_id = await _record(
        db, ticker, res.operation, params, {"value": res.value}, refs,
        res.quality_flags, invoked_by,
    )
    return {"calc_id": calc_id, "operation": res.operation,
            "value": res.value, "quality_flags": res.quality_flags}


async def list_available_metrics(db: AsyncSession, ticker: str) -> dict:
    """The agent's map: which metrics exist for this issuer, how deep, what kind.

    V12-K1 adds `kind` and, for flows, `windows_filed`. The interval engine's
    whole subject — a flow covers an interval, a balance is read at an instant —
    reached the model as the word "mixed" and nothing more. Measured externally:
    once agents have a catalogue of financial tools, 63% of what still goes
    wrong is the period (FinRetrieval), attributed to undocumented conventions.

    `windows_filed` needs period_start, which this query did not select.
    """
    from exposure_workbench.services.period_semantics import filed_window_lengths

    company_id = await _company_id(db, ticker)
    rows = (
        await db.execute(
            select(FinancialFact.normalized_metric, FinancialFact.period_end,
                   FinancialFact.period_start)
            .where(FinancialFact.company_id == company_id,
                   FinancialFact.normalized_metric.is_not(None))
        )
    ).all()
    ends: dict[str, set] = {}
    spans: dict[str, set] = {}
    for metric, period_end, period_start in rows:
        ends.setdefault(metric, set()).add(period_end)
        if period_start is not None and period_end is not None:
            spans.setdefault(metric, set()).add((period_start, period_end))

    def described(metric: str, periods: set) -> dict:
        got = {"metric": metric, "periods": len(periods),
               "latest_period_end": max(periods).isoformat()}
        # Said once, on the lines it is true of. A balance is the other case and
        # naming it on twenty rows spends bytes to repeat the absence of a word.
        if metric in spans:
            got["kind"] = "flow"
            windows = filed_window_lengths(sorted(spans[metric]))
            # Only when there is more than one. A lone "3-month" repeats what
            # `kind: flow` already said; two or more lengths off one year-start
            # is the fact that matters — this line is filed cumulatively, so a
            # single quarter after the first is a subtraction.
            if len(windows) > 1:
                got["windows_filed"] = list(windows)
        return got

    return {
        "ticker": ticker,
        "metrics": sorted((described(m, p) for m, p in ends.items()),
                          key=lambda d: d["metric"]),
    }
