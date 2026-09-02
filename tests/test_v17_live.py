"""V17 against the real desk: the universe, the reading, the ordering (live).

Three claims that only the deployed data can settle.

  ADMISSION decides, from the listed universe, whether a ticker is an issuer
  this desk can prepare. The offline suite holds its branches against a mocked
  universe; what it cannot check is that the real table answers the way the
  branches assume — that SPY is marked an ETF, that a symbol nobody lists is
  absent, that the CIK the universe stores is the padded form the readiness step
  compares against. Every case here is READ-ONLY: it exercises the decision, not
  the write, because a test that admitted an issuer would leave a company row
  and a queue of ingestion behind it every time it ran.

  THE READING is a claim about stored rows: after v17_multiple_unit.sql no
  coverage, turnover or leverage ratio on this desk is typed as a share, and no
  margin or return is typed as a multiple.

  THE ORDERING is computed over figures this desk actually holds, so its
  refusals are exercised against real types rather than constructed ones.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import company_service as cs
from exposure_workbench.services import formula_service as fsvc
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.utils import cik as cik_util

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)

MULTIPLES = {n for n, f in fm.FORMULAS.items() if f.unit_class == "multiple"}


@pytest.fixture
async def db():
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


# ── the universe decides, read-only ──────────────────────────────────────────

async def test_an_issuer_already_on_the_desk_is_returned_not_rewritten(db):
    company = await cs.admit(db, "AAPL")
    assert company.ticker == "AAPL" and company.is_investigable


async def test_the_seeded_etfs_still_refuse(db):
    for ticker in ("TLT", "HYG"):
        with pytest.raises(cs.NotInvestigable):
            await cs.admit(db, ticker)


async def test_a_listed_etf_that_was_never_seeded_refuses_as_an_etf(db):
    """SPY has a CIK — it files — and is still not an issuer with statements to
    read. The ETF flag has to be consulted before the CIK, or the desk would
    admit every fund in the universe and fail them one by one in readiness."""
    with pytest.raises(cs.NotInvestigable) as e:
        await cs.admit(db, "SPY")
    assert "10-K" in e.value.reason


async def test_a_symbol_nobody_lists_is_not_found(db):
    with pytest.raises(cs.CompanyNotFound):
        await cs.admit(db, "ZZZZZZ")


async def test_the_universe_is_large_enough_to_be_the_universe(db):
    """A truncated or unrefreshed table turns every real company into
    `unknown_ticker`, which reads to a user as "this desk does not know Tesla".
    The floor is the one security_master_service.refresh enforces."""
    n = (await db.execute(text(
        "select count(*) from security_master where status = 'active'"))).scalar()
    assert n > 10_000, f"only {n} active securities; the universe needs a refresh"


async def test_thousands_of_issuers_are_admissible_not_eight(db):
    """The point of the batch, as a number. Before V17 this desk held eight."""
    n = (await db.execute(text(
        "select count(*) from security_master "
        "where status = 'active' and not is_etf and cik is not null"))).scalar()
    assert n > 5_000, f"only {n} admissible issuers"


async def test_the_universe_stores_the_padded_cik_the_desk_normalises(db):
    """The bug that would have failed every admission: this table pads to ten
    digits and edgartools does not. If this assertion ever flips, the padding
    moved and utils/cik.py is the only place that has to care."""
    stored = (await db.execute(text(
        "select cik from security_master where ticker = 'AAPL'"))).scalar()
    assert stored == "0000320193"
    assert cik_util.canonical(stored) == "320193"
    seeded = (await db.execute(text(
        "select cik from companies where ticker = 'AAPL'"))).scalar()
    assert cik_util.same(stored, seeded), "readiness step 1 would call this a mismatch"


# ── the reading, as the stored rows now hold it ──────────────────────────────

async def test_no_coverage_or_turnover_ratio_is_still_typed_as_a_share(db):
    rows = (await db.execute(text("""
        select params->'result_type'->>'quantity', unit_class, count(*)
        from calc_ledger
        where params->'result_type'->>'quantity' = any(:names)
        group by 1, 2"""), {"names": sorted(MULTIPLES)})).fetchall()
    wrong = [(q, u, n) for q, u, n in rows if u != "MULTIPLE"]
    assert wrong == [], f"rows still read as percents: {wrong}"


async def test_no_margin_or_return_became_a_multiple(db):
    """The other direction of the same migration: a net margin printed as
    "0.25×" would be the same defect facing the other way."""
    rows = (await db.execute(text("""
        select params->'result_type'->>'quantity', unit_class, count(*)
        from calc_ledger
        where params->'result_type'->>'quantity' = any(:names)
        group by 1, 2"""), {"names": ["net_margin", "gross_margin", "operating_margin",
                                      "roe", "roa", "roic", "accruals_ratio"]})).fetchall()
    wrong = [(q, u, n) for q, u, n in rows if u != "RATIO"]
    assert wrong == [], f"rows now read as multiples: {wrong}"


async def test_the_column_and_the_blob_agree_on_every_corrected_row(db):
    """Two rules about one fact is what the unit column exists to end. The
    reader reads the column; the calculator reads the blob when the row becomes
    an operand."""
    n = (await db.execute(text("""
        select count(*) from calc_ledger
        where unit_class = 'MULTIPLE'
          and params->'result_type'->>'unit_class' is distinct from 'multiple'"""))).scalar()
    assert n == 0, f"{n} rows whose column and blob disagree"


async def test_a_freshly_evaluated_leverage_ratio_is_born_a_multiple(db):
    """Not the migration — the code path. The registry declares, units.refine
    checks, and the row records what the reader will see."""
    out = await fsvc.evaluate_formula(db, "AAPL", "current_ratio", invoked_by="test_v17")
    assert not out.get("error"), out
    assert out["unit_class"] == "multiple"
    assert dc.display(out["value"], "MULTIPLE").endswith("×")
    row = (await db.execute(text(
        "select unit_class from calc_ledger where id = :i"), {"i": out["calc_id"]})).scalar()
    assert row == "MULTIPLE"


async def test_a_beta_is_a_multiple_and_its_r2_is_not(db):
    rows = (await db.execute(text("""
        select operation, unit_class, count(*) from calc_ledger
        where operation like 'price.regress.%' group by 1, 2"""))).fetchall()
    by_op = {op: unit for op, unit, _ in rows}
    assert by_op.get("price.regress.beta") == "MULTIPLE"
    for op in ("price.regress.alpha", "price.regress.r2"):
        if op in by_op:
            assert by_op[op] == "RATIO", f"{op} is a share, not a multiple"


# ── the ordering, over figures this desk holds ───────────────────────────────

async def _margins(db, *tickers) -> dict[str, str]:
    out = {}
    for t in tickers:
        r = await fsvc.evaluate_formula(db, t, "net_margin", invoked_by="test_v17")
        assert not r.get("error"), (t, r)
        out[t] = r["calc_id"]
    return out


async def test_one_measure_across_issuers_orders_and_names_every_place(db):
    ids = await _margins(db, "AAPL", "MSFT", "XOM")
    out = await tc.rank(db, list(ids.values()), direction="highest", invoked_by="test_v17")
    assert not out.get("error"), out
    assert {e["label"] for e in out["ordering"]} == {"AAPL", "MSFT", "XOM"}
    assert [e["rank"] for e in out["ordering"]] == [1, 2, 3]
    values = [e["value"] for e in out["ordering"]]
    assert values == sorted(values, reverse=True), "the order is not the order"
    assert out["leader"] == out["ordering"][0]["label"]


async def test_the_places_reach_the_table_under_names_an_answer_can_slot(db):
    from exposure_workbench.services import quantities as qn

    ids = await _margins(db, "AAPL", "MSFT")
    out = await tc.rank(db, list(ids.values()), direction="highest", invoked_by="test_v17")
    resolved = await qn.of_ref(db, out["calc_id"])
    names = {q.label: q for q in resolved.quantities}
    leader = out["leader"]
    assert names[f"net_margin.rank.{leader}"].value == 1.0
    assert names[f"net_margin.{leader}"].unit_class == qn.RATIO
    assert names["net_margin.ranked"].value == 2.0


async def test_two_different_measures_are_refused_over_real_rows(db):
    margin = await fsvc.evaluate_formula(db, "AAPL", "net_margin", invoked_by="test_v17")
    ratio = await fsvc.evaluate_formula(db, "MSFT", "current_ratio", invoked_by="test_v17")
    out = await tc.rank(db, [margin["calc_id"], ratio["calc_id"]],
                        direction="highest", invoked_by="test_v17")
    # Two guards catch this and either is correct: the units differ (a share
    # against a multiple, since V17 types them apart) and so do the measures.
    assert out["error"] in ("incomparable_units", "incomparable_quantities"), out


async def test_an_ordering_is_not_an_operand_for_the_calculator(db):
    ids = await _margins(db, "AAPL", "MSFT")
    ranked = await tc.rank(db, list(ids.values()), direction="highest", invoked_by="test_v17")
    out = await tc.calculate(db, "add", ranked["calc_id"], list(ids.values())[0],
                             invoked_by="test_v17")
    assert out["error"] == "not_a_quantity"
