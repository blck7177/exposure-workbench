"""Issuer read routes (M11/M13) — the data behind the issuer workspace tabs.

Pure reads. The UI renders these; every number carries the id needed to drill
through /api/evidence/{id}.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user
from exposure_workbench.db.models import (
    CalcLedger, Company, Filing, FilingChunk, FilingSection, IssuerBrief, IssuerExposure,
    ResearchRun, ResearchSource,
)
from exposure_workbench.db.session import get_db
from exposure_workbench.analytics import containment as ct
from exposure_workbench.analytics import display_names as dn, interval_algebra as ia
from exposure_workbench.services import (
    calc_service, company_service, fundamentals_service, market_data_service, period_semantics,
)
from exposure_workbench.services import evidence_resolver_service as ev

router = APIRouter()

# Named windows, for the same reason the portfolio history has them: how far back
# a chart looks is a product decision, not a query parameter.
_SPANS = {"1y": 365, "3y": 365 * 3, "5y": 365 * 5}


async def _company(db: AsyncSession, ticker: str) -> Company:
    try:
        return await company_service.get_by_ticker(db, ticker.upper())
    except company_service.CompanyNotFound:
        raise HTTPException(404, {"error": "unknown_ticker", "ticker": ticker.upper()})


# ── evidence: the batch of labels, then the drill-through ────────────────────────
#
# /evidence/labels is declared FIRST and has to be. A path parameter matches any
# single segment, so with the resolver above it every request for the batch was
# answered by resolve(ref_id="labels") — a 404 reading "no evidence for labels",
# which is a sentence about the wrong question. tests/test_route_reachability.py
# derives the rule from the app's route table so the next literal path added
# under a parameterised one is caught at the same place.

# A ceiling on one request, not a page size: the caller is a rendered answer
# resolving its own citations, and the largest of those in the live database
# carries 17. A hundred is generous for that and bounded for anyone else.
MAX_LABEL_IDS = 100


@router.get("/evidence/labels", dependencies=[Depends(optional_user)])
async def evidence_labels(ids: str = "", db: AsyncSession = Depends(get_db)):
    """Short captions for many evidence ids at once (V13-S3).

    An answer citing seventeen things would otherwise open seventeen requests
    just to put words on its chips. Resolution is per-id and the envelope is
    unchanged; this returns the label alone.

    An id that does not resolve is simply absent from the result rather than
    an error: a chip whose evidence has gone is a chip that shows its id, which
    is what every chip did before this existed, and failing the whole batch for
    one of them would take the other sixteen down with it.
    """
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:MAX_LABEL_IDS]
    out: dict[str, dict] = {}
    for ref in wanted:
        try:
            resolved = await ev.resolve(db, ref)
        except ev.EvidenceNotFound:
            continue
        out[ref] = {"type": resolved["type"], "label": resolved.get("label", "")}
    return {"labels": out}


@router.get("/evidence/{ref_id}", dependencies=[Depends(optional_user)])
async def get_evidence(ref_id: str, db: AsyncSession = Depends(get_db)):
    # optional_user sets the tenant so run_/alert_ evidence for the caller's own
    # runs resolves (public demo evidence resolves anonymously via is_public).
    try:
        return await ev.resolve(db, ref_id)
    except ev.EvidenceNotFound:
        raise HTTPException(404, f"no evidence for {ref_id}")


# ── companies list (for the portfolio -> investigate entry) ───────────────────────

@router.get("/companies", dependencies=[Depends(optional_user)])
async def list_companies(db: AsyncSession = Depends(get_db)):
    rows = await company_service.list_companies(db)
    return [{"ticker": c.ticker, "name": c.name, "sector": c.sector,
             "is_investigable": c.is_investigable} for c in rows]


# ── snapshot tab ──────────────────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/snapshot", dependencies=[Depends(optional_user)])
async def snapshot(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    metrics = await calc_service.list_available_metrics(db, c.ticker)
    latest_filing = (await db.execute(
        select(Filing).where(Filing.company_id == c.id).order_by(Filing.filing_date.desc())
    )).scalars().first()
    exposure = (await db.execute(
        select(IssuerExposure).where(IssuerExposure.ticker == c.ticker).order_by(IssuerExposure.created_at.desc())
    )).scalars().first()
    return {
        "company": {"ticker": c.ticker, "name": c.name, "cik": c.cik, "exchange": c.exchange,
                    "sector": c.sector, "industry": c.industry, "is_investigable": c.is_investigable},
        "latest_filing": None if latest_filing is None else {
            "form_type": latest_filing.form_type, "filing_date": latest_filing.filing_date.isoformat(),
            "accession": latest_filing.accession_number, "source_url": latest_filing.source_url,
        },
        "portfolio_exposure": None if exposure is None else {
            "market_value": float(exposure.market_value) if exposure.market_value else None,
            "weight": float(exposure.weight) if exposure.weight else None,
            "daily_return": float(exposure.daily_return) if exposure.daily_return else None,
        },
        "available_metrics": metrics["metrics"],
    }


# ── financials tab (recipe ledger rows, each with a calc_id chip) ─────────────────

@router.get("/issuers/{ticker}/financials", dependencies=[Depends(optional_user)])
async def financials(ticker: str, db: AsyncSession = Depends(get_db)):
    """The baseline rows the latest recipe run produced, by label.

    V10-S3: read from the recipe's manifest row rather than by scanning the
    ledger for `invoked_by = 'recipe'` and keying on `params.series.metric`.
    The scan worked only because every v1 row carried the metric name in the
    same place; a v2 yoy row carries the id of the series it was taken over,
    which is a different id on every run, so "latest row per metric" had
    nothing stable to key on. The manifest names each label's row explicitly.
    An issuer whose readiness has not run since v2 has no manifest and gets an
    empty list with the reason — not the v1 rows under v2's name.
    """
    from exposure_workbench.services.recipe import OP_MANIFEST
    c = await _company(db, ticker)
    manifest = (await db.execute(
        select(CalcLedger).where(CalcLedger.company_id == c.ticker,
                                 CalcLedger.operation == OP_MANIFEST)
        .order_by(CalcLedger.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if manifest is None:
        return {"ticker": c.ticker, "calcs": [],
                "note": "no baseline computed by the current recipe yet — run readiness"}
    labels: dict = (manifest.result or {}).get("labels") or {}
    ids = [v for v in labels.values() if isinstance(v, str)]
    rows = {r.id: r for r in (await db.execute(
        select(CalcLedger).where(CalcLedger.id.in_(ids)))).scalars().all()} if ids else {}
    # `label` is the manifest's KEY — `net_margin`, `cash_to_long_term_debt_noncurrent`
    # — and it went to the page under a field called label, so the Financials tab
    # listed sixteen rows spelled the way the recipe spells them. `display` is the
    # same name in words, from the one table that holds them (V13-S3a); the key
    # stays because it is what the manifest is keyed on and what a caller matching
    # rows across runs needs.
    calcs = []
    for label, ref in labels.items():
        display = dn.label("recipe_row", label)
        if isinstance(ref, str) and ref in rows:
            r = rows[ref]
            calcs.append({"label": label, "display": display,
                          "calc_id": r.id, "operation": r.operation,
                          "params": r.params, "result": r.result,
                          "primitive_version": r.primitive_version})
        else:
            calcs.append({"label": label, "display": display,
                          "calc_id": None, "operation": None, "params": {},
                          "result": None, "primitive_version": None,
                          "unavailable": (ref or {}).get("reason") if isinstance(ref, dict) else "missing"})
    return {"ticker": c.ticker, "calcs": calcs,
            "recipe_version": (manifest.params or {}).get("recipe_version"),
            "as_of": (manifest.params or {}).get("as_of")}


# ── chart reads (V13-S5) ──────────────────────────────────────────────────────


@router.get("/issuers/{ticker}/price-index", dependencies=[Depends(optional_user)])
async def price_index(ticker: str, benchmark: str = "SPY", span: str = "1y",
                      db: AsyncSession = Depends(get_db)):
    """Two price series on one axis, and when each filing arrived.

    Indexed to 100 at the start rather than plotted on two scales: a dual-axis
    chart invents a correlation by choosing where the scales line up, and the
    only honest way to put a $250 stock and a $600 index on one plot is to make
    both of them a multiple of where they began.

    The filing markers are the point of showing this at all on an issuer page —
    the reader can see what the price did around the date this desk's evidence
    arrives from, which is the thing a price chart on a research product should
    say and usually does not.
    """
    c = await _company(db, ticker)
    if span not in _SPANS:
        raise HTTPException(422, {"error": "unknown_span", "span": span, "known": sorted(_SPANS)})
    end = await market_data_service.latest_session_date(db)
    if end is None:
        return {"ticker": c.ticker, "points": [], "detail": "no prices are loaded"}
    start = end - timedelta(days=_SPANS[span])

    series, _store = await market_data_service.price_points(db, c.ticker, start, end)
    bench, _bstore = await market_data_service.price_points(db, benchmark, start, end)
    if len(series) < 2:
        return {"ticker": c.ticker, "points": [],
                "detail": f"no price history for {c.ticker} over this window"}

    bench_by_date = {p.price_date.isoformat(): float(p.close) for p in bench}
    base = float(series[0].close)
    base_bench = next((bench_by_date[p.price_date.isoformat()] for p in series
                       if p.price_date.isoformat() in bench_by_date), None)
    points = []
    for p in series:
        day = p.price_date.isoformat()
        b = bench_by_date.get(day)
        points.append({
            "date": day,
            "value": round(float(p.close) / base * 100, 3),
            "benchmark": None if b is None or base_bench is None else round(b / base_bench * 100, 3),
        })

    filings = (await db.execute(
        select(Filing).where(Filing.company_id == c.id, Filing.filing_date >= start)
        .order_by(Filing.filing_date))).scalars().all()
    return {
        "ticker": c.ticker, "benchmark": benchmark, "span": span,
        "basis": "adjusted close, indexed to 100 at the first session shown",
        "points": points,
        "filings": [{"date": f.filing_date.isoformat(), "form": f.form_type,
                     "accession": f.accession_number, "url": f.source_url} for f in filings],
    }


@router.get("/issuers/{ticker}/windows", dependencies=[Depends(optional_user)])
async def reported_windows(ticker: str, metric: str = "revenue", last_n: int = 12,
                           db: AsyncSession = Depends(get_db)):
    """Which windows of a flow this desk can derive — and which it cannot.

    This is the interval engine's own subject matter made visible, and it uses
    the engine to say it. `consecutive_windows` walks the issuer's OWN reported
    boundaries and keeps a slot it cannot derive in place, marked unreachable
    (V10, DP2) — so the holes here are the engine's finding, not this endpoint
    guessing where a quarter ought to have been.

    That distinction is the whole value of the panel. My first version stepped
    forward 91 days at a time with a tolerance and called anything unmatched a
    gap, which invents structure: it does not know that Apple's year ends in
    late September, that a year filed as H1 + FY yields H1 and FY − H1, or that
    NVDA reported FY2023 capex as 9M + FY and has no quarterly boundary there at
    all. The engine knows all three because it was built for exactly this.

    Restatements are resolved by `derive`, which is why the same window appears
    once here and three times in the raw facts.
    """
    c = await _company(db, ticker)
    facts = await fundamentals_service._flow_facts(db, c.id, metric)
    label = dn.metric(metric)
    if not facts:
        return {"ticker": c.ticker, "metric": metric, "label": label, "rows": [],
                "detail": f"this desk holds no {label.lower()} for {c.ticker}"}

    rows = []
    for months, name in ((12, "12 months"), (6, "6 months"), (3, "3 months")):
        slots = [fundamentals_service._slot(w)
                 for w in ia.consecutive_windows(facts, months=months, last_n=last_n)]
        if slots:
            rows.append({"months": months, "label": name, "slots": slots})

    return {
        "ticker": c.ticker, "metric": metric, "label": label,
        "fiscal": await period_semantics.describe_periods(db, c.ticker),
        "rows": rows,
        "note": "any window is a signed path over the ones reported; a slot with "
                "no value is one no held filing can reach, not a figure this desk "
                "chose to omit",
    }


@router.get("/issuers/{ticker}/coverage", dependencies=[Depends(optional_user)])
async def coverage(ticker: str, db: AsyncSession = Depends(get_db)):
    """What this desk holds on an issuer, as a grid rather than as 33 chips.

    The Snapshot tab listed every metric as `operating_lease_liability_noncurrent 6`
    — an identifier and a count, which answers neither "can you answer my
    question" nor "how far back". A row per measure and a column per period
    answers both at a glance, and an empty row says the thing a chip cannot:
    interest expense is not missing by accident, it stopped being reported as a
    separate line and there is a named substitute.
    """
    c = await _company(db, ticker)
    metrics = await calc_service.list_available_metrics(db, c.ticker)
    rows = []
    for m in metrics["metrics"]:
        rows.append({
            "metric": m["metric"],
            "label": dn.metric(m["metric"]),
            "periods": m.get("periods"),
            "latest": m.get("latest_period_end"),
            "kind": m.get("kind"),
            "windows_filed": m.get("windows_filed"),
            "superseded_by": m.get("superseded_by"),
        })
    rows.sort(key=lambda r: r["label"])
    return {"ticker": c.ticker, "measures": rows}


@router.get("/issuers/{ticker}/citation-map", dependencies=[Depends(optional_user)])
async def citation_map(ticker: str, db: AsyncSession = Depends(get_db)):
    """Which parts of the filings the latest brief actually drew on.

    Indexed passages per section against the ones a brief cited. On Apple all six
    cited passages come from the 10-Q's MD&A while the 10-K's 77 risk-factor and
    statement passages were searchable and not needed — which is a fact about how
    this desk works that no other view shows, and is the kind of thing a reader
    checking a brief wants before they trust it.
    """
    c = await _company(db, ticker)
    rows = (await db.execute(
        select(Filing.form_type, Filing.filing_date, FilingSection.id,
               FilingSection.item_code, FilingSection.title,
               func.count(FilingChunk.id))
        .select_from(FilingSection)
        .join(Filing, Filing.id == FilingSection.filing_id)
        .outerjoin(FilingChunk, FilingChunk.section_id == FilingSection.id)
        .where(Filing.company_id == c.id)
        .group_by(Filing.form_type, Filing.filing_date, FilingSection.id,
                  FilingSection.item_code, FilingSection.title, FilingSection.section_order)
        .order_by(func.count(FilingChunk.id).desc())
    )).all()

    brief = (await db.execute(
        select(IssuerBrief).where(IssuerBrief.company_id == c.id)
        .order_by(IssuerBrief.created_at.desc()))).scalars().first()
    cited_chunks = [x for x in (brief.citations or []) if isinstance(x, str)
                    and x.startswith("chunk_")] if brief else []
    section_of = {}
    if cited_chunks:
        section_of = dict((await db.execute(
            select(FilingChunk.id, FilingChunk.section_id)
            .where(FilingChunk.id.in_(cited_chunks)))).all())
    from collections import Counter
    cited_per_section = Counter(section_of.values())

    return {
        "ticker": c.ticker,
        "brief_id": None if brief is None else brief.id,
        "sections": [
            {"form": form, "filed": filed.isoformat(), "item": item, "title": title,
             "passages": int(n), "cited": int(cited_per_section.get(sid, 0))}
            for form, filed, sid, item, title, n in rows
        ],
        "citation_mix": {kind: sum(1 for x in (brief.citations or [])
                                   if isinstance(x, str) and x.startswith(kind + "_"))
                         for kind in ("fact", "calc", "chunk", "src")} if brief else {},
    }


# ── containment view (V13-S6): how a composed figure was assembled ────────────

# Which containment family assembles each cover-composed measure. The KEY SET is
# the formula registry's own — every formula whose op is "cover" — and the family
# each name sums is the one its producer passes (formula_service._total_debt says
# family="debt"). Both halves are pinned to their sources by
# tests/test_v13_issuer_panels.py, so a cover formula added without a row here,
# or a producer that moves to a different family, goes red rather than serving
# the wrong tree under the right name.
_FAMILY_OF_COVER_FORMULA = {"total_debt": "debt"}


@router.get("/issuers/{ticker}/containment", dependencies=[Depends(optional_user)])
async def containment_view(ticker: str, formula: str = "total_debt",
                           db: AsyncSession = Depends(get_db)):
    """What a composed total took, what it set aside, and why it is narrower
    than the lines.

    Reads the same balance sheet the formula path reads and asks the same
    engine the same question — one instant, ct.cover over it — so the tree
    drawn here and the total a panel serves can never describe different
    assemblies. What this does NOT do is sum: the assembled value and its
    calc_id belong to evaluate_formula, which ledgers every step, and a value
    published here without one would be a number no evidence supports. Every
    figure on this view is a filed fact carrying its own fact_id.

    The set-aside lines get their explanation from the engine's own edges —
    which parts of each a wider taken node already holds — derived per request
    rather than kept as a map, because a hand-kept map here would be the eight
    debt recipes back again.

    `formula` names a cover-composed measure (total_debt) or a containment
    family directly (debt, equity, operating_leases); both sets come from
    their sources, not a list in this file.
    """
    c = await _company(db, ticker)
    if formula in _FAMILY_OF_COVER_FORMULA:
        family = _FAMILY_OF_COVER_FORMULA[formula]
    elif formula in ct.FAMILIES:
        family = formula
    else:
        raise HTTPException(422, {
            "error": "unknown_formula", "formula": formula,
            "known": sorted(set(_FAMILY_OF_COVER_FORMULA) | set(ct.FAMILIES))})

    members = ct.FAMILIES[family]
    empty = {"ticker": c.ticker, "formula": formula, "family": family,
             "as_of": None, "definition": None, "taken": [],
             "overlapping_not_added": [], "missing_at_this_date": [],
             "no_facts_for_issuer": [], "outside_family": [], "edges": []}

    bs = await fundamentals_service.get_balance_sheet(db, c.ticker)
    if bs.get("error"):
        return empty | {"detail": f"this desk holds no balance sheet for {c.ticker}"}

    available = {m: line["value"] for m, line in bs["balances"].items()}
    # Everything this issuer files, at this date or another one — without it the
    # cover cannot tell "never filed" from "not on this instant" (see _total_debt,
    # which this read path is the visible half of).
    ever = frozenset(bs["balances"]) | frozenset(bs.get("not_reported_at_this_date", {}))
    cover = ct.cover(available, family=family, ever_reported=ever)
    absent = bs.get("not_reported_at_this_date") or {}
    if isinstance(cover, ct.NoCover):
        seen = [absent[m]["last_reported"] for m in members if m in absent]
        detail = f"{cover.reason} ({bs['as_of']})"
        if seen:
            detail += f"; {family} components were last reported at {max(seen)}"
        return empty | {"as_of": bs["as_of"], "detail": detail}

    def _line(m: str) -> dict:
        return {"metric": m, "label": dn.metric(m),
                "value": bs["balances"][m]["value"],
                "fact_id": bs["balances"][m]["fact_id"]}

    # Why each set-aside line was set aside: the parts of it a wider taken node
    # already holds, walked out of EDGES through the engine's own `contains`.
    # NVDA is the canonical case — debt_current_total is reported and real, and
    # its current portion of long-term debt is already inside the taken
    # long_term_debt_total, so adding the line whole would sum that part twice.
    reachable = {child for _p, child, _n in ct.EDGES}
    overlapping = []
    for m in cover.overlapping_not_added:
        because = []
        for part in sorted(p for p in reachable if ct.contains(m, p)):
            holder = (part if part in cover.terms
                      else next((t for t in cover.terms if ct.contains(t, part)), None))
            if holder is not None:
                because.append({"part": part, "part_label": dn.metric(part),
                                "already_in": holder,
                                "already_in_label": dn.metric(holder)})
        overlapping.append(_line(m) | {"because": because})

    return empty | {
        "as_of": bs["as_of"],
        "definition": cover.formula,
        "taken": [_line(m) for m in cover.terms],
        "overlapping_not_added": overlapping,
        "missing_at_this_date": [
            {"metric": m, "label": dn.metric(m),
             "last_reported": absent[m]["last_reported"]}
            for m in cover.missing_at_this_date],
        "no_facts_for_issuer": [{"metric": m, "label": dn.metric(m)}
                                for m in cover.no_facts_for_issuer],
        "outside_family": [{"metric": m, "label": dn.metric(m)}
                           for m in sorted(bs["balances"]) if m not in members],
        # The family's containment edges among the metrics on this instant's
        # sheet, with the corpus count each was validated over kept beside it —
        # what a UI needs to draw the tree, straight from the module's own data.
        "edges": [{"parent": p, "child": ch, "observed": n}
                  for p, ch, n in ct.EDGES
                  if p in members and ch in members
                  and p in bs["balances"] and ch in bs["balances"]],
        "note": ("the assembled value and its calc_id come from evaluate_formula, "
                 "which ledgers every step; this view is the assembly itself, and "
                 "each figure on it is a filed fact"),
    }


# ── margins panel series (V13-S6) ─────────────────────────────────────────────

@router.get("/issuers/{ticker}/panel-series", dependencies=[Depends(optional_user)])
async def panel_series(ticker: str, metrics: str = "",
                       db: AsyncSession = Depends(get_db)):
    """Point series for the margins panel, filtered out of the financials rows.

    A filter, not a query: this calls the financials read above and serves the
    `points` its manifest rows already hold, so the panel and the Financials
    tab can never disagree — same manifest, same ledger rows, same calc_id per
    series. Nothing is computed and nothing is minted;
    tests/test_v13_issuer_panels_live.py counts the ledger across three reads
    to hold the second half of that. The ids the points do not have are not
    invented either: a series was one calculation, and its calc_id is the row
    that performed it.

    Which rows ARE a series is the manifest's own answer — the row's result
    carries points — and the default set is derived from each row's declared
    type rather than a list of names: a margin is a share of revenue, so the
    panel takes every series whose result_type says it was derived from
    revenue. The three margins and revenue year-on-year today, and whatever
    the recipe adds tomorrow, without this endpoint hearing about it.

    A requested name this manifest cannot chart is answered in the body —
    which name, why not, what is chartable — rather than with a 500: an
    unknown metric in a query string is a UI one release ahead or behind, not
    a server error.
    """
    fin = await financials(ticker, db)
    rows = {r["label"]: r for r in fin["calcs"]}
    chartable = {label: r for label, r in rows.items()
                 if isinstance((r.get("result") or {}).get("points"), list)}

    def _derived_from(r: dict) -> tuple[str, ...]:
        d = ((r.get("params") or {}).get("result_type") or {}).get("derived_from") or ()
        return (d,) if isinstance(d, str) else tuple(d)

    wanted = ([m.strip() for m in metrics.split(",") if m.strip()]
              or [label for label, r in chartable.items()
                  if "revenue" in _derived_from(r)])

    series, unavailable = [], []
    for m in wanted:
        r = chartable.get(m)
        if r is not None:
            series.append({"metric": m, "label": r["display"],
                           "calc_id": r["calc_id"], "operation": r["operation"],
                           "points": r["result"]["points"]})
        elif m in rows:
            unavailable.append({
                "metric": m,
                "detail": rows[m].get("unavailable")
                or "a single figure in the manifest, not a series"})
        else:
            unavailable.append({"metric": m,
                                "detail": "not a row this issuer's recipe produced"})

    out = {"ticker": fin["ticker"], "as_of": fin.get("as_of"),
           "recipe_version": fin.get("recipe_version"), "series": series}
    if unavailable:
        out["unavailable"] = unavailable
        out["chartable"] = sorted(chartable)
    if not rows:
        out["note"] = fin.get("note")
    return out


# ── filings tab ────────────────────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/filings", dependencies=[Depends(optional_user)])
async def filings(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    rows = (await db.execute(
        select(Filing).where(Filing.company_id == c.id).order_by(Filing.filing_date.desc())
    )).scalars().all()
    out = []
    for f in rows:
        secs = (await db.execute(
            select(FilingSection.id, FilingSection.item_code, FilingSection.title)
            .where(FilingSection.filing_id == f.id).order_by(FilingSection.section_order)
        )).all()
        out.append({
            "accession": f.accession_number, "form_type": f.form_type,
            "filing_date": f.filing_date.isoformat(), "period_end": f.period_end.isoformat() if f.period_end else None,
            "source_url": f.source_url,
            "sections": [{"id": sid, "item_code": ic, "title": t} for sid, ic, t in secs],
        })
    return {"ticker": c.ticker, "filings": out}


@router.get("/filing-sections/{section_id}", dependencies=[Depends(optional_user)])
async def filing_section(section_id: str, db: AsyncSession = Depends(get_db)):
    sec = (await db.execute(select(FilingSection).where(FilingSection.id == section_id))).scalar_one_or_none()
    if sec is None:
        raise HTTPException(404, "section not found")
    return {"id": sec.id, "item_code": sec.item_code, "title": sec.title, "text": sec.text}


# ── research tab ───────────────────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/research-sources", dependencies=[Depends(optional_user)])
async def research_sources(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    rows = (await db.execute(
        select(ResearchSource).where(ResearchSource.company_id == c.id)
        .order_by(ResearchSource.retrieved_at.desc())
    )).scalars().all()
    return {"ticker": c.ticker, "sources": [
        {"id": s.id, "title": s.title, "url": s.url, "publisher": s.publisher_domain,
         "published_date": s.published_date.isoformat() if s.published_date else None,
         "snippet": s.snippet, "search_query": s.search_query} for s in rows
    ]}


# ── latest brief for an issuer ─────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/latest-brief", dependencies=[Depends(optional_user)])
async def latest_brief(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    brief = (await db.execute(
        select(IssuerBrief).where(IssuerBrief.company_id == c.id).order_by(IssuerBrief.created_at.desc())
    )).scalars().first()
    if brief is None:
        return {"ticker": c.ticker, "brief": None}
    return {"ticker": c.ticker, "brief": {
        "id": brief.id, "research_run_id": brief.research_run_id,
        "financial_summary": brief.financial_summary, "key_changes": brief.key_changes,
        "management_explanation": brief.management_explanation, "market_context": brief.market_context,
        "portfolio_implications": brief.portfolio_implications, "open_questions": brief.open_questions,
        "citations": brief.citations, "confidence_flags": brief.confidence_flags,
        # V15-S5: the sections as blocks with every slot filled; None on a brief
        # written before the block exit, which the text columns alone describe.
        "blocks": brief.blocks,
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
    }}
