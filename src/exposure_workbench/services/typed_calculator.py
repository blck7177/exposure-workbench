"""Four operators that refuse the combinations provenance cannot see.

Give an agent the data and a calculator and it will compute, for AAPL,
82.700 + 8.310 = 91.010 and call it total debt. Every input is a real filed
number, the arithmetic is real, the ledger row is genuine, and the citation gate
passes it — because nothing about it is malformed. It is wrong by the current
maturities, counted twice.

The information that would have stopped it is the TYPE of each operand: what it
is a quantity of, at what instant or over what interval. A bare calculator
discards exactly that. So here every id resolves to a type, the type is written
into the ledger so the next call can read it back, and four combinations are
refused:

    two balances from different dates                  R2 — addition across time
    two flows over overlapping intervals, added        R1 — the same days twice
    a quantity added to one that contains it           R3 — the AAPL case
    money added to a ratio                             the existing unit rule

Everything else goes through. A balance over a flow is leverage and is fine, as
long as the result says it is a stock over a window. Subtracting overlapping
intervals is fine — H1 − Q1 = Q2 is how a window is derived at all. Subtracting
a balance from a later reading of it is fine too: that is the change over the
days between — a working-capital swing is exactly this — and the result is
typed as a flow over that window, so it meets a filed flow under R1 when and
only when they describe the same days. R2 is a rule about ADDING across time,
as the list above says; refusing the subtraction as well sent the one question
that needs it ("how much has it moved?") to read_fundamentals, which reads one
instant and cannot produce a change. The point is not to narrow what may be
analysed; it is that the one region where a wrong answer is indistinguishable
from a right one stops being reachable.

An operand whose type cannot be established is refused rather than assumed
compatible: a guard whose blind spot is silent is worse than no guard, because
it is trusted.

THE BOOK'S QUANTITIES (V22). Until V22 the operands were fact_ and calc_ ids
only, and a run's own figures — a weight, a market value, a limit level, a net
beta — were terminal: readable, citable, never combinable. The conversation
battery (docs/spikes/V21_CONVERSATIONS.md §2) measured what that costs: "how
much must I sell to get back under the limit" is (weight − limit) × market
value, two operations over four figures the run already holds, and no tool
could perform either. So an operand may now be a NAMED FIGURE ON A ROW —
`run_…:issuer_exposures.MSFT.weight`, `calc_…:portfolio.integration.
room_to_breach.issuer_concentration:MSFT` — typed the way a fact is, with one
more axis: its BASE, the book it is a share of. The rules that axis adds are
the ways a bare calculator gets a book wrong:

    two books' figures summed or multiplied           different_books
    a book's figure summed with a filed figure        mixed_worlds
    a share of the book times money not the book's    mixed_worlds

A weight subtracted from another book's weight is the change between them and
goes through, as R2 lets a balance's two readings be differenced.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import containment as ct
from exposure_workbench.analytics import units
from exposure_workbench.analytics.units import COUNT, MONEY, MONEY_PER_SHARE, MULTIPLE, RATIO
from exposure_workbench.db.models import CalcLedger, Company, FinancialFact
from exposure_workbench.services import calc_service as cs

OPS = ("add", "subtract", "multiply", "divide")


@dataclass(frozen=True)
class Typed:
    """A number and everything needed to decide what it may be combined with."""
    value: float
    unit_class: str                       # one of analytics.units.UNIT_CLASSES
    instant: date | None = None           # a balance: as of this date
    interval: tuple[date, date] | None = None   # a flow: over these days
    quantity: str | None = None           # the metric, for containment
    source_id: str = ""
    # What the ledger already said this operand's basis was. A `mixed` basis —
    # a balance over a flow, which is what every ratio here is — decomposes into
    # neither an instant nor an interval, so reading one back used to render it
    # "unspecified" and a second operation on it lost the periods for good.
    # Kept verbatim rather than recomputed: the row is the record.
    recorded_basis: dict | None = None
    # Whose numbers these are, as tickers. A fact has one issuer; a calculation
    # carries the union of its operands'. Empty means UNKNOWN — a row recorded
    # before quantities carried an issuer — and unknown is treated as shared, so
    # the double-count rules stay ON for legacy rows rather than off.
    issuers: tuple[str, ...] = ()
    # V22. The book this quantity is a figure OF — a run id, or a scenario
    # row's id — for a run child's column or a quantity derived from one. A
    # weight is a share of ITS book's market value and of nothing else; the
    # base is what lets the rules say so. None for a filed quantity and for
    # anything derived only from filed quantities. For a run child the entity
    # (the ticker, the sector, the check) rides in `issuers`, so rank can label
    # it and the double-count rules can tell two rows of one run apart.
    base: str | None = None

    def basis(self) -> dict:
        if self.instant:
            return {"instant": self.instant.isoformat()}
        if self.interval:
            return {"interval": [self.interval[0].isoformat(), self.interval[1].isoformat()]}
        return self.recorded_basis or {"mixed": "unspecified"}

    def as_dict(self) -> dict:
        return {"unit_class": self.unit_class, "basis": self.basis(),
                "quantity": self.quantity, "source_id": self.source_id,
                "issuers": list(self.issuers),
                **({"base": self.base} if self.base else {})}


def _err(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


# The gate's unit names (services/quantities.py) to the algebra's. The inverse
# of quantities._UNIT_CLASS_OF, written here so this module does not import
# the namer at load time (the namer imports RANK_OP from here).
_ALGEBRA_UNIT = {"MONEY": MONEY, "RATIO": RATIO, "COUNT": COUNT,
                 "MONEY_PER_SHARE": MONEY_PER_SHARE, "MULTIPLE": MULTIPLE}

# The separator between a row and a figure on it: `run_x:issuer_exposures.
# MSFT.weight`. A colon, because a name may hold dots (every run name does)
# and the run's own labels hold colons only INSIDE a label
# (`issuer_concentration:MSFT`), never before the table name — so the first
# colon is always the boundary.
NAMED_SEP = ":"


def split_named(ref: str) -> tuple[str, str] | None:
    """(row id, name) for a named operand, or None for a bare id."""
    if NAMED_SEP not in ref:
        return None
    rid, _, name = ref.partition(NAMED_SEP)
    if not rid.startswith(("run_", "calc_")) or not name:
        return None
    return rid, name


def _parse_book_name(name: str) -> tuple[str, str | None]:
    """(what the figure is a quantity of, the entity it belongs to).

    A run child's name is `<table>.<row label>.<column>` (quantities.py); the
    quantity is the column on its table and the entity is the row label. A
    whole-book column (`exposure_metrics.portfolio_market_value`), a count, or
    the regression's sum has no entity. An analysis row's name is `portfolio.
    integration.<key>.<label>`; the entity is the label.
    """
    parts = name.split(".")
    if name.startswith("portfolio.integration.") and len(parts) == 4:
        return ".".join(parts[:3]), parts[3]
    if len(parts) == 3:
        return f"{parts[0]}.{parts[2]}", parts[1]
    return name, None


async def _resolve_fact_ref(db: AsyncSession, fid: str) -> Typed | dict:
    """V24. A Fact by its id as an operand — the id the model was shown, so the
    figure it computes with is the figure it read, with the identity the Fact
    carries: unit, as-of or window, subject, and the row it rests on as base.
    The first live V24 round wrote `multiply(f_…, f_…)` unprompted and was
    refused; a scalar Fact is the most completely typed operand on the desk.
    """
    from exposure_workbench.services import ledger as ledger_svc
    rec = await ledger_svc.record(db, fid)
    if rec is None:
        return _err("unknown_operand", f"{fid} is not a fact this desk has shown")
    kind = rec.get("kind")
    if kind == "series":
        src = next((s for s in rec.get("sources") or [] if isinstance(s, str) and s.startswith("calc_")), None)
        if src:
            return await _resolve(db, src)
        return _err("not_a_quantity", f"{fid} is a series with no ledger row behind it; a series statistic "
                                      f"(compute op yoy/qoq/…) takes the series' calc id")
    if kind != "scalar" or rec.get("value") is None:
        return _err("not_a_quantity", f"{fid} is {kind or 'not a figure'} — it can be pointed at, not combined")
    if rec.get("standalone") is False:
        return _err("not_alone", f"{fid} ({rec.get('measure')}) is not determined on its own; combine the figure that is")
    unit = _ALGEBRA_UNIT.get(str(rec.get("unit") or "").upper())
    if unit is None:
        return _err("unknown_unit", f"{fid} is {rec.get('unit')!r}, which this desk cannot do algebra on")
    instant = interval = None
    w = rec.get("window") or {}
    try:
        if isinstance(w, dict) and w.get("start") and w.get("end"):
            interval = (date.fromisoformat(str(w["start"])[:10]), date.fromisoformat(str(w["end"])[:10]))
        elif rec.get("as_of") and str(rec["as_of"])[:4].isdigit():
            instant = date.fromisoformat(str(rec["as_of"])[:10])
    except ValueError:
        instant = interval = None
    subject = rec.get("subject")
    issuer = (subject,) if isinstance(subject, str) and subject and not subject.startswith(("run_", "port_", "calc_")) else ()
    base = next((s for s in rec.get("sources") or [] if isinstance(s, str) and s.startswith(("run_", "calc_"))), None)
    if not issuer and isinstance(subject, str) and subject.startswith("run_"):
        base = base or subject
    return Typed(value=float(rec["value"]), unit_class=unit, instant=instant, interval=interval,
                 quantity=rec.get("measure"), source_id=fid, issuers=issuer,
                 base=base if (rec.get("measure") or "").startswith(("issuer_exposures", "sector_exposures", "limit_checks",
                                                                        "exposure_metrics", "factor_attributions", "risk_alerts",
                                                                        "portfolio.", "trade.")) else None)


async def _resolve_named(db: AsyncSession, rid: str, name: str, ref: str) -> Typed | dict:
    """One figure on a row that holds many, typed (V22).

    The VALUE and the UNIT come from the one namer every other reader uses
    (services/quantities.py), so the figure the calculator combines is the
    figure the table shows and the gate resolves — there is no second walk.
    What this adds is the BASE and the AS-OF: a run's figures are readings at
    the run's date of that run's book; an analysis row's, of the run it
    analysed; a scenario row's, of the hypothetical book the row itself is.
    """
    resolved = await _named_quantities(db, rid)
    if resolved.kind is None:
        return _err("unknown_operand", f"{rid} is not a row this desk holds")
    held = {q.label: q for q in resolved.quantities}
    if name not in held:
        import difflib
        near = difflib.get_close_matches(name, list(held), n=5, cutoff=0.5)
        return _err("unknown_name",
                    f"{rid} holds no figure named {name!r}."
                    + (f" Nearest names it holds: {', '.join(near)}." if near else "")
                    + f" A run's names are listed by describe(run_id); an analysis or scenario "
                      f"row's names are on its table.")
    if resolved.kind == "series" and "@" in name:
        # A point of a series row — `capex@2025-12-31` — as an operand: its own
        # period, its row's issuer, no base. Live turn 3 wrote exactly this and
        # was refused undated; a point is the most dated thing on the desk.
        return await _resolve_point(db, rid, name, held[name], ref)
    if (rid.startswith("calc_") and name in held and resolved.kind == "scalar"
            and not name.startswith("portfolio.") and _is_single_valued(resolved)):
        # A named figure on a row that holds ONE figure is the row: the table
        # shows a scalar under its quantity's name, the model writes ref:name
        # as it does for a run, and the row's own type (its leaves, its base)
        # is fuller than anything re-derived from the name. Measured live on
        # the first V22 turn: `calc_…:issuer_concentration:MSFT.excess_weight`
        # was refused undated when the bare id carried the date.
        return await _resolve(db, rid)
    q = held[name]
    if q.not_alone is not None:
        return _err("not_alone", f"{name} may not be used on its own: {q.not_alone}")
    unit = _ALGEBRA_UNIT.get(q.unit_class)
    if unit is None:
        return _err("unknown_unit", f"{name} on {rid} is {q.unit_class}, which this desk "
                                    f"cannot do algebra on")
    ctx = await _named_context(db, rid)
    if isinstance(ctx, dict):
        return ctx
    base, as_of = ctx
    quantity, entity = _parse_book_name(name)
    return Typed(value=float(q.value), unit_class=unit, instant=as_of, quantity=quantity,
                 source_id=ref, issuers=(entity,) if entity else (), base=base)


async def _resolve_point(db: AsyncSession, rid: str, name: str, q, ref: str) -> Typed | dict:
    """One dated point of a series row, typed from the row's recorded type."""
    unit = _ALGEBRA_UNIT.get(q.unit_class)
    if unit is None:
        return _err("unknown_unit", f"{name} on {rid} is {q.unit_class}, which this desk cannot do algebra on")
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == rid))).scalar_one_or_none()
    params = (row.params or {}) if row is not None else {}
    rt = params.get("result_type") or {}
    period = name.rsplit("@", 1)[1]
    try:
        end = date.fromisoformat(period)
    except ValueError:
        return _err("undated_operand", f"{name}: the period {period!r} is not a date")
    point = next((pt for pt in ((row.result or {}).get("points") or [])
                  if str(pt.get(units.POINT_PERIOD_KEY) or pt.get("end") or pt.get("as_of")) == period), None)
    start = (point or {}).get("start")
    kind = rt.get("kind")
    issuers = _row_issuers(rt, getattr(row, "company_id", None))
    if start or kind == "flow":
        interval = (date.fromisoformat(start), end) if start else None
        return Typed(value=float(q.value), unit_class=unit, interval=interval,
                     instant=None if interval else end, quantity=rt.get("quantity") or name.split("@")[0],
                     source_id=ref, issuers=issuers)
    return Typed(value=float(q.value), unit_class=unit, instant=end,
                 quantity=rt.get("quantity") or name.split("@")[0], source_id=ref, issuers=issuers)


