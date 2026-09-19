"""The desk's primitive tools (V1): twelve verbs over three resource families.

WHY THIS EXISTS. Until V1 an analyst had one computing tool, `run(program)`, and
a language to write programs in: forty-five primitives, forty-six methods, the
key paths of every table. The analyst was a quant developer, its handbook a
program library, and "wrote the wrong program" was a class of failure. The
boss's decision of 2026-09-19: a tool is a LOW-LEVEL, ORTHOGONAL verb over a
resource — see what is there, read one thing off a table, take a measure by
name, do one operation on figures, find something in a file — and a question
("has volatility risen?") is the analyst's, answered with the handbook, never a
tool. Research behind it (docs/IMPLEMENTATION_PLAN_V1.md §2.0): few orthogonal
primitives beat many specialised tools; measures are governed definitions asked
for by name; the first-order failures in finance are the period and the unit,
which a typed read settles and a sentence does not.

THE VERBS.
    list              what the desk holds (names and dates, never a figure)
    filings_read      one filed line of one issuer, over a stated period
    prices_read       a name's closes over a window, or one session's
    book_read         a run's or scenario's figures, off the table they sit on
    metric            a registry measure by name (analytics/registry.METHODS)
    calc              ONE operation over figures already shown (by their f_ ids)
    filings_search    passages of an issuer's filings that match a query
    filings_section   one Item of a filing, verbatim, a page at a time
    web_search        what the filings cannot hold
    scenario          the book after a sale or a purchase (a new book, by id)
    start             background preparation (returns an id, never evidence)
    submit            the analyst's exit — in-process (agents/delegation), not here

A FACE IS A RESOURCE FAMILY, AND IT IS STRUCTURE. `build_analyst_registry(face)`
registers only that analyst's verbs, with that analyst's names in each enum: the
market analyst's `metric` cannot spell `net_debt_to_ebitda`, and no description
has to say so. A need that crosses two families is a measure on the asker's list
(`book.position` for the issuer analyst; a name's beta, volatility and volume
for the risk manager), never a wider face.

EVERY CALL SAYS WHY. `why` is required by every schema: which line of the task
the step serves and why this verb. The trace records the arguments, so the
analyst's log is its own calls read in order — nobody writes a report.

EVERY RESULT IS ROWS (tools/registry.Tool.rows): one header, then the facts as
lines a trained reader needs no legend for (services/facts.line). A refusal is a
row too: an absence on the ledger, with its reason and its way out.

Each fn is a thin wrapper over the service that has always done the work; what a
payload puts on the table is made Facts by the adapter that already knows that
payload (services/fact_adapters.ADAPTERS).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.analytics import registry as desk
from exposure_workbench.analytics import resources
from exposure_workbench.db.models import CalcLedger, ExposureRun, Filing, FilingSection, MarketPrice
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import compute_service
from exposure_workbench.services import facts as F
from exposure_workbench.services import filing_retrieval_service as frs
from exposure_workbench.services import name_table as nt
from exposure_workbench.services import portfolio_service, run_reads_service
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.services.typed_calculator import SCENARIO_OP
from exposure_workbench.tools import definitions as D
from exposure_workbench.tools.meta_tools import _start as _start_work
from exposure_workbench.tools.registry import DELEGATION, READ, Shapes, Tool, ToolRegistry, current_session_id
from exposure_workbench.tools.research_tools import _search_external_research

FACES = desk.FACES                      # ("issuer", "market", "risk")


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


_WHY = {"type": "string",
        "description": "which line of your task this step serves and why this verb, in one sentence — your log is made of these"}
_TICKER = {"type": "string", "description": "a ticker, e.g. NVDA"}
_BOOK = {"type": "string", "description": "a book: a port_… id (its latest completed run), a run_… id, or the calc_… id of a book a scenario built"}


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**properties, "why": _WHY},
            "required": [*required, "why"], "additionalProperties": False}


# ── list ─────────────────────────────────────────────────────────────────────

LIST_WHAT: dict[str, tuple[str, ...]] = {
    "issuer": ("metrics", "fundamentals", "filings"),
    "market": ("metrics", "prices"),
    "risk": ("metrics", "book", "checks"),
}


def _metric_lines(names: list[str]) -> list[str]:
    """The measures THIS registry's `metric` takes, each with what it is."""
    out = []
    for m in (desk.METHODS[n] for n in names):
        takes = ", ".join(f"{k}∈{[e for e in (v.get('enum') or []) if e is not None]}" if v.get("enum") else k
                          for k, v in (m.params_schema.get("properties") or {}).items())
        out.append(f"{m.name} — {m.reads_as}: {m.describes}" + (f" [params: {takes}]" if takes else ""))
    return out


