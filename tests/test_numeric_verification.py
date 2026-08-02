"""V3-A1 numeric verification — extraction and exemptions (offline).

Group A pins the written forms the live corpus actually contains; group B pins
the exemption set. Four of these are regressions against bugs the first draft
had, each found by running the extractor over the real agent_messages and
issuer_briefs text rather than over invented examples — which is why they are
written as the exact sentences that broke it.
"""

from __future__ import annotations

import pytest

from exposure_workbench.tools.meta_tools import _respond
from exposure_workbench.services.numeric_verification import (
    COUNT,
    MONEY,
    MULTIPLE,
    PERCENT,
    ExtractedNumber,
    extract_numbers,
    raw_forms,
)


def _one(text: str) -> ExtractedNumber:
    found = extract_numbers(text)
    assert len(found) == 1, f"expected exactly one number in {text!r}, got {raw_forms(found)}"
    return found[0]


# ── group A: the written forms ────────────────────────────────────────────────

@pytest.mark.parametrize("text,value,unit_class", [
    ("revenue was $81.615B", 81_615_000_000.0, MONEY),
    ("revenue was $111.184 billion", 111_184_000_000.0, MONEY),
    ("a new $100 billion program", 100_000_000_000.0, MONEY),
    ("total market value is $10,406,776", 10_406_776.0, MONEY),
    ("a dividend of $0.27 per share", 0.27, MONEY),
    ("gross margin of 74.93%", 0.7493, PERCENT),
    ("a 25% import tariff", 0.25, PERCENT),
    ("net income grew +85.2%", 0.852, PERCENT),
    ("a current ratio of 1.28x", 1.28, MULTIPLE),
    ("the series only returned 2 recent points", 2.0, COUNT),
])
def test_written_forms_are_read_as_written(text: str, value: float, unit_class: str):
    n = _one(text)
    assert n.unit_class == unit_class
    assert n.value == pytest.approx(value, rel=1e-12)


def test_a_scale_suffix_is_case_insensitive():
    """Regression, found on live text. The scale alternation was built from
    lowercase keys and matched case-sensitively, so "$81.615B" fell through to
    the plain-money pattern and was read as eighty-one dollars — a claim about
    eighty-one billion, verified against eighty-one, and nothing would have
    looked wrong."""
    assert _one("revenue was $81.615B").value == pytest.approx(81_615_000_000.0)
    assert _one("revenue was $81.615b").value == pytest.approx(81_615_000_000.0)


def test_a_surface_never_ends_on_a_thousands_separator():
    """Regression: "$10,406,776, and the largest..." pulled the sentence's comma
    into the surface, so the model was quoted back a number it had not written."""
    n = _one("total market value is $10,406,776, and the largest issuer weight follows")
    assert n.surface == "$10,406,776"
    assert n.key == "10406776"


def test_tolerance_is_half_an_ulp_of_what_was_written():
    """Not a relative tolerance. "$94.9B" tolerates half of its last written
    digit — 0.05B — so a true 94.93B rounds to it and a true 95.1B does not."""
    assert _one("about $94.9B").atol == pytest.approx(5e7)
    assert _one("about $94.93B").atol == pytest.approx(5e6)
    # A percent's tolerance is carried into the same canonical unit as its value.
    assert _one("a weight of 4.1%").atol == pytest.approx(0.0005)
    assert _one("a weight of 25%").atol == pytest.approx(0.005)


def test_every_number_in_a_real_multi_claim_sentence_is_found():
    """The live answer this comes from states three issuer weights. Two of them
    were silently dropped by the first draft (see the designator test below), and
    a number that is never extracted is a number that is never verified."""
    text = ("Technology is the biggest sector at 32.9% of market value, with AAPL 15.8%, "
            "MSFT 13.0%, and NVDA 4.1% inside that sleeve")
    assert raw_forms(extract_numbers(text)) == ["32.9%", "15.8%", "13.0%", "4.1%"]


def test_raw_forms_dedupes_by_span_not_by_value():
    """Two spans holding the same magnitude are two claims, and both must be
    reported; the same span reported twice is a bug in the caller's display."""
    forms = raw_forms(extract_numbers("it rose from $5.0B to $7.0B, then back to $5.0B"))
    assert forms == ["$5.0B", "$7.0B", "$5.0B"]


