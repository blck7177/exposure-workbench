"""V25 — the new reads agree with the rows they read, and mint nothing (live).

The half of the V25 guarantee only a running system can show, on the same
grounds as tests/test_v13_issuer_panels_live.py: the offline guards hold the
handler bodies away from every recording entry point, and the version of the
reconcile read that minted a row per request for a week passed both of its
offline checks.

Two claims are checked here and cannot be checked anywhere else.

AGREEMENT. The book across updates and the run detail must state the same
figures for the same run, and the picker's latest window must be the last slot
of the ladder for the same metric. Two reads of one row are the way a page
comes to disagree with itself in the third decimal, which on a risk product is
where trust goes.

NO MINTING. Three reads of each endpoint must leave the ledger where it was.
The balance series is the interesting one: its first read of a newly filed
series performs the calculation, and every read after that reuses it — so the
count is taken AFTER a warm-up read, which is the honest shape of the claim.
"""

from __future__ import annotations

import os

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import CalcLedger, IssuerBrief, Company

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
API = os.getenv("SMOKE_API_URL", f"http://127.0.0.1:{os.getenv('API_HOST_PORT', '8103')}")
TICKER = os.getenv("SMOKE_TICKER", "MSFT")
BOOK = os.getenv("SMOKE_PORTFOLIO", "port_001")


async def _ledger_rows() -> int:
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine)() as db:
            return (await db.execute(select(func.count()).select_from(CalcLedger))).scalar_one()
    finally:
        await engine.dispose()


# ── a read does not mint ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    f"/api/portfolios/{BOOK}/run-series?span=all",
    f"/api/issuers/{TICKER}/measures",
    f"/api/issuers/{TICKER}/briefs",
    f"/api/issuers/{TICKER}/balance-series?metric=cash_and_equivalents",
])
async def test_reading_three_times_leaves_the_ledger_where_it_was(path):
    async with httpx.AsyncClient(timeout=60) as c:
        # The warm-up: a balance series never drawn before is a calculation this
        # desk has not performed, and performing it once is the point of the
        # endpoint. What must not happen is performing it again per page view.
        first = await c.get(f"{API}{path}")
        assert first.status_code == 200, first.text

        before = await _ledger_rows()
        for _ in range(3):
            r = await c.get(f"{API}{path}")
            assert r.status_code == 200
        after = await _ledger_rows()

    assert after == before, (
        f"three reads of {path} added {after - before} ledger row(s). A read that "
        "records is a page view counted as a calculation")


async def test_the_balance_series_hands_back_the_same_calculation_each_time():
    async with httpx.AsyncClient(timeout=60) as c:
        ids = []
        for _ in range(3):
            r = await c.get(f"{API}/api/issuers/{TICKER}/balance-series?metric=long_term_debt_total")
            assert r.status_code == 200, r.text
            ids.append(r.json()["calc_id"])
    assert len(set(ids)) == 1 and ids[0], (
        f"the same series resolved to {sorted(set(ids))} — a chart's points must click "
        "through to one row, and a previous answer may have cited it")


# ── the series and the run agree ─────────────────────────────────────────────

async def test_the_last_update_states_what_its_run_states():
    async with httpx.AsyncClient(timeout=60) as c:
        series = (await c.get(f"{API}/api/portfolios/{BOOK}/run-series?span=all")).json()
        assert series["updates"], "the demo book has completed updates"
        last = series["updates"][-1]
        run = (await c.get(f"{API}/api/exposure-runs/{last['run_id']}")).json()

    assert run["as_of_date"] == last["as_of"]
    assert run["metrics"]["portfolio_market_value"] == pytest.approx(
        last["metrics"]["market_value"], abs=1e-8)
    assert run["metrics"]["daily_return"] == pytest.approx(
        last["metrics"]["daily_return"], abs=1e-8)

    by_ticker = {i["ticker"]: i for i in run["issuer_exposures"]}
    for row in last["issuers"]:
        assert row["weight"] == pytest.approx(by_ticker[row["ticker"]]["weight"], abs=1e-8)
        assert row["contribution"] == pytest.approx(
            by_ticker[row["ticker"]]["contribution"], abs=1e-8), (
            "the contribution the series draws is the contribution the run stored")