async def _fundamentals_lines(db: AsyncSession, ticker: str) -> list[str] | dict:
    company = await D._resolve_company(db, ticker)
    if company.get("error"):
        return company
    rows = (await cs.list_available_metrics(db, company["ticker"]))["metrics"]
    return [f"{r['metric']} — {dn.metric(r['metric'])}; {'a flow over a window' if r.get('kind') == 'flow' else 'a balance at a date'}; "
            f"filed through {r.get('latest_period_end')}" for r in sorted(rows, key=lambda r: r["metric"])]


async def _filings_lines(db: AsyncSession, ticker: str) -> list[str] | dict:
    company = await D._resolve_company(db, ticker)
    if company.get("error"):
        return company
    forms = (await db.execute(select(Filing.form_type, func.max(Filing.filing_date))
                              .where(Filing.company_id == company["id"]).group_by(Filing.form_type))).all()
    items = (await db.execute(select(FilingSection.item_code).join(Filing, Filing.id == FilingSection.filing_id)
                              .where(Filing.company_id == company["id"], FilingSection.item_code.is_not(None))
                              .group_by(FilingSection.item_code))).all()
    if not forms:
        return _err("not_indexed", f"{company['ticker']} has no filings indexed on this desk", hint="start(kind='readiness') prepares it")
    return ([f"{form} — latest filed {d.isoformat() if d else 'n/a'}" for form, d in sorted(forms)]
            + ["items indexed: " + ", ".join(sorted(i for (i,) in items))])


async def _prices_lines(db: AsyncSession, ticker: str) -> list[str] | dict:
    tk = ticker.upper()
    lo, hi, n = (await db.execute(select(func.min(MarketPrice.price_date), func.max(MarketPrice.price_date), func.count())
                                  .where(MarketPrice.ticker == tk))).one()
    if not n:
        return _err("no_price_data", f"{tk} has no price history on this desk", hint="start(kind='readiness') prepares it")
    return [f"{tk} — daily closes, adjusted closes and volume from {lo.isoformat()} to {hi.isoformat()}"]


def _table_lines() -> list[str]:
    return [f"table {r.table}" + (f" (one row per {r.label_column})" if r.label_column else " (one row)")
            + ": " + ", ".join(f"{c.name} — {c.display}" for c in r.columns) for r in resources.RUN_CHILDREN]


async def _book_lines(db: AsyncSession, subject: str | None) -> list[str] | dict:
    if not subject:
        snaps = await portfolio_service.snapshot_all(db)
        return [f"{s['portfolio_id']} — {s['name']}" for s in snaps]
    if subject.startswith("port_"):
        p = await portfolio_service.get_portfolio(db, subject)
        if p is None:
            snaps = await portfolio_service.snapshot_all(db)
            return _err("unknown_portfolio", f"no portfolio {subject} on this desk",
                        portfolios=[s["portfolio_id"] for s in snaps])
        held = (await portfolio_service.positions_with_weights(db, subject) or {}).get("holdings") or []
        runs = (await db.execute(select(ExposureRun.id, ExposureRun.as_of_date, ExposureRun.status)
                                 .where(ExposureRun.portfolio_id == subject)
                                 .order_by(ExposureRun.as_of_date.desc()).limit(5))).all()
        return ([f"{subject} — {p.name}"]
                + [f"holds {h['ticker']} — {h.get('sector') or 'sector n/a'}, {h.get('asset_class') or 'asset class n/a'}" for h in held]
                + [f"run {rid} — as of {d.isoformat()}, {status}" for rid, d, status in runs] + _table_lines())
    resolved = await _resolve_book(db, subject, None)
    if isinstance(resolved, dict):
        return resolved
    ref, as_of = resolved
    labels: dict[str, set[str]] = {}
    for q in (await qn.of_ref(db, ref)).quantities:
        parts = q.label.split(".")
        if len(parts) >= 3:
            labels.setdefault(parts[0], set()).add(".".join(parts[1:-1]))
    return ([f"{ref} — as of {as_of}"] + _table_lines()
            + [f"rows of {t}: " + ", ".join(sorted(rows)) for t, rows in sorted(labels.items())])


