"""The one place a citable quantity gets its name (V15-S2a).

WHY THIS EXISTS. Until V15 the full name of a quantity — `issuer_exposures.MSFT.
weight`, `portfolio.integration.net_beta.equity_down` — was built inside the
numeric gate, at refusal time, out of the resolver's own walk over the cited
rows. The model never saw it: the tool payload said `weight`, and the gate
answered `unknown_label` with the sixty names it had just invented. Measured on
196 real refusals: 123 label ambiguities, every one of them a name the model was
never handed.

So the walk moves here, and it runs ONCE per fact: the same function names a
quantity for the table the model reads (services/table.py) and for the table the
gate resolves against. There is no second spelling to drift.

WHAT A NAME IS. Under one ref, a name is unique (test_quantities pins it on a
real run). The parts come from two declarations that stay separate on purpose
(analytics/resources.py's docstring): `resources` says which COLUMNS carry a
value and in what unit, `display_names` says what a VALUE is called — and the
name of a run child is `<table>.<row label>.<column>`. A ledger row's name is its
operation, with the period or the declared key appended when the row holds more
than one figure.

`not_alone` (V11-F) is carried and not decided here: a collinear coefficient is a
quantity the run holds and the answer may not use alone. The table builder is
where that becomes a projection — the coefficient never reaches the model — and
the resolver is where a name that survived anyway is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import resources
from exposure_workbench.analytics import units
from exposure_workbench.db.models import (
    CalcLedger,
    Company,
    ExposureMetrics,
    FactorAttribution,
    FilingChunk,
    FinancialFact,
    Position,
    ResearchSource,
    RiskAlert,
)

# The unit classes. numeric_verification asserts these are the same strings
# (test_resources); resources.py declares MONEY / RATIO / COUNT.
PERCENT = "PERCENT"
RATIO = "RATIO"
MONEY = "MONEY"
COUNT = "COUNT"
MULTIPLE = "MULTIPLE"
MONEY_PER_SHARE = "MONEY_PER_SHARE"

# units.fact_unit speaks the algebra's lowercase names; the gate speaks these.
# One total bridge over the algebra's classes, so a stored fact's unit is
# judged once (analytics/units.py) and only translated here.
_UNIT_CLASS_OF = {units.MONEY: MONEY, units.RATIO: RATIO, units.COUNT: COUNT,
                  units.MONEY_PER_SHARE: MONEY_PER_SHARE, units.MULTIPLE: MULTIPLE}

# What a ledger row IS, for the assertion checks (trend needs a series, absence
# needs a refusal). `scalar` is everything else a calc row can be.
KIND_SCALAR = "scalar"
KIND_SERIES = "series"
KIND_ABSENCE = "absence"

_SERIES_OPS = ("series", "flow.series", "balance.series", "change.")
_ABSENCE_PREFIX = "absence."
# The ordering row's operation, named once in the calculator that writes it.
from exposure_workbench.services.typed_calculator import RANK_OP  # noqa: E402


@dataclass(frozen=True)
class Quantity:
    """One number a cited row holds: what it is worth, what unit, what it is called.

    `label` is the unique name under `source_id`. `table` is the run child it
    came from (None for anything that is not a run), which is what a tool's
    declared scope filters on.
    """

    value: float
    unit_class: str
    label: str
    source_id: str
    # V11-F. Set when the row itself says this number is not determinate on its
    # own. The regression records collinearity (max VIF above 5), under which the
    # SUM over the factor set is well determined and no single coefficient is.
    not_alone: str | None = None
    table: str | None = None
    # V16 (M2). Which question this figure answers — a key of
    # resources.GROUP_QUESTIONS. The table prints it beside the value with one
    # legend per payload, so the model reads meaning, not only a name.
    group: str = "other"


# The name the gate has used for this since V3; kept so the daily-report path and
# its tests read as they always have. One class, two names, no second copy.
EvidenceValue = Quantity


@dataclass(frozen=True)
class Resolved:
    """Everything one ref holds: its quantities, its prose digits, what it is."""

    quantities: tuple[Quantity, ...]
    quoted: frozenset[str]          # digit keys a passage literally contains
    kind: str | None                # scalar | series | absence | passage | source | run | fact | alert | position
    text: str | None = None         # the passage, for chunk_/src_
    # V19. Who the row is ABOUT, when that is not in the names it holds: a
    # get_flow series is `net_income@2025-12-31` for every issuer and the
    # issuer sits in the ledger row's params. The table renderer prefixes it
    # when deriving a comparison table's row labels; the gate never reads it.
    subject: str | None = None


# A calc's unit is fully determined by its operation name and nothing else —
# TRANSITIONAL, and shrinking: a calc row now carries its own unit_class
# (v15_calc_unit.sql). This set types rows written before that column existed.
_CALC_RATIO_OPS = resources.LEGACY_RATIO_OPS
_CALC_RESULT_KEYS: dict[str, dict[str, str]] = resources.CALC_RESULTS

# run_ resolves through its children: exposure_runs itself has no numeric column.
# Derived from analytics/resources.py (V15-S1), where "these columns carry values,
# in these units" is written once.
_RUN_CHILDREN = tuple(
    (r.model,
     tuple(c.name for c in r.columns if c.unit == MONEY),
     tuple(c.name for c in r.columns if c.unit == RATIO),
     r.label_column,
     r.qualifier_column)
    for r in resources.RUN_CHILDREN
)
_RUN_COUNTS = resources.countable()

# Every run child a scope can name, in declaration order, plus the two synthetic
# families a run resolves to: its counts, and the sum the regression determines.
RUN_TABLES: tuple[str, ...] = tuple(r.table for r in resources.RUN_CHILDREN) + ("count",)


# The period a series point is dated by, under the key its producer wrote.
# READ side only, and FROZEN (test_quantities pins the tuple): since V16 every
# writer uses units.POINT_PERIOD_KEY — the first entry here — and the other
# two keys exist to read rows the three-producer era already wrote ("end" on
# interval windows, "as_of" on balance readings). This tuple dies with those
# rows; it does not grow.
_POINT_PERIOD_KEYS = ("period_end", "end", "as_of")


def _point_period(point: dict) -> str:
    for key in _POINT_PERIOD_KEYS:
        v = (point or {}).get(key)
        if v:
            return str(v)
    return "?"


def calc_kind(row: CalcLedger) -> str:
    op = row.operation or ""
    if op.startswith(_ABSENCE_PREFIX):
        return KIND_ABSENCE
    if (row.result or {}).get("points") or op.startswith(_SERIES_OPS):
        return KIND_SERIES
    return KIND_SCALAR


def _numbers_in(payload, prefix: str, out: list, source_id: str) -> None:
    """Numeric leaves of a JSONB blob, as COUNT values (calc quality_flags)."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            _numbers_in(v, f"{prefix}.{k}", out, source_id)
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            _numbers_in(v, f"{prefix}[{i}]", out, source_id)
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        out.append(Quantity(float(payload), COUNT, prefix, source_id))


