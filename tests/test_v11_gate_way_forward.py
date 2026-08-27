"""A refusal that names the one legal move (V11-G, G7a).

The gate's standard is unchanged — every number in these tests is still refused.
What changes is that a refusable number two cited values away now says which call
would earn it an id. From the agent battery: asked whether to lend to NVDA, the
model wrote "net debt was negative 3.767bn" — correct, and derivable from the two
figures in its own sentence. Refused for having no calc id, it did not compute the
number; it substituted a different, weaker measure that was cheap to cite, and the
sentence that survived does not follow from the numbers it states. The wrong answer
was the cheapest answer.
"""

from __future__ import annotations

from exposure_workbench.services.numeric_verification import (
    MONEY,
    RATIO,
    EvidenceValue,
    extract_numbers,
    verify,
)

TOTAL_DEBT = EvidenceValue(9.47e9, MONEY, "total_debt", "calc_89e94ca94625")
CASH = EvidenceValue(13.237e9, MONEY, "cash_and_equivalents", "fact_fe41f2844502")


def _one(text: str, values=(TOTAL_DEBT, CASH)) -> dict:
    problems = verify(extract_numbers(text), list(values))
    assert len(problems) == 1, problems
    return problems[0]


def test_the_number_is_still_refused():
    p = _one("net debt was -3.767bn")
    assert p["reason"] == "not_in_cited_evidence"


def test_the_refusal_names_the_call_that_would_earn_it_an_id():
    p = _one("net debt was -3.767bn")
    assert p["derivable"] == {
        "op": "subtract", "a": "calc_89e94ca94625", "b": "fact_fe41f2844502",
        "detail": p["derivable"]["detail"],
    }
    assert "calculate(op='subtract'" in p["derivable"]["detail"]


def test_the_suggested_operand_order_follows_the_written_sign():
    """A sign is part of the number, so it is part of which operand comes first."""
    assert _one("net debt was -3.767bn")["derivable"]["a"] == "calc_89e94ca94625"
    assert _one("net debt was +3.767bn")["derivable"]["a"] == "fact_fe41f2844502"


def test_all_four_operations_are_searched():
    assert _one("the two together are 22.707bn")["derivable"]["op"] == "add"
    assert _one("that is 1.3978x")["derivable"]["op"] == "divide"


def test_a_number_no_pair_produces_carries_no_suggestion():
    p = _one("net debt was 5.0bn")
    assert "derivable" not in p, "a hint is only ever an arithmetic fact, never a guess"


def test_a_value_is_not_combined_with_itself():
    """Otherwise every refused 0 is 'derivable' as x - x, and every doubling too."""
    p = _one("the difference was 0", values=(TOTAL_DEBT,))
    assert "derivable" not in p


def test_a_supported_number_never_reaches_the_search():
    assert verify(extract_numbers("total debt was 9.47bn"), [TOTAL_DEBT, CASH]) == []


def test_incompatible_units_are_not_searched_across():
    """The search runs over the candidates the unit rule already allowed, so a
    money pair can never be offered as the derivation of a percentage."""
    share = EvidenceValue(0.5556, RATIO, "factor_share", "calc_0bf502890e53")
    problems = verify(extract_numbers("the factors explain 62.0%"), [TOTAL_DEBT, CASH, share])
    assert len(problems) == 1
    assert "derivable" not in problems[0]
