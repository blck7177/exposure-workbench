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
    left_out = got.missing_at_this_date + got.no_facts_for_issuer
    assert "long_term_debt_total" in left_out or "long_term_debt_noncurrent" in left_out


def test_a_component_never_filed_is_not_reported_as_debt_left_out():
    """The battery's sharpest false note, on its cleanest answer.

    AAPL's total debt is complete at long_term_debt_total + commercial_paper, and
    the answer said debt_current_total and short_term_borrowings "were not covered
    by that reported set" — which reads as debt omitted. AAPL has never filed
    either concept at any date. The two absences are different facts and are now
    two fields.
    """
    aapl = {"long_term_debt_total": 82.700, "long_term_debt_noncurrent": 74.404,
            "current_portion_long_term_debt": 8.310, "commercial_paper": 1.997}
    got = ct.cover(aapl, family="debt", ever_reported=frozenset(aapl))
    assert isinstance(got, ct.Cover)
    assert got.value == pytest.approx(84.697)
    assert got.missing_at_this_date == (), "nothing AAPL files is missing from this instant"
    assert set(got.no_facts_for_issuer) == {"debt_current_total", "short_term_borrowings"}


def test_a_component_filed_at_another_date_is_the_signal_that_survives():
    """The case the single field existed for: this one really may be short."""
    got = ct.cover({"long_term_debt_total": 82.700}, family="debt",
                   ever_reported=frozenset({"long_term_debt_total", "commercial_paper"}))
    assert isinstance(got, ct.Cover)
    assert got.missing_at_this_date == ("commercial_paper",)
    assert "commercial_paper" not in got.no_facts_for_issuer


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


# ── two parents, one child (round-3 battery, 2026-08-28) ───────────────────────

def test_a_candidate_reaching_into_covered_ground_is_set_aside_not_summed():
    """NVDA 2026-04-26, as filed: long_term_debt_total 8.470 = noncurrent 7.470
    + current portion 1.000, and debt_current_total 1.000 is that same current
    portion. The cover took both parents and reported 9.470 — with a calc_id,
    through the gate, on nineteen dates."""
    got = ct.cover({"long_term_debt_total": 8.470,
                    "long_term_debt_noncurrent": 7.470,
                    "current_portion_long_term_debt": 1.000,
                    "debt_current_total": 1.000}, "debt")
    assert got.value == pytest.approx(8.470)
    assert got.terms == ("long_term_debt_total",)
    assert got.overlapping_not_added == ("debt_current_total",)
    assert "debt_current_total" not in got.missing_at_this_date
    assert "debt_current_total" not in got.no_facts_for_issuer


def test_what_the_overlapping_line_holds_beyond_the_cover_is_reached_through_its_own_parts():
    """If commercial paper is reported separately it is a term of its own; if
    it is not, it is named as missing rather than smuggled in whole."""
    with_cp = ct.cover({"long_term_debt_total": 8.470, "current_portion_long_term_debt": 1.000,
                        "debt_current_total": 1.500, "commercial_paper": 0.500}, "debt")
    assert with_cp.terms == ("long_term_debt_total", "commercial_paper")
    assert with_cp.value == pytest.approx(8.970)
    assert with_cp.overlapping_not_added == ("debt_current_total",)

    without = ct.cover({"long_term_debt_total": 8.470, "current_portion_long_term_debt": 1.000,
                        "debt_current_total": 1.500}, "debt",
                       ever_reported={"commercial_paper"})
    assert without.terms == ("long_term_debt_total",)
    assert without.missing_at_this_date == ("commercial_paper",)
    assert without.overlapping_not_added == ("debt_current_total",)


def test_the_cover_is_still_an_antichain_after_the_fix():
    got = ct.cover({"long_term_debt_total": 8.470, "long_term_debt_noncurrent": 7.470,
                    "current_portion_long_term_debt": 1.000, "debt_current_total": 1.000,
                    "commercial_paper": 0.0}, "debt")
    for x in got.terms:
        for y in got.terms:
            assert x == y or not ct.contains(x, y)