def _is_single_valued(resolved) -> bool:
    """One figure on the row, not counting the quality flags it carries. Only a
    calculator row qualifies (kind scalar, a name that is not a run family's):
    an analysis row with a single distance is still a row ABOUT a run, and its
    figure is typed from the row's params, not from the row as a whole."""
    figures = [q for q in resolved.quantities if not q.label.startswith("quality_flags")]
    return len(figures) == 1


async def _named_quantities(db: AsyncSession, rid: str):
    """The figures a row holds, by the one namer (services/quantities.py)."""
    from exposure_workbench.services import quantities as qn  # lazy: qn imports RANK_OP
    return await qn.of_ref(db, rid)


async def _named_context(db: AsyncSession, rid: str) -> tuple[str, date] | dict:
    """(base, as_of) for a row's figures. A run: itself, at its date. A ledger
    row about a run — an analysis (portfolio.integration) or a scenario
    (book.scenario) — says so in its params; a scenario's base is the row
    itself, because the hypothetical book IS that row."""
    from exposure_workbench.db.models import ExposureRun
    if rid.startswith("run_"):
        run = (await db.execute(select(ExposureRun).where(ExposureRun.id == rid))).scalar_one_or_none()
        if run is None:
            return _err("unknown_operand", f"{rid} is not a run this desk holds")
        return rid, run.as_of_date
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == rid))).scalar_one_or_none()
    params = (row.params or {}) if row is not None else {}
    rt = params.get("result_type") or {}
    if row is not None and row.operation == SCENARIO_OP:
        base = rid                                   # the hypothetical book IS this row
    else:
        base = params.get("run_id") or rt.get("base") or rid
    as_of = None
    if params.get("as_of"):
        as_of = date.fromisoformat(params["as_of"])
    elif params.get("run_id"):
        run = (await db.execute(select(ExposureRun).where(ExposureRun.id == params["run_id"]))).scalar_one_or_none()
        as_of = run.as_of_date if run is not None else None
    elif (rt.get("basis") or {}).get("instant"):
        as_of = date.fromisoformat(rt["basis"]["instant"])   # a calculator row of the book
    if as_of is None:
        return _err("undated_operand", f"{rid} carries no as-of date, so its figures cannot "
                                       f"be placed in time and cannot be combined")
    return base, as_of


