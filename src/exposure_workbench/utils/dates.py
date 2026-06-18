"""Date utilities."""

from __future__ import annotations

from datetime import date, datetime, timezone


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
