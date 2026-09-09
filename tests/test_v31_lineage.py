"""V31: supersession between metric lines is derived from the filings.

The defect: `get_flow('NVDA','revenue', months=12)` returned 26.9bn through
2022-01-30 on the live site while NVDA's top line was `total_revenues` at 303.0bn
through 2026-07-26. The desk knew the two were one line — the overlap year agrees
to the dollar — but the knowledge sat in `Formula.alternatives`, readable only by
`evaluate_formula`, so the catalogue, the direct read and the series grid each
had their own wrong answer.

What is pinned here: the rule is evidence, not an alias table; there is one home
for it; and no read anchored on "the latest" can quietly return a window that
ends before the issuer's own latest period.
"""
from __future__ import annotations

import os
from datetime import date

import pytest

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import concept_mapping as cm
from exposure_workbench.services import lineage_service as ln

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_gold")
OWNER = "user_3IDBMeAxLTbecvGorzwV7FCeroR"


def _p(*rows):
    """period map: (period_end, period_start, value) -> what _periods returns."""
    return {(date.fromisoformat(e), date.fromisoformat(s)): v for e, s, v in rows}


# ── the rule is the evidence ──────────────────────────────────────────────────

def test_agreement_is_measured_over_the_periods_both_tags_were_filed_for():
    """NVDA filed 26,914,000,000 under each tag for its 2022 year. That is what
    makes them one line — not that the names look alike."""
    a = _p(("2022-01-30", "2021-02-01", 26_914e6), ("2021-01-31", "2020-01-27", 16_675e6))
    b = dict(a) | _p(("2026-01-25", "2025-01-27", 215_938e6))
    n, worst, agrees = ln._judge(a, b)
    assert (n, agrees) == (2, True) and worst == 0.0


def test_a_pair_that_disagrees_over_the_overlap_is_two_quantities():
    """XOM files both top lines; over nine shared periods they differ by 4.96%.
    An alias table would have merged them and produced a number that is wrong in
    a way no downstream check could see."""
    a = _p(("2023-06-30", "2023-04-01", 82_910e6))
    b = _p(("2023-06-30", "2023-04-01", 87_022e6))
    n, worst, agrees = ln._judge(a, b)
    assert n == 1 and worst > ln.LINEAGE_TOL and not agrees


def test_no_shared_period_is_not_agreement():
    """Two lines that never overlapped may still be two quantities. Silence is
    not evidence, so the desk does not follow it."""
    a = _p(("2022-01-30", "2021-02-01", 26_914e6))
    b = _p(("2026-01-25", "2025-01-27", 215_938e6))
    assert ln._judge(a, b) == (0, None, False)


def test_the_tolerance_is_a_declaration_not_a_slope():
    a = _p(("2024-12-31", "2024-01-01", 1_000.0))
    assert ln._judge(a, _p(("2024-12-31", "2024-01-01", 1_000.0 * (1 + ln.LINEAGE_TOL / 2))))[2]
    assert not ln._judge(a, _p(("2024-12-31", "2024-01-01", 1_000.0 * (1 + ln.LINEAGE_TOL * 2))))[2]


def test_a_lineage_says_in_words_why_the_desk_does_or_does_not_follow_it():
    agree = ln.Lineage("revenue", "total_revenues", date(2022, 1, 30), date(2026, 7, 26),
                       date(2023, 1, 29), 2, 0.0, True)
    assert "one line" in agree.statement and "2023-01-29" in agree.statement
    apart = ln.Lineage("revenue", "total_revenues", date(2023, 6, 30), date(2026, 6, 30),
                       date(2023, 9, 30), 9, 0.0496, False)
    assert "two quantities" in apart.statement and "5.0%" in apart.statement
    never = ln.Lineage("a", "b", date(2022, 1, 1), date(2026, 1, 1), None, 0, None, False)
    assert "no period was reported under both" in never.statement


# ── one home ──────────────────────────────────────────────────────────────────

def test_the_candidate_pairs_live_in_one_place_and_name_supported_metrics():
    """Before V31 the same knowledge was in Formula.alternatives, where only
    evaluate_formula could read it. A second home is how two consumers come to
    disagree about what one name means."""
    assert cm.SUPERSESSION_CANDIDATES
    for frm, to in cm.SUPERSESSION_CANDIDATES:
        assert frm in cm.SUPPORTED_METRICS and to in cm.SUPPORTED_METRICS, (frm, to)
        assert frm != to


