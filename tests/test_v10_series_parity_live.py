"""V10-S1 — the series built from consecutive windows contains the ladder (live).

Run with:  pytest -m live -k series_parity

The old series (`period_ladder.build_ladder` + `derive_q4`) and the new one
(`interval_algebra.consecutive_windows`) must agree wherever the old one had a
point. They will not agree on the SET of points: the ladder classified every
fact into {quarter, annual, instant, other} and threw the others away, so a year
an issuer reported as H1 + FY has no quarterly points in the ladder at all. The
engine walks the boundary graph and finds H1 and (FY − H1). So the assertion is
containment — new ⊇ old — and every extra point is printed, because "the new
code found more" is only good news once each extra has been looked at.

Tolerance is A6's: the two routes may reach one window through different facts
(FY − 9M against FY − (Q1+Q2+Q3)) and meet only to the precision the filings
themselves agree to.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import timedelta

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import interval_algebra as ia
from tests import legacy_ladder as pl

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
REL_TOLERANCE = 5e-5
# A ladder point is keyed by the fact's own period_end; an engine window ends on
# the canonical date of that boundary's cluster. 52/53-week filers put the two a
# few days apart, and that is the whole allowance.
END_TOLERANCE = timedelta(days=ia.BOUNDARY_TOLERANCE_DAYS)
LAST_N = 40


async def _corpus():
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows = (await db.execute(text(
                "SELECT c.ticker, f.normalized_metric AS metric, f.id, f.period_start, "
                "       f.period_end, f.value, f.source_accession, fl.filing_date "
                "  FROM financial_facts f JOIN companies c ON c.id = f.company_id "
                "  LEFT JOIN filings fl ON fl.id = f.filing_id "
                " WHERE f.normalized_metric IS NOT NULL AND f.dimensions_hash = '' "
                "   AND f.value IS NOT NULL AND f.period_start IS NOT NULL"
            ))).mappings().all()
    finally:
        await engine.dispose()
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r["ticker"], r["metric"]), []).append(r)
    return grouped


def _old(rows, period_type):
    facts = [pl.FactPoint(fact_id=r["id"], period_end=r["period_end"], value=float(r["value"]),
                          period_start=r["period_start"], source_accession=r["source_accession"],
                          filing_date=r["filing_date"]) for r in rows]
    ladder = pl.build_ladder(facts, "x", period_type)
    if period_type == pl.QUARTERLY:
        ladder = pl.derive_q4(ladder, pl.build_ladder(facts, "x", pl.ANNUAL))
    return ladder.points[-LAST_N:]


def _new(rows, months):
    flows = [ia.FlowFact(fact_id=r["id"], period_start=r["period_start"], period_end=r["period_end"],
                         value=float(r["value"]), filing_date=r["filing_date"],
                         source_accession=r["source_accession"]) for r in rows]
    return ia.consecutive_windows(flows, months=months, last_n=LAST_N)


@pytest.mark.parametrize("period_type,months", [(pl.QUARTERLY, 3), (pl.ANNUAL, 12)])
async def test_every_ladder_point_is_in_the_series(period_type, months):
    grouped = await _corpus()
    old_points = matched = 0
    extras: Counter = Counter()
    problems: list[str] = []

    for (ticker, metric), rows in sorted(grouped.items()):
        old = _old(rows, period_type)
        new = _new(rows, months)
        derived = [w for w in new if isinstance(w.window, ia.Derived)]
        by_end = {w.end: w for w in derived}

        for p in old:
            old_points += 1
            hit = next((w for e, w in by_end.items() if abs((e - p.period_end).days) <= END_TOLERANCE.days), None)
            if hit is None:
                problems.append(f"{ticker} {metric} {p.period_end}: ladder has it, series does not")
                continue
            scale = max(abs(p.value), 1.0)
            if abs(hit.window.value - p.value) / scale > REL_TOLERANCE:
                problems.append(f"{ticker} {metric} {p.period_end}: ladder {p.value:,.0f} vs "
                                f"series {hit.window.value:,.0f} via [{hit.window.formula}]")
                continue
            matched += 1

        old_ends = {p.period_end for p in old}
        for w in derived:
            if not any(abs((w.end - e).days) <= END_TOLERANCE.days for e in old_ends):
                # What kind of window did the engine find that the ladder had not?
                extras[(ticker, metric, len(w.window.terms))] += 1

    assert old_points > 0
    assert not problems, (f"{len(problems)} of {old_points} ladder points are missing or differ:\n  "
                          + "\n  ".join(problems[:15]))
    n_extra = sum(extras.values())
    print(f"\n[{period_type}] {matched}/{old_points} ladder points reproduced; "
          f"{n_extra} extra windows the ladder never had, across {len(extras)} (issuer, metric, terms) shapes")
    for (t, m, terms), n in sorted(extras.items(), key=lambda kv: -kv[1])[:12]:
        print(f"    {t:6s} {m:34s} {terms}-term  ×{n}")


async def test_a_series_never_relabels_a_short_window_as_a_long_one():
    """DP2. The old ladder's Q4 was FY minus three quarters and could not exist
    when a quarter was missing — it was absent. The engine reports a window it
    cannot derive as unreachable IN PLACE, so the points around it keep their
    true windows rather than closing ranks."""
    grouped = await _corpus()
    seen_gap = False
    for (ticker, metric), rows in grouped.items():
        for w in _new(rows, 3):
            assert (w.end - w.start).days >= 60, f"{ticker} {metric}: a 'quarter' of {(w.end-w.start).days} days"
            assert (w.end - w.start).days <= 120, f"{ticker} {metric}: a 'quarter' of {(w.end-w.start).days} days"
            if isinstance(w.window, ia.Unreachable):
                seen_gap = True
    print(f"\ngaps reported in place: {seen_gap}")
