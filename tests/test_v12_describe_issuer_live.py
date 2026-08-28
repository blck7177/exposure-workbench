"""What `describe_issuer` now says about the data (V12-K0/K1, live).

The locating tool used to hand the model a name, a period count and a date, so a
model choosing between `cash_and_equivalents` and `cash_and_restricted_cash` was
choosing between two strings. Everything asserted here already existed — in the
containment edges, the registry's named alternatives, concept_mapping's comments
and the filed periods themselves — and none of it reached the model.
"""

from __future__ import annotations

import json
import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.agents.meta_agent import TOOL_RESULT_LIMIT
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.tools.definitions import _describe_issuer
from exposure_workbench.utils.json import dumps_capped

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)
ISSUERS = ("NVDA", "AAPL", "MSFT", "GOOGL", "JPM", "LLY", "XOM", "AMZN")


async def _describe(*tickers: str) -> dict[str, dict]:
    engine = create_async_engine(URL)
    try:
        mk = async_sessionmaker(engine, expire_on_commit=False)
        async with mk() as db:
            return {t: await _describe_issuer(db, t) for t in tickers}
    finally:
        await engine.dispose()


def _row(payload: dict, metric: str) -> dict | None:
    return next((r for r in payload["available_metrics"] if r["metric"] == metric), None)


async def test_the_fiscal_calendar_is_derived_from_the_annual_facts():
    """Not from the fiscal_year column: one NVDA period is stored under both
    2026 and 2027, so a calendar built on that column would be wrong for exactly
    the issuer whose calendar matters."""
    got = await _describe(*ISSUERS)
    ends = {t: p["period_semantics"]["fiscal_year_ends"] for t, p in got.items()}
    assert ends == {"AAPL": "Sep 27", "MSFT": "Jun 30", "NVDA": "Jan 25",
                    "GOOGL": "Dec 31", "JPM": "Dec 31", "LLY": "Dec 31",
                    "XOM": "Dec 31", "AMZN": "Dec 31"}, ends

    aligned = {t: p["period_semantics"]["fiscal_quarters_align_with_calendar"]
               for t, p in got.items()}
    assert aligned["NVDA"] is False, "a late-January year end is not a calendar quarter"
    assert all(v for t, v in aligned.items() if t != "NVDA"), aligned
    # And only the issuer it is true of is told about it.
    assert "note" in got["NVDA"]["period_semantics"]
    assert "note" not in got["AAPL"]["period_semantics"]


async def test_a_cumulative_line_says_so_and_a_discrete_one_stays_quiet():
    """Whether a metric is filed cumulatively belongs to the METRIC: NVDA files
    four window lengths of operating cash flow off one year-start and one of
    revenue. Aggregated to the issuer it is 23-36% for everybody and says
    nothing."""
    nvda = (await _describe("NVDA"))["NVDA"]
    assert _row(nvda, "operating_cash_flow")["windows_filed"] == \
        ["3-month", "6-month", "9-month", "12-month"]
    # One length is what `kind: flow` already said.
    assert "windows_filed" not in _row(nvda, "revenue")
    # A balance has no windows at all, and does not spend a field saying so.
    assert "kind" not in _row(nvda, "long_term_debt_total")
    assert _row(nvda, "operating_cash_flow")["kind"] == "flow"


async def test_a_component_carries_the_rule_not_the_graph():
    """"long_term_debt_total contains current_portion" plus "a sum may not nest"
    equals "these two may not be added" — and a rule the model has to compose
    out of two facts is the class agents are measured missing."""
    nvda = (await _describe("NVDA"))["NVDA"]
    total = _row(nvda, "long_term_debt_total")
    assert set(total["do_not_add_to"]) == {"current_portion_long_term_debt",
                                           "long_term_debt_noncurrent"}
    assert total["for_a_total_call"] == "evaluate_formula(name='total_debt')"
    assert "contains" not in total and "contained_by" not in total, \
        "the graph is three ways of saying one rule"
    assert "component" in total["note"]


async def test_a_retired_tag_names_its_successor_before_the_first_call():
    """V11's absence statement names it after a refusal. This names it before
    the model has chosen — which is when the choice is made."""
    nvda = (await _describe("NVDA"))["NVDA"]
    assert _row(nvda, "revenue")["superseded_by"] == ["total_revenues"]
    assert "superseded_by" not in _row(nvda, "total_revenues")


async def test_a_note_only_ships_where_its_relationship_is_live():
    """Every note warns about a relationship. Shipped where the other side is
    absent it is a caveat about a choice this issuer does not offer, and
    irrelevant domain knowledge is measured to lower answer quality."""
    got = await _describe("NVDA", "JPM")
    # JPM tags only the cash-flow total, so it has no cash_and_equivalents and
    # the warning about confusing the two has nothing to warn about.
    assert _row(got["JPM"], "cash_and_equivalents") is None
    jpm_cash = _row(got["JPM"], "cash_and_restricted_cash")
    assert jpm_cash is not None and "note" not in jpm_cash
    nvda_cash = _row(got["NVDA"], "cash_and_restricted_cash")
    assert "note" in nvda_cash and "cash_and_equivalents" in nvda_cash["do_not_combine_with"]


async def test_the_catalogue_does_not_repeat_registry_prose():
    """`authority` is the same object sixteen times over in one catalogue, and
    `note` is the same bytes for every issuer. Both travel where they are
    load-bearing — beside the number, in evaluate_formula."""
    nvda = (await _describe("NVDA"))["NVDA"]
    for line in nvda["formulas"]:
        assert "authority" not in line and "note" not in line, line["name"]
        assert line["family"], line["name"]


async def test_every_issuer_fits_the_context_cap():
    """A payload that overflows on every call is a design fault, not an accident
    to be reported: the knowledge is only knowledge if it arrives."""
    got = await _describe(*ISSUERS)
    for ticker, payload in got.items():
        capped = json.loads(dumps_capped(payload, TOOL_RESULT_LIMIT))
        size = len(json.dumps(payload, default=str))
        assert "truncated" not in capped, f"{ticker}: {size} bytes over {TOOL_RESULT_LIMIT}"
