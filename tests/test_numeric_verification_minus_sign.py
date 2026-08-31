"""V3-A1 sign spellings — U+2212 and the sign-inside-'$' form (offline).

The docstring's property 4 says THE SIGN IS PART OF THE NUMBER, and V3-R made
the ASCII hyphen reach the value. Two spellings still did not:

  - "−$141,973" (U+2212, the typographic minus) matched from the '$', so the
    sign was silently DROPPED and a loss extracted as a positive figure. A
    mis-read is worse than a refusal: a gate that reads a loss as a gain would
    verify a wrong claim.
  - "$-141,973" (the sign inside the currency mark) broke the money pattern at
    the '-', so the bare pattern picked the digits up as a COUNT — sign intact
    but unit checking silently bypassed for exactly the malformed spelling most
    likely to accompany a malformed claim.

Both fixes are the module's own sanctioned class of edit: another way of
WRITING a sign, never a widening of the tolerance. What deliberately does NOT
change: the ASCII forms, the range/name protections the lookbehind provides
(now applied to U+2212 too), the unsigned `key` that feeds the prose route (a
filing table writes "(16,450)" as readily as "-16,450"), the tolerances, and
_EXEMPTION_PATTERNS.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services.numeric_verification import (
    COUNT,
    MONEY,
    PERCENT,
    ExtractedNumber,
    extract_numbers,
    raw_forms,
)

MINUS = "−"  # −


def _one(text: str) -> ExtractedNumber:
    found = extract_numbers(text)
    assert len(found) == 1, f"expected exactly one number in {text!r}, got {raw_forms(found)}"
    return found[0]


# ── U+2212 is a minus, and it negates ─────────────────────────────────────────

def test_a_typographic_minus_before_the_dollar_negates_the_money():
    """Regression. "−$141,973" extracted as "$141,973", value +141973 — the one
    corruption this domain punishes hardest, an inverted figure, produced by the
    gate's own reading rather than by the model."""
    n = _one(f"down {MINUS}$141,973 today")
    assert n.unit_class == MONEY
    assert n.value == pytest.approx(-141973.0)
    assert n.surface == f"{MINUS}$141,973"


def test_a_typographic_minus_before_a_percent_negates_it():
    n = _one(f"the factor contributed {MINUS}0.83% of the move")
    assert n.unit_class == PERCENT
    assert n.value == pytest.approx(-0.0083)


def test_a_typographic_minus_before_scaled_money_negates_it():
    assert _one(f"a swing of {MINUS}$81.615B").value == pytest.approx(-81_615_000_000.0)


# ── the sign inside the '$' is still a sign, and still money ──────────────────

def test_a_sign_inside_the_currency_mark_is_negative_money_not_a_count():
    """Regression. "$-141,973" fell through to the bare pattern as a COUNT: the
    sign survived but the '$' did not, so _COMPATIBLE let the figure meet any
    stored class and unit checking was silently bypassed."""
    n = _one("down $-141,973 today")
    assert n.unit_class == MONEY
    assert n.value == pytest.approx(-141973.0)
    assert n.surface == "$-141,973"


def test_a_typographic_minus_inside_the_currency_mark_is_negative_money():
    n = _one(f"down ${MINUS}141,973 today")
    assert n.unit_class == MONEY
    assert n.value == pytest.approx(-141973.0)


# ── what must NOT change ──────────────────────────────────────────────────────

def test_the_ascii_forms_read_exactly_as_before():
    assert _one("a P&L of -$141,973").value == pytest.approx(-141973.0)
    assert _one("a P&L of -$141,973").unit_class == MONEY
    assert _one("the factor detracted -0.83%").value == pytest.approx(-0.0083)
    assert _one("net income grew +85.2%").value == pytest.approx(0.852)


def test_a_typographic_minus_as_a_range_dash_is_not_a_sign():
    """The lookbehind protects U+2212 exactly as it protects the hyphen:
    "15−20%" is a range, and the second figure is not negative twenty percent."""
    forms = raw_forms(extract_numbers(f"a 15{MINUS}20% band"))
    assert forms == ["15", "20%"]
    values = {n.surface: n.value for n in extract_numbers(f"a 15{MINUS}20% band")}
    assert values["20%"] == pytest.approx(0.20)


def test_the_key_stays_unsigned_for_the_prose_route():
    """A filing table writes a negative as "(16,450)" as readily as "-16,450",
    so the prose probe must not carry the sign — for U+2212 as for the hyphen."""
    assert _one(f"down {MINUS}$141,973 today").key == "141973"
    assert _one("down $-141,973 today").key == "141973"


def test_a_bare_count_with_a_typographic_minus_negates():
    n = _one(f"a net change of {MINUS}1,250 contracts")
    assert n.unit_class == COUNT
    assert n.value == pytest.approx(-1250.0)