def _calc_unit(row: CalcLedger) -> str:
    """The row's own column first, then the params blob, then the legacy table."""
    if row.unit_class in (MONEY, RATIO, COUNT, MONEY_PER_SHARE, MULTIPLE):
        return row.unit_class
    recorded = ((row.params or {}).get("result_type") or {}).get("unit_class")
    if recorded in units.UNIT_CLASSES:
        return _UNIT_CLASS_OF[recorded]
    return RATIO if row.operation in _CALC_RATIO_OPS else MONEY


async def _from_calc(db: AsyncSession, cid: str) -> Resolved:
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == cid))).scalar_one_or_none()
    if row is None:
        return Resolved((), frozenset(), None)
    unit = _calc_unit(row)
    result = row.result or {}
    values: list[Quantity] = []
    # What the row says it is a quantity OF — the metric a series carries, the
    # measure a formula named its final step — is the name; the operation is
    # the name only for a row that recorded no quantity. A model asked for
    # net_margin and shown `calc.scalar.divide` wrote the name it knew.
    quantity = ((row.params or {}).get("result_type") or {}).get("quantity")
    head = quantity if isinstance(quantity, str) and quantity else row.operation
    if row.operation == RANK_OP:
        return _from_ranking(row, head, unit, cid)
    if "points" in result:
        for p in result.get("points") or []:
            v = (p or {}).get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values.append(Quantity(float(v), unit, f"{head}@{_point_period(p)}", cid))
    v = result.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        values.append(Quantity(float(v), unit, head, cid))
    for key, key_unit in _CALC_RESULT_KEYS.get(row.operation, {}).items():
        kv = result.get(key)
        for i, item in enumerate(kv if isinstance(kv, list) else [kv]):
            if isinstance(item, dict):
                iv, name = item.get("value"), item.get("label")
                if isinstance(iv, (int, float)) and not isinstance(iv, bool) and isinstance(name, str):
                    values.append(Quantity(float(iv), key_unit, f"{row.operation}.{key}.{name}", cid))
                continue
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                label = f"{row.operation}.{key}" + (f"[{i}]" if isinstance(kv, list) else "")
                values.append(Quantity(float(item), key_unit, label, cid))
    _numbers_in(result.get("quality_flags") or {}, "quality_flags", values, cid)
    # The group: a label that is one of a run's families (a portfolio.integration
    # row's net betas and rooms) keeps that family; otherwise the row's head
    # decides — a measure the formula registry defines is `derived`, everything
    # else is a filed figure or a read over filed figures.
    fallback = ("price" if (row.operation or "").startswith("price.")
                else "derived" if head in fm.FORMULAS else "fundamentals")
    values = [replace(q, group=resources.group_of(q.label) or fallback) for q in values]
    # The ledger's company_id column holds the TICKER the row is about (a plain
    # column, so SPY and the like fit); the params carry one only on the price
    # rows. Column first, params second, and nothing for a row about no single
    # issuer (a typed-calculator combination across two).
    ticker = getattr(row, "company_id", None) or (row.params or {}).get("ticker")
    return Resolved(tuple(values), frozenset(), calc_kind(row),
                    subject=ticker.upper() if isinstance(ticker, str) and ticker else None)