# ── group B: the exemption set ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "the quarter ended 2026-04-26",                       # ISO date
    "shipping is expected to start in 2027.",             # year ending a sentence
    "the 10-K filed for Q2",                              # form type + period label
    "see calc_50c612fc9f59 for the derivation",           # id token
    "You can follow it with run id rrun_0bef53cb5360.",   # non-citable id prefix
    "the run completed as run_seed_prev_01",              # a non-hex id tail
    "filed under 0000320193-24-000123",                   # SEC accession
    "the H200 China licensing path",                      # product designator
    "outperformed the S&P 500 this quarter",              # index designator
    "Microsoft 365 Commercial cloud grew",                # product designator
    "over the last 3 months",                             # duration
    "a 1-year relative return",                           # duration
    "as of March 28, 2026",                               # long date
    "1) first item\n2) second item",                      # list ordinals
])
def test_digits_that_are_not_claims_are_exempt(text: str):
    assert extract_numbers(text) == [], f"{text!r} yielded {raw_forms(extract_numbers(text))}"


def test_a_year_ending_a_sentence_is_still_a_year():
    """Regression: the year pattern refused any year followed by a '.', which is
    every year that ends a sentence. Two live brief blocks tripped it."""
    assert extract_numbers("a dividend increase beginning in Q3 2026.") == []


def test_a_designator_does_not_swallow_the_claim_beside_it():
    """Regression, and the most dangerous of the four. "AAPL 15.8%" looks like
    "Microsoft 365" to a pattern that only asks whether digits follow a capital
    word. Two of three real issuer weights in a live answer were exempted, which
    means the gate would have accepted any number the model put after a ticker."""
    assert raw_forms(extract_numbers("with AAPL 15.8% and MSFT 13.0%")) == ["15.8%", "13.0%"]
    assert extract_numbers("the H200 accelerator") == []


def test_an_id_is_exempt_whole_not_digit_by_digit():
    """A naive scan of calc_50c612fc9f59 yields 50, 612 and 59 — three numbers
    the model never claimed, in a reply that is otherwise number-free."""
    assert extract_numbers("evidence: calc_50c612fc9f59") == []
    # and the exemption must not extend past the token
    assert raw_forms(extract_numbers("calc_50c612fc9f59 gives 16.2%")) == ["16.2%"]


def test_a_number_free_reply_yields_nothing():
    assert extract_numbers("Sure — what would you like to know about the portfolio?") == []
    assert extract_numbers("") == []


# ── group C: the gate that consumes it (A0-1) ─────────────────────────────────
# db is None throughout: the empty-citations branch provably never touches it,
# and a test that needed a database to prove a pure refusal would be testing the
# database.

@pytest.mark.asyncio
async def test_the_gate_refuses_a_number_without_a_citation():
    out = await _respond(None, "NVDA's most recent quarterly revenue was $81.615B.", [])
    assert out["error"] == "citations_required"
    assert out["numbers_found"] == ["$81.615B"]
    assert "responded" not in out


@pytest.mark.asyncio
async def test_the_gate_lets_a_number_free_reply_through_uncited():
    out = await _respond(None, "Sure — which issuer would you like me to look at?", [])
    assert out["responded"] is True
    assert out["citations"] == []


@pytest.mark.asyncio
async def test_an_id_in_the_reply_is_not_a_number_the_gate_demands_evidence_for():
    """The live corpus contains exactly this reply, uncited and legitimate: it
    hands the user a run id to follow. Keying the id exemption to the six
    citable prefixes would have refused it, because rrun_ is not one of them."""
    out = await _respond(None, "Started it. You can follow it with run id rrun_0bef53cb5360.", [])
    assert out["responded"] is True


@pytest.mark.asyncio
async def test_every_refused_number_is_reported_so_the_model_can_fix_them():
    out = await _respond(None, "Technology is 32.9% of the book, with AAPL 15.8%.", None)
    assert out["error"] == "citations_required"
    assert out["numbers_found"] == ["32.9%", "15.8%"]


# ── group D: matching a number against the evidence (A1) ──────────────────────

from exposure_workbench.services.numeric_verification import (  # noqa: E402
    RATIO,
    EvidenceValue,
    quoted_keys,
    resolve_cited_values,
    verify,
)


def _val(v: float, unit: str = RATIO, label: str = "x") -> EvidenceValue:
    return EvidenceValue(value=v, unit_class=unit, label=label, source_id="calc_1")


