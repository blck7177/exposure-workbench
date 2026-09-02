"""Evidence resolver (M11) — one endpoint resolves any evidence id.

Every citable id (fact_/calc_/chunk_/src_/alert_/run_) resolves through here to a
uniform envelope {type, body, provenance, upstream}. The UI's citation chip,
evidence drawer, brief rendering and agent monitor all call this one resolver, so
drill-through is one component, not per-page fetch logic. `upstream` lets the
drawer keep drilling (a calc -> its input facts -> the filing).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.services import portfolio_service
from exposure_workbench.db.models import (
    CalcLedger,
    Company,
    ExposureRun,
    Filing,
    FilingChunk,
    FilingSection,
    FinancialFact,
    Position,
    ResearchSource,
    RiskAlert,
)


# ── labels (V13-S3) ──────────────────────────────────────────────────────────
#
# Every envelope carries a `label`: a short phrase naming what this piece of
# evidence IS. The chips a reader sees were `calc 2b5395` — a type and six hex
# digits, which tells them nothing and cannot be checked against anything — and
# 131 of the 234 answers in the live database still had raw ids embedded in the
# prose itself. The id stays, because the gate needs it and the audit layer shows
# it; the label is what goes on the chip.
#
# Built only from fields that are actually on the row. Where a row carries
# nothing nameable — an operation with no metric and no window — the label says
# what the operation is rather than inventing a subject, which is the honest
# answer and is also visibly poor, so it can be improved by someone who can see
# it is poor.

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day(iso: str | None) -> str:
    """`2026-03-28` -> `Mar 28, 2026`. Dates are read, not parsed, by people."""
    if not iso or len(iso) < 10:
        return ""
    y, m, d = iso[:4], iso[5:7], iso[8:10]
    try:
        return f"{_MONTHS[int(m) - 1]} {int(d)}, {y}"
    except (ValueError, IndexError):
        return iso


def _window(start: str | None, end: str | None) -> str:
    """The period a figure belongs to, spelled the way it should be said.

    A balance is AS OF a date and a flow is OVER a window, and this desk refuses
    to let the two be confused anywhere else — a label that said "Mar 28, 2026"
    for both would put the confusion back on the chip.
    """
    if end and start:
        return f"{_day(start)} – {_day(end)}"
    if end:
        return f"as of {_day(end)}"
    return ""


# What an operation is, in words, for the rows that carry no subject of their own.
_OPERATION: dict[str, str] = {
    "derive.interval": "Derived window",
    "flow.series": "Series",
    "balance.series": "Series",
    "series": "Series",
    "change.yoy": "Year-on-year change",
    "change.qoq": "Quarter-on-quarter change",
    "change.pct": "Percent change",
    "change.abs": "Change",
    "window_return": "Return",
    "window_return.relative": "Return vs benchmark",
    "portfolio.window_return": "Portfolio return",
    "portfolio.drawdown_episodes": "Drawdown episodes",
    "portfolio.reconcile": "Move reconciliation",
    "recipe.manifest": "Issuer baseline",
    "calc.scalar.add": "Sum",
    "calc.scalar.subtract": "Difference",
    "calc.scalar.divide": "Ratio",
    "calc.scalar.multiply": "Product",
    "calc.scalar.scale": "Scaled value",
    "calc.series.add": "Sum, series",
    "calc.series.subtract": "Difference, series",
    "calc.series.divide": "Ratio, series",
    "combine.divide": "Ratio",
    "combine.sub": "Difference",
    "stat.avg": "Average",
    "stat.sum": "Total",
    "stat.std": "Standard deviation",
    "stat.cagr": "Compound annual growth",
    "stat.latest": "Latest value",
    "stat.min": "Minimum",
    "stat.max": "Maximum",
}


def _basis_day(rt: dict) -> str:
    """The date a typed result is anchored to, if it has exactly one.

    `mixed` holds two dates when a ratio spans them and is deliberately not used
    here: a label that showed one of the two would be asserting a single point in
    time for a figure that has none, which is the confusion the typed calculator
    exists to refuse.
    """
    basis = (rt or {}).get("basis") or {}
    return _day(basis.get("instant")) if isinstance(basis, dict) else ""


def _calc_label(row) -> str:
    params = row.params or {}
    result = row.result or {}
    op = row.operation or ""

    if op.startswith("absence."):
        # The service already wrote a sentence for this; its first clause is the
        # label, because "This desk holds no depreciation_amortization for
        # GOOGL over any period" IS what the evidence says.
        statement = (result.get("statement") or "").strip()
        if statement:
            first = statement.split(". ")[0]
            return first if len(first) <= 90 else first[:87] + "…"
        return "Absent"

    rt = params.get("result_type") or {}
    subject = params.get("metric") or rt.get("quantity") or rt.get("derived_from")
    named = dn.metric(subject) if isinstance(subject, str) else ""
    verb = _OPERATION.get(op, op.replace(".", " ").replace("_", " ").capitalize())

    if op in ("window_return", "window_return.relative", "portfolio.window_return"):
        # A ticker is a name a reader knows; `port_001` is not, and putting it
        # here would be this function reintroducing exactly what it exists to
        # remove. A portfolio-level return says so and leaves the book unnamed —
        # the reader is looking at one book, and it is the one on the screen.
        who = params.get("ticker") or ""
        span = _window(params.get("start"), params.get("end"))
        bench = params.get("benchmark")
        head = f"{verb} · {who}".strip(" ·") if who else verb
        if bench:
            head = f"{head} vs {bench}"
        return f"{head} · {span}".strip(" ·")

    # combine.* names both sides in its own params, so the label can say what
    # was divided by what instead of only that something was.
    a, b = params.get("a"), params.get("b")
    if isinstance(a, dict) and isinstance(b, dict):
        left, right = dn.metric(a.get("metric")), dn.metric(b.get("metric"))
        if left and right:
            joiner = "÷" if op.endswith("divide") else "−" if op.endswith(("sub", "subtract")) else "·"
            return f"{left} {joiner} {right}"

    if named:
        return f"{named} · {verb.lower()}" if verb != named else named

    day = _basis_day(rt)
    return f"{verb} · {day}" if day else verb


class EvidenceNotFound(Exception):
    def __init__(self, ref_id: str):
        super().__init__(f"no evidence for id {ref_id!r}")
        self.ref_id = ref_id


def _edgar_index(cik: str, accession: str) -> str:
    """The filing's folder on EDGAR: /Archives/edgar/data/<cik as int>/<accession without dashes>/."""
    return f"https://www.sec.gov/Archives/edgar/data/{int(str(cik).strip())}/{accession.replace('-', '')}/"


