"""Which metric contains which, and how to add up without double-counting.

Axiom R3: the terms of a sum may not nest. `LongTermDebt` already contains the
current maturities, so `long_term_debt_total + current_portion_long_term_debt`
counts 8.31bn of AAPL's debt twice — and the citation gate cannot object,
because every input has a real fact id and every step a real calc id. A
well-formed error is the one shape that architecture cannot catch, so the
knowledge that prevents it has to exist somewhere. It is here, as DATA.

This replaces eight hand-written debt recipes: an ordered list of combinations
that happened not to overlap, one per issuer shape, needing a new entry for the
next issuer. An antichain over the containment graph derives all eight and
covers the shapes nobody has met.

The edges are the taxonomy's, not ours, and every one was validated against the
corpus before it was written down — child never exceeds parent, over 787
co-occurrences with zero violations (2026-08-25). test_v9_containment_live
re-runs that check, so an edge that stops holding goes red rather than quiet.

Two relationships that ARE true of the taxonomy are deliberately absent:
debt_current_total > short_term_borrowings and short_term_borrowings >
commercial_paper. No issuer in this corpus reports either pair together, so
there is nothing to validate them against, and an unvalidated edge asserted as
validated is the shape this module exists to remove. They go in when data does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# (parent, child, times observed together in the corpus with child <= parent).
# The count is the evidence, kept beside the claim.
EDGES: tuple[tuple[str, str, int], ...] = (
    ("long_term_debt_total", "long_term_debt_noncurrent", 90),
    ("long_term_debt_total", "current_portion_long_term_debt", 85),
    ("debt_current_total", "current_portion_long_term_debt", 24),
    ("debt_current_total", "commercial_paper", 21),
    ("stockholders_equity_including_noncontrolling", "stockholders_equity", 40),
    ("stockholders_equity_including_noncontrolling", "noncontrolling_interest", 40),
    ("operating_lease_liability_total", "operating_lease_liability_current", 66),
    ("operating_lease_liability_total", "operating_lease_liability_noncurrent", 87),
    ("total_liabilities", "current_liabilities", 109),
    ("total_liabilities", "long_term_debt_noncurrent", 74),
    ("total_assets", "current_assets", 151),
)

# What a caller may ask to be covered. A family is a question ("what does this
# issuer owe"), not a taxonomy node.
FAMILIES: dict[str, tuple[str, ...]] = {
    "debt": (
        "long_term_debt_total", "long_term_debt_noncurrent",
        "current_portion_long_term_debt", "debt_current_total",
        "short_term_borrowings", "commercial_paper",
    ),
    "equity": (
        "stockholders_equity_including_noncontrolling",
        "stockholders_equity", "noncontrolling_interest",
    ),
    "operating_leases": (
        "operating_lease_liability_total",
        "operating_lease_liability_current", "operating_lease_liability_noncurrent",
    ),
}


@dataclass(frozen=True)
class Cover:
    """The widest non-overlapping set of what was reported, and what it misses.

    What it misses is TWO things and they were one field until V11-U, which made
    the cleanest answer in the battery carry a falsehood. AAPL's total debt is
    complete at 84.697bn — and the answer said "debt_current_total and
    short_term_borrowings were not covered by that reported set", which a reader
    takes as debt left out. AAPL has never filed either concept, at any date.

    `missing_at_this_date` is the signal: the issuer files this component, not on
    this instant, so the total may genuinely be short. `no_facts_for_issuer` is a
    statement about THIS DESK's coverage of that issuer, not about its debt.
    """
    value: float
    terms: tuple[str, ...]
    formula: str
    missing_at_this_date: tuple[str, ...] = field(default_factory=tuple)
    no_facts_for_issuer: tuple[str, ...] = field(default_factory=tuple)
    # Reported at this date, and NOT added, because part of it was already
    # summed through a wider node. NVDA files debt_current_total (1.0bn) and
    # that 1.0bn is the current portion long_term_debt_total already holds.
    # It is neither missing nor unfiled, so it is neither of the two above; a
    # reader who sees it here knows why the total is narrower than the lines.
    overlapping_not_added: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NoCover:
    reason: str
    looked_for: tuple[str, ...] = field(default_factory=tuple)


Result = Cover | NoCover


def _descendants(node: str) -> set[str]:
    out, frontier = set(), [node]
    while frontier:
        cur = frontier.pop()
        for parent, child, _n in EDGES:
            if parent == cur and child not in out:
                out.add(child)
                frontier.append(child)
    return out


def contains(ancestor: str, descendant: str) -> bool:
    """Transitive: total_liabilities contains current_liabilities contains ..."""
    return descendant in _descendants(ancestor)


def cover(available: dict[str, float], family: str,
          *, ever_reported: frozenset[str] | set[str] = frozenset()) -> Result:
    """Add up a family without counting anything twice.

    Widest-first: a node the issuer reported is its own arithmetic, and each term
    dropped is one fewer number that can be restated or misread. Having taken a
    node, everything beneath it is covered — that exclusion IS axiom R3 — and a
    later candidate that REACHES INTO covered ground is set aside too, because
    taking it would sum the shared part twice.

    The second half is the round-3 battery's finding (2026-08-28). The exclusion
    used to run one way only: it kept the descendants of taken nodes out, and
    never asked whether a candidate's own descendants were already in. Two
    parents sharing one child — long_term_debt_total and debt_current_total
    both hold current_portion_long_term_debt — were both taken, and NVDA's
    total debt came out 9.47bn against a filed 8.47bn, on 19 dates, with a
    calc_id, through the gate. Every number was real; the antichain was not.

    What is left over is named, because a cover is the widest non-overlapping set
    of what exists and that is not the same as complete: JPM reports only
    short-term borrowings, and 68bn is its short end, not its debt. Widest-first
    means every member that IS present ends up taken or excluded, so the leftovers
    are always members with no value here — split by whether the issuer files them
    at all. `ever_reported` is what the caller knows about other dates; without it
    every absence reads as one this desk has never seen, which is what it is from
    inside this function.
    """
    members = FAMILIES.get(family)
    if members is None:
        return NoCover(reason=f"unknown family {family!r}; known: {sorted(FAMILIES)}")

    present = [m for m in members if m in available and available[m] is not None]
    if not present:
        return NoCover(reason=f"no {family} component reported at this date",
                       looked_for=members)

    # Widest first: most descendants, then the declared order for determinism —
    # a total whose composition changed between identical calls could not be
    # checked by a reader.
    ranked = sorted(present, key=lambda m: (-len(_descendants(m) & set(members)),
                                            members.index(m)))
    taken: list[str] = []
    covered: set[str] = set()          # taken nodes and everything beneath them
    overlapping: list[str] = []
    for node in ranked:
        if node in covered:
            continue
        below = _descendants(node)
        if below & covered:
            # Part of this line is already in the sum. The part that is NOT is
            # reachable only through this line's own descendants, which the
            # ranking visits next — taken if reported here, named as missing
            # if not. What must not happen is taking the line whole.
            overlapping.append(node)
            continue
        taken.append(node)
        covered |= {node} | below

    taken_in_order = [m for m in members if m in taken]
    left_over = [m for m in members
                 if m not in taken and m not in covered and m not in overlapping]
    return Cover(
        value=sum(available[m] for m in taken_in_order),
        terms=tuple(taken_in_order),
        formula=" + ".join(taken_in_order),
        missing_at_this_date=tuple(m for m in left_over if m in ever_reported),
        no_facts_for_issuer=tuple(m for m in left_over if m not in ever_reported),
        overlapping_not_added=tuple(m for m in members if m in overlapping),
    )