# what a check is a check ON, by the three entity types a limit has (db/models.RiskLimit); a
# fourth is a new kind of check and is named here before it is listed
_CHECKED = {"portfolio": "the whole book", "issuer": "one issuer", "sector": "one sector"}


async def _checks_lines(db: AsyncSession, subject: str | None) -> list[str] | dict:
    if not (subject or "").startswith("port_"):
        return _err("invalid_params", "checks are a portfolio's: give its port_… id")
    limits = await run_reads_service.list_risk_limits(db, subject)
    if isinstance(limits, dict) and limits.get("error"):
        return limits
    return [f"{l['limit_type']}" + (f":{l['entity_id']}" if l.get("entity_id") else "")
            + f" — a check on {_CHECKED[l.get('entity_type') or 'portfolio']}, with a warning and a breach tier"
            + ("" if l.get("is_active", True) else " (inactive)")
            for l in (limits.get("limits") or [])]


def _list_for(metric_names: list[str]):
    async def _list(db: AsyncSession, what: str, subject: str | None = None, *, why: str) -> dict:
        if what == "metrics":
            got: list[str] | dict = _metric_lines(metric_names)
        elif what == "book":
            got = await _book_lines(db, subject)
        elif what == "checks":
            got = await _checks_lines(db, subject)
        elif not subject:
            return _err("invalid_params", f"list(what='{what}') is about one name: give its ticker as `subject`")
        else:
            got = await {"fundamentals": _fundamentals_lines, "filings": _filings_lines, "prices": _prices_lines}[what](db, subject)
        return got if isinstance(got, dict) else {"catalogue": got}
    return _list


# ── the three reads ──────────────────────────────────────────────────────────

async def _filings_read(db: AsyncSession, ticker: str, line: str | None = None, months: int | None = None,
                        start: str | None = None, end: str | None = None, at: str | None = None,
                        last_n: int | None = None, *, why: str) -> dict:
    # 12.0 is an integer to a JSON schema and a TypeError to a slice: coerced here
    return await D._read_fundamentals(db, ticker, metric=line,
                                      months=int(months) if months is not None else None, start=start, end=end,
                                      last_n=int(last_n) if last_n is not None else None, at=at)


async def _prices_read(db: AsyncSession, ticker: str, window: str | None = None, date: str | None = None, *, why: str) -> dict:
    return await D._read_prices(db, ticker, window=window, as_of=date)


async def _resolve_book(db: AsyncSession, book: str, which: str | None) -> tuple[str, str | None] | dict:
    """(the run or scenario id the book is read at, its date) — or the refusal."""
    if book.startswith("calc_"):
        row = (await db.execute(select(CalcLedger).where(CalcLedger.id == book))).scalar_one_or_none()
        if row is None or row.operation != SCENARIO_OP:
            return _err("unknown_name", f"{book} is not a book a scenario built")
        return book, (row.params or {}).get("as_of")
    if book.startswith("run_"):
        run = await run_reads_service.completed_run(db, book)
        return run if isinstance(run, dict) else (run.id, run.as_of_date.isoformat())
    if not book.startswith("port_") or await portfolio_service.get_portfolio(db, book) is None:
        snaps = await portfolio_service.snapshot_all(db)
        return _err("unknown_portfolio", f"no book {book!r} on this desk",
                    portfolios=[s["portfolio_id"] for s in snaps])
    fresh = await run_reads_service.get_run_freshness(db, book)
    latest = fresh.get("latest_completed_run") if isinstance(fresh, dict) else None
    if not latest:
        return _err("no_completed_run", f"{book} has no completed run", hint="start(kind='exposure_run') runs the book")
    run = await run_reads_service.completed_run(db, latest)
    if isinstance(run, dict):
        return run
    if which == "prior":
        prior = (await db.execute(
            select(ExposureRun).where(ExposureRun.portfolio_id == book, ExposureRun.status == "completed",
                                      ExposureRun.as_of_date < run.as_of_date)
            .order_by(ExposureRun.as_of_date.desc(), ExposureRun.created_at.desc()).limit(1))).scalar_one_or_none()
        if prior is None:
            return _err("no_prior_run", f"{book} has no completed run before {run.as_of_date.isoformat()}")
        run = prior
    return run.id, run.as_of_date.isoformat()


BOOK_TABLES: tuple[str, ...] = tuple(r.table for r in resources.RUN_CHILDREN) + ("count", "trade")