# The operation a scenario row is recorded under (services/scenario_service.py
# writes it; named here because _resolve_named reads it and the namer reads
# both). One string, one owner.
SCENARIO_OP = "book.scenario"


async def _resolve(db: AsyncSession, ref: str) -> Typed | dict:
    """A fact, a calc, or a named figure on a run or a ledger row, as a typed quantity."""
    if ref.startswith("f_"):
        return await _resolve_fact_ref(db, ref)
    named = split_named(ref)
    if named is not None:
        return await _resolve_named(db, named[0], named[1], ref)
    if ref.startswith("fact_"):
        row = (await db.execute(
            select(FinancialFact).where(FinancialFact.id == ref)
        )).scalar_one_or_none()
        if row is None or row.value is None:
            return _err("unknown_operand", f"{ref} is not a fact this desk holds")
        ticker = (await db.execute(
            select(Company.ticker).where(Company.id == row.company_id)
        )).scalar_one_or_none()
        # The one judgement of a fact's unit lives in analytics.units. This
        # function used to make its own (dollars → money, everything else →
        # ratio) while quantities made a different one, and the same fact
        # combined differently depending on who resolved it.
        unit = units.fact_unit(row.unit)
        if unit is None:
            return _err("unknown_unit",
                        f"{ref} is denominated in {row.unit!r}, which is not a unit "
                        f"this desk can do algebra on; it can be quoted and cited, "
                        f"not combined")
        return Typed(
            value=float(row.value),
            unit_class=unit,
            instant=row.period_end if row.period_start is None else None,
            interval=None if row.period_start is None else (row.period_start, row.period_end),
            quantity=row.normalized_metric, source_id=ref,
            issuers=(ticker,) if ticker else (),
        )
    if ref.startswith("calc_"):
        row = (await db.execute(
            select(CalcLedger).where(CalcLedger.id == ref)
        )).scalar_one_or_none()
        if row is None:
            return _err("unknown_operand", f"{ref} is not a calculation this desk holds")
        if row.operation == RANK_OP:
            # An ordering has no value of its own. Without this branch it fell
            # through to the untyped_operand refusal, whose sentence ("recorded
            # before quantities carried their type") is about a legacy row and
            # would send the caller to recompute something that is not wrong.
            return _err("not_a_quantity",
                        f"{ref} is an ordering — a relation between quantities, not a "
                        f"quantity. Its entries' own rows are the operands; its places "
                        f"and values are on the table by name.")
        params = row.params or {}
        owned = _row_issuers(params.get("result_type"), row.company_id)
        points = (row.result or {}).get("points")
        if isinstance(points, list):
            return _resolve_series(ref, row.operation, params, points, owned)
        value = (row.result or {}).get("value")
        # derive.interval rows since V16 state their type; older ones predate
        # result_type but carry everything needed, and every one was a dollar flow.
        if row.operation == cs_op_flow() and params.get("period"):
            p = params["period"]
            rt0 = params.get("result_type") or {}
            return Typed(value=float(value), unit_class=rt0.get("unit_class", MONEY),
                         interval=(date.fromisoformat(p["start"]), date.fromisoformat(p["end"])),
                         quantity=rt0.get("quantity") or params.get("metric"),
                         source_id=ref, issuers=owned)
        t = params.get("result_type")
        if not t or value is None:
            return _err(
                "untyped_operand",
                f"{ref} was recorded before quantities carried their type, so what it "
                f"may be combined with cannot be established. Recompute it with "
                f"read_fundamentals or compute.")
        unit = t.get("unit_class")
        if unit is None:
            # A result_type without a unit is not "probably money": refusing it
            # is what keeps the unit algebra's blind spot from being silent.
            return _err("untyped_operand",
                        f"{ref} recorded a result_type without a unit_class; recompute it")
        basis = t.get("basis") or {}
        return Typed(
            value=float(value), unit_class=unit,
            instant=date.fromisoformat(basis["instant"]) if basis.get("instant") else None,
            interval=(date.fromisoformat(basis["interval"][0]),
                      date.fromisoformat(basis["interval"][1])) if basis.get("interval") else None,
            quantity=t.get("quantity"), source_id=ref, recorded_basis=basis or None,
            issuers=owned, base=t.get("base") or None,
        )
    if ref.startswith(("chunk_", "src_")):
        # V11-A. Asked what share of Lilly's revenue its top products make up,
        # the agent found the figures in the 10-K, was refused for computing the
        # share in its head, and then passed the two chunk ids here — the only
        # remaining move it could think of. It ended the turn promising to
        # recompute, which is the worst answer in the battery: no figure, no
        # reason, and a follow-up it cannot deliver. Say what is true of a
        # passage instead, so "I cannot compute this" is available to it.
        return _err("unknown_operand",
                    f"{ref} is a filing passage. Figures inside one can be quoted and "
                    f"cited, but they are not typed quantities and cannot be operands — "
                    f"there is no basis, no unit and no metric to check a combination "
                    f"against. If the filing states the figure you want, quote it; if it "
                    f"only states the parts, this desk cannot combine them.")
    if "." in ref and not ref.startswith(("fact_", "calc_", "run_")):
        # A run's name written without its run: the first live V23 turn wrote
        # `issuer_exposures.MSFT.market_value` bare. The name is right; it
        # needs the row it is on.
        return _err("unknown_operand",
                    f"{ref!r} looks like a figure's name without its row: write it as "
                    f"run_<id>:{ref} (or calc_<id>:{ref} on a scenario row). An operand is an "
                    f"id or ref:name, never an expression.")
    return _err("unknown_operand",
                f"{ref} is not a fact_ or calc_ id, nor a named figure on a row "
                f"(run_…:<name>, calc_…:<name>); an operand is never an expression")


