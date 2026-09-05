"""The book after a sale, as a ledger row every reader can take for a run (V22).

The pure arithmetic is analytics/scenario.py. This module does the three things
that touch the world: reads the run's own children, applies the portfolio's own
thresholds through the same engine the workflow uses (analytics/limits.
check_limits, with the risk, stress and P&L inputs absent — so exactly the
concentration and exposure checks run, and the payload says which did not),
and records ONE row whose result mirrors a run's tables. The namer
(services/quantities._from_scenario) publishes that row under a run's names,
and the calculator resolves `calc_…:issuer_exposures.MSFT.weight` on it with
the row itself as the BASE — so a scenario weight and a run weight may be
differenced (the change the sale makes) and may not be summed.

What is NOT carried: the factor exposures. A beta is a regression over the
book's return history, and the book after the sale has no history; carrying
the old betas would report the fit of a different book. They are stated as
unmeasured, the same word a run uses for a risk no factor speaks to.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import scenario as sc
from exposure_workbench.analytics.exposure import ExposureResult
from exposure_workbench.analytics.limits import LimitBook, MissingLimit, check_limits
from exposure_workbench.db.models import ExposureRun, IssuerExposure
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import portfolio_service
from exposure_workbench.services.typed_calculator import SCENARIO_OP
from exposure_workbench.tools.registry import current_session_id


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


def _sales(raw: list[dict]) -> list[sc.Sale] | dict:
    out = []
    for i, s in enumerate(raw or []):
        if not isinstance(s, dict) or not isinstance(s.get("ticker"), str) or not s["ticker"]:
            return _err("bad_sale", f"sales[{i}] must name a ticker")
        fraction = s.get("fraction", 1.0)
        if fraction is None:
            fraction = 1.0
        try:
            fraction = float(fraction)
        except (TypeError, ValueError):
            return _err("bad_sale", f"sales[{i}].fraction {fraction!r} is not a number")
        out.append(sc.Sale(s["ticker"].upper(), fraction))
    if not out:
        return _err("bad_sale", "at least one sale is needed")
    return out


async def _limit_book(db: AsyncSession, portfolio_id: str) -> LimitBook:
    rows = await portfolio_service.get_risk_limits(db, portfolio_id, active_only=False)
    return LimitBook([
        {"id": lim.id, "limit_type": lim.limit_type, "entity_id": lim.entity_id,
         "warning_level": lim.warning_level, "breach_level": lim.breach_level,
         "unit": lim.unit, "is_active": lim.is_active}
        for lim in rows
    ])


# The keys a scenario row writes under each run table, beside the row label.
# Every VALUE key must be a column resources.py declares for that table, or
# the namer never publishes it (tests/test_v22_book_algebra pins the subset).
def recorded_shape(book: sc.ScenarioBook, checks: list, alerts: list) -> dict:
    """The row's result: a run's tables as lists of {label, <columns>}."""
    fired = {a.check_key for a in alerts}
    return {
        "issuer_exposures": [
            {"label": h.ticker, "sector": h.sector, "market_value": h.market_value,
             "weight": book.weights[h.ticker]}
            for h in sorted(book.holdings, key=lambda h: (-book.weights[h.ticker], h.ticker))
        ],
        "sector_exposures": [
            {"label": k, "market_value": v["market_value"], "weight": v["weight"]}
            for k, v in sorted(book.sectors.items(), key=lambda kv: (-kv[1]["weight"], kv[0]))
        ],
        "exposure_metrics": {"portfolio_market_value": book.market_value,
                             "gross_exposure": book.market_value,
                             "net_exposure": book.market_value},
        "limit_checks": [
            {"label": c.check_key, "current_value": c.current_value,
             "warning_level": c.warning_level, "breach_level": c.breach_level,
             "status": c.status, "fired": c.check_key in fired}
            for c in sorted(checks, key=lambda c: c.check_key)
        ],
        "alerts": [
            {"alert_type": a.alert_type, "entity_id": a.entity_id, "severity": a.severity,
             "current_value": a.current_value, "limit_value": a.limit_value}
            for a in alerts
        ],
        "sold": [{"ticker": s.ticker, "fraction": s.fraction,
                  "market_value_sold": s.market_value_sold, "exited": s.exited}
                 for s in book.sold],
        "proceeds": book.proceeds,
    }


async def hypothetical_book(db: AsyncSession, run_id: str, sales: list[dict]) -> dict:
    """The book after `sales`, from `run_id`'s positions, checked against the
    portfolio's limits and recorded as one row."""
    parsed = _sales(sales)
    if isinstance(parsed, dict):
        return parsed
    return await _scenario(db, run_id, lambda holdings: sc.without(holdings, parsed),
                           {"sales": [{"ticker": s.ticker, "fraction": s.fraction} for s in parsed]})


def _buys(raw: list[dict]) -> list[sc.Buy] | dict:
    out = []
    for i, b in enumerate(raw or []):
        if not isinstance(b, dict) or not isinstance(b.get("ticker"), str) or not b["ticker"]:
            return _err("bad_buy", f"buys[{i}] must name a ticker")
        try:
            w = float(b.get("weight"))
        except (TypeError, ValueError):
            return _err("bad_buy", f"buys[{i}].weight {b.get('weight')!r} is not a number")
        out.append(sc.Buy(b["ticker"].upper(), w))
    if not out:
        return _err("bad_buy", "at least one purchase is needed")
    return out


