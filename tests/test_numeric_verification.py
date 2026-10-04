"""V3-A1 numeric verification — extraction and exemptions (offline).

V15-S4: this is the v1 PROSE route, kept for the daily report and the eval over
stored prose answers. The chat exit no longer reads figures out of sentences —
it resolves slots by name (services/resolver.py) — so the old group C, which
drove `_respond` with prose, has no subject and is gone.

Group A pins the written forms the live corpus actually contains; group B pins
the exemption set. Four of these are regressions against bugs the first draft
had, each found by running the extractor over the real agent_messages and
issuer_briefs text rather than over invented examples — which is why they are
written as the exact sentences that broke it.
"""

from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("text,forms", [
    ("Your holdings are AAPL 5000, MSFT 3500.", ["5000", "3500"]),   # the A0-1 bypass
    ("Backlog 2500 units", ["2500"]),
    ("A 500 basis point move", ["500"]),
    ("priced in USD 5000", ["5000"]),
    ("a $2000 rebate", ["$2000"]),                                   # not a year: it has a currency mark
    ("1950 million shares outstanding", ["1950 million"]),           # not a year: it has a scale
])
def test_a_capitalised_word_in_front_of_digits_does_not_make_them_a_name(text: str, forms: list[str]):
    """V3-R3, and the review's third blocker sits in the first case. The old
    designator pattern asked only whether a capitalised word preceded the
    digits, so "AAPL 5000" read as a product name like "Microsoft 365" — and a
    reply made entirely of share counts extracted to NOTHING, which means it
    carried no numbers, which means A0-1 let it through with no citations at
    all. The two holes A1 was built to close, open at once, on the single most
    ordinary question a portfolio user asks."""
    assert raw_forms(extract_numbers(text)) == forms


@pytest.mark.parametrize("text", [
    "the H200 accelerator",          # digits attached to the name
    "the GB200 rack",
    "an RTX4090 card",
    "outperformed the S&P 500",      # enumerated: a name with a space in it
    "Microsoft 365 Commercial cloud",
    "the Russell 2000 index",
    "Nasdaq 100 futures",
    "a Fortune 500 customer",
    "the Dow 30 constituents",
    "shipping in 2027 M&A activity",  # a year, and "M&A" is not a scale word
])
def test_a_real_designator_is_still_exempt(text: str):
    assert extract_numbers(text) == [], f"{text!r} yielded {raw_forms(extract_numbers(text))}"


def test_a_date_without_a_year_is_still_a_date():
    """Found by the corpus re-run rather than by reasoning: the old designator
    pattern was also — accidentally — the only thing exempting "March 28", and
    removing it would have started refusing "for the quarter ended March 28" as
    an unsupported 28. The day is closed with a word boundary so the pattern
    cannot back off to "March 1" and leave "5%" standing next to it."""
    assert extract_numbers("for the quarter ended March 28") == []
    assert extract_numbers("the April 30 close") == []
    assert raw_forms(extract_numbers("In March 15% of revenue came from China")) == ["15%"]


def test_the_designator_exemption_is_two_shapes_and_a_closed_list():
    """Which is the point of the redesign, not an implementation detail. Digits
    ATTACHED to a name are self-evidently part of it; a name with a space in it
    cannot be recognised by shape at all, so it is enumerated. Adding one is an
    edit to this tuple plus a test — the same rule the exemption set as a whole
    is built on — rather than a pattern that widens to admit it and everything
    shaped like it."""
    from exposure_workbench.services.numeric_verification import _SPACED_DESIGNATORS
    for name in _SPACED_DESIGNATORS:
        assert extract_numbers(f"tracking the {name} today") == [], name


def test_an_id_is_exempt_whole_not_digit_by_digit():
    """A naive scan of calc_50c612fc9f59 yields 50, 612 and 59 — three numbers
    the model never claimed, in a reply that is otherwise number-free."""
    assert extract_numbers("evidence: calc_50c612fc9f59") == []
    # and the exemption must not extend past the token
    assert raw_forms(extract_numbers("calc_50c612fc9f59 gives 16.2%")) == ["16.2%"]


def test_a_decimal_written_without_its_leading_zero_is_not_ten_times_bigger():
    """The literal had to start on a digit, so ".5%" was read as "5%" — the
    number the model wrote, off by a factor of ten, silently verified against
    whatever ten times it happens to be near. A missed extraction is a hole; a
    misread magnitude is a wrong answer with a citation on it."""
    n = _one("a .5% move")
    assert n.value == pytest.approx(0.005)
    assert _one("$.50 per share").value == pytest.approx(0.50)


def test_a_scale_letter_that_starts_another_word_is_not_a_scale():
    """"3 M&A deals" is three deals, not three million, and "10 T-bills" is ten
    bills. The boundary looks for the compound the letter belongs to; a range
    like "$5B-10B" is left alone, because there the hyphen separates numbers
    rather than starting a word."""
    assert [n.value for n in extract_numbers("3 M&A deals closed")] == [3.0]
    assert [n.value for n in extract_numbers("10 T-bills matured")] == [10.0]
    assert extract_numbers("$5B-10B of buybacks")[0].value == pytest.approx(5e9)


