"""The briefing (V33): the desk's map for the subjects a question names, pushed
to the analyst before it decides anything.

WHY THIS EXISTS. In the 20-question round the model called describe 43 times in
20 turns and still lacked the one dimension it needed — the holdings' sectors —
because no read it made carried them (Q07 ranked JPM among "the five technology
holdings"). The catalogue was pulled, late, and by name; here it is pushed,
first, and by subject. What the briefing carries is IDENTITY: names, dates,
coverage, what applies and what does not. What it deliberately does not carry
is a single figure — a number the analyst has not requested is a number no fact
stands behind, and the check would refuse it. The figures come back from
request_evidence, each with its id.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.db.models import ExposureRun
from exposure_workbench.services import catalogue_service, company_service, portfolio_service, quantities as qn
from exposure_workbench.services import run_reads_service

BRIEFING_CHAR_LIMIT = 12_000
_BOOK_WORDS = frozenset("""book portfolio holding holdings position positions weight weights exposure exposures limit limits
concentration drawdown liquidity liquidate scenario sell selling buy buying hedge beta stress alert alerts run runs mandate tier
breach warning attribution reconcile factor factors we our us""".split())
_NAME_STOP = frozenset("inc corp corporation company co holdings group the and plc ltd limited class common stock".split())
_TICKER = re.compile(r"\b[A-Z]{1,6}(?:\.[A-Z])?\b")


async def subjects_in(db: AsyncSession, text: str) -> dict:
    """The tickers, portfolios and runs a question names — by symbol, by a word
    of the company's name, by id, or (for the book) by the words a book question
    is asked in."""
    companies = await company_service.list_companies(db, investigable_only=True)
    by_ticker = {c.ticker: c for c in companies}
    words_upper = set(_TICKER.findall(text or ""))
    lower = (text or "").lower()
    tickers: list[str] = [t for t in by_ticker if t in words_upper]
    for c in companies:
        if c.ticker in tickers or not c.name:
            continue
        for w in re.findall(r"[A-Za-z][A-Za-z']{3,}", c.name):
            if w.lower() not in _NAME_STOP and re.search(r"\b" + re.escape(w.lower()) + r"(?:'s)?\b", lower):
                tickers.append(c.ticker)
                break
    portfolios = re.findall(r"\bport_[A-Za-z0-9]+\b", text or "")
    if not portfolios and (set(re.findall(r"[a-z]+", lower)) & _BOOK_WORDS):
        snaps = await portfolio_service.snapshot_all(db)
        portfolios = [s["portfolio_id"] for s in snaps if s.get("run_id")][:3]
    runs = re.findall(r"\b(?:run|calc)_[A-Za-z0-9]+\b", text or "")
    return {"tickers": list(dict.fromkeys(tickers))[:6], "portfolios": list(dict.fromkeys(portfolios))[:3],
            "runs": list(dict.fromkeys(runs))[:3]}


async def for_question(db: AsyncSession, text: str) -> dict:
    subs = await subjects_in(db, text)
    out: dict = {"subjects": subs, "portfolios": {}, "issuers": {}, "desk": {}}
    for pid in subs["portfolios"]:
        out["portfolios"][pid] = await _portfolio(db, pid)
    for tk in subs["tickers"]:
        out["issuers"][tk] = await _issuer(db, tk)
    out["desk"] = await _desk(db)
    return _trim(out)


async def _desk(db: AsyncSession) -> dict:
    """The desk's own map: which issuers can be asked about now, which are still
    being prepared (registered by `start`; facts and chunks not yet in), what it
    does not hold and cannot do, and its domains by name."""
    companies = await company_service.list_companies(db, investigable_only=True)
    ready = await company_service.ready_company_ids(db, [c.id for c in companies])
    # V1: what the desk does not hold or will not do is the ROSTER's to say, once
    # (analytics/handbook, each chapter's `absent`); the domains and their method
    # names were the desk's vocabulary, handed to the one reader told not to use it.
    return {
        "issuers_on_desk": sorted(c.ticker for c in companies if c.id in ready),
        "issuers_preparing": sorted(c.ticker for c in companies if c.id not in ready),
    }


def _trim(out: dict) -> dict:
    """Under the limit by dropping the longest lists first; never a figure, since
    there are none."""
    for path in (("issuers", "*", "coverage"), ("desk", "issuers_preparing")):
        if len(json.dumps(out, default=str)) <= BRIEFING_CHAR_LIMIT:
            break
        if path[1] == "*":
            for tk in out.get(path[0], {}):
                out[path[0]][tk].pop(path[2], None)
        else:
            out[path[0]].pop(path[1], None)
    return out


async def _portfolio(db: AsyncSession, pid: str) -> dict:
    pos = await portfolio_service.positions_with_weights(db, pid)
    if pos is None:
        return {"error": "unknown_portfolio"}
    fresh = await run_reads_service.get_run_freshness(db, pid)
    runs = (await db.execute(
        select(ExposureRun.id, ExposureRun.as_of_date).where(ExposureRun.portfolio_id == pid, ExposureRun.status == "completed")
        .order_by(ExposureRun.as_of_date.desc(), ExposureRun.created_at.desc()).limit(2))).all()
    checks: dict[str, list[str]] = {}
    latest = fresh.get("latest_completed_run") if isinstance(fresh, dict) else None
    if latest:
        resolved = await qn.of_ref(db, latest)
        for q in resolved.quantities:
            parts = q.label.split(".")
            if parts[0] == "limit_checks" and len(parts) == 3:
                checks.setdefault(parts[1], [])
                if parts[2] not in checks[parts[1]]:
                    checks[parts[1]].append(parts[2])
    return {
        "name": pos.get("name"),
        "runs": {"latest": {"id": runs[0][0], "as_of": runs[0][1].isoformat()} if runs else None,
                 "prev": {"id": runs[1][0], "as_of": runs[1][1].isoformat()} if len(runs) > 1 else None},
        "positions_as_of": pos.get("positions_as_of"),
        "holdings": [{"ticker": h["ticker"], "sector": h.get("sector"), "asset_class": h.get("asset_class")}
                     for h in pos.get("holdings", [])],
        # which checks the mandate defines, as the desk SAYS them — never a level:
        # a tier is a figure, and a figure comes back from an analyst under an id
        "checks": sorted({_check_said(name) for name in checks}),
    }


def _check_said(name: str) -> str:
    kind, _, entity = name.partition(":")
    return dn.label("limit", kind) + (f": {entity}" if entity else "")


async def _issuer(db: AsyncSession, tk: str) -> dict:
    d = await catalogue_service.describe(db, tk, None)
    if d.get("error"):
        return {"error": d["error"], "detail": d.get("detail")}
    f = d.get("fundamentals") or {}
    fil = (d.get("filings") or {}).get("filings") or {}
    return {
        "name": (d.get("identity") or {}).get("name"),
        "status": "ready" if (d.get("identity") or {}).get("prepared") else "preparing",
        "sector": (d.get("identity") or {}).get("sector"),
        "fiscal_year_end": (f.get("fiscal") or {}).get("fiscal_year_ends"),
        "latest_period_end": f.get("latest_period_end"),
        "filings": {form: {"latest": v.get("latest")} for form, v in fil.items() if isinstance(v, dict)},
        "prices": {k: (d.get("prices") or {}).get(k) for k in ("from", "to")},
        "held_in": [{"portfolio_id": h.get("portfolio_id"), "as_of": h.get("as_of")}
                    for h in ((d.get("book") or {}).get("held_in") or [])],
        # FOR THE ANALYST WHO IS ASKED ABOUT THIS NAME, never for the lead
        # (`for_lead` drops it): the desk's own names — which filed lines stop
        # early, which measures this issuer's filings cannot feed, which Items are
        # indexed. They are its tools' vocabulary, and the lead has none.
        "coverage": {"lines_ending_early": f.get("lines"),
                     "measures_not_computable": f.get("methods_not_computable"),
                     "items_indexed": (d.get("filings") or {}).get("items_indexed")},
    }


def for_lead(briefing: dict) -> dict:
    """The lead's copy of the briefing: names, dates and coverage — and none of
    the desk's vocabulary (V1). An analyst asked about a name gets that name's
    whole entry (agents/sub_analyst._coverage_of)."""
    out = {k: v for k, v in briefing.items() if k != "issuers"}
    out["issuers"] = {tk: ({k: v for k, v in d.items() if k != "coverage"} if isinstance(d, dict) else d)
                      for tk, d in (briefing.get("issuers") or {}).items()}
    return out