def _row_issuers(result_type: dict | None, company_id: str | None) -> tuple[str, ...]:
    """The issuers a ledger row belongs to.

    Scalar rows written since quantities carried an issuer say so in their
    result_type; the flow and series rows fundamentals_service writes have
    always put the ticker in the row's company column. A row with neither is
    unknown, which the rules treat as shared.
    """
    named = (result_type or {}).get("issuers")
    if named:
        return tuple(named)
    return (company_id,) if company_id else ()


@dataclass(frozen=True)
class TypedSeries:
    """A series of typed quantities keyed by the date each one ends.

    V10-S2. The scalar calculator lifts to series element-wise: two series are
    aligned on their end dates (within the engine's snap tolerance — a 52/53-
    week filer's quarter ends a few days from a calendar filer's), and every
    aligned pair goes through the same `_check` a pair of scalars would. One
    refused pair refuses the whole operation and names the slot, because a
    series with a silently dropped point is a series that lies about its length.
    """
    points: tuple[tuple[date, Typed], ...]
    unit_class: str
    kind: str                     # flow | instant | series | scalar (derived)
    quantity: str | None
    source_id: str
    issuers: tuple[str, ...] = ()


def _resolve_series(ref: str, operation: str, params: dict, points: list,
                    issuers: tuple[str, ...] = ()) -> TypedSeries | dict:
    rt = params.get("result_type")
    if not rt:
        return _err("untyped_operand",
                    f"{ref} is a series recorded before series carried their type. "
                    f"Recompute it with read_fundamentals(last_n=…).")
    unit = rt.get("unit_class")
    if unit is None:
        return _err("untyped_operand",
                    f"{ref} is a series whose recorded type has no unit_class; "
                    f"recompute it with read_fundamentals(last_n=…).")
    kind = rt.get("kind", "series")
    quantity = rt.get("quantity")
    typed: list[tuple[date, Typed]] = []
    for p in points:
        # Writers use POINT_PERIOD_KEY and only that; the other two keys are
        # the frozen legacy vocabulary of rows written before V16.
        end_s = p.get(units.POINT_PERIOD_KEY) or p.get("end") or p.get("as_of")
        if end_s is None or p.get("value") is None:
            continue                       # an unreachable slot has no quantity to combine
        end = date.fromisoformat(end_s)
        if kind == "flow" and p.get("start"):
            t = Typed(value=float(p["value"]), unit_class=unit,
                      interval=(date.fromisoformat(p["start"]), end), quantity=quantity,
                      source_id=ref, issuers=issuers)
        elif kind == "instant":
            t = Typed(value=float(p["value"]), unit_class=unit, instant=end, quantity=quantity,
                      source_id=ref, issuers=issuers)
        else:
            t = Typed(value=float(p["value"]), unit_class=unit, quantity=quantity,
                      source_id=ref, issuers=issuers)
        typed.append((end, t))
    if not typed:
        return _err("empty_series", f"{ref} holds no derivable points")
    return TypedSeries(points=tuple(typed), unit_class=unit, kind=kind, quantity=quantity,
                       source_id=ref, issuers=issuers)


def cs_op_flow() -> str:
    from exposure_workbench.services.fundamentals_service import OP_FLOW
    return OP_FLOW


# ── the four refusals ─────────────────────────────────────────────────────────

def _shared_issuer(a: Typed, b: Typed) -> bool:
    """Whether the two quantities may describe the same company — the condition
    under which adding them can count something twice. Unknown counts as shared."""
    return not a.issuers or not b.issuers or bool(set(a.issuers) & set(b.issuers))


def _book_rule(op: str, a: Typed, b: Typed) -> dict | None:
    """The rules a base adds (V22). None when neither operand has one.

    A weight is a share of ITS book's market value. Summed with another
    book's weight it is a share of nothing; multiplied by another book's
    market value it is a position that does not exist. Differenced it is the
    change between the two books, and divided it is a ratio that says which
    two — R2's shape, one axis over. A book figure summed with a filed figure
    (a position's market value plus the issuer's cash) is two worlds in one
    number; a share of the book times money that is not the book's is the
    same mistake as a product. A share times an issuer's RATIO (weight × net
    margin, the weighted margin) is an analyst's arithmetic and goes through.
    """
    if a.base is None and b.base is None:
        return None
    if a.base and b.base and a.base != b.base and op in ("add", "multiply"):
        return _err("different_books",
                    f"{a.source_id} is a figure of {a.base} and {b.source_id} of {b.base}: "
                    f"a share is a share of its own book's market value, so two books' "
                    f"figures cannot be summed or multiplied. Subtract them for the change "
                    f"between the two books, or divide for the ratio.")
    if (a.base is None) != (b.base is None):
        filed = b if a.base else a
        if op in ("add", "subtract"):
            return _err("mixed_worlds",
                        f"{filed.source_id} is a filed figure and the other operand is a "
                        f"figure of the book: a position and an issuer's own accounts are "
                        f"not parts of one whole and cannot be summed or differenced. "
                        f"Multiply a share of the book by an issuer's ratio, or divide, "
                        f"if that is the measure meant.")
        if op == "multiply" and filed.unit_class == MONEY:
            return _err("mixed_worlds",
                        f"{filed.source_id} is money that is not this book's: a share of "
                        f"the book multiplied by it is a position that does not exist. "
                        f"Multiply the share by the book's own market value "
                        f"(exposure_metrics.portfolio_market_value).")
    return None


