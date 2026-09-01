"""Issuers change tags, and this desk finds out on purpose (V11-D, gap G8).

Four times now a metric has gone quiet because the filer moved to a different
us-gaap concept, and four times it was found the same way: someone asked a
question, got a wrong or empty answer, and traced it back. AAPL's interest
expense, MSFT's, NVDA's revenue, and LLY's capex — which is still unmapped, and
was found only because a battery of real questions ran into it.

A drifting tag is not an error. AAPL genuinely stopped disclosing interest
expense, and LLY genuinely stopped filing a long-term-debt total while
continuing to file both its halves. So this is a LEAD LIST, not a failure list:
every stale (issuer, metric) pair is enumerated below with what it turned out to
be, and the test fails when the corpus grows one that nobody has read yet.

The threshold is two reporting periods plus slack. A quarterly filer that skips
one period has not drifted; one that has been silent for three quarters has.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)

STALE_AFTER_DAYS = 200

_DRIFT_SQL = text(f"""
WITH issuer AS (
    SELECT company_id, max(period_end) AS latest
    FROM financial_facts WHERE normalized_metric IS NOT NULL GROUP BY company_id),
per_metric AS (
    SELECT company_id, normalized_metric, max(period_end) AS latest
    FROM financial_facts WHERE normalized_metric IS NOT NULL
    GROUP BY company_id, normalized_metric)
SELECT c.ticker, m.normalized_metric
FROM per_metric m
JOIN issuer i USING (company_id)
JOIN companies c ON c.id = m.company_id
WHERE m.latest < i.latest - INTERVAL '{STALE_AFTER_DAYS} days'
ORDER BY 1, 2
""")

# Read on 2026-08-27, one at a time, against the raw concepts still arriving for
# that issuer after the metric fell silent.
#
#   covered_by_alternative  the filer moved and the destination is mapped; the
#                           registry records the substitution, so a formula that
#                           needs it still resolves
#   covered_by_cover        the filer stopped publishing a TOTAL and still files
#                           its components; the containment cover composes it
#   issuer_stopped          nothing of that shape arrives any more — a real
#                           change in what the company discloses
#   unmapped_candidate      the data is still arriving under a concept this
#                           mapping does not know. THE ONE THAT NEEDS WORK.
#   unresolved              read, and not explained by any of the above
CLASSIFIED: dict[tuple[str, str], str] = {
    ("AMZN", "interest_expense"): "covered_by_alternative",   # -> interest_expense_nonoperating
    ("GOOGL", "interest_expense"): "covered_by_alternative",
    ("LLY", "interest_expense"): "covered_by_alternative",
    ("MSFT", "interest_expense"): "covered_by_alternative",
    ("NVDA", "interest_expense"): "covered_by_alternative",
    ("GOOGL", "revenue"): "covered_by_alternative",           # -> total_revenues
    ("NVDA", "revenue"): "covered_by_alternative",
    ("XOM", "revenue"): "covered_by_alternative",

    # Still files DebtCurrent and LongTermDebtNoncurrent, just not the total.
    ("LLY", "long_term_debt_total"): "covered_by_cover",
    ("LLY", "operating_lease_liability_total"): "covered_by_cover",

    # Every interest concept AAPL files ends 2023-09-30; it folded the line into
    # other income/(expense), net. The consequence is real and correct: AAPL's
    # EBIT can only be computed through FY2023.
    ("AAPL", "interest_expense"): "issuer_stopped",
    ("AAPL", "interest_paid"): "issuer_stopped",
    ("LLY", "net_income_including_noncontrolling"): "issuer_stopped",  # plain NetIncomeLoss continues
    ("MSFT", "commercial_paper"): "issuer_stopped",
    ("NVDA", "commercial_paper"): "issuer_stopped",
    # Named by mapping v4 (2026-09-01), silent since then: AMZN's cash
    # repurchases (PaymentsForRepurchaseOfCommonStock) end 2024-12-31 — the
    # company stopped buying back, so the cash-flow line drops out. What still
    # arrives is the program's shell: StockRepurchasedDuringPeriodShares and
    # the remaining-authorization amount, both through 2026-03-31. A refusal
    # for AMZN buybacks after FY2024 is therefore the correct answer.
    ("AMZN", "buybacks"): "issuer_stopped",

    # us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment, 26 periods through
    # 2026-03-31, normalized_metric NULL. LLY's free cash flow is refused for
    # want of a capex the filings contain. Adding it to the capex tuple needs the
    # validation the containment edges got — whether the two tags ever co-occur,
    # and whether the "Other" line is the whole of capex for filers that use it —
    # so it is a lead here rather than a mapping change made on a hunch.
    ("LLY", "capex"): "unmapped_candidate",

    ("JPM", "interest_expense"): "unresolved",   # no successor of that shape arrives
    ("NVDA", "interest_paid"): "unresolved",     # not a formula input; low impact
}


async def _drift() -> set[tuple[str, str]]:
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return {(t, m) for t, m in (await db.execute(_DRIFT_SQL)).all()}
    finally:
        await engine.dispose()


async def test_no_metric_has_gone_quiet_without_being_read():
    """The ratchet. A new pair means an issuer moved and nobody has looked yet."""
    unread = sorted(await _drift() - set(CLASSIFIED))
    assert not unread, (
        f"{len(unread)} metric(s) stopped updating and are not in CLASSIFIED: {unread}. "
        f"For each, look at what raw concepts still arrive for that issuer after it "
        f"fell silent, then add it with what you found — do not delete the row."
    )


async def test_the_list_does_not_outlive_what_it_describes():
    """A pair that stopped drifting was fixed, and the note about it is now a lie."""
    stale_entries = sorted(set(CLASSIFIED) - await _drift())
    assert not stale_entries, (
        f"{stale_entries} no longer drift — remove them from CLASSIFIED"
    )


async def test_the_lead_that_needs_work_is_still_named():
    """Not a pass/fail on the mapping: a refusal to let the one actionable entry
    blend into seventeen explained ones."""
    leads = {k for k, v in CLASSIFIED.items() if v == "unmapped_candidate"}
    assert ("LLY", "capex") in leads
    assert leads <= await _drift(), "a lead that stopped drifting was mapped; reclassify it"
