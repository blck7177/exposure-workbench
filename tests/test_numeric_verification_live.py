"""V3-A1 numeric verification against the real database (live).

Run with:  pytest -m live -k numeric_verification

The offline file proves the matching rule. This one proves the three things that
can only be proved against real rows: that a citable prefix actually resolves to
the values its rows hold, that the derived-Q4 series is verifiable now that it is
ledgered, and that the whole thing does not refuse the answers the system has
already produced.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import AgentMessage
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import numeric_verification as nv

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _session():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_a_derived_q4_is_verifiable_only_because_the_series_is_ledgered():
    """The structural false rejection A1c closes, on the exact figure that
    produced it. MSFT's FY2025 Q4 revenue is annual minus three filed quarters —
    $76.441B, which is what one live brief states and which equals no row in
    financial_facts. Citing the four facts it came from is honest and, before
    the series had a ledger id of its own, unverifiable."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            out = await fs.get_flow(db, "MSFT", "revenue", months=3, last_n=8, invoked_by="test")
            await db.commit()
            derived = [p for p in out["points"] if len(p.get("fact_ids") or []) > 1]
            assert derived, "expected at least one derived Q4 point in a quarterly series"

            point = derived[-1]
            written = f"revenue of ${point['value'] / 1e9:.3f}B"
            numbers = nv.extract_numbers(written)

            values, quoted = await nv.resolve_cited_values(db, [out["calc_id"]])
            assert nv.verify(numbers, values, quoted) == [], "the ledgered series must carry it"

            only_facts, q2 = await nv.resolve_cited_values(db, point["fact_ids"])
            assert nv.verify(numbers, only_facts, q2) != [], (
                "citing only the input facts must still fail — each holds a different number, "
                "which is the whole reason the series needed an id"
            )
    finally:
        await engine.dispose()


async def test_a_run_resolves_through_its_children_not_its_own_columns():
    """exposure_runs has no numeric column at all. If run_ resolved against the
    run row, every portfolio-level figure would come back unverified and the
    refusal would name the model rather than this table."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            run_id = (await db.execute(text(
                "SELECT run_id FROM exposure_metrics ORDER BY id LIMIT 1"))).scalar_one_or_none()
            if run_id is None:
                pytest.skip("no completed exposure run in this database")

            values, _ = await nv.resolve_cited_values(db, [run_id])
            assert values, "a completed run must resolve to the numbers on its children"
            labels = {v.label.split(".")[0] for v in values}
            assert "exposure_metrics" in labels
            # Two classes of value, and they are told apart by label. A child
            # column is a MEASUREMENT and is money or a ratio; a COUNT is V8-P4's
            # row count and may only come from the count.* labels. Written as an
            # equivalence rather than a subset so that a COUNT arriving from
            # anywhere else — a column mistyped, a JSONB leaf walked by accident —
            # still fails here.
            for v in values:
                if v.unit_class == nv.COUNT:
                    assert v.label.startswith("count."), f"{v.label} is not a row count"
                else:
                    assert v.unit_class in (nv.MONEY, nv.RATIO), v.label
            assert any(v.label.startswith("count.") for v in values), (
                "a completed run has children, so it has counts of them")
    finally:
        await engine.dispose()


async def test_a_negative_number_can_be_cited_and_its_flip_cannot():
    """V3-R1, on the rows that make it a blocker rather than a curiosity.

    Three real negatives, one per shape the desk writes: a portfolio P&L in
    money, a daily return in percent, a factor contribution in percent. 117 of
    the 127 factor_attributions rows in this database are negative, and before
    the sign reached the value every one of them was uncitable — the claim was
    compared against its own positive and matched nothing the run holds. The
    mirror assertion is the reason the first half is not enough: written
    POSITIVE, the same figure must be refused against the same citation, which
    is the sign flip the review reproduced."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            row = (await db.execute(text(
                "SELECT run_id, daily_pnl, daily_return FROM exposure_metrics "
                "WHERE daily_pnl < 0 AND daily_return < 0 ORDER BY daily_pnl LIMIT 1"
            ))).first()
            if row is None:
                pytest.skip("no losing day in this database")
            run_id, pnl, ret = row
            factor = (await db.execute(text(
                "SELECT factor_name, contribution FROM factor_attributions "
                "WHERE run_id = :r AND contribution < 0 ORDER BY contribution LIMIT 1"
            ), {"r": run_id})).first()

            values, quoted = await nv.resolve_cited_values(db, [run_id])
            # "-$165,456.00", the form the desk writes: the sign leads, the
            # currency mark follows it. ("$-165,456.00" is not a form this
            # extractor claims to read — see the module's known limits.)
            claims = [f"the book lost -${abs(float(pnl)):,.2f}",
                      f"a daily return of {float(ret) * 100:.2f}%"]
            if factor is not None:
                claims.append(f"{factor[0]} contributed {float(factor[1]) * 100:.2f}%")

            for claim in claims:
                signed = nv.extract_numbers(claim)
                assert signed and signed[0].value < 0, f"{claim!r} did not extract as negative"
                assert nv.verify(signed, values, quoted) == [], (
                    f"{claim!r} is what the run holds and must verify")
                flipped = nv.extract_numbers(claim.replace("-", ""))
                assert nv.verify(flipped, values, quoted) != [], (
                    f"{claim!r} written positive is a sign flip and must be refused")
    finally:
        await engine.dispose()