def _check(op: str, a: Typed, b: Typed) -> dict | None:
    refusal = _book_rule(op, a, b)
    if refusal:
        return refusal
    # Multiply and divide are exempt from the period and basis rules below —
    # a ratio may cross bases; it says which — but not from the unit algebra:
    # whether a product means anything is a lookup in units.PRODUCTS/QUOTIENTS,
    # and a combination with no row is undefined, not defaulted.
    if op == "multiply":
        if units.product_unit(a.unit_class, b.unit_class) is None:
            return _err("undefined_product",
                        f"{a.source_id} is {a.unit_class} and {b.source_id} is "
                        f"{b.unit_class}; {a.unit_class} × {b.unit_class} has no row "
                        f"in units.PRODUCTS, so the product is undefined on this desk")
        return None
    if op == "divide":
        if units.quotient_unit(a.unit_class, b.unit_class) is None:
            return _err("undefined_quotient",
                        f"{a.source_id} is {a.unit_class} and {b.source_id} is "
                        f"{b.unit_class}; {a.unit_class} ÷ {b.unit_class} has no row "
                        f"in units.QUOTIENTS, so the quotient is undefined on this desk")
        return None

    if a.unit_class != b.unit_class:
        return _err("incompatible_units",
                    f"{a.source_id} is {a.unit_class} and {b.source_id} is {b.unit_class}")

    ka, kb = _kind(a), _kind(b)
    if "mixed" not in (ka, kb) and ka != kb:
        word = {"instant": "a balance", "flow": "a flow"}
        return _err("incompatible_bases",
                    f"{a.source_id} is {word[ka]} and {b.source_id} is {word[kb]}; "
                    f"a stock and a flow may be divided, not added")

    if not _shared_issuer(a, b):
        # Different companies: nothing below can double-count, because the two
        # numbers were never parts of one whole. AAPL's cash at 2026-03-28 plus
        # MSFT's at 2026-03-31 is a sum of two moments, not one moment counted
        # twice, and the result says both dates rather than pretending to one.
        # Until 2026-08-30 this function was issuer-blind: it refused that sum
        # in the same words it refuses AAPL@March + AAPL@December, and told
        # the caller to fetch both at one date — which two issuers on
        # different fiscal calendars never have. Every book-level question
        # ("how much cash do the tech names hold between them?") was
        # unreachable by construction.
        return None

    for t in (a, b):
        if (t.unit_class not in (RATIO, COUNT) and t.instant is None and t.interval is None
                and (t.recorded_basis or {}).get("leaves")):
            # COUNT is exempt alongside RATIO (V16): the guard exists to stop a
            # MONEY sum across periods being counted twice, and a day-count —
            # DSO + days_inventory − days_payable is the cash conversion cycle —
            # has no money in it to double-count.
            # A money quantity resting on several periods is a sum across
            # issuers (the only way one arises), and this operand shares an
            # issuer with it. Whether that issuer's slice is being counted a
            # second time cannot be told from here, so it is refused rather
            # than assumed — the one asymmetry in this function that errs
            # toward a refusal, because the alternative is the AAPL case
            # through a side door.
            lv = _leaves(t)
            return _err("mixed_basis_operand",
                        f"{t.source_id} is a sum across several periods "
                        f"({', '.join(lv['instants'] + ['..'.join(x) for x in lv['intervals']])}) "
                        f"and shares an issuer with {b.source_id if t is a else a.source_id}; "
                        f"combine it only with other issuers' quantities, or rebuild "
                        f"the sum from single-period parts.")

    # R2 is about ADDITION across time. The difference between two readings of a
    # balance is the change over the days between them, and it is the only way
    # "how much has it moved" can be answered from balances at all; the series
    # axis has always allowed it element-wise. This guard used to fire on
    # subtract as well, and its way out pointed at read_fundamentals — which
    # reads one instant and cannot produce a change.
    if op == "add" and a.instant and b.instant and a.instant != b.instant:
        return _err("different_instants",
                    f"{a.source_id} is as of {a.instant.isoformat()} and {b.source_id} is "
                    f"as of {b.instant.isoformat()}. Balances from two dates describe two "
                    f"company-moments and cannot be summed; ask for both at one date with "
                    f"read_fundamentals, or subtract them for the change between the two "
                    f"readings.")

    # R3 — containment, in both directions.
    if a.quantity and b.quantity:
        if ct.contains(a.quantity, b.quantity) or ct.contains(b.quantity, a.quantity):
            wide, narrow = ((a, b) if ct.contains(a.quantity, b.quantity) else (b, a))
            if op == "add":
                return _err("overlapping_quantities",
                            f"{wide.quantity} already contains {narrow.quantity}, so adding "
                            f"them counts {narrow.quantity} twice. Take the total, or take "
                            f"its components — not one of each.")

    # R1 — two flows may be added in exactly two situations, and the acceptance
    # battery found the hole between them. Blocking only OVERLAP let through the
    # worse case: NVDA's EBIT came out as 2026 net income plus 2024 interest
    # expense, because the two windows merely failed to overlap and nothing
    # objected. Summing incomparable periods is not double-counting, it is
    # arithmetic on two different years.
    if a.interval and b.interval and op == "add":
        (a0, a1), (b0, b1) = a.interval, b.interval
        same_window = (a0, a1) == (b0, b1)
        adjacent = b0 == a1 + timedelta(days=1) or a0 == b1 + timedelta(days=1)
        if same_window or adjacent:
            return None
        if a0 <= b1 and b0 <= a1:
            return _err("overlapping_intervals",
                        f"{a.source_id} covers {a0}..{a1} and {b.source_id} covers "
                        f"{b0}..{b1}; the shared days would be counted twice. Subtract "
                        f"to get the difference, or add windows that do not overlap.")
        return _err("mismatched_windows",
                    f"{a.source_id} covers {a0}..{a1} and {b.source_id} covers {b0}..{b1}. "
                    f"Components of one period may be added when they cover the SAME "
                    f"window, and consecutive periods may be added when they meet; these "
                    f"do neither, so their sum belongs to no period. Fetch both over one "
                    f"window with read_fundamentals(start=..., end=...).")
    return None


_JOIN = {"multiply": " × ", "divide": " / ", "add": " + ", "subtract": " − "}


def _leaves(t: Typed) -> dict:
    """The instants and intervals a quantity ultimately rests on.

    A fact has one; a derived quantity has whatever its operands had, carried
    in its recorded basis. This is what lets a depth-two product say which
    periods it is made of — the ROE that is a margin times a turnover times a
    multiplier used to reach the ledger with basis `' multiply '`, its periods
    gone, and an answer stating them was stating what its evidence did not
    hold (round-4 battery, 2026-08-29).
    """
    if t.instant:
        return {"instants": [t.instant.isoformat()], "intervals": []}
    if t.interval:
        return {"instants": [],
                "intervals": [[t.interval[0].isoformat(), t.interval[1].isoformat()]]}
    rec = (t.recorded_basis or {}).get("leaves") or {}
    return {"instants": list(rec.get("instants", [])),
            "intervals": [list(x) for x in rec.get("intervals", [])]}


def _kind(t: Typed) -> str:
    """instant | flow | mixed — what a quantity IS for the stock/flow rule.

    A fact says so directly. A derived quantity says so through its leaves: a
    sum of three issuers' cash rests on instants only and is still a balance;
    a ratio of a flow to a balance rests on both and is neither.
    """
    if t.instant:
        return "instant"
    if t.interval:
        return "flow"
    lv = _leaves(t)
    if lv["instants"] and not lv["intervals"]:
        return "instant"
    if lv["intervals"] and not lv["instants"]:
        return "flow"
    return "mixed"