async def _fact(db: AsyncSession, fid: str) -> dict | None:
    row = (await db.execute(select(FinancialFact).where(FinancialFact.id == fid))).scalar_one_or_none()
    if row is None:
        return None
    # V19. The filing row carries the SEC URL, the form and the date; until
    # now the card stopped at an accession number the reader had to go and
    # look up. By filing_id when the fact has one, else by the accession the
    # fact itself names (facts folded from a restatement keep their own).
    filing = None
    if row.filing_id:
        filing = (await db.execute(select(Filing).where(Filing.id == row.filing_id))).scalar_one_or_none()
    if filing is None and row.source_accession:
        filing = (await db.execute(
            select(Filing).where(Filing.accession_number == row.source_accession))).scalar_one_or_none()
    accession = filing.accession_number if filing else row.source_accession
    # Most facts (12,239 of 13,343 at mapping v4) name an accession the desk
    # never ingested as a filing row: the XBRL feed carries every filing the
    # figure was reported in, the filings table only the documents read for
    # passages. The EDGAR index of a filing is a function of (CIK, accession)
    # and nothing else, so the pointer is derived rather than absent — and
    # says which of the two it is (`source_url_kind`), because an index page
    # is not the primary document.
    source_url = filing.source_url if filing else None
    url_kind = "document" if source_url else None
    if source_url is None and accession:
        cik = (await db.execute(select(Company.cik).where(Company.id == row.company_id))).scalar_one_or_none()
        if cik:
            source_url = _edgar_index(cik, accession)
            url_kind = "edgar_index"
    return {
        "type": "fact", "id": fid,
        "label": " · ".join(x for x in (
            dn.metric(row.normalized_metric) or row.raw_concept,
            _window(row.period_start.isoformat() if row.period_start else None,
                    row.period_end.isoformat() if row.period_end else None),
        ) if x),
        "body": {
            "raw_concept": row.raw_concept, "normalized_metric": row.normalized_metric,
            "value": float(row.value) if row.value is not None else None, "unit": row.unit,
            "period_start": row.period_start.isoformat() if row.period_start else None,
            "period_end": row.period_end.isoformat() if row.period_end else None,
        },
        "provenance": {
            "source_accession": row.source_accession or accession,
            "form_type": filing.form_type if filing else None,
            "filing_date": filing.filing_date.isoformat() if filing and filing.filing_date else None,
            "source_url": source_url, "source_url_kind": url_kind,
            "provider": row.provider, "mapping_version": row.mapping_version,
            "quality_flags": row.quality_flags,
        },
        "upstream": [],
    }