def test_a_number_free_reply_yields_nothing():
    assert extract_numbers("Sure — what would you like to know about the portfolio?") == []
    assert extract_numbers("") == []


# ── group D: the prose route — what a cited passage's digits can vouch for ────
# The match of a written number against a cited row's VALUE (the gate's A1,
# `verify`) left with services/gate: a draft is now read against the view it was
# written from (services/observer). What stays here is the prose route the quote
# check still rests on — a number is "quoted" when its digits, as the kind of
# thing it is, appear in a cited passage.

from exposure_workbench.services.numeric_verification import (  # noqa: E402
    _is_quoted,
    quoted_keys,
)


def _quoted(text: str, passage: str) -> bool:
    return _is_quoted(_one(text), quoted_keys(passage))


def test_a_figure_quoted_verbatim_from_a_cited_passage_is_accepted():
    """The prose route. It is an existence check on the digits, not a magnitude
    check — a filing table's scale often lives in a header the chunk does not
    carry — and that limit is recorded rather than hidden."""
    passage = "Total net sales increased to 111,184 for the quarter"
    assert _quoted("net sales of 111,184", passage)
    assert not _quoted("net sales of 111,185", passage)


def test_every_citable_prefix_has_a_value_source():
    """A prefix the table can place but the namer cannot value would put an id on
    the table that holds nothing and says nothing. run_ and chunk_/src_ were
    both missing from the first design."""
    from exposure_workbench.services import quantities as qn
    assert set(qn.SOURCES) == set(qn.CITABLE_PREFIXES)


def test_a_short_digit_string_cannot_be_verified_by_prose_alone():
    """Found in live acceptance, not by a test. A brief claimed H200 shipments
    face "a 25% import tariff" and cited two filing chunks containing neither
    "H200" nor "tariff" — and the gate accepted it, because "25" occurs
    somewhere in one of them. Nine of that chunk's seventeen distinct digit keys
    are two characters or shorter, so the prose route was accepting coincidences.

    A number with fewer than three significant digits now has to come through
    the structured route or be refused. That does refuse some correct claims
    quoted from prose; in this domain a false accept costs more."""
    passage = "as described in Note 25 of the accompanying financial statements"
    assert not _quoted("a 25% import tariff", passage)
    assert not _quoted("the series returned 25 points", passage)      # two bare digits: a coincidence
    # a long enough string is still evidence
    long_passage = "Total net sales increased to 111,184 for the quarter"
    assert _quoted("net sales of 111,184", long_passage)


# ── group E: the sign axis (V3-R1) ────────────────────────────────────────────
# The axis did not exist. _LIT begins at a digit, so the [+-] the patterns
# matched reached the SURFACE and never the value: "-$81.615B" extracted as
# POSITIVE 81.615 billion. Both halves of that are defects and the first is the
# one a finance desk cares about — a sign flip verified clean against the
# evidence it inverts.

@pytest.mark.parametrize("text,value,unit_class", [
    ("free cash flow of -$16,450.00", -16_450.0, MONEY),
    ("revenue was -$81.615B", -81_615_000_000.0, MONEY),
    ("the momentum factor contributed -0.8%", -0.008, PERCENT),
    ("interest coverage of -1.28x", -1.28, MULTIPLE),
    ("daily P&L fell to -16,450", -16_450.0, COUNT),
    ("net income grew +85.2%", 0.852, PERCENT),
])
def test_a_written_sign_reaches_the_value(text: str, value: float, unit_class: str):
    n = _one(text)
    assert n.unit_class == unit_class
    assert n.value == pytest.approx(value, rel=1e-12)


def test_a_hyphen_between_numbers_is_not_a_minus_sign():
    """A range, a product name and a date fragment all put a '-' in front of
    digits and none of them is a negative. A sign is a sign only when nothing
    runs into it from the left — which is also what stops the model from being
    quoted back a "-20%" it never wrote."""
    assert raw_forms(extract_numbers("revenue grew 15-20%")) == ["15", "20%"]
    assert [n.value for n in extract_numbers("the COVID-19 era")] == [19.0]
    assert [n.value for n in extract_numbers("a range of $5-10B")] == [5.0, 1e10]


def test_the_prose_route_cannot_speak_to_sign():
    """Pinned as a limit rather than left to be discovered. The prose route is
    an existence check on the digits a passage contains, and a filing table
    writes a negative as (16,450) at least as often as -16,450 — so requiring
    the minus to appear would refuse the ordinary case. A chunk citation buys
    the magnitude; the sign is checked exactly on the structured route, which is
    where every calc, fact, alert and run figure comes from. Same shape, and the
    same reason, as the scale limit quoted_keys already carries."""
    passage = "Operating cash flow for the quarter was (16,450), in thousands"
    assert _quoted("a swing of -16,450", passage)