async def _book_read(db: AsyncSession, book: str, table: str, column: str | None = None, row: str | None = None,
                     which: str | None = None, *, why: str) -> dict:
    resolved = await _resolve_book(db, book, which)
    if isinstance(resolved, dict):
        return resolved
    ref, as_of = resolved
    quantities = [q for q in (await qn.of_ref(db, ref)).quantities if q.label.split(".")[0] == table]
    if not quantities:
        return _err("not_held", f"{ref} holds no figures on {table}", tables=sorted(BOOK_TABLES))

    def parts(label: str) -> tuple[str | None, str]:
        rest = label.split(".", 1)[1]
        return (rest.rsplit(".", 1)[0], rest.rsplit(".", 1)[1]) if "." in rest else (None, rest)

    rows = sorted({r for r, _c in map(parts, (q.label for q in quantities)) if r})
    columns = sorted({c for _r, c in map(parts, (q.label for q in quantities))})
    if column is not None and column not in columns:
        return _err("unknown_name", f"{table} has no column {column!r} on {ref}", columns_of_table=columns)
    if row is not None and row not in rows:
        return _err("unknown_name", f"{table} has no row {row!r} on {ref}", available=rows[:40])
    wanted = [q for q in quantities
              if (column is None or parts(q.label)[1] == column) and (row is None or parts(q.label)[0] == row)]
    return {"book": ref, "as_of": as_of, "table": table,
            "figures": [{"name": q.label, "value": q.value, "unit_class": q.unit_class, "means": q.means or {}}
                        for q in wanted if q.not_alone is None],
            "withheld": [{"name": q.label, "reason": q.not_alone} for q in wanted if q.not_alone is not None]}


# ── a measure by name; one operation over figures ────────────────────────────

async def _at_its_run(db: AsyncSession, subject):
    """A BOOK IS NAMED ONE WAY ON EVERY VERB: a port_… id is its latest completed
    run, as `book_read` and `scenario` read it. A measure over a run was the one
    place that did not hold — the smoke asked book.analysis of port_001 and was
    told no such run exists. One book that cannot be resolved is refused with
    the resolver's reason (no completed run: start one); in a list it is left
    as it was written, and the measure refuses that one subject in its own row."""
    one = isinstance(subject, str)
    out = []
    for s in ([subject] if one else list(subject or [])):
        if isinstance(s, str) and s.startswith("port_"):
            resolved = await _resolve_book(db, s, None)
            if isinstance(resolved, dict):
                if one:
                    return resolved
                out.append(s)
                continue
            s = resolved[0]
        out.append(s)
    return out[0] if one else out


def _metric_for(face: str):
    async def _metric(db: AsyncSession, name: str, subject, params: dict | None = None, *, why: str) -> dict:
        spec = desk.METHODS.get(name)
        if spec is not None and spec.subject_kind == "run":
            subject = await _at_its_run(db, subject)
            if isinstance(subject, dict):
                return subject
        return await compute_service.compute(db, method=name, subject=subject, params=params)
    return _metric


CALC_OPS: tuple[str, ...] = ("add", "subtract", "multiply", "divide", "scale", "rank", "top", "filter",
                             "sum", "avg", "min", "max", "std", "abs", "yoy", "qoq", "pct", "cagr", "latest")
_COMPARE = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


async def _level(db: AsyncSession, level) -> float | dict:
    """A filter's level: the f_ id of a figure, or a figure WRITTEN AS THE DESK
    SHOWS ONE — "8%", "$1.5M", "2.0×" — read in that marker's terms. A weight is
    stored as a fraction and shown as a percentage; the analyst never converts."""
    if isinstance(level, str) and level.startswith("f_"):
        t = await tc._resolve(db, level)
        return t if isinstance(t, dict) else float(t.value)
    written = Ledger.written(str(level))
    if written is None:
        return _err("invalid_params", f"level {level!r} is neither an f_ id nor a figure as the desk writes one (8%, $1.5M, 2.0×)")
    return written[0]


