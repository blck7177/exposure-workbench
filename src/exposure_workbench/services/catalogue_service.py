"""What the desk holds about an issuer, as names, dates and coverage (V23, cut down for V1).

Until V1 this module was `describe(subject)` — one catalogue for the model, across
every kind of subject, with each entry's call spelled in the desk's program
language and the fourteen domains, the desk rules and the readings rendered
beside it. V1 retired that tool with the language it taught: an analyst sees
what is there with the `list` verb (tools/primitives), and what the desk knows is
the handbook's (analytics/handbook).

What remains is what two readers still need, and neither is a model:
  * the scope catalogue (services/scope) — an issuer's identity, how far its filed
    lines reach and which measures its filings cannot feed, its filings and
    indexed Items, its price history's span, and the books that hold it;
  * the POSITION measure (services/position_service) — a name's place in the
    latest completed run of each book that holds it.
No figure leaves here as a figure: counts and dates describe coverage.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import withheld as wh
from exposure_workbench.db.models import (
    Company, ExposureRun, Filing, FilingChunk, FilingSection, IssuerExposure, LimitCheck, MarketPrice, RiskAlert,
)
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import company_service


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


async def issuer(db: AsyncSession, ticker: str) -> dict:
    """One issuer: who it is, and what the desk holds about it — coverage, never a figure."""
    from exposure_workbench.services import security_master_service
    tk = ticker.upper()
    company = (await db.execute(select(Company).where(Company.ticker == tk))).scalar_one_or_none()
    if company is None:
        if await security_master_service.is_in_universe(db, tk):
            return _err("not_prepared", f"{tk} is a listed security this desk has not prepared: it holds no "
                                        f"filings or facts for it", ticker=tk)
        return _err("company_not_found", f"{tk} is not a company this desk knows", ticker=tk)
    prepared = company.id in await company_service.ready_company_ids(db, [company.id])
    return {
        "subject": tk, "kind": "issuer",
        "identity": {"ticker": tk, "name": company.name, "cik": company.cik, "sector": company.sector,
                     "industry": company.industry, "investigable": company.is_investigable, "prepared": prepared},
        "fundamentals": await _fundamentals(db, tk, company, False),
        "filings": await _filings(db, company.id, False),
        "prices": await _prices(db, tk),
        "book": await in_book(db, tk),
    }


async def _computability(db: AsyncSession, tk: str, have: set[str]) -> tuple[list, dict]:
    """(computable, {name: why not}) for this issuer — the check
    `evaluate_formula` applies, in ONE place.

    V31: it was inline in `_fundamentals`, which is why the issuer view and the
    domain view could disagree about the same issuer. Both read it here now:
    a domain that says which of its methods refuse for this subject, and a
    domain OPENED for that subject, are the same statement or they are a defect.
    """
    from exposure_workbench.services import formula_service
    sector = await formula_service._sector(db, tk)
    is_financial = sector in formula_service.FINANCIAL_SECTORS
    computable, not_computable = [], {}
    for name, f in fm.FORMULAS.items():
        missing = sorted(_leaves(name) - have)
        if is_financial and f.not_for_financials is not None:
            not_computable[name] = "not for a financial issuer"
        elif missing:
            not_computable[name] = f"missing {', '.join(missing)}"
        else:
            computable.append(name)
    return computable, not_computable


async def _fundamentals(db: AsyncSession, tk: str, company, full: bool) -> dict:
    from exposure_workbench.services import lineage_service, period_semantics
    metrics = await cs.list_available_metrics(db, tk)
    rows = metrics["metrics"]
    have = {m["metric"] for m in rows}
    kinds: dict[str, int] = {}
    latest, earliest = None, None
    for m in rows:
        k = m.get("kind") or "instant"          # the map marks flows; the rest are balances
        kinds[k] = kinds.get(k, 0) + 1
        lp = m.get("latest_period_end")
        if lp and (latest is None or lp > latest):
            latest = lp
    periods = await period_semantics.describe_periods(db, tk)
    # which methods this issuer's filings can feed — the check evaluate_formula applies
    computable, not_computable = await _computability(db, tk, have)
    # V31. `names` plus one issuer date said, by omission, that every name reached
    # that date. NVDA's `revenue` stops 2022-01-30 and that string did not occur
    # anywhere in describe's 22.5 KB, so a model asking for it read a map that was
    # wrong. Every exception is listed; a name absent from `lines` reaches
    # `latest_period_end` by construction, which is the whole point.
    lineage = await lineage_service.for_issuer(db, tk)
    lines: dict[str, dict] = {}
    for m in rows:
        lp, name = m.get("latest_period_end"), m["metric"]
        if not lp or not latest or str(lp) >= str(latest):
            continue
        entry: dict = {"ends": str(lp)}
        lin = lineage.get(name)
        if lin:
            entry["continues_as"] = lin.to_metric
            entry["through"] = lin.to_last_period_end.isoformat()
            entry["read_as_one_line"] = lin.agrees
            entry["because"] = lin.statement
        lines[name] = entry

    out = {
        "metrics": len(rows), "latest_period_end": latest, "kinds": kinds,
        # what a name covers, wherever that is not the issuer's own latest period
        **({"lines": lines} if lines else {}),
        # The NAMES, always: thirty-odd short strings. Without them the first
        # live V23 turn guessed `capital_expenditures` and was refused eight
        # times over; a catalogue that makes the reader guess the key is not
        # a catalogue.
        "names": sorted(have),
        "fiscal": ({k: v for k, v in periods.items() if not isinstance(v, (list, dict))}
                   if isinstance(periods, dict) else periods),
        "methods_computable": len(computable), "methods_not_computable": not_computable,
    }
    if full:
        out["metrics_detail"] = rows
        out["period_semantics"] = periods
    return out


def _leaves(name: str, seen: frozenset = frozenset()) -> set[str]:
    f = fm.FORMULAS.get(name)
    if f is None:
        return {name}
    out: set[str] = set()
    for inp in f.inputs:
        if inp not in seen:
            out |= _leaves(inp, seen | {inp})
    return out


async def _filings(db: AsyncSession, company_id: str, full: bool) -> dict:
    forms = (await db.execute(
        select(Filing.form_type, func.count(), func.max(Filing.filing_date))
        .where(Filing.company_id == company_id).group_by(Filing.form_type))).all()
    passages = (await db.execute(
        select(func.count()).select_from(FilingChunk).where(FilingChunk.company_id == company_id))).scalar_one()
    items = (await db.execute(
        select(FilingSection.item_code, func.count())
        .join(Filing, Filing.id == FilingSection.filing_id)
        .where(Filing.company_id == company_id, FilingSection.item_code.is_not(None))
        .group_by(FilingSection.item_code))).all()
    out = {
        "filings": {f: {"count": n, "latest": d.isoformat() if d else None} for f, n, d in forms},
        "items_indexed": sorted(i for i, _ in items),
        "passages": passages,
    }
    if full:
        # V28 C2: a count of indexed sections is a figure the desk holds about
        # itself — declared here as COUNT so the adapter mints it, instead of
        # meeting an undeclared numeric leaf and killing the whole route (X3).
        out["items_detail"] = {"numeric_unit": "count", **{i: n for i, n in items}}
    return out


async def _prices(db: AsyncSession, tk: str) -> dict:
    row = (await db.execute(
        select(func.min(MarketPrice.price_date), func.max(MarketPrice.price_date), func.count())
        .where(MarketPrice.ticker == tk))).one()
    lo, hi, n = row
    if not n:
        return {"sessions": 0, "note": "no price history on this desk"}
    return {"sessions": n, "from": lo.isoformat(), "to": hi.isoformat()}


async def in_book(db: AsyncSession, tk: str) -> dict | None:
    """The name's place in the latest completed run of each portfolio holding it."""
    runs = (await db.execute(
        select(ExposureRun).where(ExposureRun.status == "completed")
        .order_by(ExposureRun.portfolio_id, ExposureRun.as_of_date.desc()))).scalars().all()
    latest: dict[str, ExposureRun] = {}
    for r in runs:
        latest.setdefault(r.portfolio_id, r)
    out = []
    for pid, run in latest.items():
        pos = (await db.execute(select(IssuerExposure).where(
            IssuerExposure.run_id == run.id, IssuerExposure.ticker == tk))).scalar_one_or_none()
        if pos is None:
            continue
        checks = (await db.execute(select(LimitCheck).where(
            LimitCheck.run_id == run.id, LimitCheck.limit_type == f"issuer_concentration:{tk}"))).scalars().all()
        alerts = (await db.execute(select(RiskAlert).where(
            RiskAlert.run_id == run.id, RiskAlert.entity_id == tk))).scalars().all()
        # What this puts on the table for the name: its own three columns, its
        # check's three tiers, the alert's columns, and the BOOK's market value
        # — the four figures a trim or a weight question is arithmetic over.
        # The first live V23 turn could not price a trim because the book's
        # market value was not among the names describe(MSFT) had put on the
        # table. Everything else on the run is describe(run_id).
        names = [f"issuer_exposures.{tk}.weight", f"issuer_exposures.{tk}.market_value",
                 f"issuer_exposures.{tk}.contribution", "exposure_metrics.portfolio_market_value"]
        names += [f"limit_checks.{c.limit_type}.{col}" for c in checks
                  for col in ("current_value", "warning_level", "breach_level")]
        names += [f"risk_alerts.issuer_concentration:{tk}.{col}" for a in wh.published_alerts(alerts)
                  for col in ("current_value", "limit_value", "utilization")]
        out.append({
            "portfolio_id": pid, "run_id": run.id, "as_of": run.as_of_date.isoformat(),
            "names": names,
            "checks": [{"name": f"limit_checks.{c.limit_type}.current_value", "status": c.status} for c in checks],
            "alerts": [a.severity for a in wh.published_alerts(alerts)],
        })
    return {"held_in": out} if out else {"held_in": [], "note": "not a position of any run on this desk"}