def test_a_correctly_rounded_number_is_accepted():
    """0.04061908 written as "4.1%" is 0.94% off in relative terms and would be
    refused by rtol=0.005. It is the correct rounding, and half an ulp says so."""
    assert verify(extract_numbers("a weight of 4.1%"), [_val(0.04061908)]) == []


def test_a_corrupted_last_digit_is_refused():
    """The other half of the same rule: rtol on "$82.886B" opens a ±$414M window,
    so an $82.887B corruption slips through. Half an ulp of the written precision
    is ±$500k, and 82.887 does not round to 82.886."""
    numbers = extract_numbers("cash of $82.886B")
    assert verify(numbers, [_val(82_887_000_000.0, MONEY)]) != []
    assert verify(numbers, [_val(82_886_000_000.0, MONEY)]) == []


def test_truncating_instead_of_rounding_is_refused():
    """A live brief writes 32.2% for a true 32.2753% operating margin. Half an ulp
    of one decimal is 0.0005, and the gap is 0.00075 — so this is a refusal by
    design, not an accident: the rule is that the true value must ROUND to what
    was written."""
    assert verify(extract_numbers("a margin of 32.2%"), [_val(0.322753)]) != []
    assert verify(extract_numbers("a margin of 32.3%"), [_val(0.322753)]) == []


def test_a_percent_may_not_be_matched_against_an_unrelated_scale():
    """The reason unit classes exist, taken from a real risk_alerts row that
    carries current_value 0.158, limit_value 0.15 and utilization 0.792 at once.
    A scale-blind rule accepts "at 15.8% of its limit" when the answer is 79.2%;
    here 15.8% meets the 0.158 ratio and nothing else, and a claim ABOUT
    utilization has to cite the number that is the utilization."""
    alert = [_val(0.15840195, RATIO, "current_value"),
             _val(0.15, RATIO, "limit_value"),
             _val(0.79200974, RATIO, "utilization")]
    assert verify(extract_numbers("AAPL is at 15.8%"), alert) == []
    # and money never meets a ratio, whatever the digits look like
    assert verify(extract_numbers("AAPL is at $0.16"), alert) != []


def test_money_and_ratio_never_meet():
    assert verify(extract_numbers("revenue of $81.6B"), [_val(81.6, RATIO)]) != []
    assert verify(extract_numbers("a weight of 81.6%"), [_val(81_600_000_000.0, MONEY)]) != []


def test_a_bare_number_may_match_anything_because_it_claims_no_unit():
    assert verify(extract_numbers("the series returned 2 points"), [_val(2.0, COUNT)]) == []
    assert verify(extract_numbers("it was 81600000000"), [_val(81.6e9, MONEY)]) == []


def test_a_figure_quoted_verbatim_from_a_cited_passage_is_accepted():
    """The prose route. It is an existence check on the digits, not a magnitude
    check — a filing table's scale often lives in a header the chunk does not
    carry — and that limit is recorded rather than hidden."""
    passage = "Total net sales increased to 111,184 for the quarter"
    assert verify(extract_numbers("net sales of 111,184"), [], quoted_keys(passage)) == []
    assert verify(extract_numbers("net sales of 111,185"), [], quoted_keys(passage)) != []


def test_every_refusal_names_the_nearest_thing_the_evidence_held():
    """Without it the model can only guess again. With it, "you wrote $58.3B, the
    nearest value this citation holds is $61.157B (gross_profit)" points straight
    at the missing citation — which is the real live case this was measured on."""
    problems = verify(extract_numbers("net income of $58.3B"),
                      [_val(61_157_000_000.0, MONEY, "gross_profit@2026-04-26")])
    assert len(problems) == 1
    assert problems[0]["reason"] == "not_in_cited_evidence"
    assert problems[0]["nearest"]["label"] == "gross_profit@2026-04-26"


def test_no_evidence_at_all_reports_nearest_none_rather_than_crashing():
    problems = verify(extract_numbers("revenue of $81.6B"), [])
    assert problems[0]["nearest"] is None


def test_every_citable_prefix_has_a_value_source():
    """A prefix the gate accepts but the verifier cannot resolve would report the
    model's correct number as unverified, blaming it for a hole in this table.
    run_ and chunk_/src_ were both missing from the first design."""
    from exposure_workbench.services import evidence_trail_service as trail
    from exposure_workbench.services.numeric_verification import _VALUE_SOURCES
    assert set(trail._RESOLVERS) == set(_VALUE_SOURCES)
