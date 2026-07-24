"""CSV holdings parser (V2-B) — pure, no DB.

Format: `ticker,quantity[,cost_basis]`, one holding per line. A first line that
contains "ticker" is treated as a header. Returns (rows, problems): every
malformed line becomes a CsvProblem with its 1-based row number and reason. The
caller enforces atomicity — any problem => reject the whole upload, zero writes
(see portfolio_service.upload_positions). Fail loud, never silently drop a row.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_ROWS = 200


@dataclass(frozen=True)
class PositionRow:
    ticker: str
    quantity: float
    cost_basis: float | None


@dataclass(frozen=True)
class CsvProblem:
    row: int          # 1-based line number in the submitted text
    ticker: str       # best-effort ticker text (may be "")
    reason: str


def _num(s: str) -> float | None:
    """Parse a number, rejecting non-finite values. Bare float() accepts 'nan',
    'inf' and overflowing literals like '1e400' — NaN/Inf would slip past the
    quantity>0 guard (NaN comparisons are always False) and commit as corrupt
    NUMERIC, or raise a raw asyncpg error deep in the write. Reject here."""
    try:
        v = float(s.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_csv(text: str) -> tuple[list[PositionRow], list[CsvProblem]]:
    rows: list[PositionRow] = []
    problems: list[CsvProblem] = []

    lines = [ln for ln in (text or "").splitlines()]
    # drop trailing blank lines but keep row numbering aligned to the input
    data_lines: list[tuple[int, str]] = [
        (i + 1, ln) for i, ln in enumerate(lines) if ln.strip() != ""
    ]
    if not data_lines:
        return [], [CsvProblem(0, "", "empty: no rows")]

    # header detection: a first non-empty line mentioning "ticker"
    first_no, first_ln = data_lines[0]
    if "ticker" in first_ln.lower():
        data_lines = data_lines[1:]

    if len(data_lines) > MAX_ROWS:
        problems.append(CsvProblem(0, "", f"too many rows: {len(data_lines)} > {MAX_ROWS}"))
        # still parse for per-row feedback, but this alone rejects the upload

    seen: set[str] = set()
    for line_no, raw in data_lines:
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) < 2 or len(parts) > 3:
            problems.append(CsvProblem(line_no, parts[0] if parts else "",
                                       f"expected 'ticker,quantity[,cost_basis]', got {len(parts)} field(s)"))
            continue
        ticker = parts[0].upper()
        if not ticker:
            problems.append(CsvProblem(line_no, "", "missing ticker"))
            continue
        qty = _num(parts[1])
        if qty is None:
            problems.append(CsvProblem(line_no, ticker, f"quantity not a number: {parts[1]!r}"))
            continue
        if qty <= 0:
            problems.append(CsvProblem(line_no, ticker, f"quantity must be > 0, got {qty}"))
            continue
        cost = None
        if len(parts) == 3 and parts[2] != "":
            cost = _num(parts[2])
            if cost is None:
                problems.append(CsvProblem(line_no, ticker, f"cost_basis not a number: {parts[2]!r}"))
                continue
        if ticker in seen:
            problems.append(CsvProblem(line_no, ticker, "duplicate ticker"))
            continue
        seen.add(ticker)
        rows.append(PositionRow(ticker=ticker, quantity=qty, cost_basis=cost))

    return rows, problems