async def _filter(db: AsyncSession, inputs: list[str], cmp: str | None, level) -> dict:
    if cmp not in _COMPARE or level is None:
        return _err("invalid_params", "filter takes cmp (one of > >= < <= == !=) and level", allowed=list(_COMPARE))
    lvl = await _level(db, level)
    if isinstance(lvl, dict):
        return lvl
    kept, seen = [], []
    for fid in inputs:
        t = await tc._resolve(db, fid)
        if isinstance(t, dict):
            return t | {"at": fid}
        seen.append(float(t.value))
        if _COMPARE[cmp](float(t.value), lvl):
            kept.append(fid)
    if not kept:
        return _err("no_entry_satisfies", f"none of the {len(inputs)} figures is {cmp} {level}; they run "
                                          f"{min(seen):g} to {max(seen):g} in their own unit")
    counted = await tc.constant(db, float(len(kept)), unit_class="count", invoked_by=current_session_id())
    if counted.get("error"):
        return counted
    return {**counted, "quantity": f"figures {cmp} {level}, of the {len(inputs)} given", "op": "filter", "kept": kept}


async def _calc(db: AsyncSession, op: str, inputs: list[str], by: str | None = None, factor: float | None = None,
                direction: str | None = None, n: int | None = None, cmp: str | None = None, level=None,
                name: str | None = None, *, why: str) -> dict:
    if op == "filter":
        return await _filter(db, inputs, cmp, level)
    params = {k: v for k, v in (("by", by), ("factor", factor)) if v is not None}
    out = await compute_service.compute(db, op="rank" if op == "top" else op, operands=list(inputs),
                                        params=params, as_quantity=name, direction=direction)
    if op == "top" and not out.get("error"):
        if not isinstance(n, int) or n < 1:
            return _err("invalid_params", "top takes n, a positive integer")
        out["ordering"] = (out.get("ordering") or [])[:n]
        out.pop("spread", None)     # highest to lowest of ALL the inputs: beside the first n it reads as theirs
    return out


# ── the text ─────────────────────────────────────────────────────────────────

async def _filings_search(db: AsyncSession, ticker: str, query: str, item: str | None = None,
                          form: str | None = None, filed_after: str | None = None, k: int = 5, *, why: str) -> dict:
    company = await D._resolve_company(db, ticker)
    if company.get("error"):
        return company
    from datetime import date as _date
    try:
        after = _date.fromisoformat(filed_after) if filed_after else None
    except ValueError:
        return _err("invalid_params", f"filed_after {filed_after!r} is not a YYYY-MM-DD date")
    code = (item if item.lower().startswith("item") else f"Item {item}") if item else None
    try:
        passages = await frs.search_passages(db, company["id"], query, k=int(k), form_type=form,
                                             item_code=code, filed_after=after)
    except frs.NotIndexed:
        return _err("not_indexed", f"{company['ticker']} has no filings indexed", hint="start(kind='readiness') indexes them")
    return {"ticker": company["ticker"], "query": query,
            "passages": [{"chunk_id": p.chunk_id, "text": p.text, "item": p.item_code,
                          "section_title": p.section_title, "citation": p.citation()} for p in passages]}


async def _filings_section(db: AsyncSession, ticker: str, item: str, form: str | None = None, offset: int = 0, *, why: str) -> dict:
    out = await D._read_filings(db, ticker, item=item, form_type=form)
    if out.get("error") or not isinstance(out.get("text"), str):
        return out
    text, start = out["text"], max(0, int(offset or 0))
    page = text[start:start + F.PASSAGE_CHARS]
    if not page:
        return _err("invalid_params", f"offset {start} is past the end of this section ({len(text)} characters)")
    more = start + len(page) < len(text)
    return {**out, "text": page, **({"next_offset": start + len(page)} if more else {})}


async def _web_search(db: AsyncSession, ticker: str, query: str, days: int | None = None, *, why: str) -> dict:
    return await _search_external_research(db, ticker, query, reason=why, days=days)


# ── the two actions ──────────────────────────────────────────────────────────

async def _scenario(db: AsyncSession, book: str, sales: list | None = None, buys: list | None = None, *, why: str) -> dict:
    if (sales is None) == (buys is None):
        return _err("invalid_params", "a scenario is ONE trade list: give `sales` or `buys`; to do both, run the "
                                      "sale, then run the purchase on the book it made (its calc_… id)")
    resolved = await _resolve_book(db, book, None)
    if isinstance(resolved, dict):
        return resolved
    out = await compute_service.compute(db, method="book.sell" if sales is not None else "book.buy",
                                        subject=resolved[0],
                                        params={"sales": sales} if sales is not None else {"buys": buys})
    if isinstance(out, dict) and not out.get("error") and isinstance(out.get("calc_id"), str):
        out["made"] = out["calc_id"]           # the new book, by the id `book_read` and `scenario` take
    return out


