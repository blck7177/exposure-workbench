"""V9-P — the panel is a batch of calls the agent could have made (live).

Run with:  pytest -m live -k v9_panel

The first draft of this was a method tool with its own arithmetic inside it: a
TTM, a fallback, eight debt recipes. That made it a privileged path — the panel
could produce numbers the agent had no way to reproduce, and a number nobody can
reproduce is a number nobody can check.

So the panel evaluates the registry over the same primitives and adds nothing.
The load-bearing test is the one asserting each of its lines can be reproduced,
value for value, by a single evaluate_formula call. If that ever fails, the
panel has grown logic of its own.
"""

from __future__ import annotations

import json
import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import formula_service as svc

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_the_panel_has_no_arithmetic_the_agent_cannot_repeat():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            panel = await svc.build_panel(db, "AAPL")
            await db.commit()
            for name, line in panel["lines"].items():
                if line.get("error"):
                    continue
                alone = await svc.evaluate_formula(db, "AAPL", name)
                await db.commit()
                assert alone["value"] == pytest.approx(line["value"], rel=1e-12), (
                    f"{name}: the panel computed {line['value']} and a single call "
                    f"computed {alone['value']} — the panel has logic of its own")
    finally:
        await engine.dispose()


async def test_total_debt_is_composed_not_double_counted():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await svc.evaluate_formula(db, "AAPL", "total_debt")
            await db.commit()
    finally:
        await engine.dispose()
    assert got["value"] == pytest.approx(84.697e9, rel=1e-9)
    assert got["value"] != pytest.approx(91.010e9, rel=1e-3)


async def test_ebit_is_never_about_a_period_it_does_not_name():
    """The property that makes an old number safe.

    `us-gaap:InterestExpense` stops in 2024 for seven of the eight issuers held.
    Five moved to InterestExpenseNonoperating, which is its own metric and
    reaches EBIT as a NAMED alternative — the substitution is in the definition,
    never only in the code. AAPL moved to nothing: after 2023-09-30 it tags no
    interest expense at all, reporting other income and expense as one line.

    So the window is anchored on the BINDING input, and AAPL's EBIT is a real
    FY2023 figure that says it is FY2023. That is the whole difference from what
    the acceptance battery caught: before window alignment, AAPL's EBIT was 2026
    net income plus 2023 interest expense — a number belonging to no period,
    with nothing on the page to reveal it.
    """
    engine, mk = await _mk()
    try:
        async with mk() as db:
            for tk in ("MSFT", "GOOGL", "NVDA", "AMZN", "LLY", "AAPL"):
                got = await svc.evaluate_formula(db, tk, "ebit")
                await db.commit()
                assert not got.get("error"), f"{tk}: {got}"
                assert "net income" in got["definition"]
                start, end = got["basis"].split()[-1].split("..")
                assert start < end, f"{tk}: basis does not state a window ({got['basis']})"
                if got.get("substituted_inputs"):
                    assert "used for" in got["definition"], (
                        f"{tk}: an input was substituted without saying so")

            aapl = await svc.evaluate_formula(db, "AAPL", "ebit")
            await db.commit()
            assert aapl["basis"].endswith("2022-09-25..2023-09-30"), (
                f"AAPL's EBIT should be the last window its interest expense reaches, "
                f"stated as such: {aapl['basis']}")
    finally:
        await engine.dispose()


async def test_an_unavailable_input_names_itself_and_keeps_the_definition():
    """MSFT reports no D&A, so EBITDA is unavailable — and the reader is told
    which input was missing, not handed a hole."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await svc.evaluate_formula(db, "MSFT", "ebitda")
    finally:
        await engine.dispose()
    assert got["error"] == "input_unavailable"
    assert got["missing"] == "depreciation_amortization"
    assert "value" not in got
    assert got["definition"]


async def test_a_bank_is_refused_before_any_number_is_produced():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            panel = await svc.build_panel(db, "JPM")
            one = await svc.evaluate_formula(db, "JPM", "ebit_interest_coverage")
    finally:
        await engine.dispose()
    assert panel["error"] == "not_applicable" and "lines" not in panel
    assert one["error"] == "not_applicable"


async def test_every_line_carries_its_definition_and_its_source():
    """The panel carries what varies per issuer; the source travels with the formula.

    V11-T moved `note` and `source_url` off the panel lines: identical bytes for
    every issuer on every call, 2.0kB of an 8.2kB payload, and the overflow cost
    the model four whole lines silently. The guarantee is unchanged, so this
    checks it where it now lives — a source url for every line the panel names,
    from evaluate_formula.
    """
    engine, mk = await _mk()
    try:
        async with mk() as db:
            panel = await svc.build_panel(db, "AAPL")
            sources = {name: await svc.evaluate_formula(db, "AAPL", name)
                       for name in panel["lines"]}
            await db.commit()
    finally:
        await engine.dispose()
    assert panel["judgement"].startswith("none")
    assert "evaluate_formula" in panel["per_formula_sources"]
    for name, line in panel["lines"].items():
        assert line.get("definition"), f"{name} has no definition"
        assert "note" not in line and "source_url" not in line, f"{name} still ships registry prose"
        assert sources[name]["source_url"].startswith("http"), f"{name} has no source"
        if not line.get("error"):
            assert line["basis"], f"{name} states no period basis"
            assert line["calc_id"].startswith(("calc_", "fact_"))


async def test_the_panel_fits_the_context_cap_for_every_issuer():
    """No issuer's panel may need truncating.

    The cap is real and dropping entries is honest, but a payload that overflows
    on every call is a design fault, not an accident to be reported: NVDA's panel
    was 8235 bytes against a 6000-byte cap and lost net_debt every time.
    """
    from exposure_workbench.agents.meta_agent import TOOL_RESULT_LIMIT
    from exposure_workbench.utils.json import dumps_capped

    engine, mk = await _mk()
    try:
        async with mk() as db:
            panels = {t: await svc.build_panel(db, t)
                      for t in ("NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "LLY", "XOM")}
            await db.commit()
    finally:
        await engine.dispose()
    for ticker, panel in panels.items():
        capped = dumps_capped(panel, TOOL_RESULT_LIMIT)
        assert "truncated" not in json.loads(capped), (
            f"{ticker}'s panel needs truncating at {TOOL_RESULT_LIMIT}: "
            f"{len(json.dumps(panel, default=str))} bytes")
