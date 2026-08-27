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
intervals is fine — H1 − Q1 = Q2 is how a window is derived at all. The point is
not to narrow what may be analysed; it is that the one region where a wrong
answer is indistinguishable from a right one stops being reachable.

An operand whose type cannot be established is refused rather than assumed
compatible: a guard whose blind spot is silent is worse than no guard, because
it is trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import containment as ct
from exposure_workbench.db.models import CalcLedger, FinancialFact
from exposure_workbench.services import calc_service as cs

OPS = ("add", "subtract", "multiply", "divide")
MONEY, RATIO = "money", "ratio"


@dataclass(frozen=True)
class Typed:
    """A number and everything needed to decide what it may be combined with."""
    value: float
    unit_class: str                       # money | ratio
    instant: date | None = None           # a balance: as of this date
    interval: tuple[date, date] | None = None   # a flow: over these days
    quantity: str | None = None           # the metric, for containment
    source_id: str = ""

    def basis(self) -> dict:
        if self.instant:
            return {"instant": self.instant.isoformat()}
        if self.interval:
            return {"interval": [self.interval[0].isoformat(), self.interval[1].isoformat()]}
        return {"mixed": "unspecified"}

    def as_dict(self) -> dict:
        return {"unit_class": self.unit_class, "basis": self.basis(),
                "quantity": self.quantity, "source_id": self.source_id}


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
        return Typed(
            value=float(row.value),
            unit_class=MONEY if (row.unit or "").upper() == "USD" else RATIO,
            instant=row.period_end if row.period_start is None else None,
            interval=None if row.period_start is None else (row.period_start, row.period_end),
            quantity=row.normalized_metric, source_id=ref,
        )
    if ref.startswith("calc_"):
        row = (await db.execute(
            select(CalcLedger).where(CalcLedger.id == ref)
        )).scalar_one_or_none()
        if row is None:
            return _err("unknown_operand", f"{ref} is not a calculation this desk holds")
        params = row.params or {}
        value = (row.result or {}).get("value")
        # derive.interval rows predate result_type but carry everything needed.
        if row.operation == cs_op_flow() and params.get("period"):
            p = params["period"]
            return Typed(value=float(value), unit_class=MONEY,
                         interval=(date.fromisoformat(p["start"]), date.fromisoformat(p["end"])),
                         quantity=params.get("metric"), source_id=ref)
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
            quantity=t.get("quantity"), source_id=ref,
        )
    return _err("unknown_operand", f"{ref} is not a fact_ or calc_ id")


def cs_op_flow() -> str:
    from exposure_workbench.services.fundamentals_service import OP_FLOW
    return OP_FLOW


# ── the four refusals ─────────────────────────────────────────────────────────

def _check(op: str, a: Typed, b: Typed) -> dict | None:
    if op in ("multiply", "divide"):
        return None                      # a ratio may cross bases; it says which

    if a.unit_class != b.unit_class:
        return _err("incompatible_units",
                    f"{a.source_id} is {a.unit_class} and {b.source_id} is {b.unit_class}")

    if (a.instant is not None) != (b.instant is not None):
        return _err("incompatible_bases",
                    f"{a.source_id} is {'a balance' if a.instant else 'a flow'} and "
                    f"{b.source_id} is {'a balance' if b.instant else 'a flow'}; "
                    f"a stock and a flow may be divided, not added")

    if a.instant and b.instant and a.instant != b.instant:
        return _err("different_instants",
                    f"{a.source_id} is as of {a.instant.isoformat()} and {b.source_id} is "
                    f"as of {b.instant.isoformat()}. Balances from two dates describe two "
                    f"company-moments; ask for both at one date with get_balance_sheet.")

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


def _result_type(op: str, a: Typed, b: Typed, value: float) -> Typed:
    if op in ("multiply", "divide"):
        unit = RATIO if (op == "divide" and a.unit_class == b.unit_class) else a.unit_class
        return Typed(value=value, unit_class=unit, quantity=None)
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
                    invoked_by: str = "agent") -> dict:
    """Combine two quantities, if their types permit it."""
    if op not in OPS:
        return _err("unsupported_op", f"{op!r}; supported: {', '.join(OPS)}")

    left = await _resolve(db, a)
    if isinstance(left, dict):
        return left
    right = await _resolve(db, b)
    if isinstance(right, dict):
        return right

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
    if op in ("multiply", "divide"):
        basis = {"mixed": " / ".join(
            v for v in (_basis_str(left), _basis_str(right)) if v)}

    rt = {"unit_class": result.unit_class, "basis": basis, "quantity": result.quantity}
    calc_id = await cs._record(
        db, None, f"calc.scalar.{op}",
        {"op": op, "operands": [a, b],
         "operand_types": [left.as_dict(), right.as_dict()],
         "result_type": rt},
        {"value": value}, [a, b], {}, invoked_by,
    )
    return {"calc_id": calc_id, "op": op, "value": value, "type": rt,
            "operands": [a, b],
            "basis": f"{_basis_str(left)} {op} {_basis_str(right)}"}


def _basis_str(t: Typed) -> str:
    if t.instant:
        return t.instant.isoformat()
    if t.interval:
        return f"{t.interval[0].isoformat()}..{t.interval[1].isoformat()}"
    return ""