START_KINDS: dict[str, tuple[str, ...]] = {"issuer": ("readiness",), "market": ("readiness",), "risk": ("exposure_run",)}


def _start_for(face: str):
    async def _start(db: AsyncSession, kind: str, subject: str, as_of_date: str | None = None, *, why: str) -> dict:
        return await _start_work(db, kind, subject, reason=why, as_of_date=as_of_date)
    return _start


# ── registration ─────────────────────────────────────────────────────────────

def _tools(face: str, measures_of: tuple[str, ...] | None = None, kinds: tuple[str, ...] | None = None,
           what: tuple[str, ...] | None = None) -> dict[str, Tool]:
    """Every verb, shaped for one face: `measures_of` are the faces whose measures
    `metric` may name, `kinds` what `start` may start, `what` what `list` may list."""
    metric_names = list(dict.fromkeys(m.name for f in (measures_of or (face,)) for m in desk.metrics_for(f)))
    start_kinds = list(kinds or START_KINDS[face])
    list_what = list(what or LIST_WHAT[face])
    t = {
        "list": Tool(
            name="list", display="Looking at what the desk holds", rows=True, tool_class=READ, fn=_list_for(metric_names),
            description="What the desk holds, as names and dates — never a figure. `metrics`: the measures you may ask for "
                        "by name, each with what it is and the params it takes. The others take a `subject` and list what "
                        "is there for it: filed lines and how far each is filed; filings and the Items indexed; the span of "
                        "prices; a book's holdings, runs, tables and rows (no subject: the desk's books); a book's checks.",
            json_schema=_schema({"what": {"type": "string", "enum": list_what},
                                 "subject": {"type": ["string", "null"], "description": "a ticker, or a port_/run_/calc_ id"}},
                                ["what"])),
        "filings_read": Tool(
            name="filings_read", display="Reading {ticker}'s filed figures", rows=True, tool_class=READ, fn=_filings_read,
            description="One filed line of one issuer, as filed (a restatement supersedes what it restates). A flow is read "
                        "over a window — `months` ending at the latest period or at `end`, or `start`..`end`; a balance at a "
                        "date (`at`; omitted = the latest). `last_n` gives the line's last N readings as one series. `line` "
                        "omitted: every balance at one date. The row states the period it HAS. Refused: a line this issuer "
                        "does not file (the lines it does are named); a flow asked `at` a date; a window the filings cannot make.",
            json_schema=_schema({"ticker": _TICKER,
                                 "line": {"type": ["string", "null"], "enum": [*nt.TABLE_FILED_LINES, None]},
                                 "months": {"type": ["integer", "null"], "enum": [3, 6, 9, 12, None]},
                                 "start": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                                 "end": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                                 "at": {"type": ["string", "null"], "description": "YYYY-MM-DD, a reported period end"},
                                 "last_n": {"type": ["integer", "null"], "minimum": 1, "maximum": 40}}, ["ticker"])),
        "prices_read": Tool(
            name="prices_read", display="Reading {ticker}'s prices", rows=True, tool_class=READ, fn=_prices_read,
            description="A name's daily adjusted closes over a named window, as one series — or, with `date` (or neither), "
                        "one session's close and adjusted close. A price statistic (volatility, beta, a drawdown, volume) is "
                        "a measure: ask `metric` for it by name. Refused: a name with no price history here.",
            json_schema=_schema({"ticker": _TICKER,
                                 "window": {"type": ["string", "null"], "enum": ["1m", "3m", "6m", "1y", "3y", None]},
                                 "date": {"type": ["string", "null"], "description": "YYYY-MM-DD; omitted = the latest session"}},
                                ["ticker"]),
            shapes=Shapes(("window", "date"), "window reads a series and date reads one session: give one of them")),
        "book_read": Tool(
            name="book_read", display="Reading {table} of {book}", rows=True, tool_class=READ, fn=_book_read,
            description="Figures of a book, off the table they sit on: one `column` for every row, one `row` across its "
                        "columns, one cell, or the whole table. A port_… id reads its latest completed run (`which`='prior': "
                        "the one before); a run_… or a scenario's calc_… id reads that book. A check's figures say where the "
                        "check stands; a coefficient of a collinear fit is withheld, with the figure that IS determined named. "
                        "Refused: a table, column or row the book does not hold (what it does hold is named).",
            json_schema=_schema({"book": _BOOK, "table": {"type": "string", "enum": list(BOOK_TABLES)},
                                 "column": {"type": ["string", "null"]}, "row": {"type": ["string", "null"],
                                 "description": "a row's label as `list` shows it: a ticker, a sector, a check"},
                                 "which": {"type": ["string", "null"], "enum": ["latest", "prior", None]}},
                                ["book", "table"])),
        "metric": Tool(
            name="metric", display="Measuring {name} for {subject}", rows=True, tool_class=READ, fn=_metric_for(face),
            description="A measure of this desk's registry, by name, over one subject or a list of them (one row each, or "
                        "each one's own refusal). The definition is the registry's: what it was built on, which filed line "
                        "stood in for which, and what a composed total left out come back on the row. `list(what='metrics')` "
                        "names every measure you may ask for and the params each takes. Refused: a subject the measure has "
                        "no meaning for, an input not filed, too little history — each with its reason.",
            json_schema=_schema({"name": {"type": "string", "enum": metric_names},
                                 "subject": {"type": ["string", "array"], "items": {"type": "string"}, "maxItems": 40,
                                             "description": "a ticker, a run_/port_ id, or a list of them — what the measure says it is over"},
                                 "params": {"type": ["object", "null"]}}, ["name", "subject"])),
        "calc": Tool(
            name="calc", display="Computing {op}", rows=True, tool_class=READ, fn=_calc,
            description="ONE operation over figures you were already shown, named by their f_ ids — never a number typed "
                        "in. add/multiply take two or more; subtract/divide exactly two, or a list each combined with `by`; "
                        "scale takes one and `factor`; rank orders two or more (`direction`), top keeps its first `n`; "
                        "filter keeps those `cmp` a `level` (an f_ id, or a figure written as the desk shows one: 8%, $1.5M); "
                        "sum/avg/min/max/std/abs are over a set; yoy/qoq/pct/cagr/latest over ONE series. The result is a new "
                        "figure with what it was made of. Refused: units, periods or books that do not combine — it says which.",
            json_schema=_schema({"op": {"type": "string", "enum": list(CALC_OPS)},
                                 "inputs": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 40},
                                 "by": {"type": ["string", "null"]}, "factor": {"type": ["number", "null"]},
                                 "direction": {"type": ["string", "null"], "enum": ["highest", "lowest", None]},
                                 "n": {"type": ["integer", "null"], "minimum": 1, "maximum": 40},
                                 "cmp": {"type": ["string", "null"], "enum": [*_COMPARE, None]},
                                 "level": {"type": ["string", "number", "null"]},
                                 "name": {"type": ["string", "null"], "description": "what to call the result, in words"}},
                                ["op", "inputs"])),
        "filings_search": Tool(
            name="filings_search", display="Searching {ticker}'s filings", rows=True, tool_class=READ, fn=_filings_search,
            description="Passages of one issuer's filings that match a query, each quotable verbatim under its id, with the "
                        "form, Item and accession it came from. Narrow with `item`, `form` or `filed_after`. A figure stated "
                        "only in prose is quoted from here, never computed. Refused: filings not indexed.",
            json_schema=_schema({"ticker": _TICKER, "query": {"type": "string", "minLength": 3},
                                 "item": {"type": ["string", "null"], "description": "'1A', '7', '7A', …"},
                                 "form": D._FORM_TYPE, "filed_after": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                                 "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}, ["ticker", "query"])),
        "filings_section": Tool(
            name="filings_section", display="Reading Item {item} of {ticker}'s filing", rows=True, tool_class=READ,
            fn=_filings_section,
            description="One Item of the latest filing, verbatim, a page at a time: `next_offset` comes back while there is "
                        "more. Refused: an Item the filing does not have.",
            json_schema=_schema({"ticker": _TICKER, "item": {"type": "string", "description": "'1', '1A', '7', '7A', '8', …"},
                                 "form": D._FORM_TYPE, "offset": {"type": "integer", "minimum": 0, "default": 0}},
                                ["ticker", "item"])),
        "web_search": Tool(
            name="web_search", display="Searching the web about {ticker}", rows=True, tool_class=DELEGATION,
            fn=_web_search, budget_key="external_search",
            description="What the filings cannot hold: recent items about one issuer from the web, each a source quotable "
                        "under its id with its publisher and date. Refused: a name that is not a listed SEC filer.",
            json_schema=_schema({"ticker": _TICKER, "query": {"type": "string", "minLength": 3},
                                 "days": {"type": ["integer", "null"], "minimum": 1, "maximum": 365}}, ["ticker", "query"])),
        "scenario": Tool(
            name="scenario", display="Building the book after a trade", rows=True, tool_class=READ, fn=_scenario,
            description="The book after ONE list of sales or of purchases: weights, sector weights, market value, and every "
                        "concentration and exposure check re-run — a NEW book, returned by its id (`made`), which `book_read` "
                        "and `scenario` take, so trades chain. It re-prices and re-checks; it does not re-fit betas, "
                        "volatility or P&L. Refused: a name not held or sold twice, a weight outside (0, 1), a name with no "
                        "sector on this desk, a name already held bought again.",
            json_schema=_schema({"book": _BOOK,
                                 "sales": desk.METHODS["book.sell"].params_schema["properties"]["sales"] | {"type": ["array", "null"]},
                                 "buys": desk.METHODS["book.buy"].params_schema["properties"]["buys"] | {"type": ["array", "null"]}},
                                ["book"]),
            shapes=Shapes(("sales", "buys"), "one trade list a call: a sale, then a purchase on the book it made")),
        "start": Tool(
            name="start", display="Starting {kind} for {subject}", rows=True, tool_class=DELEGATION, fn=_start_for(face),
            description="Background preparation, returning an id at once and NEVER evidence: `readiness` puts a listed SEC "
                        "filer on the desk (filings, facts, prices — a couple of minutes); `exposure_run` runs a book as it "
                        "is. Once per subject is enough; say it is being prepared.",
            json_schema=_schema({"kind": {"type": "string", "enum": start_kinds},
                                 "subject": {"type": "string", "description": "a ticker (readiness) or a port_… id (exposure_run)"},
                                 "as_of_date": {"type": ["string", "null"], "description": "YYYY-MM-DD; exposure_run only"}},
                                ["kind", "subject"])),
    }
    return t


# which verbs each analyst has; `submit` is in-process and the same for all three
FACE_TOOLS: dict[str, tuple[str, ...]] = {
    "issuer": ("list", "filings_read", "metric", "calc", "filings_search", "filings_section", "web_search", "start"),
    "market": ("list", "prices_read", "metric", "calc", "start"),
    "risk": ("list", "book_read", "metric", "calc", "scenario", "start"),
}


# THE RESEARCH RUN (agents/research_session) writes an Issuer Risk Brief: an issuer
# from its filings AND its price, so it holds the issuer analyst's verbs, the
# price read, and both families' measures. It starts nothing: the workflow that
# runs it has prepared the name already.
RESEARCH_TOOLS: tuple[str, ...] = ("list", "filings_read", "prices_read", "metric", "calc",
                                   "filings_search", "filings_section", "web_search")
# THE DEBUG DOOR (apps/mcp/server, the mount named "meta"): every verb, for a
# person at a terminal. No agent holds this face — the lead holds none at all.
DESK_TOOLS: tuple[str, ...] = ("list", "filings_read", "prices_read", "book_read", "metric", "calc",
                               "filings_search", "filings_section", "web_search", "scenario", "start")
_EVERYTHING = tuple(dict.fromkeys(w for f in FACES for w in LIST_WHAT[f]))


def _registry(names: tuple[str, ...], tools: dict[str, Tool]) -> ToolRegistry:
    reg = ToolRegistry()
    for name in names:
        reg.register(tools[name])
    return reg


def build_research_verbs() -> ToolRegistry:
    return _registry(RESEARCH_TOOLS, _tools("issuer", measures_of=("issuer", "market"),
                                            what=("metrics", "fundamentals", "filings", "prices")))


def build_desk_registry() -> ToolRegistry:
    return _registry(DESK_TOOLS, _tools("risk", measures_of=FACES, what=_EVERYTHING,
                                        kinds=tuple(dict.fromkeys(k for f in FACES for k in START_KINDS[f]))))


def build_analyst_registry(face: str) -> ToolRegistry:
    """One analyst's tools and nothing else: the face is what is REGISTERED, so a
    verb or a measure of another family is not refused — it does not exist here."""
    if face not in FACES:
        raise ValueError(f"face {face!r} is not one of {FACES}")
    reg, tools = ToolRegistry(), _tools(face)
    for name in FACE_TOOLS[face]:
        reg.register(tools[name])
    return reg
