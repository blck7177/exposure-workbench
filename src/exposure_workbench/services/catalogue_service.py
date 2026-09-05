"""describe(subject) — the one catalogue: what the desk holds, what it means,
what is missing, and which methods and procedures apply (V23).

WHY ONE. Until V23 the model saw "what is here" through three tools in three
formats: describe_issuer (14.9k characters for MSFT), describe_run (7.7k),
get_portfolio_snapshot (11.5k) — 34k to look at the desk, and the tool
descriptions carried a further 31k of "use this for". The catalogue is the
boss's first requirement: get it right, then the agent decides what to look
at. So a subject — a ticker, a portfolio, a run, a scenario row, or nothing
(the desk) — is described ONCE, across every domain that holds something
about it, in one format.

THREE KINDS OF ABSENCE, as data (IMPLEMENTATION_PLAN_V23 §2.1):
  not_reported   the issuer did not file it        (absence rows, unchanged)
  not_held       the desk holds no such figure     NOT_HELD below, derived
                 (segment revenue lives in prose)  against the concept map
  cannot         the desk has no method for it     derived from the registry's
                                                   subject kinds and withheld.py
The second and third were invisible before V23 and are why the model
substituted a true figure for the one asked (C04, C13 of the conversation
battery): the honest sentence had nothing to point at.

LAYERS. The default answer is existence, counts, ranges, absences and the
NAMES of applicable methods and procedures; `expand` opens one domain's
detail. The default layer's ceiling is DEFAULT_CEILING characters, pinned by
a live test on every subject kind.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import resources, skill
from exposure_workbench.analytics import withheld as wh
from exposure_workbench.db.models import (
    CalcLedger, Company, ExposureRun, Filing, FilingChunk, FilingSection, IssuerBrief,
    IssuerExposure, LimitCheck, MarketPrice, RiskAlert,
)
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import company_service, portfolio_service, run_reads_service
from exposure_workbench.services import quantities as qn
from exposure_workbench.services.typed_calculator import SCENARIO_OP

DEFAULT_CEILING = 8_000
EXPANDS = ("fundamentals", "methods", "procedures", "book", "filings", "readings")

# What the desk does NOT hold as figures, with where the same fact lives.
# Derived, not asserted: test_v23_catalogue checks each kind against the
# concept map (no mapped concept carries a dimension) so this list cannot
# claim a gap the ingest has since closed.
NOT_HELD: dict[str, str] = {
    "segment_revenue": "not held as figures (companyfacts carries no dimensions); stated in the "
                       "10-K's segment note and Item 7 — read_filings",
    "product_revenue": "not held as figures; stated in Item 7 and the product table — read_filings",
    "geographic_revenue": "not held as figures; stated in the segment note — read_filings",
    "customer_concentration": "not held as figures; stated in Item 1 / the concentration note — read_filings",
    "backlog": "not held as figures; stated in Item 7 where the issuer discloses it — read_filings",
}

# What no method on this desk produces. Derived at import from the registry:
# a capability is "cannot" when no method's subject kind and yields cover it.
# The sentences are data; the test pins that each names a real gap.
CANNOT: dict[str, str] = {
    "per_name_factor_sensitivity": "the factor regression is over the BOOK's return; a holding's "
                                   "sensitivity to a factor is price.beta with that factor's ETF as "
                                   "benchmark (TLT for rates, HYG for credit), one call per name",
    "scenario_refit": "a scenario (book.sell / book.buy) re-runs the limit checks and does not "
                      "re-fit betas, volatility or P&L: stated unmeasured",
}


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


# What a model writes when it means "no subject": the schema says null, and
# the first live V23 turn wrote the string "null" (and "port_" for a portfolio
# it had not looked up). The desk is the desk under any of these spellings.
_DESK_ALIASES = ("", "null", "none", "desk", "book", "portfolio", "portfolios")


def kind_of(subject: str | None) -> str:
    if subject is None or subject.strip().lower() in _DESK_ALIASES:
        return "desk"
    if subject.startswith("run_"):
        return "run"
    if subject.startswith("calc_"):
        return "scenario"
    if subject.startswith("port_"):
        return "portfolio"
    return "issuer"


async def describe(db: AsyncSession, subject: str | None = None, expand: str | None = None) -> dict:
    if expand is not None and expand not in EXPANDS:
        return _err("unknown_expand", f"expand must be one of {', '.join(EXPANDS)}")
    kind = kind_of(subject)
    if kind == "desk":
        out = await _desk(db)
    elif kind == "issuer":
        out = await _issuer(db, subject, expand)
    elif kind == "portfolio":
        out = await _portfolio(db, subject, expand)
    elif kind == "run":
        out = await _run(db, subject, expand)
    else:
        out = await _scenario(db, subject, expand)
    if out.get("error"):
        return out
    # V24: the catalogue's own date. Its counts and latest values are facts and
    # a fact says as of when; a map of the desk is as of the moment it is drawn.
    out["catalogue_as_of"] = date.today().isoformat()
    out["how_to_read"] = _HOW_TO_READ
    out["withheld"] = wh.withheld_note()
    return out


_HOW_TO_READ = (
    "Every name under `table` is a figure you can slot {ref, name} or use as an operand "
    "(ref:name) in compute. `methods` are what compute can produce for this subject; "
    "`procedures` are how an analyst approaches a kind of question about it; `not_held` and "
    "`cannot` are figures this desk does not have and why — say so, do not substitute. "
    "expand=<domain> opens one domain's detail."
)


# ── the desk ─────────────────────────────────────────────────────────────────

async def _desk(db: AsyncSession) -> dict:
    """The desk: which portfolios, their latest run and its alerts — a map to
    describe(port_…) and describe(run_…), not the run's payload (the old
    snapshot carried the whole run state, 11.5k characters, before any
    question had been asked)."""
    snaps = await portfolio_service.snapshot_all(db)
    portfolios = [{
        "portfolio_id": sn["portfolio_id"], "name": sn["name"], "is_own": sn.get("is_own"),
        "run_id": sn.get("run_id"), "as_of": sn.get("as_of_date"),
        "positions": len(sn.get("top_issuers") or []) if sn.get("run_id") else None,
        "alerts": len(sn.get("alerts") or []),
        "market_value_name": f"exposure_metrics.portfolio_market_value on {sn['run_id']}" if sn.get("run_id") else None,
        "scenario": (f"compute(method='book.sell' | 'book.buy', subject='{sn['run_id']}', params=…) "
                     f"rebuilds the book after a trade as a row read like a run"
                     if sn.get("run_id") else None),
    } for sn in snaps]
    companies = await company_service.list_companies(db, investigable_only=True)
    return {
        "subject": None, "kind": "desk",
        "portfolios": portfolios,
        "issuers_prepared": sorted(c.ticker for c in companies),
        "domains": ["fundamentals (filed figures)", "filings (text)", "prices", "book (runs, positions, limits)",
                    "web (search_web)"],
        "methods": {k: [m.name for m in skill.methods_for(k)] for k in ("issuer", "price", "run", "portfolio")},
        "procedures": [{"name": p.name, "question": p.question, "subject": p.subject_kind}
                       for p in skill.PROCEDURES.values()],
        "not_held": NOT_HELD,
        "cannot": CANNOT,
    }


# ── an issuer ────────────────────────────────────────────────────────────────

async def _issuer(db: AsyncSession, ticker: str, expand: str | None) -> dict:
    from exposure_workbench.services import security_master_service
    tk = ticker.upper()
    company = (await db.execute(select(Company).where(Company.ticker == tk))).scalar_one_or_none()
    if company is None:
        if await security_master_service.is_in_universe(db, tk):
            return _err("not_prepared", f"{tk} is a listed security this desk has not prepared: it holds "
                                        f"no filings or facts for it. start(kind='readiness') puts it "
                                        f"on the desk; the work runs in the background", ticker=tk)
        return _err("company_not_found", f"{tk} is not a company this desk knows", ticker=tk)
    out: dict = {
        "subject": tk, "kind": "issuer",
        "identity": {"ticker": tk, "name": company.name, "cik": company.cik, "sector": company.sector,
                     "industry": company.industry, "investigable": company.is_investigable},
    }
    out["fundamentals"] = await _fundamentals(db, tk, company, expand == "fundamentals")
    out["filings"] = await _filings(db, company.id, expand == "filings")
    out["prices"] = await _prices(db, tk)
    out["book"] = await _in_book(db, tk)
    out["desk"] = await _desk_about(db, company.id, tk)
    out["not_held"] = NOT_HELD
    out["cannot"] = {k: v for k, v in CANNOT.items() if k == "per_name_factor_sensitivity"}
    out["methods"] = _methods("issuer", expand == "methods") | _methods("price", expand == "methods")
    out["procedures"] = _procedures("issuer", expand == "procedures")
    if expand == "readings":
        out["readings"] = _readings()
    return out


async def _fundamentals(db: AsyncSession, tk: str, company, full: bool) -> dict:
    from exposure_workbench.services import formula_service, period_semantics
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
    out = {
        "metrics": len(rows), "latest_period_end": latest, "kinds": kinds,
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
        "read_with": "read_filings(ticker, query=…) for passages; read_filings(ticker, item='1A') for a section",
    }
    if full:
        out["items_detail"] = {i: n for i, n in items}
    return out


async def _prices(db: AsyncSession, tk: str) -> dict:
    row = (await db.execute(
        select(func.min(MarketPrice.price_date), func.max(MarketPrice.price_date), func.count())
        .where(MarketPrice.ticker == tk))).one()
    lo, hi, n = row
    if not n:
        return {"sessions": 0, "note": "no price history on this desk"}
    return {"sessions": n, "from": lo.isoformat(), "to": hi.isoformat(),
            "read_with": "read_prices(ticker, window)"}


async def _in_book(db: AsyncSession, tk: str) -> dict | None:
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
            "methods_on_this_run": [m.name for m in skill.methods_for("run")],
            "procedures": [p.name for p in skill.procedures_for("portfolio")],
            "everything_else": f"describe('{run.id}')",
        })
    return {"held_in": out} if out else {"held_in": [], "note": "not a position of any run on this desk"}


async def _desk_about(db: AsyncSession, company_id: str, tk: str) -> dict:
    brief = (await db.execute(
        select(IssuerBrief.id, IssuerBrief.created_at).where(IssuerBrief.company_id == company_id)
        .order_by(IssuerBrief.created_at.desc()).limit(1))).first()
    return {"brief": ({"id": brief[0], "created_at": brief[1].isoformat()} if brief else None),
            "read_with": f"read_book('{tk}', names=['brief'])" if brief else "start(kind='research') produces one"}


# ── a portfolio ──────────────────────────────────────────────────────────────

async def _portfolio(db: AsyncSession, pid: str, expand: str | None) -> dict:
    p = await portfolio_service.get_portfolio(db, pid)
    if p is None:
        return _err("unknown_portfolio", f"no portfolio {pid}", portfolio_id=pid)
    positions = await portfolio_service.positions_with_weights(db, pid)
    limits = await run_reads_service.list_risk_limits(db, pid)
    fresh = await run_reads_service.get_run_freshness(db, pid)
    runs = (await db.execute(
        select(ExposureRun.id, ExposureRun.as_of_date, ExposureRun.status).where(ExposureRun.portfolio_id == pid)
        .order_by(ExposureRun.as_of_date.desc()).limit(5))).all()
    out: dict = {
        "subject": pid, "kind": "portfolio",
        "identity": {"name": p.name, "portfolio_id": pid},
        "positions": {"count": len((positions or {}).get("positions", [])),
                      "read_with": f"read_book('{pid}', names=['positions'])"},
        "limits": {"count": len(limits.get("limits", [])) if isinstance(limits, dict) else None,
                   "read_with": f"read_book('{pid}', names=['limits'])"},
        "runs": [{"run_id": r[0], "as_of": r[1].isoformat(), "status": r[2]} for r in runs],
        "freshness": fresh,
        "methods": _methods("portfolio", expand == "methods") | _methods("run", expand == "methods"),
        "procedures": _procedures("portfolio", expand == "procedures"),
        "cannot": CANNOT,
    }
    if expand == "book" and positions:
        out["positions"]["detail"] = positions
    return out


# ── a run, a scenario ────────────────────────────────────────────────────────

async def _run(db: AsyncSession, run_id: str, expand: str | None) -> dict:
    run = (await db.execute(select(ExposureRun).where(ExposureRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return _err("unknown_run", f"no exposure run {run_id}", run_id=run_id)
    if run.status != "completed":
        return _err("run_not_completed", f"run {run_id} is {run.status}", run_id=run_id, status=run.status)
    out = await _book_names(db, run_id, expand == "book")
    return {"subject": run_id, "kind": "run", "portfolio_id": run.portfolio_id,
            "as_of": run.as_of_date.isoformat(), **out,
            "methods": _methods("run", expand == "methods"),
            "procedures": _procedures("portfolio", expand == "procedures"),
            "cannot": CANNOT}


async def _scenario(db: AsyncSession, cid: str, expand: str | None) -> dict:
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == cid))).scalar_one_or_none()
    if row is None:
        return _err("unknown_row", f"no ledger row {cid}")
    if row.operation != SCENARIO_OP:
        return _err("not_a_book", f"{cid} is a {row.operation} row, not a scenario; its figures are on "
                                  f"its own table under their names")
    out = await _book_names(db, cid, expand == "book")
    params = row.params or {}
    return {"subject": cid, "kind": "scenario", "from_run": params.get("run_id"),
            "as_of": params.get("as_of"), "trade": {k: params[k] for k in ("sales", "buys") if k in params},
            **out, "methods": [], "cannot": CANNOT}


async def _book_names(db: AsyncSession, ref: str, full: bool) -> dict:
    """A run's (or scenario's) names by the question each group answers,
    factored as pattern × labels — the compression describe_run proved."""
    resolved = await qn.of_ref(db, ref)
    names = [q.label for q in resolved.quantities if q.not_alone is None]
    withheld = sorted({q.label for q in resolved.quantities if q.not_alone is not None})
    groups, grouped = [], set()
    for key, question, patterns in resources.RUN_GROUPS:
        members = [n for n in names if n not in grouped and any(resources.matches(p, n) for p in patterns)]
        if members:
            grouped.update(members)
            groups.append({"group": key, "answers": question,
                           **(_factored(members) if not full else {"names": sorted(members)})})
    rest = [n for n in names if n not in grouped]
    return {"names": len(names), "groups": groups,
            **({"other": _factored(rest)} if rest else {}),
            **({"withheld_collinear": _factored(withheld)} if withheld else {}),
            "units": {r.table: {c.name: c.unit for c in r.columns} for r in resources.RUN_CHILDREN},
            "read_with": f"read_book('{ref}', names=[…])"}


def _factored(names: list[str]) -> dict:
    """Names as patterns over their row labels where that is shorter (from
    definitions._factored, V15): the mandate group's 144 names are five
    patterns over 27 labels."""
    by_shape: dict[tuple[str, str], list[str]] = {}
    plain: list[str] = []
    for n in names:
        parts = n.split(".")
        if len(parts) == 3:
            by_shape.setdefault((parts[0], parts[2]), []).append(parts[1])
        elif len(parts) == 4 and parts[0] == "portfolio":
            by_shape.setdefault((".".join(parts[:3]), ""), []).append(parts[3])
        else:
            plain.append(n)
    by_labels: dict[tuple[str, ...], list[str]] = {}
    for (head, tail), labels in by_shape.items():
        if len(labels) <= 3:
            plain.extend(f"{head}.{lb}.{tail}" if tail else f"{head}.{lb}" for lb in labels)
            continue
        by_labels.setdefault(tuple(sorted(labels)), []).append(
            f"{head}.<label>.{tail}" if tail else f"{head}.<label>")
    out: dict = {}
    if plain:
        out["names"] = sorted(plain)
    if by_labels:
        out["patterns"] = [{"patterns": pats, "labels": list(labels)} for labels, pats in by_labels.items()]
    return out


# ── the skill layer, listed ──────────────────────────────────────────────────

def _methods(kind: str, full: bool) -> dict:
    ms = skill.methods_for(kind)
    if not full:
        return {kind: [m.name for m in ms]}
    return {kind: [{"name": m.name, "describes": m.describes, "authority": m.authority,
                    "fails_when": m.fails_when, "params": list(m.params_schema.get("properties", {})),
                    "yields": list(m.yields)} for m in ms]}


def _procedures(kind: str, full: bool) -> list:
    ps = skill.procedures_for(kind)
    if not full:
        return [{"name": p.name, "question": p.question} for p in ps]
    return [{"name": p.name, "question": p.question, "gather": list(p.gather), "compute": list(p.compute),
             "compare": list(p.compare), "close": list(p.close), "absent": p.absent, "authority": p.authority}
            for p in ps]


def _readings() -> list:
    return [{"method": r.method, "compare_within": r.compare_within, "reads": r.reads,
             "meaningless_when": r.meaningless_when, "authority": r.authority}
            for r in skill.READINGS.values()]


def size_of(payload: dict) -> int:
    return len(json.dumps(payload, default=str))
