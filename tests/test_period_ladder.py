"""M3 period ladder — the three scenarios that motivated it (offline, exact values)."""

from __future__ import annotations

from datetime import date

from exposure_workbench.analytics import period_ladder as pl


def f(fid, end, value, start=None, acc=None, filed=None) -> pl.FactPoint:
    return pl.FactPoint(
        fact_id=fid,
        period_end=date.fromisoformat(end),
        value=value,
        period_start=date.fromisoformat(start) if start else None,
        source_accession=acc,
        filing_date=date.fromisoformat(filed) if filed else None,
    )


def test_classify_duration_buckets():
    assert pl.classify_duration(None, date(2026, 1, 25)) == pl.INSTANT
    assert pl.classify_duration(date(2026, 1, 26), date(2026, 4, 26)) == pl.QUARTERLY   # 90d
    assert pl.classify_duration(date(2025, 1, 27), date(2026, 1, 25)) == pl.ANNUAL      # 363d
    assert pl.classify_duration(date(2025, 1, 27), date(2025, 7, 27)) == pl.HALF        # ~181d
    assert pl.classify_duration(date(2025, 1, 27), date(2025, 10, 26)) == pl.NINE_MONTH


def test_cumulative_ytd_facts_are_not_treated_as_quarters():
    facts = [
        f("q1", "2025-04-27", 44.0, "2025-01-27"),      # quarter
        f("h1", "2025-07-27", 90.0, "2025-01-27"),      # half-year cumulative
        f("m9", "2025-10-26", 147.0, "2025-01-27"),     # nine-month cumulative
    ]
    lad = pl.build_ladder(facts, "revenue", pl.QUARTERLY)
    assert [p.period_end.isoformat() for p in lad.points] == ["2025-04-27"]


def test_restatement_picks_latest_filing_and_flags_it():
    facts = [
        f("old", "2025-04-27", 44.0, "2025-01-27", acc="0001045810-25-000116", filed="2025-05-28"),
        f("new", "2025-04-27", 44.5, "2025-01-27", acc="0001045810-26-000052", filed="2026-05-20"),
    ]
    lad = pl.build_ladder(facts, "revenue", pl.QUARTERLY)
    assert len(lad.points) == 1
    assert lad.points[0].value == 44.5                       # latest filing wins
    assert lad.points[0].input_fact_ids == ["new"]
    assert lad.points[0].quality_flags["restated_superseded"] == 1
    assert lad.quality_flags["restated_periods"] == 1


def test_fiscal_year_labels_are_irrelevant_only_periods_matter():
    """Same period filed twice under different FY labels must collapse to one point."""
    facts = [
        f("a", "2025-04-27", 44.06, "2025-01-27", acc="0001045810-25-000116", filed="2025-05-28"),
        f("b", "2025-04-27", 44.06, "2025-01-27", acc="0001045810-26-000052", filed="2026-05-20"),
    ]
    assert len(pl.build_ladder(facts, "revenue", pl.QUARTERLY).points) == 1


def test_derive_q4_fills_the_missing_quarter():
    quarters = [
        f("q1", "2025-04-27", 44.0, "2025-01-27"),
        f("q2", "2025-07-27", 46.0, "2025-04-28"),
        f("q3", "2025-10-26", 57.0, "2025-07-28"),
    ]
    annual = [f("fy", "2026-01-25", 215.0, "2025-01-27")]
    q = pl.build_ladder(quarters, "revenue", pl.QUARTERLY)
    a = pl.build_ladder(annual, "revenue", pl.ANNUAL)
    out = pl.derive_q4(q, a)

    assert len(out.points) == 4
    q4 = out.points[-1]
    assert q4.period_end == date(2026, 1, 25)
    assert q4.value == 215.0 - (44.0 + 46.0 + 57.0)          # == 68.0
    assert q4.quality_flags["derived_q4"] is True
    assert out.quality_flags["derived_q4_periods"] == 1
    # provenance: derived point cites all four source facts
    assert set(q4.input_fact_ids) == {"q1", "q2", "q3", "fy"}


def test_derive_q4_refuses_when_year_is_incomplete():
    quarters = [f("q1", "2025-04-27", 44.0, "2025-01-27"),
                f("q2", "2025-07-27", 46.0, "2025-04-28")]     # only 2 quarters
    annual = [f("fy", "2026-01-25", 215.0, "2025-01-27")]
    out = pl.derive_q4(
        pl.build_ladder(quarters, "revenue", pl.QUARTERLY),
        pl.build_ladder(annual, "revenue", pl.ANNUAL),
    )
    assert len(out.points) == 2                                # guessed nothing
    assert "derived_q4_periods" not in out.quality_flags


def test_derive_q4_skips_when_real_q4_present():
    quarters = [
        f("q1", "2025-04-27", 44.0, "2025-01-27"),
        f("q2", "2025-07-27", 46.0, "2025-04-28"),
        f("q3", "2025-10-26", 57.0, "2025-07-28"),
        f("q4", "2026-01-25", 68.0, "2025-10-27"),
    ]
    annual = [f("fy", "2026-01-25", 215.0, "2025-01-27")]
    out = pl.derive_q4(
        pl.build_ladder(quarters, "revenue", pl.QUARTERLY),
        pl.build_ladder(annual, "revenue", pl.ANNUAL),
    )
    assert len(out.points) == 4
    assert not any(p.quality_flags.get("derived_q4") for p in out.points)


def test_empty_input_flags_rather_than_raises():
    lad = pl.build_ladder([], "revenue", pl.QUARTERLY)
    assert lad.points == [] and lad.quality_flags["no_facts_for_period_type"] is True