async def test_a_day_with_several_runs_is_one_point_that_says_how_many():
    async with httpx.AsyncClient(timeout=60) as c:
        series = (await c.get(f"{API}/api/portfolios/{BOOK}/run-series?span=all")).json()
    dates = [u["as_of"] for u in series["updates"]]
    assert len(dates) == len(set(dates)), "one point per date"
    assert any(u["runs_that_day"] > 1 for u in series["updates"]), (
        "this guard is vacuous unless the demo book still has a day it re-ran")


async def test_no_withheld_check_appears_in_the_series():
    async with httpx.AsyncClient(timeout=60) as c:
        series = (await c.get(f"{API}/api/portfolios/{BOOK}/run-series?span=all")).json()
    keys = {c["key"] for u in series["updates"] for c in u["checks"]}
    assert keys, "the demo book's runs evaluated checks"
    leaked = {k for k in keys if k.split(":")[0] in ("var_95", "expected_shortfall_95", "stress_loss")}
    assert not leaked, f"withheld checks reached a reader through the series: {sorted(leaked)}"


async def test_an_unknown_span_is_refused_rather_than_defaulted():
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{API}/api/portfolios/{BOOK}/run-series?span=7y")
    assert r.status_code == 422 and r.json()["detail"]["error"] == "unknown_span"


# ── the picker and the ladder agree ──────────────────────────────────────────

async def test_the_pickers_latest_quarter_is_the_ladders_last_quarter():
    async with httpx.AsyncClient(timeout=60) as c:
        measures = (await c.get(f"{API}/api/issuers/{TICKER}/measures")).json()
        revenue = next(f for f in measures["flows"] if f["metric"] == "revenue")
        ladder = (await c.get(f"{API}/api/issuers/{TICKER}/windows?metric=revenue")).json()

    quarters = next(r for r in ladder["rows"] if r["months"] == 3)
    last_with_value = [s for s in quarters["slots"] if s["value"] is not None][-1]
    assert revenue["latest"]["value"] == pytest.approx(last_with_value["value"], rel=1e-12)
    assert revenue["latest"]["end"] == last_with_value["period_end"]


async def test_every_view_a_measure_offers_answers():
    """A control the picker renders must lead somewhere. A `yoy` view whose
    series is not in the manifest would be a button that opens an empty chart."""
    async with httpx.AsyncClient(timeout=60) as c:
        measures = (await c.get(f"{API}/api/issuers/{TICKER}/measures")).json()
        checked = 0
        for row in measures["flows"]:
            for name in ("yoy_metric", "share_metric"):
                metric = row.get(name)
                if not metric:
                    continue
                got = (await c.get(
                    f"{API}/api/issuers/{TICKER}/panel-series?metrics={metric}")).json()
                assert got["series"], f"{row['metric']}.{name} = {metric} charts nothing"
                checked += 1
        for row in measures["ratios"]:
            got = (await c.get(
                f"{API}/api/issuers/{TICKER}/panel-series?metrics={row['metric']}")).json()
            assert got["series"], f"ratio {row['metric']} charts nothing"
            checked += 1
    assert checked > 0, "this guard is vacuous unless the issuer has recipe rows"


