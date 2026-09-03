"""V8-A/B/D against the real database (live).

The offline files prove the shapes and the absences. These prove the three things
only real rows can: that the reads return what the workflow wrote, that the
identities close on a book nobody constructed for them, and that the figures the
new tools produce are ones the citation gate accepts.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.services import drawdown_service as dds
from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.services import reconcile_service as rs
from exposure_workbench.services import run_reads_service as rr

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _latest_full_run(db) -> str | None:
    """A run that has the V8-P children — older runs predate the writers."""
    return (await db.execute(text(
        "SELECT m.run_id FROM exposure_metrics m "
        "WHERE m.observations IS NOT NULL "
        "  AND EXISTS (SELECT 1 FROM limit_checks c WHERE c.run_id = m.run_id) "
        "  AND EXISTS (SELECT 1 FROM stress_results s WHERE s.run_id = m.run_id) "
        "ORDER BY m.id DESC LIMIT 1"))).scalar_one_or_none()


async def test_the_run_reads_return_what_the_workflow_wrote():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            run_id = await _latest_full_run(db)
            if run_id is None:
                pytest.skip("no run carrying the V8-P children in this database")

            a = await rr.get_attribution(db, run_id)
            assert a["factors"] and a["positions"]
            assert a["metadata"] is not None and a["metadata"]["observations"] > 0
            # Every beta carries the determinacy of its own estimate.
            assert all("quotable_individually" in f for f in a["factors"])
            if a["metadata"]["collinear"]:
                assert all(f["quotable_individually"] is False for f in a["factors"])
                assert a["factor_note"] is not None

            state = await rr.get_risk_state(db, run_id)
            assert state["not_a_forecast"] is True
            checks = state["limit_checks"]
            assert checks["evaluated"] == checks["fired"] + checks["clear"]
            # An unevaluated scenario holds no loss. The CHECK constraint says so
            # in the database; this says the read does not paper over it.
            for s in state["scenarios"]:
                if s["status"] == "unevaluated":
                    assert s["loss_pct"] is None and s["reason"]

            alerts = await rr.list_run_alerts(db, run_id)
            assert alerts["checks_run"] == checks["evaluated"]
            assert len(alerts["alerts"]) == checks["fired"]
    finally:
        await engine.dispose()


async def test_an_alerts_sentence_names_the_denominator_of_its_utilisation():
    """On the live rows, where limit_value is a WARNING level and utilisation is
    measured against the breach level above it."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            run_id = await _latest_full_run(db)
            if run_id is None:
                pytest.skip("no run carrying the V8-P children")
            out = await rr.list_run_alerts(db, run_id)
            if not out["alerts"]:
                pytest.skip("this run raised no alerts")
            for a in out["alerts"]:
                if a["current_value"] is None or a["limit_value"] is None:
                    continue
                assert "never a level in itself" in a["reads_as"]
                if a["severity"] == "warning" and a["utilization"] is not None:
                    assert "BREACH" in a["reads_as"]
    finally:
        await engine.dispose()


async def test_the_row_counts_are_the_row_counts():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            run_id = await _latest_full_run(db)
            if run_id is None:
                pytest.skip("no run carrying the V8-P children")
            values, _ = await nv.resolve_cited_values(db, [run_id])
            counts = {v.label: v.value for v in values if v.label.startswith("count.")}

            # V20: the table counts PUBLISHED checks — rows of a withheld
            # check (analytics/withheld.py) written before the check stopped
            # running are not on it, so the row count is taken the same way.
            from exposure_workbench.analytics import withheld as wh
            fired = (await db.execute(text(
                "SELECT count(*) FILTER (WHERE fired), count(*) FROM limit_checks "
                "WHERE run_id = :r AND split_part(limit_type, ':', 1) <> ALL(:withheld)"),
                {"r": run_id, "withheld": list(wh.WITHHELD_CHECKS)})).one()
            assert counts["count.limit_checks"] == fired[1]
            assert counts["count.limit_checks.fired=true"] == fired[0]
            assert counts["count.limit_checks.fired=false"] == fired[1] - fired[0]
            # The complement of a boolean split is emitted even at zero: "none
            # fired" is a claim about this run and it is checkable.
            assert "count.limit_checks.fired=false" in counts
    finally:
        await engine.dispose()