def _from_ranking(row: CalcLedger, head: str, unit: str, cid: str) -> Resolved:
    """The names an ordering puts on the table (V17).

    An ordering is the one row whose POINT is the relation between its entries,
    so what it publishes is a place per entry as well as a value per entry:
    `accruals_ratio.rank.JPM` is 1 or it is not, and an answer that says JPM is
    the highest can slot the ordinal that says so. The leader is a label rather
    than a figure and is not a quantity — it rides in the payload, where a
    ticker is text the model may write.
    """
    entries = (row.result or {}).get("ordering") or []
    values: list[Quantity] = []
    for e in entries:
        label, value, place = e.get("label"), e.get("value"), e.get("rank")
        if not isinstance(label, str):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(Quantity(float(value), unit, f"{head}.{label}", cid))
        if isinstance(place, int):
            values.append(Quantity(float(place), COUNT, f"{head}.rank.{label}", cid))
    spread = (row.result or {}).get("spread")
    if isinstance(spread, (int, float)) and not isinstance(spread, bool):
        values.append(Quantity(float(spread), unit, f"{head}.spread", cid))
    values.append(Quantity(float(len(entries)), COUNT, f"{head}.ranked", cid))
    fallback = "derived" if head in fm.FORMULAS else "fundamentals"
    values = [replace(q, group=resources.group_of(q.label) or fallback) for q in values]
    return Resolved(tuple(values), frozenset(), calc_kind(row))


async def _from_fact(db: AsyncSession, fid: str) -> Resolved:
    row = (await db.execute(select(FinancialFact).where(FinancialFact.id == fid))).scalar_one_or_none()
    if row is None or row.value is None:
        return Resolved((), frozenset(), None)
    unit = units.fact_unit(row.unit)
    if unit is None:
        # A unit the desk has no algebra for — a segment count, MWh, jobs
        # (analytics/units.py returns None). The row is real and stays citable,
        # but it puts no figure on the table: the resolver's own refusal
        # ("this id holds no figures; it can be cited, not slotted") is the
        # trace the model sees, the same one a passage gets.
        return Resolved((), frozenset(), "fact")
    unit_class = _UNIT_CLASS_OF[unit]
    company_id = getattr(row, "company_id", None)
    ticker = None
    if db is not None and company_id:
        ticker = (await db.execute(select(Company.ticker).where(Company.id == company_id))).scalar_one_or_none()
    return Resolved((Quantity(float(row.value), unit_class,
                              f"{row.normalized_metric or row.raw_concept}@{row.period_end}", fid,
                              group="price" if unit_class == MONEY_PER_SHARE else "fundamentals"),),
                    frozenset(), "fact", subject=ticker)


