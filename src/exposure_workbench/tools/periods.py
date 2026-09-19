"""The typed period two verbs share (plan V1 §2.3: `period ∈ {fy, quarter, ttm_to,
months+end, at}`).

WHY THIS EXISTS. Step 3 built `filings_read` and `metric` as thin wrappers, so each
spoke its service's parameters: a window's end was `end` on one and `at` on the
other, and a fiscal year could not be said at all. Thirteen of 118 period-carrying
calls in the first live runs got the spelling wrong, ten of them by handing `end`
to a measure. Period misalignment is the first thing a finance agent gets wrong
(plan §2.0), so the period is a TYPE, said one way on both verbs, and resolved
HERE — the tool layer — into the concrete window a service is asked with. The
services keep taking dates; they do not learn a vocabulary.

THE FIVE KINDS, each one key:
    {"fy": 2025}                      the issuer's fiscal year, as IT labels it
    {"quarter": "2026Q2"}             the issuer's fiscal quarter
    {"ttm_to": "2025-06-30"}          the twelve months ending there
    {"months": 6, "end": "2025-06-30"}  N months ending there (3, 6, 9 or 12)
    {"at": "2025-06-30"}              a date — a balance's
Any date, year or quarter may be "latest". No period at all is the latest: the
latest twelve months of a flow, the latest date of a balance. The row always
states the period it HAS.

A fiscal year is the issuer's own label and is read off what it filed
(services/period_semantics.fiscal_calendar), so FY2025 is Microsoft's year to
June and Apple's to September — the same question asked of each.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import period_semantics

_DATE = r"^(\d{4}-\d{2}-\d{2}|latest)$"
_A_DATE = {"type": "string", "pattern": _DATE}


def _one(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_KINDS = [
    _one({"fy": {"oneOf": [{"type": "integer", "minimum": 1990, "maximum": 2100}, {"const": "latest"}]}}, ["fy"]),
    _one({"quarter": {"type": "string", "pattern": r"^(\d{4}Q[1-4]|latest)$"}}, ["quarter"]),
    _one({"ttm_to": _A_DATE}, ["ttm_to"]),
    _one({"months": {"type": "integer", "enum": [3, 6, 9, 12]}, "end": _A_DATE}, ["months", "end"]),
    _one({"at": _A_DATE}, ["at"]),
    {"type": "null"},
]
PERIOD_SAID = ("the period, said ONE way — {\"fy\": 2025} the issuer's own fiscal year · {\"quarter\": \"2026Q2\"} its "
               "fiscal quarter · {\"ttm_to\": \"2025-06-30\"} the twelve months ending there · {\"months\": 6, \"end\": "
               "\"2025-06-30\"} N months ending there · {\"at\": \"2025-06-30\"} a date, for a balance. A date is "
               "YYYY-MM-DD; any of them may be \"latest\". Omitted: the latest — a flow's latest twelve months, a "
               "balance's latest date.")
# said in full once a face (on the read); the measure verb beside it points there
PERIOD_SCHEMA: dict = {"description": PERIOD_SAID, "oneOf": _KINDS}
PERIOD_SCHEMA_BRIEF: dict = {"description": "the same typed period `filings_read` takes", "oneOf": _KINDS}

LAST_N_SCHEMA: dict = {"type": ["integer", "null"], "minimum": 1, "maximum": 40,
                       "description": "the last N as ONE series: N fiscal years with {\"fy\": \"latest\"}, N fiscal "
                                      "quarters with {\"quarter\": \"latest\"}, a balance's last N filed dates with "
                                      "{\"at\": \"latest\"}"}

WINDOW_KINDS = ("fy", "quarter", "ttm_to", "months")


@dataclass(frozen=True)
class Asked:
    """One resolved period: what a service is asked with."""
    kind: str                       # fy | quarter | ttm_to | months | at | latest
    start: date | None = None       # fy, quarter: the period as filed
    end: date | None = None         # None: the latest
    months: int | None = None       # the window's length, where it has one
    latest: bool = False            # the caller said "latest" (or nothing)
    said: str = ""                  # "FY2025", "FY2026 Q2" — the label, where there is one

    @property
    def end_iso(self) -> str | None:
        return self.end.isoformat() if self.end else None


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


def _day(value: str) -> date | None | dict:
    if value == "latest":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return _err("invalid_params", f"{value!r} is not a date: YYYY-MM-DD, or \"latest\"")


async def resolve(db: AsyncSession, ticker: str, period: dict | None) -> Asked | dict:
    """The period as asked, against THIS issuer's calendar — or the refusal."""
    if period is None:
        return Asked("latest", latest=True)
    if not isinstance(period, dict) or len([k for k in period if k != "end"]) != 1:
        return _err("invalid_params", "a period is ONE of fy, quarter, ttm_to, months (with end), at")
    if "fy" in period or "quarter" in period:
        cal = await period_semantics.fiscal_calendar(db, ticker)
        if cal is None:
            return _err("not_held", f"{ticker} has filed no period this desk can place in a fiscal calendar")
        if "fy" in period:
            fy = period["fy"]
            year = (cal.years[-1] if cal.years else None) if fy == "latest" else cal.year(int(fy)) if isinstance(fy, int) else None
            if year is None:
                return _err("not_held", f"{ticker} has no fiscal year {fy} on file",
                            available=[f"{y.label} ({y.start.isoformat()} to {y.end.isoformat()})" for y in cal.years[-6:]])
            return Asked("fy", year.start, year.end, 12, latest=fy == "latest", said=year.label)
        q = str(period["quarter"])
        m = re.fullmatch(r"(\d{4})Q([1-4])", q)
        quarter = (cal.quarters[-1] if cal.quarters else None) if q == "latest" else cal.quarter(int(m[1]), int(m[2])) if m else None
        if quarter is None:
            return _err("not_held", f"{ticker} has no fiscal quarter {q} on file",
                        available=[f"{x.fy}Q{x.q} ({x.start.isoformat()} to {x.end.isoformat()})" for x in cal.quarters[-8:]])
        return Asked("quarter", quarter.start, quarter.end, 3, latest=q == "latest", said=quarter.label)
    key = next(k for k in period if k != "end")
    if key not in ("ttm_to", "months", "at"):
        return _err("invalid_params", f"{key!r} is not a kind of period: fy, quarter, ttm_to, months (with end), at")
    raw = period["end"] if key == "months" else period[key]
    if key == "months" and "end" not in period:
        return _err("invalid_params", "months goes with `end`: {\"months\": 6, \"end\": \"2025-06-30\"}")
    day = _day(str(raw))
    if isinstance(day, dict):
        return day
    if key == "at":
        return Asked("at", end=day, latest=day is None)
    months = 12 if key == "ttm_to" else int(period["months"])
    if months not in (3, 6, 9, 12):
        return _err("invalid_params", f"a window is 3, 6, 9 or 12 months; got {months}")
    return Asked("ttm_to" if key == "ttm_to" else "months", end=day, months=months, latest=day is None)
