"""M3 calculation algebra — exact values + missing-data honesty (offline)."""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.analytics import series_ops as so


def sp(end: str, v, ids=None) -> so.SeriesPoint:
    return so.SeriesPoint(date.fromisoformat(end), v, ids or [])


Q = ["2025-01-31", "2025-04-30", "2025-07-31", "2025-10-31", "2026-01-31"]


def test_change_yoy_matches_one_year_back_by_date():
    s = [sp(Q[i], v) for i, v in enumerate([100.0, 110.0, 120.0, 130.0, 150.0])]
    r = so.compute_change(s, "yoy")
    assert len(r.points) == 1
    assert r.points[0].value == pytest.approx(0.5)          # 2026-01-31 vs 2025-01-31
    assert r.points[0].period_end == date(2026, 1, 31)


def test_yoy_on_a_SPARSE_series_does_not_compare_across_years():
    """Regression: cash-flow metrics are filed cumulatively, so a 'quarterly'
    series can hold only Q1 of each year. Positional lag-4 compared 2026 against
    2022 and reported it as YoY growth (a measured 2808%). Date matching must
    compare each point with ~1 year earlier, or emit nothing."""
    sparse = [sp("2022-05-01", 10.0), sp("2023-04-30", 20.0),
              sp("2024-04-28", 30.0), sp("2025-04-27", 40.0), sp("2026-04-26", 50.0)]
    r = so.compute_change(sparse, "yoy")
    # each point (except the first) has a genuine ~1-year prior
    assert len(r.points) == 4
    assert r.points[-1].period_end == date(2026, 4, 26)
    assert r.points[-1].value == pytest.approx(0.25)        # 50 vs 40, NOT 50 vs 10
    assert all(p.value is not None and p.value < 1.5 for p in r.points)


def test_yoy_emits_nothing_when_no_comparable_prior_exists():
    gappy = [sp("2022-05-01", 10.0), sp("2026-04-26", 50.0)]   # 4-year hole
    r = so.compute_change(gappy, "yoy")
    assert r.points == []                                   # refuses to bridge the gap
    assert r.quality_flags["periods_without_comparable_prior"] >= 1


def test_change_qoq_matches_one_quarter_back_by_date():
    s = [sp(Q[0], 100.0), sp(Q[1], 150.0)]                  # ~89 days apart
    assert so.compute_change(s, "qoq").points[0].value == pytest.approx(0.5)


def test_change_abs_uses_immediately_prior_point():
    s = [sp(Q[0], 100.0), sp(Q[1], 150.0)]
    assert so.compute_change(s, "abs").points[0].value == pytest.approx(50.0)


def test_change_insufficient_history_is_flagged():
    r = so.compute_change([sp(Q[0], 100.0)], "yoy")
    assert r.points == []
    assert "insufficient_history" in r.quality_flags


def test_change_zero_base_is_none():
    r = so.compute_change([sp(Q[0], 0.0), sp(Q[1], 10.0)], "qoq")
    assert r.points[0].value is None
    assert r.quality_flags["zero_base_periods"] == 1


def test_stat_ops_exact():
    s = [sp(Q[0], 10.0), sp(Q[1], 20.0), sp(Q[2], 30.0)]
    assert so.compute_stat(s, "avg").value == pytest.approx(20.0)
    assert so.compute_stat(s, "min").value == 10.0
    assert so.compute_stat(s, "max").value == 30.0
    assert so.compute_stat(s, "sum").value == 60.0
    assert so.compute_stat(s, "latest").value == 30.0
    assert so.compute_stat(s, "std").value == pytest.approx(10.0)


def test_stat_cagr_and_undefined_cases():
    s = [sp("2021-01-31", 100.0), sp("2026-01-31", 200.0)]     # 5 years, 2x
    v = so.compute_stat(s, "cagr").value
    assert v == pytest.approx(0.1487, abs=1e-3)
    # sign change / zero base -> undefined, not a bogus number
    bad = so.compute_stat([sp("2021-01-31", -5.0), sp("2026-01-31", 10.0)], "cagr")
    assert bad.value is None and bad.quality_flags["cagr_undefined"] is True


def test_stat_skips_missing_points_and_flags():
    r = so.compute_stat([sp(Q[0], 10.0), sp(Q[1], None), sp(Q[2], 30.0)], "avg")
    assert r.value == pytest.approx(20.0)
    assert r.quality_flags["skipped_missing_points"] == 1


def test_stat_empty_series():
    r = so.compute_stat([], "avg")
    assert r.value is None and r.quality_flags["no_values"] is True


def _px(pairs) -> list[so.PricePoint]:
    return [so.PricePoint(date.fromisoformat(d), c) for d, c in pairs]


def test_window_return_uses_last_close_on_or_before_bounds():
    prices = _px([("2026-01-02", 100.0), ("2026-01-05", 110.0), ("2026-01-09", 121.0)])
    # 2026-01-03 is a weekend -> falls back to 01-02 close
    r = so.compute_window_return(prices, date(2026, 1, 3), date(2026, 1, 9))
    assert r.value == pytest.approx(0.21)


def test_window_return_relative_to_benchmark():
    stock = _px([("2026-01-02", 100.0), ("2026-01-09", 120.0)])     # +20%
    bench = _px([("2026-01-02", 100.0), ("2026-01-09", 110.0)])     # +10%
    r = so.compute_window_return(stock, date(2026, 1, 2), date(2026, 1, 9), benchmark=bench)
    assert r.value == pytest.approx(0.10)
    assert r.operation == "window_return.relative"


def test_window_return_without_prices_is_none():
    r = so.compute_window_return([], date(2026, 1, 1), date(2026, 2, 1))
    assert r.value is None and r.quality_flags["no_price_for_window"] is True