# What an alert row carries is declared once, in resources.py, beside the other
# run children; reading the declaration here is what deleted the hand-written
# second copy of the three columns (test_symmetry pins the derivation).
_ALERT_COLUMNS = next(r for r in resources.RUN_CHILDREN if r.model is RiskAlert).columns


async def _from_alert(db: AsyncSession, aid: str) -> Resolved:
    row = (await db.execute(select(RiskAlert).where(RiskAlert.id == aid))).scalar_one_or_none()
    if row is None:
        return Resolved((), frozenset(), None)
    return Resolved(tuple(
        Quantity(float(v), c.unit, c.name, aid, group="mandate")
        for c in _ALERT_COLUMNS
        if (v := getattr(row, c.name)) is not None
    ), frozenset(), "alert")


def _row_label(row, label_col: str | None, qualifier_col: str | None) -> str:
    if not label_col:
        return ""
    who = str(getattr(row, label_col))
    q = getattr(row, qualifier_col, None) if qualifier_col else None
    if q:
        who = f"{who}:{q}"
    return f".{who}"


async def _from_run(db: AsyncSession, rid: str) -> Resolved:
    """exposure_runs has no numeric columns — every number lives on a child."""
    out: list[Quantity] = []
    by_model: dict[type, list] = {}
    for model, abs_cols, ratio_cols, name_col, qual_col in _RUN_CHILDREN:
        rows = (await db.execute(select(model).where(model.run_id == rid))).scalars().all()
        by_model[model] = list(rows)
        table = model.__tablename__
        for row in rows:
            who = _row_label(row, name_col, qual_col)
            for cols, unit in ((abs_cols, MONEY), (ratio_cols, RATIO)):
                for col in cols:
                    v = getattr(row, col, None)
                    if v is not None:
                        out.append(Quantity(float(v), unit, f"{table}{who}.{col}", rid, table=table))

    # Under collinearity a single beta is not identified; the sum is.
    metrics = next(iter(by_model.get(ExposureMetrics) or []), None)
    fa_table = FactorAttribution.__tablename__
    if metrics is not None and getattr(metrics, "collinear", None):
        total = sum(float(r.contribution) for r in by_model.get(FactorAttribution) or []
                    if r.contribution is not None)
        instead = (f"these factors are collinear, so no single beta is determined; "
                   f"their sum, {total:.8f}, is")
        out = [q if not q.label.startswith(f"{fa_table}.")
               else Quantity(q.value, q.unit_class, q.label, q.source_id, instead, q.table)
               for q in out]
        out.append(Quantity(total, RATIO, f"{fa_table}.sum_of_contributions", rid, table=fa_table))

    # V8-P4: the counts, as COUNT. Zero is emitted as a value.
    for model, label, split in _RUN_COUNTS:
        rows = by_model.get(model)
        if rows is None:
            continue
        out.append(Quantity(float(len(rows)), COUNT, f"count.{label}", rid, table="count"))
        if split is None:
            continue
        seen: dict[str, int] = {}
        for row in rows:
            key = getattr(row, split, None)
            seen[str(key).lower()] = seen.get(str(key).lower(), 0) + 1
        for key, n in seen.items():
            out.append(Quantity(float(n), COUNT, f"count.{label}.{split}={key}", rid, table="count"))
        col_type = model.__table__.columns[split].type
        if isinstance(getattr(col_type, "python_type", None), type) and col_type.python_type is bool:
            for key in ("true", "false"):
                if key not in seen:
                    out.append(Quantity(0.0, COUNT, f"count.{label}.{split}={key}", rid, table="count"))
    kind = "run" if any(by_model.values()) else None
    # Every run quantity's group is a pure function of its name (the RUN_GROUPS
    # patterns); "other" for a name no pattern claims, which the manifest lists
    # under `other` for the same reason.
    out = [replace(q, group=resources.group_of(q.label) or "other") for q in out]
    return Resolved(tuple(out), frozenset(), kind)


