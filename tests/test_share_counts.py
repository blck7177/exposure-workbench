"""V16 Lane B: the per-share / capital-allocation layer of mapping v4 (offline).

Corpus facts these tests rest on (measured 2026-09-01, 8 issuers): every mapped
concept carries exactly one unit string and one period shape — EPS in
"USD per share", the three counts in "shares", the cash flows in "USD"; EPS,
the weighted counts and the cash flows are durations, CommonStockSharesOutstanding
is instant-only. The two dividends tags are filed by disjoint issuer sets, which
is what licenses their merge into one metric. Measurements live in the mapping's
comments; these tests pin the decisions the measurements produced.
"""

from __future__ import annotations

import importlib

from exposure_workbench.analytics import semantics as sm
from exposure_workbench.services import concept_mapping as cm

_V4_METRICS = (
    "eps_diluted",
    "eps_basic",
    "shares_diluted_weighted",
    "shares_basic_weighted",
    "shares_outstanding",
    "buybacks",
    "dividends_paid",
    "sbc",
)

_CONCEPT_TO_EXPECTED = {
    "us-gaap:EarningsPerShareDiluted": "eps_diluted",
    "us-gaap:EarningsPerShareBasic": "eps_basic",
    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding": "shares_diluted_weighted",
    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic": "shares_basic_weighted",
    "us-gaap:CommonStockSharesOutstanding": "shares_outstanding",
    "us-gaap:PaymentsForRepurchaseOfCommonStock": "buybacks",
    "us-gaap:PaymentsOfDividends": "dividends_paid",
    "us-gaap:PaymentsOfDividendsCommonStock": "dividends_paid",
    "us-gaap:ShareBasedCompensation": "sbc",
}


def test_v4_metrics_are_all_supported():
    assert cm.MAPPING_VERSION == "v4"
    missing = [m for m in _V4_METRICS if m not in cm.SUPPORTED_METRICS]
    assert not missing, missing


def test_duplicate_claim_guard_survives_v4():
    """The import-time guard makes a double-claimed concept a RuntimeError, so a
    clean re-import IS the proof no v4 concept was claimed twice — and the
    inverted map must agree with the table it was built from."""
    importlib.reload(cm)  # raises RuntimeError if any concept is claimed twice
    for metric, concepts in cm._METRIC_CONCEPTS.items():
        for c in concepts:
            assert cm._CONCEPT_TO_METRIC[c] == metric


def test_three_share_counts_are_mutually_do_not_combine():
    """Weighted-diluted, weighted-basic and point-in-time outstanding are three
    quantities wearing one word. The model may arrive at any of the three first,
    so every one must name the other two."""
    counts = ("shares_diluted_weighted", "shares_basic_weighted", "shares_outstanding")
    for name in counts:
        s = sm.METRICS.get(name)
        assert s is not None, name
        others = set(counts) - {name}
        assert others <= set(s.do_not_combine_with), f"{name}: missing {others - set(s.do_not_combine_with)}"


def test_us_gaap_concepts_normalize_to_their_metric():
    for concept, expected in _CONCEPT_TO_EXPECTED.items():
        assert cm.normalize_concept(concept) == expected, concept


def test_dei_cover_page_count_stays_unnormalized():
    """dei:EntityCommonStockSharesOutstanding is stored but NOT normalized:
    normalize_concept normalizes us-gaap only, and widening that rule is its own
    decision rather than a side effect of this batch."""
    assert cm.normalize_concept("dei:EntityCommonStockSharesOutstanding") is None
