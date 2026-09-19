"""V1 step 1 (docs/IMPLEMENTATION_PLAN_V1.md §2.2, §3 步骤 1): a fact carries what
it MEANS, and one line renders it.

The services computed the words — a net beta's `loses`, a check's `warning`, a
collinear fit, which line stood in for which — and the tool boundary dropped
them. These tests pin the four things the step adds: the closed vocabulary, the
line as a pure function of the stored row, the standing policy absences, and
the two checks that can now contradict a sentence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exposure_workbench.analytics import formulas as FM
from exposure_workbench.analytics import registry as R
from exposure_workbench.analytics import resources as RS
from exposure_workbench.services import answer_check as AC
from exposure_workbench.services import fact_adapters as FA
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger, rows_for

ROOT = Path(__file__).resolve().parents[1]


# ── the rows a reader is shown: the plan's six, and a series ────────────────────

# A BETA IS A MULTIPLE (step 2): the unit is read off the desk's own declaration, not typed here. This
# fixture said "RATIO" by hand and its gold line pinned "-86.0%" — the very writing step 1's first
# finding set out to end — for as long as nobody looked, because a fixture that types its own unit
# cannot notice the desk changed its mind.
NET_BETA = F.Fact(id="f_3a9c", kind=F.SCALAR, measure="portfolio.integration.net_beta.equity_down",
                  subject="run_20260910", unit=RS.CALC_RESULTS["portfolio.integration"]["net_beta"], value=-0.86,
                  as_of="2026-09-10",
                  params={"method": "book.analysis"},
                  means={"direction": "loses", "flags": ["collinear_legs_not_quotable"]}, sources=("calc_1",))
# as program_service births it: resources.identity_of splits the check off the name (V38/S4)
ROOM = F.Fact(id="f_r00m", kind=F.SCALAR, measure="portfolio.integration.room_to_warning",
              subject="issuer_concentration:LLY", unit="RATIO", value=-0.01, as_of="2026-09-10",
              params={"method": "book.analysis", "place": 20, "of": 20}, means={"status": "warning"})
COVERAGE = F.Fact(id="f_7d21", kind=F.SCALAR, measure="ebit_interest_coverage", subject="XOM", unit="MULTIPLE",
                  value=18.4, as_of="2025-06-30", window={"start": "2024-07-01", "end": "2025-06-30"},
                  params={"method": "ebit_interest_coverage",
                          "substituted": {"interest_expense": "interest_expense_nonoperating"}})
# the plan's fourth row (§3 步骤 1: 净 beta、余地、利息覆盖、DSO、缺席、政策缺席): what a turnover in days is
# BUILT ON rides on the row. Unit and basis are the registry entry's, as fact_adapters.compute reads them.
DSO = F.Fact(id="f_d5d0", kind=F.SCALAR, measure="days_sales_outstanding", subject="AAPL",
             unit=FM.FORMULAS["days_sales_outstanding"].unit_class.upper(), value=30.0, as_of="2023-09-30",
             window={"start": "2023-07-02", "end": "2023-09-30"}, params={"method": "days_sales_outstanding"},
             means={"basis": list(R.METHODS["days_sales_outstanding"].basis)})
MARGINS = F.Fact(id="f_5b10", kind=F.SERIES, measure="gross_margin", subject="MSFT", unit="RATIO",
                 points=(("2024-06-30", 0.69), ("2025-06-30", 0.688)), as_of="2025-06-30",
                 params={"method": "gross_margin"})
REFUSED = F.Fact(id="f_9e02", kind=F.ABSENCE, measure="net_debt_to_ebitda", subject="JPM",
                 text="net debt / EBITDA is refused for a financial issuer: interest is a bank's operating cost",
                 as_of="n/a", params={"error": "not_for_financials"},
                 means={"reason": "meaningless", "way_out": "ROE, ROA and the accruals ratio do apply to banks"})

GOLD = {
    "f_3a9c": "[f_3a9c] net beta to equity down, run_20260910, as of 2026-09-10: -0.86× — the book loses if this "
              "risk happens; collinear fit: the net is quotable, no single leg is — method book.analysis",
    "f_r00m": "[f_r00m] room to the warning tier, issuer_concentration:LLY, as of 2026-09-10: -1.00% — in warning; "
              "20th highest of 20 — method book.analysis",
    "f_7d21": "[f_7d21] EBIT / interest coverage, XOM, 2024-07-01 to 2025-06-30: 18.40× — built on interest expense "
              "nonoperating in place of interest expense — method ebit_interest_coverage",
    # NOT YET THE DESIGN'S ROW ("30.0 天 — 按 91 天换算，期末余额"): the algebra counts days as a COUNT, so the
    # value carries no unit word, and the day count is only in the window. Open item in the plan (§5).
    "f_d5d0": "[f_d5d0] days sales outstanding, AAPL, 2023-07-02 to 2023-09-30: 30 — built on ending balances — "
              "method days_sales_outstanding",
    "f_5b10": "[f_5b10] gross margin, MSFT, annual, 2024-06-30 to 2025-06-30, 2 points: 2024-06-30 69.0%; "
              "2025-06-30 68.8% — method gross_margin",
    "f_9e02": "[f_9e02] absent: net debt / EBITDA, JPM: — — net debt / EBITDA is refused for a financial issuer: "
              "interest is a bank's operating cost; ROE, ROA and the accruals ratio do apply to banks — other",
    "f_policy_no_forecast": "[f_policy_no_forecast] absent: policy no forecast: — — The desk does not forecast. Asked "
                            "for next year's figure, it says so and gives what the issuer's own filings say would "
                            "move the figure either way. — boundary",
}
ROWS = {f.id: f for f in (NET_BETA, ROOM, COVERAGE, DSO, MARGINS, REFUSED)}


@pytest.mark.parametrize("fid", sorted(GOLD))
def test_a_row_reads_as_its_gold_line(fid):
    rec = ROWS[fid] if fid in ROWS else next(p for p in R.POLICY_ABSENCES if p["id"] == fid)
    assert F.line(rec) == GOLD[fid]


def test_the_line_is_a_pure_function_of_the_stored_row():
    """Analyst, ledger, lead and reader see one row: the line from the Fact, from
    its record, from the record after a round trip and from the table row agree."""
    for f in ROWS.values():
        rec = F.for_record(f)
        row = rows_for([f], session_id="s", step_id=None, message_id=None)[0]
        stored = {c: getattr(row, c) for c in ("id", "kind", "measure", "subject", "unit", "value", "points", "text",
                                                "as_of", "window", "params", "standalone", "sources", "group", "means")}
        assert F.line(f) == F.line(rec) == F.line(F.for_record(F.from_record(rec))) == F.line(stored)


def test_the_row_has_eight_fields_and_each_is_a_string_a_reader_reads():
    row = F.model_row(NET_BETA)
    assert tuple(row) == F.ROW_FIELDS == ("id", "kind", "what", "of", "when", "value", "means", "from")
    assert row["kind"] == "reading" and all(isinstance(v, str) for v in row.values())


# ── the vocabulary is closed ─────────────────────────────────────────────────

@pytest.mark.parametrize("means", [
    {"direction": "short"}, {"status": "fine"}, {"flags": ["looks_risky"]}, {"basis": ["guess"]},
    {"reason": "dunno"}, {"note": "free text is not a slot"}, {"flags": "collinear_legs_not_quotable"},
])
def test_a_word_outside_the_registry_is_refused_at_construction(means):
    with pytest.raises(ValueError):
        F.Fact(id="f_bad", kind=F.SCALAR, measure="m", value=1.0, means=means)


def test_a_record_from_before_v1_loads_with_no_means():
    rec = F.for_record(COVERAGE)
    rec.pop("means")
    assert F.from_record(rec).means == {}
    assert "—" in F.line(rec)               # and still renders


def test_the_limits_engines_ok_is_the_registrys_clear():
    assert R.words_beside({"status": "ok"}) == {"status": "clear"}
    assert R.words_beside({"status": "breach"}) == {"status": "breach"}
    # an ordering's `direction` is another vocabulary and is not taken
    assert R.words_beside({"direction": "highest"}) == {}
    assert R.words_beside({"direction": "loses", "quotable_individually": False}) == {
        "direction": "loses", "flags": ["collinear_legs_not_quotable"]}


# ── the words travel from the producer to the fact ───────────────────────────

def test_a_checks_status_and_an_exposures_direction_reach_the_fact():
    payload = {"run_id": "run_1", "as_of": "2026-09-10",
               "net_exposures": {"equity_down": {"measured": True, "direction": "loses", "net_beta": -0.86,
                                                 "gross_beta": 1.66, "quotable_individually": False}},
               "headroom": [{"check": "issuer_concentration", "status": "warning", "current": 0.16,
                             "room_to_warning": -0.01, "room_to_breach": 0.04, "cite": "run_1"}]}
    facts, _note = FA.harvest(payload, FA.Ctx("compute", subject="run_1", as_of="2026-09-10",
                                              leaf_unit="RATIO", sources=("run_1",)))
    by = {f.measure.split(".")[-1]: f for f in facts}
    assert by["net_beta"].means == {"direction": "loses", "flags": ["collinear_legs_not_quotable"]}
    assert "direction" not in by["net_beta"].params            # a meaning, not a parameter
    assert by["room_to_warning"].means == {"status": "warning"}


# ── what the desk does not say stands on every ledger ────────────────────────

def test_the_three_policies_are_on_every_ledger_and_not_among_what_was_shown():
    led = Ledger.of_facts([COVERAGE])
    assert R.POLICY_IDS == {"f_policy_no_forecast", "f_policy_no_threshold", "f_policy_no_estimate"}
    assert all(led.holds(i) and led.kind(i) == F.ABSENCE for i in R.POLICY_IDS)
    assert set(led.shown) == {"f_7d21"}
    assert led.means("f_policy_no_forecast") == {"reason": "policy"}
    for p in R.POLICY_ABSENCES:                          # each is a Fact the dataclass accepts
        assert F.from_record(dict(p)).means == {"reason": "policy"}


# ── a sentence can now contradict the desk's own word ────────────────────────

def _problems(text: str, facts) -> list[str]:
    return [p["reason"] for p in AC.check(text, Ledger.of_facts(facts), "").problems]


def test_a_book_that_loses_to_equities_falling_is_not_net_short():
    wrong = "The book is net short equities, with a net beta of -0.86× [f_3a9c] to an equity fall."
    assert "sense_conflict" in _problems(wrong, [NET_BETA])
    right = "The book loses if equities fall: its net beta to that risk is -0.86× [f_3a9c]."
    assert "sense_conflict" not in _problems(right, [NET_BETA])
    denied = "The book is not short equities: its net beta to an equity fall is -0.86× [f_3a9c]."
    assert "sense_conflict" not in _problems(denied, [NET_BETA])


def test_a_check_in_warning_is_not_clear():
    wrong = "LLY remains clear of its warning tier, with room of -1.00% [f_r00m]."
    assert "status_conflict" in _problems(wrong, [ROOM])
    right = "LLY's issuer concentration is already in warning: its room to the tier is -1.00% [f_r00m]."
    assert "status_conflict" not in _problems(right, [ROOM])


# ── the column exists wherever a fact is stored ──────────────────────────────

def test_the_means_column_is_in_the_schema_the_migration_and_the_model():
    from exposure_workbench.db.models import FactRecord
    assert "means" in FactRecord.__table__.columns
    assert "means       JSONB NOT NULL DEFAULT '{}'" in (ROOT / "infra/init.sql").read_text()
    mig = (ROOT / "infra/migrations/v39_fact_means.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS means JSONB NOT NULL DEFAULT '{}'" in mig


def test_a_refusal_row_says_why_and_the_way_out():
    fact = FA.refusal_fact("metric", {"name": "roce", "subject": "MSFT"},
                           {"error": "unknown_method", "detail": "roce: not a measure this desk has",
                            "nearest": ["roe", "roic"]})
    assert fact.kind == F.ABSENCE and fact.means == {"reason": "no_such_name", "way_out": "nearest: roe, roic"}
    assert "nearest: roe, roic — boundary" in F.line(fact)
    assert R.reason_of("something_new") == "cannot" and R.reason_of(None) == "cannot"
