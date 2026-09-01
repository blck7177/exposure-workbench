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
that needs it ("how much has it moved?") to get_balance_sheet, which reads one
instant and cannot produce a change. The point is not to narrow what may be
analysed; it is that the one region where a wrong answer is indistinguishable
from a right one stops being reachable.

An operand whose type cannot be established is refused rather than assumed
compatible: a guard whose blind spot is silent is worse than no guard, because
it is trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import containment as ct
from exposure_workbench.db.models import CalcLedger, Company, FinancialFact
from exposure_workbench.services import calc_service as cs

OPS = ("add", "subtract", "multiply", "divide")
# COUNT is what a ratio becomes when a constant with a unit is applied to it:
# a fraction of a year times 365 is a number of days. It is never inferred —
# only `scale` produces it, and only because its caller says so.
MONEY, RATIO, COUNT = "money", "ratio", "count"


@dataclass(frozen=True)
class Typed:
    """A number and everything needed to decide what it may be combined with."""
    value: float
    unit_class: str                       # money | ratio | count
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

    def basis(self) -> dict:
        if self.instant:
            return {"instant": self.instant.isoformat()}
        if self.interval:
            return {"interval": [self.interval[0].isoformat(), self.interval[1].isoformat()]}
        return self.recorded_basis or {"mixed": "unspecified"}

    def as_dict(self) -> dict:
        return {"unit_class": self.unit_class, "basis": self.basis(),
                "quantity": self.quantity, "source_id": self.source_id,
                "issuers": list(self.issuers)}


def _err(code: str, detail: str) -> dict:
    return {"error": code, "detail": detail}


async def _resolve(db: AsyncSession, ref: str) -> Typed | dict:
    """A fact or a calc, as a typed quantity."""
    if ref.startswith("fact_"):
        row = (await db.execute(
            select(FinancialFact).where(FinancialFact.id == ref)
        )).scalar_one_or_none()
        if row is None or row.value is None:
            return _err("unknown_operand", f"{ref} is not a fact this desk holds")
        ticker = (await db.execute(
            select(Company.ticker).where(Company.id == row.company_id)
        )).scalar_one_or_none()
        return Typed(
            value=float(row.value),
            unit_class=MONEY if (row.unit or "").upper() == "USD" else RATIO,
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
        params = row.params or {}
        owned = _row_issuers(params.get("result_type"), row.company_id)
        points = (row.result or {}).get("points")
        if isinstance(points, list):
            return _resolve_series(ref, row.operation, params, points, owned)
        value = (row.result or {}).get("value")
        # derive.interval rows predate result_type but carry everything needed.
        if row.operation == cs_op_flow() and params.get("period"):
            p = params["period"]
            return Typed(value=float(value), unit_class=MONEY,
                         interval=(date.fromisoformat(p["start"]), date.fromisoformat(p["end"])),
                         quantity=params.get("metric"), source_id=ref, issuers=owned)
        t = params.get("result_type")
        if not t or value is None:
            return _err(
                "untyped_operand",
                f"{ref} was recorded before quantities carried their type, so what it "
                f"may be combined with cannot be established. Recompute it with "
                f"get_flow, get_balance_sheet or calculate.")
        basis = t.get("basis") or {}
        return Typed(
            value=float(value), unit_class=t.get("unit_class", MONEY),
            instant=date.fromisoformat(basis["instant"]) if basis.get("instant") else None,
            interval=(date.fromisoformat(basis["interval"][0]),
                      date.fromisoformat(basis["interval"][1])) if basis.get("interval") else None,
            quantity=t.get("quantity"), source_id=ref, recorded_basis=basis or None,
            issuers=owned,
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
    return _err("unknown_operand", f"{ref} is not a fact_ or calc_ id")


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
                    f"Recompute it with get_flow(last_n=…) or get_balance_series.")
    unit = rt.get("unit_class", MONEY)
    kind = rt.get("kind", "series")
    quantity = rt.get("quantity")
    typed: list[tuple[date, Typed]] = []
    for p in points:
        end_s = p.get("end") or p.get("as_of")
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


def _check(op: str, a: Typed, b: Typed) -> dict | None:
    if op in ("multiply", "divide"):
        return None                      # a ratio may cross bases; it says which

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
        if (t.unit_class != RATIO and t.instant is None and t.interval is None
                and (t.recorded_basis or {}).get("leaves")):
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
    # subtract as well, and its way out pointed at get_balance_sheet — which
    # reads one instant and cannot produce a change.
    if op == "add" and a.instant and b.instant and a.instant != b.instant:
        return _err("different_instants",
                    f"{a.source_id} is as of {a.instant.isoformat()} and {b.source_id} is "
                    f"as of {b.instant.isoformat()}. Balances from two dates describe two "
                    f"company-moments and cannot be summed; ask for both at one date with "
                    f"get_balance_sheet, or subtract them for the change between the two "
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
                    f"window with get_flow(start=..., end=...).")
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


def _result_type(op: str, a: Typed, b: Typed, value: float) -> Typed:
    issuers = tuple(sorted(set(a.issuers) | set(b.issuers)))
    if op in ("multiply", "divide"):
        unit = RATIO if (op == "divide" and a.unit_class == b.unit_class) else a.unit_class
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


async def calculate(db: AsyncSession, op: str, a: str, b: str,
                    invoked_by: str = "agent", as_quantity: str | None = None) -> dict:
    """Combine two quantities, if their types permit it.

    `as_quantity` is the name the CALLER gives the result — a formula naming
    its final step `net_margin`. The row records it as result_type.quantity,
    which is what the table calls the value (services/quantities.py); without
    it a measure the model asked for by name came back named `calc.scalar.
    divide`, and the model wrote the name it knew and was refused for it.
    The typing is unchanged: a named quantity is still checked like any other.
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
    basis = result.basis()

    rt = {"unit_class": result.unit_class, "basis": basis,
          "quantity": as_quantity or result.quantity, "issuers": list(result.issuers)}
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
    rt = {"unit_class": unit_class, "basis": left.basis(), "quantity": quantity,
          "issuers": list(left.issuers)}
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
            points.append({"end": end.isoformat(), "value": None, "flags": {"division_by_zero": True},
                           "fact_ids": []})
            continue
        value = {"add": lt.value + rt.value, "subtract": lt.value - rt.value,
                 "multiply": lt.value * rt.value, "divide": lt.value / rt.value}[op]
        r = _result_type(op, lt, rt, value)
        sample_type = sample_type or r
        pt = {"end": end.isoformat(), "value": value, "fact_ids": []}
        if r.interval:
            pt["start"] = r.interval[0].isoformat()
        points.append(pt)

    unit = sample_type.unit_class if sample_type else left.unit_class
    kind = ("flow" if sample_type and sample_type.interval else
            "instant" if sample_type and sample_type.instant else "series")
    rt_out = {"unit_class": unit, "kind": kind, "quantity": None,
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