def _mixed_basis(op: str, a: Typed, b: Typed) -> dict:
    """A basis for a quantity that rests on more than one period: the operands'
    bases as one expression, and every leaf period beneath them."""
    la, lb = _leaves(a), _leaves(b)
    out = {
        "mixed": f"{_basis_str(a)}{_JOIN[op]}{_basis_str(b)}",
        "leaves": {
            "instants": sorted(set(la["instants"]) | set(lb["instants"])),
            "intervals": [list(x) for x in sorted({tuple(x) for x in la["intervals"] + lb["intervals"]})],
        },
    }
    if not _shared_issuer(a, b):
        out["cross_issuer"] = True
    return out


def _result_base(op: str, a: Typed, b: Typed) -> str | None:
    """Which book the result is a figure of. One book: that book. A share
    times a filed ratio: still the book. Two books differenced or divided:
    neither — the result is ABOUT two books and a figure of none."""
    if a.base == b.base:
        return a.base
    if op == "multiply" and (a.base is None) != (b.base is None):
        return a.base or b.base
    return None


def _result_type(op: str, a: Typed, b: Typed, value: float) -> Typed:
    t = _result_type_inner(op, a, b, value)
    return replace(t, base=_result_base(op, a, b))


def _result_type_inner(op: str, a: Typed, b: Typed, value: float) -> Typed:
    issuers = tuple(sorted(set(a.issuers) | set(b.issuers)))
    if op in ("multiply", "divide"):
        # The unit is the table's answer, never the operand order's: before V16
        # this line read `a.unit_class`, so money × ratio was money but
        # ratio × money was ratio. _check already refused any pair with no row.
        unit = (units.product_unit(a.unit_class, b.unit_class) if op == "multiply"
                else units.quotient_unit(a.unit_class, b.unit_class))
        if unit is None:
            raise ValueError(f"{op} of {a.unit_class} and {b.unit_class} reached "
                             f"_result_type without a row in the unit tables")
        return Typed(value=value, unit_class=unit, quantity=None,
                     recorded_basis=_mixed_basis(op, a, b), issuers=issuers)
    if (not _shared_issuer(a, b)
            and not (a.instant and a.instant == b.instant)
            and not (a.interval and a.interval == b.interval)):
        # Two companies' quantities over different moments or windows, summed or
        # differenced. There is no single period to stamp on it, so it carries
        # both as leaves; it stays money (or a count), not a ratio.
        return Typed(value=value, unit_class=a.unit_class,
                     recorded_basis=_mixed_basis(op, a, b), issuers=issuers)
    t = _result_type_within(op, a, b, value)
    if t.instant is None and t.interval is None and t.recorded_basis is None:
        # A difference of two ratios, say: no single period, but not nothing.
        t = replace(t, recorded_basis=_mixed_basis(op, a, b))
    return replace(t, issuers=issuers)


def _result_type_within(op: str, a: Typed, b: Typed, value: float) -> Typed:
    """The basis of a sum or difference of one issuer's quantities."""
    if op == "subtract" and a.instant and b.instant and a.instant != b.instant:
        # The change in a balance between two readings. It accrues over the days
        # AFTER the earlier reading through the later one — the convention the
        # filed flows already use, a fiscal year starting the day after the prior
        # year-end — so the delta and a flow over the same period carry the same
        # interval and R1 sees them as one window. No quantity: a change is not
        # a line on the balance sheet, so containment has nothing to say about it.
        earlier, later = sorted((a.instant, b.instant))
        return Typed(value=value, unit_class=a.unit_class,
                     interval=(earlier + timedelta(days=1), later))
    if a.instant:
        return Typed(value=value, unit_class=a.unit_class, instant=a.instant)
    if a.interval and b.interval:
        (a0, a1), (b0, b1) = a.interval, b.interval
        # Components of ONE period summed: EBIT is net income plus interest plus
        # tax over the same window, and the result is about that window. Losing
        # it here left debt_to_ebitda printing a basis with an empty half.
        if (a0, a1) == (b0, b1):
            return Typed(value=value, unit_class=a.unit_class, interval=(a0, a1))
        if op == "add" and b0 == a1 + timedelta(days=1):
            return Typed(value=value, unit_class=a.unit_class, interval=(a0, b1))
        if op == "add" and a0 == b1 + timedelta(days=1):
            return Typed(value=value, unit_class=a.unit_class, interval=(b0, a1))
        if op == "subtract" and a0 == b0 and b1 < a1:
            return Typed(value=value, unit_class=a.unit_class,
                         interval=(b1 + timedelta(days=1), a1))
        if op == "subtract" and a1 == b1 and b0 > a0:
            return Typed(value=value, unit_class=a.unit_class,
                         interval=(a0, b0 - timedelta(days=1)))
    return Typed(value=value, unit_class=a.unit_class)


def _derived_name(op: str, a, b) -> str:
    """The name a derived quantity answers to when its caller gave none.

    `net_income.divide.total_revenues` is nobody's word for a margin, but the
    ledger now refuses a valued row with no quantity at all (V16, _record), and
    a lineage name states what the number is where None stated nothing.
    Containment does not know these names, so R3 has nothing to say about them
    — the same silence None bought, without the blank column.
    """
    return (f"{getattr(a, 'quantity', None) or a.source_id}.{op}."
            f"{getattr(b, 'quantity', None) or b.source_id}")


async def calculate(db: AsyncSession, op: str, a: str, b: str,
                    invoked_by: str = "agent", as_quantity: str | None = None,
                    named_by: str | None = None,
                    as_unit_class: str | None = None) -> dict:
    """Combine two quantities, if their types permit it.

    `as_quantity` is the name the CALLER gives the result — a formula naming
    its final step `net_margin`. The row records it as result_type.quantity,
    which is what the table calls the value (services/quantities.py); without
    it a measure the model asked for by name came back named `calc.scalar.
    divide`, and the model wrote the name it knew and was refused for it.
    The typing is unchanged: a named quantity is still checked like any other.

    `as_unit_class` is the caller's declaration of how the result READS, and it
    is checked, not obeyed: units.refine accepts it only where the algebra's own
    answer leaves a genuine choice (a dimensionless quotient is a share or a
    multiple; money ÷ money cannot tell), and refuses anything else. The registry
    passes it for the eight measures whose quotient is a coverage or a turnover
    — without it debt/EBITDA of 2.3 reached the reader as "230.0%".
    """
    if op not in OPS:
        return _err("unsupported_op", f"{op!r}; supported: {', '.join(OPS)}")

    left = await _resolve(db, a)
    if isinstance(left, dict):
        return left
    right = await _resolve(db, b)
    if isinstance(right, dict):
        return right

    if isinstance(left, TypedSeries) or isinstance(right, TypedSeries):
        return await _calculate_series(db, op, a, b, left, right, invoked_by)

    refusal = _check(op, left, right)
    if refusal:
        return refusal

    if op == "divide" and right.value == 0:
        return _err("division_by_zero", f"{b} is zero")
    value = {"add": left.value + right.value, "subtract": left.value - right.value,
             "multiply": left.value * right.value,
             "divide": left.value / right.value if right.value else None}[op]

    result = _result_type(op, left, right, value)
    recorded_unit = units.refine(result.unit_class, as_unit_class)
    if recorded_unit is None:
        return _err("undeclarable_unit",
                    f"{op} of {left.unit_class} and {right.unit_class} is "
                    f"{result.unit_class}, and {as_unit_class!r} is not a reading of it. "
                    f"A declaration may choose between readings of one dimension "
                    f"(a dimensionless quotient is a share or a multiple); it may not "
                    f"change the dimension the algebra computed.")
    result = replace(result, unit_class=recorded_unit)
    basis = result.basis()

    rt = {"unit_class": result.unit_class, "basis": basis,
          "quantity": as_quantity or result.quantity or _derived_name(op, left, right),
          "issuers": list(result.issuers)}
    if result.base:
        rt["base"] = result.base
    if named_by and as_quantity:
        # Who chose the name — "session" when the model named its own
        # composition (Tier 2). Recorded so a misnamed row is attributable,
        # never authoritative: the typing above treated it like any other.
        rt["named_by"] = named_by
    calc_id = await cs._record(
        db, None, f"calc.scalar.{op}",
        {"op": op, "operands": [a, b],
         "operand_types": [left.as_dict(), right.as_dict()],
         "result_type": rt},
        {"value": value}, [a, b], {}, invoked_by,
    )
    out = {"calc_id": calc_id, "op": op, "value": value, "type": rt,
           "operands": [a, b],
           "basis": f"{_basis_str(left)} {op} {_basis_str(right)}"}
    if "leaves" in basis:
        # Every period this number is made of, structured, so an answer can
        # state them and the gate can see it stating what the row holds.
        out["periods"] = basis["leaves"]
    return out


