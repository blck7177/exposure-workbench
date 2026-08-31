"""Negative money in the report input carries its sign OUTSIDE the '$' (offline).

The report model is instructed to copy figures exactly, so whatever spelling
_build_user_message uses is the spelling the published briefing uses. The lambda
wrote the sign inside the currency mark — a daily P&L of -141972.82 rendered as
"$-141,973" and the briefing read "down $-141,973". The correct form is
"-$141,973": ASCII hyphen-minus before the '$', magnitude after. ASCII, not
U+2212 — this string goes through the numeric verification gate, and "-$" is the
form the gate parses as negative MONEY.

The money fields are DERIVED, not listed: every float field of ReportInput is
set to a distinct negative value, and a field is a money field iff its rounded
magnitude shows up next to a '$' in the built message. A new money field added
to the report is therefore covered the day it is added, not the day someone
remembers to extend a hand-written list.
"""

from __future__ import annotations

import dataclasses

from exposure_workbench.agents.direct_llm_agent import _build_user_message
from exposure_workbench.agents.schemas import ReportInput


def _all_negative_input() -> tuple[ReportInput, dict[str, float]]:
    """A ReportInput whose every float field is a distinct negative value.

    Distinct magnitudes (spaced by more than 1, so they stay distinct after
    rounding to whole dollars) let the test attribute each '$' in the message
    back to the field it came from.
    """
    kwargs: dict = {"portfolio_id": "port_test", "as_of_date": "2026-08-28"}
    magnitudes: dict[str, float] = {}
    for i, f in enumerate(dataclasses.fields(ReportInput)):
        if f.type in ("float", "float | None"):
            value = -(241972.82 + i * 11111.11)
            kwargs[f.name] = value
            magnitudes[f.name] = value
    # The exact figure from the live defect, so the test asserts the published
    # spelling verbatim. The offsets above start high enough not to collide.
    kwargs["daily_pnl"] = magnitudes["daily_pnl"] = -141972.82
    return ReportInput(**kwargs), magnitudes


def _money_fields(message: str, magnitudes: dict[str, float]) -> dict[str, str]:
    """field name -> rounded magnitude string, for the fields rendered as money."""
    out: dict[str, str] = {}
    for name, value in magnitudes.items():
        mag = f"{abs(value):,.0f}"
        if any(form in message for form in (f"${mag}", f"$-{mag}", f"-${mag}")):
            out[name] = mag
    return out


def test_negative_money_signs_sit_before_the_dollar():
    inp, magnitudes = _all_negative_input()
    message = _build_user_message(inp)

    money = _money_fields(message, magnitudes)
    # The two money interpolations the message holds today. A new one is picked
    # up by the derivation above; losing one of these two is a regression.
    assert "daily_pnl" in money
    assert "portfolio_market_value" in money

    for name, mag in money.items():
        assert f"-${mag}" in message, f"{name}: negative money must render as -${mag}"
        assert f"$-{mag}" not in message, f"{name}: the sign may not sit inside the '$'"

    # No money interpolation anywhere in the message may put the sign inside
    # the currency mark — this covers interpolations the magnitude attribution
    # above cannot see (e.g. a future one formatted at a different precision).
    assert "$-" not in message

    # The exact figure from the live defect, spelled the way the gate parses.
    assert inp.daily_pnl == -141972.82
    assert "-$141,973" in message
    assert "$-141,973" not in message

    # The gate parses ASCII "-$"; a U+2212 here would be silently dropped by
    # the old extractor and must never be introduced by the formatter.
    assert "−" not in message


def test_positive_money_is_unchanged():
    inp = ReportInput(
        portfolio_id="port_test", as_of_date="2026-08-28",
        portfolio_market_value=10_406_776.0, daily_pnl=141972.82,
    )
    message = _build_user_message(inp)
    assert "$10,406,776" in message
    assert "$141,973" in message
    assert "-$" not in message


def test_none_money_is_still_na():
    inp = ReportInput(
        portfolio_id="port_test", as_of_date="2026-08-28",
        var_95_1d=None, vol_30d=None, max_drawdown=None,
    )
    # None must keep rendering as N/A, not raise on abs(None).
    assert "N/A" in _build_user_message(inp)