async def hypothetical_buy(db: AsyncSession, run_id: str, buys: list[dict]) -> dict:
    """The book after adding names at target weights (V23, the half V22 did
    not build): the new name's sector comes from the desk's company record,
    and a name the desk cannot place in a sector is refused rather than
    filed under Unknown — a sector check on it would be a check on nothing."""
    from exposure_workbench.db.models import Company
    parsed = _buys(buys)
    if isinstance(parsed, dict):
        return parsed
    placed: list[sc.Buy] = []
    for b in parsed:
        sector = (await db.execute(select(Company.sector).where(Company.ticker == b.ticker))).scalar_one_or_none()
        if not sector:
            return _err("no_sector", f"{b.ticker} has no sector on this desk (not prepared, or "
                                     f"not an SEC filer), so a sector-concentration check on the "
                                     f"book with it cannot run; prepare the name first", run_id=run_id)
        placed.append(sc.Buy(b.ticker, b.weight, sector))
    return await _scenario(db, run_id, lambda holdings: sc.with_buys(holdings, placed),
                           {"buys": [{"ticker": b.ticker, "weight": b.weight} for b in placed]})


async def _scenario(db: AsyncSession, base_id: str, rebuild, identifying: dict) -> dict:
    """The book after a trade, from a run's positions — or, V24, from another
    scenario row's, so a sale and then a purchase are two calls on one book
    (live round 3: book.buy on the sale's calc row was refused unknown_run and
    the second leg went unanswered). The chain is recorded: the new row's
    input is the row it built on, and `from_scenario` names it."""
    from exposure_workbench.db.models import CalcLedger
    from_scenario = None
    if base_id.startswith("calc_"):
        prior = (await db.execute(select(CalcLedger).where(CalcLedger.id == base_id))).scalar_one_or_none()
        if prior is None or prior.operation != SCENARIO_OP:
            return _err("not_a_scenario", f"{base_id} is not a scenario row; a scenario starts from a "
                                          f"completed run (run_…) or from another scenario's calc_ row", ref=base_id)
        run_id = (prior.params or {}).get("run_id")
        from_scenario = base_id
        prior_holdings = (prior.result or {}).get("issuer_exposures") or []
    else:
        run_id = base_id
        prior_holdings = None
    run = (await db.execute(select(ExposureRun).where(ExposureRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return _err("unknown_run", f"no exposure run {run_id}", run_id=run_id)
    if run.status != "completed":
        return _err("run_not_completed", f"run {run_id} is {run.status}; a scenario starts "
                                          f"from a completed run", run_id=run_id, status=run.status)
    if prior_holdings is not None:
        holdings = [sc.Holding(str(h["label"]), h.get("sector"),
                               None if h.get("market_value") is None else float(h["market_value"]))
                    for h in prior_holdings if isinstance(h, dict) and h.get("label")]
    else:
        positions = list((await db.execute(
            select(IssuerExposure).where(IssuerExposure.run_id == run_id)
            .order_by(IssuerExposure.ticker))).scalars().all())
        holdings = [sc.Holding(p.ticker, p.sector,
                               None if p.market_value is None else float(p.market_value))
                    for p in positions]
    book = rebuild(holdings)
    if isinstance(book, dict):
        return {**book, "run_id": run_id}

    # The thresholds, through the one engine. Only the inputs a sale changes
    # are given; the checks whose inputs are absent (daily loss, volatility)
    # do not run and are listed as such rather than shown clear.
    exposure = ExposureResult(
        portfolio_market_value=book.market_value,
        gross_exposure=book.market_value, net_exposure=book.market_value,
        positions=[],
        sector_map={k: {"market_value": v["market_value"], "weight": v["weight"]}
                    for k, v in book.sectors.items()},
        issuer_map={h.ticker: {"market_value": h.market_value, "weight": book.weights[h.ticker],
                               "sector": h.sector} for h in book.holdings},
    )
    try:
        alerts, evaluated, checks = check_limits(
            risk_metrics_result=None, stress_result=None, exposure_result=exposure,
            pnl_result=None, limits=await _limit_book(db, run.portfolio_id),
        )
    except MissingLimit as e:
        return _err("limits_incomplete", str(e), run_id=run_id)
    as_of = run.as_of_date.isoformat()
    recorded = recorded_shape(book, checks, alerts)
    calc_id = await cs._record(
        db, None, SCENARIO_OP,
        {"run_id": run_id, "as_of": as_of, **identifying,
         **({"from_scenario": from_scenario} if from_scenario else {}),
         "result_type": {"unit_class": "ratio", "basis": {"instant": as_of}}},
        recorded, [from_scenario or run_id], {"checks_run": len(checks), "alerts": len(alerts)},
        current_session_id(),
    )
    return {
        "calc_id": calc_id,
        "from_run": run_id,
        **({"from_scenario": from_scenario} if from_scenario else {}),
        "as_of": as_of,
        **identifying,
        "sold": recorded["sold"],
        "proceeds": book.proceeds,
        "market_value": book.market_value,
        "positions": recorded["issuer_exposures"],
        "sectors": recorded["sector_exposures"],
        "limit_checks": recorded["limit_checks"],
        "alerts": recorded["alerts"],
        "checks_not_run": ["daily_loss", "rolling_volatility_30d"],
        "factor_exposure": {"measured": False,
                            "reason": "betas are a regression over the book's return history; "
                                      "the book after the sale has none, so none is carried"},
        "reads_as": (
            "The book as it would stand after the trade, as of the run's date: each weight is "
            "its market value over the book's; sale proceeds leave the book and purchase money "
            "comes from outside it. Every name here is on the table under the calc_id, and the "
            f"same names on {run_id} are the book before — subtract for the change."
        ),
        "not_a_forecast": True,
        "cite": calc_id,
    }