async def scale(db: AsyncSession, ref: str, factor: float, *, unit_class: str,
                quantity: str | None = None, invoked_by: str = "agent") -> dict:
    """Multiply one typed quantity by a constant, and record it.

    A constant is not an operand — it has no id, no basis and nothing to check
    against — so this is not `calculate`. It exists because the days formulas
    finish with x365 and, until V11, that last step happened in the caller with
    no ledger row: the panel published `days_inventory = 143.67` while the
    calc_id it shipped alongside held 0.3936, the ratio before the scaling. The
    number a tool prints has to be a number the ledger holds, or the gate refuses
    what the desk itself computed — measured three times in the agent battery.

    `unit_class` is the caller's to declare because a constant changes it:
    inventory/cost-of-revenue is a ratio, and the same figure times 365 is a
    count of days.
    """
    left = await _resolve(db, ref)
    if isinstance(left, dict):
        return left
    value = left.value * factor
    rt = {"unit_class": unit_class, "basis": left.basis(),
          "quantity": quantity or f"{left.quantity or ref}.scale",
          "issuers": list(left.issuers),
          **({"base": left.base} if left.base else {})}
    calc_id = await cs._record(
        db, None, "calc.scalar.scale",
        {"op": "scale", "operands": [ref], "factor": factor,
         "operand_types": [left.as_dict()], "result_type": rt},
        {"value": value}, [ref], {}, invoked_by,
    )
    return {"calc_id": calc_id, "op": "scale", "value": value, "type": rt,
            "operands": [ref], "factor": factor,
            "basis": f"{_basis_str(left)} scaled by {factor:g}"}


def _basis_str(t: Typed) -> str:
    if t.instant:
        return t.instant.isoformat()
    if t.interval:
        return f"{t.interval[0].isoformat()}..{t.interval[1].isoformat()}"
    mixed = (t.recorded_basis or {}).get("mixed")
    if mixed and mixed != "unspecified":
        return f"({mixed})"          # a derived operand: its own expression, nested
    return ""


# ── series arithmetic (V10-S2) ────────────────────────────────────────────────

# How far apart two series' end dates may be and still be the same period. The
# interval engine's boundary tolerance, for the same reason it exists there.
from exposure_workbench.analytics.interval_algebra import BOUNDARY_TOLERANCE_DAYS as _ALIGN_DAYS


def _align(left: TypedSeries, right: TypedSeries) -> list[tuple[date, Typed, Typed]] | dict:
    """Pairs of points whose end dates coincide, and a refusal if none do.

    Unmatched points on either side are dropped from the RESULT and counted in
    its quality flags — the rule the v1 combine_series applied, kept here now
    that it is the only aligner. Dropping is honest here where it would not be for a single refused
    pair: an unmatched period is not a wrong number, it is a period only one
    side reported, and the result says how many there were.
    """
    pairs = []
    rights = list(right.points)
    for end, lt in left.points:
        match = min(rights, key=lambda rp: abs((rp[0] - end).days), default=None)
        if match is None or abs((match[0] - end).days) > _ALIGN_DAYS:
            continue
        pairs.append((end, lt, match[1]))
    if not pairs:
        return _err("misaligned_series",
                    f"{left.source_id} and {right.source_id} share no period end within "
                    f"{_ALIGN_DAYS} days; they are on different reporting grids "
                    f"({left.points[0][0]}..{left.points[-1][0]} vs "
                    f"{right.points[0][0]}..{right.points[-1][0]})")
    return pairs


def _broadcast(scalar: Typed, series: TypedSeries) -> list[tuple[date, Typed, Typed]]:
    return [(end, scalar, t) for end, t in series.points]


async def _calculate_series(db, op, a, b, left, right, invoked_by) -> dict:
    if isinstance(left, TypedSeries) and isinstance(right, TypedSeries):
        pairs = _align(left, right)
        if isinstance(pairs, dict):
            return pairs
        unmatched = len(left.points) + len(right.points) - 2 * len(pairs)
        order = [(end, lt, rt) for end, lt, rt in pairs]
    elif isinstance(left, TypedSeries):
        order = [(end, lt, right) for end, lt in left.points]
        unmatched = 0
    else:
        order = [(end, left, rt) for end, rt in right.points]
        unmatched = 0

    # Every pair through the scalar rules. The first refusal is the answer,
    # with the slot that produced it.
    for end, lt, rt in order:
        refusal = _check(op, lt, rt)
        if refusal:
            return refusal | {"at": end.isoformat(),
                              "detail": f"at {end.isoformat()}: " + refusal["detail"]}

    points, div_zero = [], 0
    sample_type = None
    for end, lt, rt in order:
        if op == "divide" and rt.value == 0:
            div_zero += 1
            points.append({units.POINT_PERIOD_KEY: end.isoformat(), "value": None,
                           "flags": {"division_by_zero": True}, "fact_ids": []})
            continue
        value = {"add": lt.value + rt.value, "subtract": lt.value - rt.value,
                 "multiply": lt.value * rt.value, "divide": lt.value / rt.value}[op]
        r = _result_type(op, lt, rt, value)
        sample_type = sample_type or r
        pt = {units.POINT_PERIOD_KEY: end.isoformat(), "value": value, "fact_ids": []}
        if r.interval:
            pt["start"] = r.interval[0].isoformat()
        points.append(pt)

    unit = sample_type.unit_class if sample_type else left.unit_class
    kind = ("flow" if sample_type and sample_type.interval else
            "instant" if sample_type and sample_type.instant else "series")
    rt_out = {"unit_class": unit, "kind": kind, "quantity": _derived_name(op, left, right),
              # The panel's default selection reads derived_from
              # (apps/api/routes/issuers.panel_series), so the inputs' own
              # names stay recorded beside the synthesized one.
              "derived_from": [getattr(left, "quantity", None), getattr(right, "quantity", None)],
              "issuers": sorted(set(getattr(left, "issuers", ())) | set(getattr(right, "issuers", ())))}
    flags = {}
    if unmatched:
        flags["unmatched_periods"] = unmatched
    if div_zero:
        flags["division_by_zero_periods"] = div_zero
    calc_id = await cs._record(
        db, None, f"calc.series.{op}",
        {"op": op, "operands": [a, b], "result_type": rt_out},
        {"points": points}, [a, b], flags, invoked_by,
    )
    return {"calc_id": calc_id, "op": op, "operands": [a, b], "points": points,
            "type": rt_out, "quality_flags": flags,
            "basis": f"{op}, element-wise over {len(points)} aligned period ends"}