async def test_a_share_count_can_be_cited_to_the_holding_it_came_from():
    """V3-R4, and it is C3's own acceptance query: "how many shares of AAPL do I
    hold". The quantity is real and sits on a positions row; before this that row
    had no evidence identity, so the honest answer had nothing to cite and the
    gate refused it by construction.

    A position offers its QUANTITY and nothing else. Its price and market_value
    columns are a stale snapshot the exposure run supersedes — V2-E5 removed the
    third valuation convention from this codebase deliberately, and a position
    that could hand back a price would put it straight back, with a citable id
    attached this time."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            row = (await db.execute(text(
                "SELECT id, ticker, quantity FROM positions ORDER BY as_of_date DESC, id LIMIT 1"
            ))).first()
            if row is None:
                pytest.skip("no positions in this database")
            pos_id, ticker, qty = row
            assert pos_id.startswith("pos_"), f"{pos_id!r} is not a citable id"

            values, quoted = await nv.resolve_cited_values(db, [pos_id])
            assert [v.unit_class for v in values] == [nv.COUNT], (
                "a position offers its quantity, as a count, and nothing else")

            claim = f"You hold {float(qty):,.0f} shares of {ticker}"
            assert nv.verify(nv.extract_numbers(claim), values, quoted) == []
            wrong = f"You hold {float(qty) + 1:,.0f} shares of {ticker}"
            assert nv.verify(nv.extract_numbers(wrong), values, quoted) != []
    finally:
        await engine.dispose()


async def test_every_holding_in_the_database_has_a_citable_id():
    """The demo book's ten holdings were minted as bare UUIDs by the seed script
    — the third time in this project an id has been minted without the prefix
    that makes it evidence (alert<hex> was the first). A position the agent can
    read and cannot cite is worse than one it cannot read: it is a number in
    front of the model with no way to support it."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            bad = (await db.execute(text(
                "SELECT count(*) FROM positions WHERE id NOT LIKE 'pos\\_%'"))).scalar_one()
            assert bad == 0, f"{bad} positions rows cannot be cited"
    finally:
        await engine.dispose()


async def test_the_answers_already_in_the_database_still_pass():
    """The acceptance bar, measured rather than asserted: verification must not
    start refusing the system's own past work. Every number-bearing assistant
    message that carries citations is re-checked against them."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            rows = (await db.execute(
                select(AgentMessage).where(AgentMessage.role == "assistant")
            )).scalars().all()

            checked = failed = 0
            offenders: list[str] = []
            for m in rows:
                numbers = nv.extract_numbers(m.content or "")
                if not numbers or not m.citations:
                    continue
                values, quoted = await nv.resolve_cited_values(db, list(m.citations))
                problems = nv.verify(numbers, values, quoted)
                checked += len(numbers)
                failed += len(problems)
                if problems:
                    offenders.append(f"{m.id}: {[p['number'] for p in problems]}")

            assert checked >= 10, "expected a meaningful corpus of cited numbers"
            # The plan's bar is 2 in 20. Measured at 0 in 20 when this was written.
            assert failed * 10 <= checked, f"{failed}/{checked} refused: {offenders}"
    finally:
        await engine.dispose()