async def _calc(db: AsyncSession, cid: str) -> dict | None:
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == cid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "calc", "id": cid,
        "label": _calc_label(row),
        "body": {"operation": row.operation, "params": row.params, "result": row.result},
        "provenance": {"primitive_version": row.primitive_version, "invoked_by": row.invoked_by,
                       "created_at": row.created_at.isoformat() if row.created_at else None},
        # upstream = the fact/calc ids this calculation consumed (keep drilling)
        "upstream": [{"type": "fact" if r.startswith("fact_") else "calc" if r.startswith("calc_") else "ref", "id": r}
                     for r in (row.input_refs or []) if isinstance(r, str)],
    }


async def _chunk(db: AsyncSession, chid: str) -> dict | None:
    row = (await db.execute(select(FilingChunk).where(FilingChunk.id == chid))).scalar_one_or_none()
    if row is None:
        return None
    filing = (await db.execute(select(Filing).where(Filing.id == row.filing_id))).scalar_one_or_none()
    item = title = None
    if row.section_id:
        sec = (await db.execute(select(FilingSection).where(FilingSection.id == row.section_id))).scalar_one_or_none()
        if sec:
            item, title = sec.item_code, sec.title
    return {
        "type": "chunk", "id": chid,
        "label": " · ".join(x for x in (
            row.form_type, item, title if title and title != item else None,
        ) if x) or "Filing passage",
        "body": {"text": row.text, "item": item, "section_title": title,
                 "char_span": [row.char_start, row.char_end]},
        "provenance": {
            "accession": filing.accession_number if filing else None,
            "form_type": row.form_type,
            "filing_date": row.filing_date.isoformat() if row.filing_date else None,
            "source_url": filing.source_url if filing else None,
        },
        "upstream": [],
    }