# ── is the sum a TOTAL? (V18) ────────────────────────────────────────────────
#
# "What did the cover leave out" and "does what it took add up to a total" are
# different questions, and only the first was answered. Both of the shapes below
# report a missing long_term_debt_total; one of them is complete and the other is
# short by two orders of magnitude, and telling them apart needs the containment
# graph — which is here, and was not in the caller's hands.

# What an issuer files is never the whole family — no issuer in the corpus files
# all six. Each fixture below carries the set its own issuer actually files,
# measured on the desk (2026-09-02), because `ever_reported` is what separates a
# hole from a concept the issuer does not use.
LONG_AND_PAPER = frozenset({"long_term_debt_total", "long_term_debt_noncurrent",
                            "current_portion_long_term_debt", "commercial_paper"})


def test_a_missing_parent_whose_children_are_both_summed_is_bookkeeping():
    """Alphabet's shape: no long_term_debt_total at this date, both of its
    children reported. The parent is missing and nothing is."""
    c = ct.cover({"long_term_debt_noncurrent": 90.0,
                  "current_portion_long_term_debt": 10.0}, "debt",
                 ever_reported=LONG_AND_PAPER - {"commercial_paper"})
    assert "long_term_debt_total" in c.missing_at_this_date
    assert c.short_by == ()
    assert c.complete
    assert c.value == 100.0


def test_a_missing_parent_whose_children_are_also_missing_is_a_hole():
    """Coca-Cola's shape: commercial paper alone, with the long-term lines filed
    at other dates and reached by nothing here. 250m was returned as a total."""
    c = ct.cover({"commercial_paper": 0.25}, "debt", ever_reported=LONG_AND_PAPER)
    assert not c.complete
    assert "long_term_debt_total" in c.short_by
    assert "long_term_debt_noncurrent" in c.short_by


def test_a_missing_leaf_the_issuer_files_is_a_hole_however_small():
    """Microsoft's and NVIDIA's shape. Commercial paper is usually a small part
    of a large issuer's debt, and the rule does not ask how big: absent is not
    zero, and an issuer that files a line and omits it at one date has not said
    it went to zero."""
    c = ct.cover({"long_term_debt_total": 40.0}, "debt", ever_reported=LONG_AND_PAPER)
    assert not c.complete
    assert c.short_by == ("commercial_paper",)


def test_a_component_the_issuer_never_files_does_not_make_the_sum_short():
    """Apple's shape, and the V11-U finding this rests on: Apple has never filed
    debt_current_total or short_term_borrowings at any date, and reporting them
    as debt left out read to a reader as a hole in a complete total.

    `no_facts_for_issuer` is a statement about THIS DESK's coverage, and the
    cover deliberately does not turn it into a claim about the issuer's debt —
    that question belongs to concept_mapping, which is the layer that can tell
    an unused concept from an unmapped tag."""
    c = ct.cover({"long_term_debt_total": 84.0, "commercial_paper": 0.7}, "debt",
                 ever_reported=frozenset({"long_term_debt_total",
                                          "long_term_debt_noncurrent",
                                          "current_portion_long_term_debt",
                                          "commercial_paper"}))
    assert c.complete
    assert set(c.no_facts_for_issuer) == {"debt_current_total", "short_term_borrowings"}
    assert c.short_by == ()


def test_completeness_asks_the_graph_and_nothing_else():
    """No threshold, no appeal to magnitude, no issuer rule. A leaf that is
    absent and filed elsewhere is short; a parent whose ground is in the sum is
    not; and that is the whole judgement."""
    assert ct._accounted_for("long_term_debt_total",
                             {"long_term_debt_noncurrent", "current_portion_long_term_debt"},
                             set(ct.FAMILIES["debt"]))
    assert not ct._accounted_for("long_term_debt_total", {"commercial_paper"},
                                 set(ct.FAMILIES["debt"]))
    # A leaf has no other way to be reached.
    assert not ct._accounted_for("commercial_paper", {"long_term_debt_total"},
                                 set(ct.FAMILIES["debt"]))


def test_a_complete_cover_is_the_default_and_stays_quiet():
    c = ct.cover({"long_term_debt_total": 84.0}, "debt",
                 ever_reported=frozenset({"long_term_debt_total"}))
    assert c.complete and c.short_by == ()
