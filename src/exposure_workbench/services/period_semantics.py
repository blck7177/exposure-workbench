"""This issuer's fiscal calendar, derived from the facts it filed (V12-K0).

FinRetrieval measured what is left once an agent has a catalogue of financial
tools: 63% of the remaining failures were the wrong PERIOD, attributed to
"undocumented tool conventions" — fiscal quarters read as calendar quarters,
a fiscal-year label read off the wrong end, a year-to-date figure read as a
quarter. Their conclusion was that better tool documentation would address
nearly two thirds of what still goes wrong.

Periods are the strongest thing this desk owns: the interval engine resolves any
window into a signed path over the boundary graph, so Q4, H1 and TTM are one
algorithm rather than three special cases. What the model saw of that was the
word "instant", "window" or "mixed". This is the rest of it.

Two details that decide the answer:

  * The fiscal calendar is derived from the ANNUAL FACTS, not from the
    `fiscal_year` column. That column is not trustworthy — one NVDA period is
    stored under both 2026 and 2027 — and a calendar built on it would be wrong
    for exactly the issuer whose calendar matters most.

  * Whether a metric is filed cumulatively is a property of the METRIC, not the
    issuer. NVDA files four window lengths of operating cash flow off one
    fiscal-year start and one length of revenue. Aggregated to the issuer it is
    23-36% for everybody and says nothing, so that half lives in the metric
    entries (S3) and not here.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, FinancialFact

# A filed window this long is the issuer's year. Wide enough for a 52/53-week
# retailer's calendar and for the odd late filing; narrow enough that a two-year
# comparative can never be mistaken for one.
_ANNUAL_DAYS = (330, 400)

# A fiscal year ending within a few days of a calendar quarter end is aligned
# with the calendar for a reader's purposes. NVDA's late-January year end is the
# case this exists to catch.
_QUARTER_END_MONTHS = (3, 6, 9, 12)
_QUARTER_END_FROM_DAY = 25

_HOW_TO_ASK = (
    "A flow is measured over an interval and a balance is read at an instant; "
    "they are different kinds of number and may not be added. Ask get_flow for "
    "the window you want — months=3 for a quarter, months=12 for a year — and it "
    "derives exactly that window from the periods this issuer filed, or refuses. "
    "It never returns a shorter period than the one you asked for."
)


async def describe_periods(db: AsyncSession, ticker: str) -> dict | None:
    """The fiscal calendar and how to ask for a window. None if nothing is filed."""
    company_id = (await db.execute(
        select(Company.id).where(Company.ticker == ticker.upper())
    )).scalar_one_or_none()
    if company_id is None:
        return None

    rows = (await db.execute(
        select(FinancialFact.period_start, FinancialFact.period_end)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric.is_not(None))
    )).all()
    if not rows:
        return None

    latest = max(pe for _ps, pe in rows if pe is not None)
    annual = [pe for ps, pe in rows
              if ps is not None and pe is not None
              and _ANNUAL_DAYS[0] <= (pe - ps).days <= _ANNUAL_DAYS[1]]

    out: dict = {"latest_period_end": latest.isoformat(), "how_to_ask": _HOW_TO_ASK}
    if not annual:
        return out

    fy_end = max(annual)
    aligned = (fy_end.month in _QUARTER_END_MONTHS and fy_end.day >= _QUARTER_END_FROM_DAY)
    out["fiscal_year_ends"] = fy_end.strftime("%b %d").replace(" 0", " ")
    out["fiscal_quarters_align_with_calendar"] = aligned
    if not aligned:
        out["note"] = (
            f"This issuer's fiscal year ends {out['fiscal_year_ends']}, so its "
            f"quarters do NOT line up with calendar quarters — a window ending "
            f"{latest.isoformat()} is one of its own fiscal quarters. State the "
            f"window dates rather than a quarter label."
        )
    return out


# The window lengths an issuer actually files, as day ranges. Ranges rather than
# nearest-match: snapping every span to the closest of four labels would report a
# two-year comparative as a twelve-month window, and a stub period as a quarter.
# A span outside all four is not labelled, which is the honest answer.
_WINDOW_BUCKETS: tuple[tuple[int, int, str], ...] = (
    (80, 100, "3-month"), (170, 195, "6-month"),
    (260, 285, "9-month"), (330, 400, "12-month"),
)


def filed_window_lengths(spans: list[tuple[date, date]]) -> tuple[str, ...]:
    """Which window lengths a metric was filed over — 3, 6, 9 or 12 months.

    The reason a caller needs this: an issuer filing 6- and 9-month windows off
    one fiscal-year start is filing cumulatively, and a single quarter after the
    first is then a subtraction rather than a reported number. That is a fact
    about the shape of what was filed, not a threshold — and it belongs to the
    METRIC, because NVDA files four lengths of operating cash flow and one of
    revenue.
    """
    found: set[str] = set()
    for start, end in spans:
        days = (end - start).days
        for lo, hi, label in _WINDOW_BUCKETS:
            if lo <= days <= hi:
                found.add(label)
                break
    order = [label for _lo, _hi, label in _WINDOW_BUCKETS]
    return tuple(sorted(found, key=order.index))
