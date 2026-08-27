"""V9-A4 — a sum's terms may not nest (offline).

Axiom R3. `LongTermDebt` already contains the current maturities, so adding
`LongTermDebtCurrent` to it double-counts them — 8.31bn on AAPL, with every
input holding a real fact id and every step a real calc id. The citation gate
cannot see that; nothing about the arithmetic is malformed. What makes it
catchable is knowing which metric contains which, and that is DATA, not code.

The eight hand-written debt recipes this replaces were the same knowledge in a
worse form: an ordered list of combinations that happened to be non-overlapping,
one per issuer shape, with a new entry needed for the next issuer. An antichain
over the containment graph derives all of them and generalises to the ones
nobody has met yet.

Every edge is validated against the corpus by test_v9_containment_live, which is
what makes the table an assertion rather than an opinion.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import containment as ct


def test_the_aapl_double_count_is_now_impossible():
    """The number this whole batch exists to prevent: 82.700 + 8.310 = 91.010."""
    got = ct.cover({"long_term_debt_total": 82.700,
                    "long_term_debt_noncurrent": 74.404,
                    "current_portion_long_term_debt": 8.310,
                    "commercial_paper": 1.997}, family="debt")
    assert isinstance(got, ct.Cover)
    assert got.value == pytest.approx(84.697, abs=1e-9)
    assert set(got.terms) == {"long_term_debt_total", "commercial_paper"}


def test_a_cover_is_an_antichain():
    """No term may be an ancestor of another. That is the whole rule; the recipes
    were one enumeration of its consequences."""
    got = ct.cover({"long_term_debt_total": 82.700,
                    "long_term_debt_noncurrent": 74.404,
                    "current_portion_long_term_debt": 8.310}, family="debt")
    assert isinstance(got, ct.Cover)
    for a in got.terms:
        for b in got.terms:
            assert a == b or not ct.contains(a, b), f"{a} contains {b}"


def test_the_widest_available_node_is_preferred():
    """Fewer terms means fewer numbers that can be restated or misread, and a
    reported total is the issuer's own arithmetic rather than ours."""
    got = ct.cover({"long_term_debt_total": 82.700,
                    "long_term_debt_noncurrent": 74.404,
                    "current_portion_long_term_debt": 8.310}, family="debt")
    assert isinstance(got, ct.Cover) and got.terms == ("long_term_debt_total",)


def test_components_are_used_when_no_total_is_reported():
    """XOM's shape: no long_term_debt_total anywhere in the corpus."""
    got = ct.cover({"long_term_debt_noncurrent": 20.0,
                    "current_portion_long_term_debt": 6.2,
                    "debt_current_total": 14.531}, family="debt")
    assert isinstance(got, ct.Cover)
    # debt_current_total contains current_portion_long_term_debt, so only one of
    # them may appear — the wider one.
    assert set(got.terms) == {"long_term_debt_noncurrent", "debt_current_total"}
    assert got.value == pytest.approx(34.531, abs=1e-9)


def test_a_family_with_nothing_reported_is_a_refusal():
    got = ct.cover({"cash_and_equivalents": 45.0}, family="debt")
    assert isinstance(got, ct.NoCover)
    assert got.reason


def test_what_the_cover_left_out_is_reported_not_hidden():
    """A cover is the widest non-overlapping set available, which is not the same
    as complete. JPM reports only short-term borrowings, and a reader has to
    know that the long end is missing rather than zero."""
    got = ct.cover({"short_term_borrowings": 68.048}, family="debt")
    assert isinstance(got, ct.Cover)
    assert got.value == pytest.approx(68.048)
    assert "long_term_debt_total" in got.uncovered or "long_term_debt_noncurrent" in got.uncovered


def test_a_zero_component_is_present():
    """Several issuers report commercial paper of exactly 0. Treating that as
    absent would move the answer to a different cover for no reason."""
    got = ct.cover({"long_term_debt_total": 10.0, "commercial_paper": 0.0}, family="debt")
    assert isinstance(got, ct.Cover) and set(got.terms) == {"long_term_debt_total", "commercial_paper"}


def test_containment_is_transitive():
    assert ct.contains("total_liabilities", "current_liabilities")
    assert ct.contains("stockholders_equity_including_noncontrolling", "noncontrolling_interest")
    assert not ct.contains("long_term_debt_noncurrent", "current_portion_long_term_debt")


def test_every_declared_edge_carries_the_evidence_for_it():
    """An edge nobody measured is an opinion. Each carries the co-occurrence
    count from the corpus survey it was admitted on, and the live test re-runs
    that survey."""
    for parent, child, observed in ct.EDGES:
        assert observed > 0, f"{parent} > {child} was never observed"


def test_the_family_members_with_no_validated_edge_are_named():
    """`short_term_borrowings` belongs to the debt family and sits on no edge,
    because the two relationships that would connect it — debt_current_total >
    short_term_borrowings and short_term_borrowings > commercial_paper — are
    true of the taxonomy and are never observed together in this corpus. There
    is nothing to validate them against, and an unvalidated edge asserted as
    validated is exactly what this module removes.

    An isolated member is SAFE: with no ancestor it can never be excluded, so it
    is always taken, and with no descendant it can never swallow anything. What
    it cannot be is invisible — the moment a real filing pairs it with a parent,
    the cover would double-count until the edge is added. So the list is pinned,
    the way the outstanding concept bets are, and cannot grow by one unnoticed.
    """
    on_an_edge = {m for p, c, _n in ct.EDGES for m in (p, c)}
    isolated = {m for members in ct.FAMILIES.values() for m in members} - on_an_edge
    assert isolated == {"short_term_borrowings"}, (
        f"a family member gained or lost its edges without a decision: {sorted(isolated)}")