async def test_both_identities_close_on_a_real_book():
    """The measurement that corrected the plan. Identity B is written against
    attribution_portfolio_return; against daily_return it misses by the holdings'
    dividend history, which on this book is forty times the tolerance."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            run_id = await _latest_full_run(db)
            if run_id is None:
                pytest.skip("no run carrying the V8-P children")
            out = await rs.reconcile_move(db, run_id)
            await db.commit()
            assert out["reconciles"] is True
            a, b = out["identity_positions"], out["identity_factors"]
            assert a["holds"] and a["gap"] <= a["tolerance"]
            assert b["holds"] and b["gap"] <= b["tolerance"]

            # The plan's version, on the same numbers.
            wrong = abs((out["return_conventions"]["daily_return"]
                         - b["sum_of_factor_contributions"]) - b["recorded_alpha_plus_residual"])
            if out["return_conventions"]["difference"] != 0.0:
                assert wrong > b["tolerance"], (
                    "on a book with dividend history the two conventions must be "
                    "distinguishable, or this correction has nothing to correct")

            # The gate takes the share the tool just produced.
            values, quoted = await nv.resolve_cited_values(db, [out["calc_id"]])
            written = f"factors account for {out['factor_share']:.1%} of the move"
            assert nv.verify(nv.extract_numbers(written), values, quoted) == []
    finally:
        await engine.dispose()


async def test_the_deepest_episode_is_consistent_with_the_max_drawdown_on_file():
    """Two parts of one system must not disagree about the same book — but they
    are looking through different windows, so the honest assertion is directional
    rather than an equality.

    The workflow's series is 1200 calendar days (V6-W raised it from 90) and the
    longest span here is 1096, so this search can only find an equal or shallower
    trough than the run did. Asserting equality would make the test fail for a
    true reason: a deeper episode lying between 1096 and 1200 days back.

    Two facts this pinned down while being written, both worth keeping. Runs of
    the SAME book on the SAME date disagree about max_drawdown — 0.0624 on the
    pre-V6 runs against 0.1766 after, entirely the window change — which is why
    the run is selected by carrying V8-P metadata rather than by being newest.
    And on this deployment the two windows do currently coincide: the deepest
    episode of the last three years is the one the 1200-day run reports."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            run_id = await _latest_full_run(db)
            if run_id is None:
                pytest.skip("no run carrying the V8-P children")
            row = (await db.execute(text(
                "SELECT r.portfolio_id, m.max_drawdown FROM exposure_metrics m "
                "JOIN exposure_runs r ON r.id = m.run_id WHERE m.run_id = :r"),
                {"r": run_id})).one()
            pid, stated = row[0], row[1]

            out = await dds.get_drawdown_episodes(db, pid, "3y")
            await db.commit()
            if out.get("error"):
                pytest.skip(out["error"])
            assert out["deepest"] is not None
            assert out["deepest"]["depth"] > 0.0

            if stated is not None:
                assert out["deepest"]["depth"] <= float(stated) + 1e-8, (
                    "a shorter window cannot find a deeper trough than the run did")

            # And the depths can be quoted.
            values, quoted = await nv.resolve_cited_values(db, [out["calc_id"]])
            written = f"the worst drawdown was {out['deepest']['depth']:.2%} deep"
            assert nv.verify(nv.extract_numbers(written), values, quoted) == []
    finally:
        await engine.dispose()


async def test_the_benchmark_comes_from_the_store_that_tracks_it():
    """SPY's history in the holdings store starts wherever an upload backfilled
    it; the factor sync keeps the full series because the regression needs it.
    Asking the wrong store returns a null the reader cannot distinguish from a
    broken lookup."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            pid = (await db.execute(text(
                "SELECT portfolio_id FROM exposure_runs WHERE status = 'completed' "
                "ORDER BY as_of_date DESC LIMIT 1"))).scalar_one_or_none()
            if pid is None:
                pytest.skip("no completed run")
            eps = await dds.get_drawdown_episodes(db, pid, "3y")
            await db.commit()
            if eps.get("error") or not eps["episodes"]:
                pytest.skip("no episode to explain")
            deepest = eps["episodes"][0]
            out = await dds.explain_episode(db, pid, deepest["peak_date"], deepest["trough_date"])
            await db.commit()
            bench = out["benchmark"]
            # Either a number, or a reason. Never a bare null.
            assert (bench["window_return"] is not None) != (bench["unavailable_reason"] is not None)
            assert out["fixed_window_caveat"]
    finally:
        await engine.dispose()
