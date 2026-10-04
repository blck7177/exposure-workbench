"""The quote check, and the percentage a filing spells out (offline).

Two existence tests over what a cited passage actually holds, neither of them
semantic. (The collinear-coefficient flag was the gate's `verify` and left with it.)
"""

from __future__ import annotations

from exposure_workbench.services.numeric_verification import (
    extract_numbers,
    quoted_keys,
    quoted_spans,
    verify_quotes,
    _is_quoted,
)

MSFT_10Q = ("The investments we are making in cloud and AI infrastructure and devices will "
            "continue to increase our operating costs and may decrease our operating margins.")
LLY_10K = ("that collectively accounted for 82 percent of our total revenues in 2025. In "
           "particular, Mounjaro and Zepbound accounted for 56 percent of our total revenues")


# ── quoted text ───────────────────────────────────────────────────────────────

def test_a_verbatim_quotation_passes():
    answer = ('Management says the investments it is making in “cloud and AI '
              'infrastructure and devices” will continue to raise costs.')
    assert verify_quotes(answer, [MSFT_10Q]) == []


def test_one_changed_word_is_caught():
    answer = 'Management says “cloud and AI investment and devices” will raise costs.'
    problems = verify_quotes(answer, [MSFT_10Q])
    assert len(problems) == 1 and problems[0]["reason"] == "not_in_cited_passages"


def test_typography_and_whitespace_are_not_letters():
    """A filing's curly quotes and line wraps are not the model's edits."""
    answer = 'It says "cloud  and AI\ninfrastructure and devices" plainly.'
    assert verify_quotes(answer, [MSFT_10Q]) == []


def test_a_term_of_art_in_scare_quotes_is_not_a_quotation():
    assert quoted_spans('the “free cash flow” line is unavailable') == []
    assert verify_quotes('the “free cash flow” line', [MSFT_10Q]) == []


def test_a_paraphrase_outside_the_marks_is_not_checked():
    """Recorded as this check's limit, not implied away."""
    answer = "Microsoft is expanding datacenters faster than anyone expected."
    assert verify_quotes(answer, [MSFT_10Q]) == []


# ── a percentage the filing spells out ────────────────────────────────────────

def test_a_spelled_out_percentage_is_citable_in_both_spellings():
    keys = quoted_keys(LLY_10K)
    for written in ("82 percent of 2025 revenue came from six products",
                    "82% of revenue came from six products"):
        n = extract_numbers(written)[0]
        assert _is_quoted(n, keys), written


def test_a_percentage_the_passage_does_not_state_is_still_refused():
    n = extract_numbers("81 percent of revenue")[0]
    assert not _is_quoted(n, quoted_keys(LLY_10K))


def test_percent_the_word_is_matched_and_its_lookalikes_are_not():
    """`5 points` and `3 pages` must not mint a percent key."""
    assert "%:82" in quoted_keys("accounted for 82 percent of revenue")
    assert "%:5" not in quoted_keys("rose 5 points on the day")
    assert "%:3" not in quoted_keys("see 3 pages of notes")
    assert "%:12" not in quoted_keys("up 12 percentage points")