async def _source(db: AsyncSession, sid: str) -> dict | None:
    row = (await db.execute(select(ResearchSource).where(ResearchSource.id == sid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "source", "id": sid,
        # Publisher first: it is what a reader weighs a web source by, and the
        # headline is usually too long to sit on a chip.
        "label": " · ".join(x for x in (row.publisher_domain, row.title) if x) or "Web source",
        "body": {"title": row.title, "snippet": row.snippet, "search_query": row.search_query},
        "provenance": {"url": row.url, "publisher": row.publisher_domain,
                       "published_date": row.published_date.isoformat() if row.published_date else None,
                       "provider": row.provider,
                       "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None},
        "upstream": [],
    }


async def _alert(db: AsyncSession, aid: str) -> dict | None:
    row = (await db.execute(select(RiskAlert).where(RiskAlert.id == aid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "alert", "id": aid,
        # The alert's own sentence, which check_limits already wrote for a
        # reader ("Issuer LLY: 13.8% vs limit 12.0% [WARNING]").
        "label": (row.message or f"{dn.label('limit', row.alert_type)} alert").strip(),
        "body": {"alert_type": row.alert_type, "severity": row.severity, "message": row.message,
                 "entity_id": row.entity_id,
                 "utilization": float(row.utilization) if row.utilization is not None else None},
        # the run that raised the alert is itself citable evidence — keep drilling
        "provenance": {"run_id": row.run_id},
        "upstream": [{"type": "exposure_run", "id": row.run_id}] if row.run_id else [],
    }


def _num(v) -> float | None:
    return float(v) if v is not None else None


async def _run(db: AsyncSession, rid: str) -> dict | None:
    row = (await db.execute(
        select(ExposureRun).where(ExposureRun.id == rid).options(selectinload(ExposureRun.metrics))
    )).scalar_one_or_none()
    if row is None:
        return None
    m = row.metrics
    return {
        "type": "exposure_run", "id": rid,
        "label": f"Exposure run · {_day(row.as_of_date.isoformat() if row.as_of_date else None)}".strip(" ·"),
        "body": {
            "portfolio_id": row.portfolio_id,
            "as_of_date": row.as_of_date.isoformat() if row.as_of_date else None,
            "status": row.status,
            "market_value": _num(m.portfolio_market_value) if m else None,
            "daily_return": _num(m.daily_return) if m else None,
            "var_95_1d": _num(m.var_95_1d) if m else None,
            "rolling_vol_30d": _num(m.rolling_vol_30d) if m else None,
            "max_drawdown": _num(m.max_drawdown) if m else None,
        },
        "provenance": {
            "triggered_by": row.triggered_by,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "task_id": row.task_id,
        },
        # V19. The holdings the run was computed over, resolved the one way
        # the workflow resolves them (portfolio_service.positions_for_run).
        # A weight or a day's P&L used to stop here; now it reaches the rows
        # that were held.
        "upstream": [
            {"type": "position", "id": p.id,
             "label": " · ".join(x for x in (
                 p.ticker, f"{_num(p.quantity):,.0f} units" if p.quantity is not None else None) if x)}
            for p in await portfolio_service.positions_for_run(db, row.portfolio_id, row.as_of_date)
        ],
    }


async def _position(db: AsyncSession, pid: str) -> dict | None:
    """A holding, as the drawer shows it: what is held, how much, and as of when.

    Price and market_value are on this row and are deliberately NOT in the body.
    They are a snapshot the seed writes and no run updates, and the whole reason
    positions_with_weights values a book from issuer_exposures is that this
    codebase already carried three valuation conventions and cut back to one.
    Rendering a stale price in the evidence drawer would resurrect it in the one
    place a user goes to check a number.
    """
    row = (await db.execute(select(Position).where(Position.id == pid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "position", "id": pid,
        "label": " · ".join(x for x in (
            row.ticker,
            f"{_num(row.quantity):,.0f} units" if row.quantity is not None else None,
        ) if x) or "Holding",
        "body": {"ticker": row.ticker, "quantity": _num(row.quantity),
                 "asset_class": row.asset_class, "sector": row.sector, "currency": row.currency,
                 "as_of_date": row.as_of_date.isoformat() if row.as_of_date else None},
        "provenance": {"portfolio_id": row.portfolio_id,
                       "created_at": row.created_at.isoformat() if row.created_at else None},
        "upstream": [],
    }


_RESOLVERS = {
    "fact_": _fact,
    "calc_": _calc,
    "chunk_": _chunk,
    "src_": _source,
    "alert_": _alert,
    "run_": _run,
    "pos_": _position,
}


async def resolve(db: AsyncSession, ref_id: str) -> dict:
    for prefix, fn in _RESOLVERS.items():
        if ref_id.startswith(prefix):
            result = await fn(db, ref_id)
            if result is None:
                raise EvidenceNotFound(ref_id)
            return result
    raise EvidenceNotFound(ref_id)