async def _from_position(db: AsyncSession, pid: str) -> Resolved:
    """A holding supports its QUANTITY and nothing else (V2-E5 valuation rule)."""
    row = (await db.execute(select(Position).where(Position.id == pid))).scalar_one_or_none()
    if row is None or row.quantity is None:
        return Resolved((), frozenset(), None)
    return Resolved((Quantity(float(row.quantity), COUNT,
                              f"{row.ticker}.quantity@{row.as_of_date}", pid),),
                    frozenset(), "position")


async def _from_chunk(db: AsyncSession, cid: str) -> Resolved:
    row = (await db.execute(select(FilingChunk).where(FilingChunk.id == cid))).scalar_one_or_none()
    if row is None:
        return Resolved((), frozenset(), None)
    return Resolved((), frozenset(quoted_keys(row.text)), "passage", row.text or "")


async def _from_source(db: AsyncSession, sid: str) -> Resolved:
    row = (await db.execute(select(ResearchSource).where(ResearchSource.id == sid))).scalar_one_or_none()
    if row is None:
        return Resolved((), frozenset(), None)
    text = f"{row.title or ''} {row.snippet or ''}"
    return Resolved((), frozenset(quoted_keys(text)), "source", text)


# Data, not an if-chain: the symmetry test asserts this covers every prefix the
# gate accepts, so a newly citable prefix cannot arrive without a value source.
SOURCES = {
    "calc_": _from_calc,
    "fact_": _from_fact,
    "alert_": _from_alert,
    "run_": _from_run,
    "pos_": _from_position,
    "chunk_": _from_chunk,
    "src_": _from_source,
}

CITABLE_PREFIXES: tuple[str, ...] = tuple(SOURCES)


async def of_ref(db: AsyncSession, ref: str) -> Resolved:
    """Everything one id holds, or an empty Resolved with kind None if it is not a row."""
    for prefix, fn in SOURCES.items():
        if ref.startswith(prefix):
            return await fn(db, ref)
    return Resolved((), frozenset(), None)


async def resolve_cited_values(
    db: AsyncSession, citation_ids: Iterable[str]
) -> tuple[list[Quantity], set[str]]:
    """Every number the cited rows hold, plus the digits their prose contains.

    The daily-report gate's entry point (v1 prose, server-assembled evidence
    set); the block exit reads services/table.py instead.
    """
    values: list[Quantity] = []
    quoted: set[str] = set()
    for cid in citation_ids:
        r = await of_ref(db, cid)
        values.extend(r.quantities)
        quoted |= r.quoted
    return values, quoted


# ── the prose route (v1 answers and the daily report only) ────────────────────
# What digits a passage literally contains, tagged by the unit the text puts
# beside them. An EXISTENCE check on the digits, not a magnitude check.
import re as _re  # noqa: E402

_LIT = r"(?:\d(?:[\d,]*\d)?(?:\.\d+)?|\.\d+)"
_DIGITS = _re.compile(_LIT)
_PERCENT_WORD = _re.compile(r"\s*percent\b", _re.IGNORECASE)
_PERCENT_WORD_WINDOW = 9


def quoted_keys(text: str) -> set[str]:
    text = text or ""
    keys: set[str] = set()
    for m in _DIGITS.finditer(text):
        digits = m.group(0).replace(",", "")
        before = text[max(0, m.start() - 2):m.start()]
        after = text[m.end():m.end() + 2]
        after_word = text[m.end():m.end() + _PERCENT_WORD_WINDOW]
        if after.lstrip().startswith("%") or _PERCENT_WORD.match(after_word):
            keys.add(f"%:{digits}")
        elif "$" in before:
            keys.add(f"$:{digits}")
        keys.add(f":{digits}")
    return keys