# ── ordering (V17) ────────────────────────────────────────────────────────────

RANK_OP = "calc.set.rank"
DIRECTIONS = ("highest", "lowest")


def _label_of(t: Typed) -> str | None:
    """What to call one entry in a ranking: the issuer it belongs to."""
    return t.issuers[0] if len(t.issuers) == 1 else None


async def rank(db: AsyncSession, refs: list[str], *, direction: str = "highest",
               as_quantity: str | None = None, invoked_by: str = "agent") -> dict:
    """Order quantities that are comparable, and record the order.

    WHY THIS EXISTS. The gate guarantees where every figure came from; it says
    nothing about the sentence between two figures. Asked which of five holdings
    had the highest accruals ratio, the model laid out five true, correctly cited
    values and then wrote "3.40% on JPM was the highest, above 4.11%" — every
    slot true, the ordering claim false (V16 battery, G6). It had no ordering
    primitive, so it compared by eye.

    So an ordering becomes a computation like any other: it has operands, it has
    refusals, it writes a ledger row, and its result is a set of NAMES the answer
    can slot — `accruals_ratio.rank.JPM` is 1 or it is not. What this removes is
    the class where the ordering was never computed at all. A superlative typed
    into prose is still prose; the difference is that the correct ordering now
    costs one call and arrives with the ordinals.

    The refusals are the ones a league table can be wrong in before any
    arithmetic happens: two different measures compared as one, two units
    compared as one, the same figure entered twice, or entries with nothing to
    tell them apart.
    """
    if direction not in DIRECTIONS:
        return _err("unsupported_direction", f"{direction!r}; supported: {', '.join(DIRECTIONS)}")
    refs = list(refs or [])
    if len(refs) < 2:
        return _err("too_few_operands",
                    f"an ordering needs at least two quantities; got {len(refs)}")
    if len(set(refs)) != len(refs):
        dupes = sorted({r for r in refs if refs.count(r) > 1})
        return _err("duplicate_operand",
                    f"{', '.join(dupes)} appears more than once. One figure cannot hold "
                    f"two places in an order.")

    typed: list[Typed] = []
    for ref in refs:
        t = await _resolve(db, ref)
        if isinstance(t, dict):
            return t
        if isinstance(t, TypedSeries):
            return _err("unrankable_operand",
                        f"{ref} is a series, which has no single value to place. Rank the "
                        f"points' own rows, or take a statistic of the series first.")
        typed.append(t)

    units_seen = {t.unit_class for t in typed}
    if len(units_seen) > 1:
        return _err("incomparable_units",
                    f"these are not one measure: {', '.join(sorted(units_seen))}. An order "
                    f"over mixed units ranks dollars against percentages.")

    quantities_seen = {t.quantity for t in typed}
    if len(quantities_seen) > 1 or None in quantities_seen:
        named = sorted(str(q) for q in quantities_seen)
        return _err("incomparable_quantities",
                    f"an ordering compares one measure across several holders; these are "
                    f"{', '.join(named)}. Compute the same measure for each name first.")
    quantity = typed[0].quantity

    labels = [_label_of(t) for t in typed]
    if None in labels or len(set(labels)) != len(labels):
        # Two entries this function cannot tell apart would produce a table with
        # two rows called the same thing, and a rank name that resolves to
        # whichever was written last. Refused rather than numbered.
        return _err("indistinguishable_operands",
                    f"each entry in an ordering must belong to exactly one issuer, and to a "
                    f"different one: got {[l or '?' for l in labels]}. Rank one measure "
                    f"across issuers.")

    # V24: the entry's date as data beside the basis sentence — an instant's
    # date, or the end of an interval — so the Fact made of it says as of when.
    entries = [{"label": lb, "ref": t.source_id, "value": t.value, "basis": _basis_str(t),
                "as_of": (t.instant.isoformat() if t.instant else t.interval[1].isoformat() if t.interval else None)}
               for lb, t in zip(labels, typed)]
    entries.sort(key=lambda e: e["value"], reverse=(direction == "highest"))
    # Competition ranking: equal values share a place, because numbering them
    # 1 and 2 asserts a difference the figures do not have.
    ties = 0
    for i, e in enumerate(entries):
        if i and e["value"] == entries[i - 1]["value"]:
            e["rank"] = entries[i - 1]["rank"]
            ties += 1
        else:
            e["rank"] = i + 1

    values = [e["value"] for e in entries]
    name = as_quantity or quantity
    unit = typed[0].unit_class
    result = {
        "ordering": entries,
        "leader": entries[0]["label"],
        "direction": direction,
        "ranked": len(entries),
        "spread": max(values) - min(values),
    }
    flags = {"tied_places": ties} if ties else {}
    rt = {"unit_class": unit, "kind": "ranking", "quantity": name,
          "issuers": sorted({lb for lb in labels if lb})}
    bases = {t.base for t in typed}
    if len(bases) == 1 and None not in bases:
        rt["base"] = bases.pop()     # an ordering of one book's figures is a figure of it
    calc_id = await cs._record(
        db, None, RANK_OP,
        {"op": "rank", "operands": refs, "direction": direction,
         "operand_types": [t.as_dict() for t in typed], "result_type": rt},
        result, refs, flags, invoked_by,
    )
    # V24: the ordering's date is the latest of its entries' — the spread is a
    # figure and a figure says as of when; each entry still keeps its own.
    dated = [e["as_of"] for e in entries if e.get("as_of")]
    return {"calc_id": calc_id, "op": "rank", "quantity": name, "direction": direction,
            "as_of": max(dated) if dated else None,
            "leader": result["leader"], "ordering": entries, "spread": result["spread"],
            "type": rt, "operands": refs, "quality_flags": flags,
            "basis": (f"{len(entries)} quantities named {quantity}, ordered {direction} "
                      f"first; each entry keeps its own period")}