async def test_a_measure_that_cannot_be_drawn_says_why():
    """NVDA holds two annual revenue facts and no quarterly boundary near them.
    The row must be listed as unavailable with a reason rather than as a row
    that draws nothing — and the twelve-month figure must never stand in for
    the quarter that is missing."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{API}/api/issuers/NVDA/measures")
        if r.status_code != 200:
            pytest.skip("NVDA is not prepared on this desk")
        measures = r.json()
    for row in measures["flows"]:
        if row["latest"] is None:
            assert row["latest_unreachable"], (
                f"{row['metric']} has no latest quarter and no sentence saying why")
            assert row["latest_12m"] is not None, (
                "a flow with neither window belongs in `unavailable`, not in the list")
    for row in measures["unavailable"]:
        assert row.get("detail"), f"{row['metric']} is unavailable for no stated reason"


# ── the snapshot answers about the book it was asked about ───────────────────

async def test_the_snapshot_reads_the_named_books_own_run():
    async with httpx.AsyncClient(timeout=60) as c:
        snap = (await c.get(f"{API}/api/issuers/{TICKER}/snapshot?portfolio={BOOK}")).json()
        exposure = snap["portfolio_exposure"]
        assert exposure and exposure["portfolio_id"] == BOOK
        run = (await c.get(f"{API}/api/exposure-runs/{exposure['run_id']}")).json()

    assert run["portfolio_id"] == BOOK, "the run must belong to the book that was named"
    row = next(i for i in run["issuer_exposures"] if i["ticker"] == TICKER)
    assert exposure["weight"] == pytest.approx(row["weight"], abs=1e-8)
    assert exposure["market_value"] == pytest.approx(row["market_value"], abs=1e-8)


async def test_without_a_book_the_snapshot_states_no_exposure():
    async with httpx.AsyncClient(timeout=60) as c:
        snap = (await c.get(f"{API}/api/issuers/{TICKER}/snapshot")).json()
    assert snap["portfolio_exposure"] is None, (
        "a hand-typed URL names no book, and a figure about somebody else's book "
        "is the thing this endpoint stopped serving")


# ── the brief history is what the database holds ─────────────────────────────

async def test_the_brief_history_lists_what_the_desk_wrote():
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine)() as db:
            company_id = (await db.execute(
                select(Company.id).where(Company.ticker == TICKER))).scalar_one()
            stored = (await db.execute(
                select(func.count()).select_from(IssuerBrief)
                .where(IssuerBrief.company_id == company_id))).scalar_one()
    finally:
        await engine.dispose()

    async with httpx.AsyncClient(timeout=60) as c:
        got = (await c.get(f"{API}/api/issuers/{TICKER}/briefs")).json()

    assert len(got["briefs"]) == stored
    if stored:
        assert got["briefs"][0]["is_current"] is True
        assert all(b["created_at"] for b in got["briefs"]), "every brief carries its date"
        dates = [b["created_at"] for b in got["briefs"]]
        assert dates == sorted(dates, reverse=True), "newest first"


# ── room to a tier, and the spans a client may ask for ───────────────────────

async def test_room_agrees_with_the_levels_beside_it():
    async with httpx.AsyncClient(timeout=60) as c:
        runs = (await c.get(f"{API}/api/exposure-runs?portfolio_id={BOOK}")).json()
        run_id = next(r["id"] for r in runs if r["status"] == "completed")
        book = (await c.get(f"{API}/api/exposure-runs/{run_id}/limit-book")).json()

    measured = [c for c in book["checks"] if c["current"] is not None and c["warning"] is not None]
    assert measured, "this guard is vacuous unless the run recorded levels"
    for check in measured:
        assert check["room_warning"] == pytest.approx(
            check["warning"] - check["current"], abs=1e-8)
        if check["status"] == "warning":
            assert check["room_warning"] < 0, (
                f"{check['key']} fired a warning and reports room left under it")


async def test_the_span_lists_are_served():
    async with httpx.AsyncClient(timeout=60) as c:
        history = (await c.get(f"{API}/api/portfolios/{BOOK}/history?span=1y")).json()
        price = (await c.get(f"{API}/api/issuers/{TICKER}/price-index")).json()
        series = (await c.get(f"{API}/api/portfolios/{BOOK}/run-series")).json()
    assert history["spans"] == ["1y", "3y", "5y"]
    assert price["spans"] == ["1y", "3y", "5y"]
    assert series["spans"] == ["1y", "3y", "all"]
