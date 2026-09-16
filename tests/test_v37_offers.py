"""V37/K1 — the ROSTER may not promise what the desk withholds.

The lead analyst picks a domain by reading its `offers` and nothing else, so an
offer is a routing decision made in advance. Round B sent `book_market_risk`
seven tasks and twenty-four lines and got six back; of its twenty-three programs
exactly one came back clean. Its offers promise "the stress losses the desk's
shocks produce" and "the book's own factor betas", and the desk's own words in the
same `Procedure` say stress results are withheld pending validation and that a
collinear fit is not quotable name by name. The lead routed correctly on what it
was told; what it was told was not true.

9/15's wording sheet went unread for a day, and that is the reason this is a test
and not a review note: a table beside the code fails the build, a table in a
document does not. Every entry below cites where the desk says it, and the first
test checks that it really says it there — so the table cannot drift into fiction
of its own.
"""
from __future__ import annotations

import pytest

from exposure_workbench.analytics import skill
from exposure_workbench.services import program_service as ps

# term the offers may not promise -> (where the desk says so, the words it says)
NOT_PRODUCED = {
    "stress loss": ("book_market_risk.desk", "stress results are withheld"),
    "stress losses": ("book_market_risk.desk", "stress results are withheld"),
    "correlation": ("book_market_risk.absent", "correlations between holdings"),
    "forecast": ("BOUNDARIES", "the desk does not forecast"),
    "look-through": ("book_composition.offers", "no look-through"),
    "as of a past date": ("BOUNDARIES", "never an as-of date"),
}


def _sources() -> dict[str, str]:
    out = {"BOUNDARIES": " ".join(ps.BOUNDARIES)}
    for p in skill.PROCEDURES.values():
        out[f"{p.name}.desk"] = " ".join(p.desk)
        out[f"{p.name}.absent"] = p.absent
        out[f"{p.name}.compare"] = " ".join(p.compare)
        out[f"{p.name}.offers"] = " ".join(p.offers)
    return out


@pytest.mark.parametrize("term", sorted(NOT_PRODUCED))
def test_the_desk_really_says_it_withholds_this(term):
    """The table is checked against the code, so it cannot become a claim about
    the desk that the desk does not make."""
    where, words = NOT_PRODUCED[term]
    sources = _sources()
    assert where in sources, where
    assert words.lower() in sources[where].lower(), (term, where)


# A term NAMED is not a term promised: the last line of each domain's offers
# states its boundary, and a boundary has to be able to use the word. What is
# refused is the word standing without one of these in front of it.
_NEGATORS = ("no ", "not ", "never ", "without ", "nor ")


def _promised(line: str, term: str) -> bool:
    """Whether this line OFFERS the term rather than naming it in a boundary.

    A negator anywhere earlier in the line negates it, because a boundary states
    a list: "no re-fitted beta, volatility, VaR or stress loss" negates all four,
    and only the first sits next to the word "no"."""
    low = line.lower()
    at = low.find(term)
    while at != -1:
        if not any(n in low[:at] for n in _NEGATORS):
            return True
        at = low.find(term, at + 1)
    return False


@pytest.mark.parametrize("name", sorted(skill.PROCEDURES))
def test_a_domains_offers_do_not_promise_what_the_desk_withholds(name):
    bad = [f"{name} offers {line!r}, and {where} says the desk withholds {term!r}"
           for line in skill.PROCEDURES[name].offers
           for term, (where, _words) in NOT_PRODUCED.items() if _promised(line, term)]
    assert not bad, "\n".join(bad)


def test_an_offer_about_factor_betas_says_which_ones_the_desk_gives():
    """`factor_attributions.beta` on a run is `not_alone` — the legs are collinear
    and only their netted sum is quotable — and the offers said "the book's own
    factor betas" with no such qualification. Round B's Q16 asked four times and
    the answer told the reader the book's net beta was unavailable."""
    offers = " ".join(skill.PROCEDURES["book_market_risk"].offers).lower()
    if "factor beta" in offers:
        assert "collinear" in offers or "netted" in offers or "net beta" in offers, \
            "an offer of factor betas has to say the desk gives the netted figure, not the legs"
