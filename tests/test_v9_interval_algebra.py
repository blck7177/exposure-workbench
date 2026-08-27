"""V9-A1 — any window is a signed path over reported intervals (offline).

An issuer does not file the periods an analyst wants. AAPL files, for one
metric, a quarter, a half, a nine-month, a year, and then a quarter and a half
again — the same fiscal fact reported cumulatively from the year's start. The
old ladder classified the half and nine-month facts in order to DISCARD them,
kept two buckets, and left a trailing twelve months unreachable: its answer for
AAPL's operating cash flow was a ten-month-old fiscal year with an apology.

The data supports the answer. Flows add across adjacent intervals, so a window
is a path over boundaries, taken forwards or backwards:

    TTM to 2026-03-28  =  FY25 111.482 − H1'25 53.887 + H1'26 82.627 = 140.222
    Q2 FY26            =  H1'26 82.627 − Q1'26 53.925              =  28.702

Both are the same algorithm, and so is Q4 = FY − 9M, which the codebase already
had as a special case. The numbers below are AAPL's real filings, read out of
the corpus on 2026-08-25.
"""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.analytics import interval_algebra as ia


def f(fid: str, start: str, end: str, value: float) -> ia.FlowFact:
    return ia.FlowFact(fact_id=fid, period_start=date.fromisoformat(start),
                       period_end=date.fromisoformat(end), value=value)


# AAPL operating_cash_flow, $bn, exactly as filed.
AAPL = [
    f("h1_25", "2024-09-29", "2025-03-29", 53.887),
    f("m9_25", "2024-09-29", "2025-06-28", 81.754),
    f("fy_25", "2024-09-29", "2025-09-27", 111.482),
    f("q1_26", "2025-09-28", "2025-12-27", 53.925),
    f("h1_26", "2025-09-28", "2026-03-28", 82.627),
]
# MSFT files discrete quarters instead — the same engine, a different path.
MSFT = [
    f("q1", "2025-07-01", "2025-09-30", 45.06),
    f("q2", "2025-10-01", "2025-12-31", 35.76),
    f("q3", "2026-01-01", "2026-03-31", 46.68),
    f("q4", "2026-04-01", "2026-06-30", 40.00),
]


def test_a_trailing_year_that_no_single_fact_reports():
    got = ia.derive(AAPL, date(2025, 3, 30), date(2026, 3, 28))
    assert isinstance(got, ia.Derived)
    assert got.value == pytest.approx(140.222, abs=1e-9)
    assert dict(got.terms) == {"fy_25": 1, "h1_25": -1, "h1_26": 1}


def test_a_quarter_the_issuer_never_filed():
    """AAPL's second fiscal quarter exists only as the difference between two
    cumulative facts. The old ladder dropped both and reported no quarter."""
    got = ia.derive(AAPL, date(2025, 12, 28), date(2026, 3, 28))
    assert isinstance(got, ia.Derived)
    assert got.value == pytest.approx(28.702, abs=1e-9)
    assert dict(got.terms) == {"h1_26": 1, "q1_26": -1}


def test_a_reported_interval_is_returned_as_itself():
    got = ia.derive(AAPL, date(2024, 9, 29), date(2025, 9, 27))
    assert isinstance(got, ia.Derived)
    assert got.value == pytest.approx(111.482) and dict(got.terms) == {"fy_25": 1}


def test_q4_is_the_general_rule_not_a_special_case():
    """derive_q4 in the (now retired) period ladder was FY − (Q1+Q2+Q3). Here it is FY − 9M, one
    subtraction, and it falls out of the same search."""
    got = ia.derive(AAPL, date(2025, 6, 29), date(2025, 9, 27))
    assert isinstance(got, ia.Derived)
    assert got.value == pytest.approx(111.482 - 81.754, abs=1e-9)
    assert dict(got.terms) == {"fy_25": 1, "m9_25": -1}


def test_discrete_quarters_add_up_the_ordinary_way():
    got = ia.derive(MSFT, date(2025, 7, 1), date(2026, 6, 30))
    assert isinstance(got, ia.Derived)
    assert got.value == pytest.approx(45.06 + 35.76 + 46.68 + 40.00, abs=1e-9)
    assert len(got.terms) == 4 and all(sign == 1 for _fid, sign in got.terms)


def test_the_shortest_path_wins_because_every_edge_is_an_input():
    """Two routes reach the FY25 boundary; the one with fewer facts is preferred
    because each extra term is another number that can be restated or wrong."""
    got = ia.derive(AAPL, date(2025, 3, 30), date(2025, 9, 27))
    assert isinstance(got, ia.Derived)
    assert dict(got.terms) == {"fy_25": 1, "h1_25": -1}


def test_an_unreachable_window_is_refused_and_says_where_it_stopped():
    got = ia.derive(AAPL, date(2020, 1, 1), date(2026, 3, 28))
    assert isinstance(got, ia.Unreachable)
    assert "2020-01-01" in got.reason or "no path" in got.reason.lower()


def test_no_fact_is_used_twice_in_one_path():
    got = ia.derive(AAPL, date(2025, 3, 30), date(2026, 3, 28))
    assert isinstance(got, ia.Derived)
    ids = [fid for fid, _s in got.terms]
    assert len(ids) == len(set(ids))


# ── boundary tolerance: 52/53-week fiscal calendars ───────────────────────────

def test_boundaries_a_few_days_apart_are_the_same_boundary():
    """A 52/53-week filer's year ends on a different calendar date each year, so
    the end of one period and the start of the next can miss by a day or two.
    They are the same seam."""
    facts = [
        f("a", "2024-09-29", "2025-03-29", 10.0),
        f("b", "2025-03-31", "2025-09-27", 15.0),   # starts 2 days after a ends
    ]
    got = ia.derive(facts, date(2024, 9, 29), date(2025, 9, 27))
    assert isinstance(got, ia.Derived) and got.value == pytest.approx(25.0)


def test_a_real_gap_is_not_bridged_by_tolerance():
    facts = [
        f("a", "2024-09-29", "2025-03-29", 10.0),
        f("b", "2025-06-30", "2025-09-27", 15.0),   # three months missing
    ]
    got = ia.derive(facts, date(2024, 9, 29), date(2025, 9, 27))
    assert isinstance(got, ia.Unreachable)


# ── the window an agent actually asks for ─────────────────────────────────────

def test_latest_window_finds_the_most_recent_derivable_twelve_months():
    got = ia.latest_window(AAPL, months=12)
    assert isinstance(got, ia.Derived)
    assert got.value == pytest.approx(140.222, abs=1e-9)
    assert got.end == date(2026, 3, 28)
    assert "140" not in got.formula          # the formula names facts, not the answer
    assert got.formula.count("−") + got.formula.count("+") >= 2


def test_latest_window_states_the_interval_it_actually_derived():
    """Not "TTM" as a label — the two dates it really covers, because a window
    that had to stop short is still useful and must not pretend otherwise."""
    got = ia.latest_window(AAPL, months=12)
    assert isinstance(got, ia.Derived)
    assert got.start == date(2025, 3, 30) and got.end == date(2026, 3, 28)


def test_latest_window_refuses_rather_than_returning_a_shorter_period():
    """Three quarters is not a year. The old code's fallback was a different
    period wearing the same name."""
    got = ia.latest_window(MSFT[:2], months=12)
    assert isinstance(got, ia.Unreachable)