def test_a_candidate_pair_is_a_hypothesis_about_tags_not_a_claim_about_an_issuer():
    """`revenue`/`total_revenues` are one line for NVDA and two for XOM. The pair
    list cannot say which; only the filings can, which is why nothing reads it
    except the derivation."""
    import subprocess
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "src"
    hits = subprocess.run(["grep", "-rln", "--include=*.py", "SUPERSESSION_CANDIDATES", str(root)],
                          capture_output=True, text=True).stdout.split()
    readers = {pathlib.Path(h).name for h in hits} - {"concept_mapping.py"}
    assert readers <= {"lineage_service.py", "absence_service.py"}, readers


# ── live: the desk's own filings ──────────────────────────────────────────────

@pytest.mark.live
@pytest.mark.asyncio
async def test_the_derivation_finds_the_lines_that_moved_and_refuses_the_one_that_did_not():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.db.models import Company
    engine = create_async_engine(URL)
    current_user_ctx.set(OWNER)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            got = {}
            for cid, tk in (await db.execute(select(Company.id, Company.ticker))).all():
                for lin in await ln.derive(db, cid):
                    got[(tk, lin.from_metric)] = lin
            await db.rollback()
    finally:
        await engine.dispose()
    nvda = got[("NVDA", "revenue")]
    assert nvda.to_metric == "total_revenues" and nvda.agrees and nvda.overlap_max_rel_diff == 0.0
    xom = got[("XOM", "revenue")]
    assert xom.to_metric == "total_revenues" and not xom.agrees and xom.overlap_periods >= 1
    assert ("AAPL", "revenue") not in got, "AAPL's revenue line never stopped"


@pytest.mark.live
@pytest.mark.asyncio
async def test_no_latest_anchored_read_ends_before_the_issuer_says_it_does():
    """The guard the defect asks for. For every prepared issuer and every flow
    metric it reports, a read anchored on "the latest" either reaches the issuer's
    own latest period, or says which line it followed, or refuses."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.db.models import Company
    from exposure_workbench.services import calc_service as cs
    from exposure_workbench.services import fundamentals_service as fs
    engine = create_async_engine(URL)
    current_user_ctx.set(OWNER)
    bad = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            for (tk,) in (await db.execute(select(Company.ticker).where(Company.is_investigable))).all():
                rows = (await cs.list_available_metrics(db, tk))["metrics"]
                latest = max((r["latest_period_end"] for r in rows if r.get("latest_period_end")), default=None)
                for r in rows:
                    if (r.get("kind") or "instant") != "flow":
                        continue
                    out = await fs.get_flow(db, tk, r["metric"], months=12, invoked_by="guard")
                    if out.get("error") or out.get("via"):
                        continue
                    end = (out.get("period") or {}).get("end")
                    if end and latest and str(end) < str(latest) and str(r["latest_period_end"]) >= str(latest):
                        bad.append((tk, r["metric"], end, latest))
            await db.rollback()
    finally:
        await engine.dispose()
    assert bad == [], bad


@pytest.mark.live
@pytest.mark.asyncio
async def test_every_name_on_the_map_carries_a_true_coverage_statement():
    """`names` plus one issuer date said, by omission, that every name reached
    that date. A name now either reaches it or appears in `lines`."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select
    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.db.models import Company
    from exposure_workbench.services import catalogue_service as cat
    engine = create_async_engine(URL)
    current_user_ctx.set(OWNER)
    bad = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            for (tk,) in (await db.execute(select(Company.ticker).where(Company.is_investigable))).all():
                f = (await cat.describe(db, tk)).get("fundamentals") or {}
                detail = {m["metric"]: m for m in ((await cat.cs.list_available_metrics(db, tk))["metrics"])}
                for name in f.get("names") or []:
                    lp = str(detail[name].get("latest_period_end") or "")
                    if lp and lp < str(f["latest_period_end"]) and name not in (f.get("lines") or {}):
                        bad.append((tk, name, lp))
            await db.rollback()
    finally:
        await engine.dispose()
    assert bad == [], bad
