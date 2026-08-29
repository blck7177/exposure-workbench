"""V13-S3 — every piece of evidence can say what it is, in words (offline).

The chips a reader saw were `calc 2b5395`: a type and six hex digits, which
names nothing and can be checked against nothing. Worse, 131 of the 234 answers
in the live database had raw ids embedded in the prose itself, and each brief
ended its paragraphs with `[fact_d92b2cee6290, fact_7f72a249795d, …]` rendered
verbatim. The id is not the problem — the gate needs it and the audit layer shows
it. The problem is that it was the only thing on offer.

Two properties, and the second is the one that makes this a guard rather than a
feature: every resolver produces a label, and no label contains an id. A label
that quietly fell back to the id would satisfy the first and defeat the entire
point, which is exactly the shape of failure this file is here to catch.
"""

from __future__ import annotations

import inspect
import re

import pytest

from exposure_workbench.services import evidence_resolver_service as ev

# The id shapes this system mints. Kept as a pattern rather than a list of
# prefixes because the assertion is about hex tails, which is what makes an id
# unreadable — `fact_`, spelled out in prose, would be fine.
ID_PATTERN = re.compile(r"\b(?:fact|calc|chunk|src|alert|run|rrun|pos|sess|task|port)_[0-9a-f]{6,}\b")


def test_every_resolver_produces_a_label():
    """Derived from the resolver table, not from a list written here.

    _RESOLVERS is the closed set of things that can be cited — it is the same
    set the citation gate resolves against — so a new evidence kind arrives here
    automatically rather than when somebody remembers to add it.
    """
    unlabelled = []
    for prefix, fn in ev._RESOLVERS.items():
        src = inspect.getsource(fn)
        if '"label"' not in src:
            unlabelled.append(prefix)
    assert unlabelled == [], (
        f"evidence kinds whose resolver returns no label: {unlabelled}. Each one "
        "reaches the reader as a type and six hex digits."
    )


@pytest.mark.parametrize("iso,expected", [
    ("2026-03-28", "Mar 28, 2026"),
    ("2025-12-01", "Dec 1, 2025"),
    ("", ""),
    (None, ""),
])
def test_dates_are_written_the_way_they_are_read(iso, expected):
    assert ev._day(iso) == expected


def test_a_balance_and_a_flow_do_not_get_the_same_shape_of_label():
    """A balance is AS OF a date; a flow is OVER a window.

    This desk refuses to let the two be confused anywhere else — it is the
    distinction the interval engine and the typed calculator are built around —
    and a label that rendered both as a bare date would put the confusion back
    on the chip, in the one place a reader looks to check.
    """
    assert ev._window("2025-12-28", "2026-03-28") == "Dec 28, 2025 – Mar 28, 2026"
    assert ev._window(None, "2026-03-28") == "as of Mar 28, 2026"


def test_a_calc_label_never_names_a_portfolio_id():
    """The one that fired while this was being written.

    portfolio.window_return's params carry `portfolio_id`, and the first version
    of the label used it: `Portfolio return · port_001 · Jan 7 – Mar 27`. An
    internal id, in the very function whose job is to stop showing internal ids.
    """
    class _Row:
        operation = "portfolio.window_return"
        params = {"portfolio_id": "port_001", "start": "2026-01-07", "end": "2026-03-27"}
        result = {"value": 0.04}

    label = ev._calc_label(_Row())
    assert "port_001" not in label
    assert label == "Portfolio return · Jan 7, 2026 – Mar 27, 2026"


def test_no_label_this_module_can_build_contains_an_id():
    """The property that makes the labels worth having, over every branch.

    Each row here is shaped after a real operation in the live ledger, including
    the two that carry raw ids in their params (`operands`, `terms`) — those are
    the ones a careless label would leak.
    """
    class _Row:
        def __init__(self, operation, params, result=None):
            self.operation, self.params, self.result = operation, params, result or {}

    rows = [
        _Row("calc.scalar.add", {"op": "add", "operands": ["fact_f676a3998449", "fact_969db7d095e6"],
                                 "result_type": {"basis": {"instant": "2026-03-28"}, "unit_class": "money"}}),
        _Row("derive.interval", {"terms": [{"sign": 1, "fact_id": "fact_4b139bcd1aee"}],
                                 "result_type": {"quantity": "revenue", "unit_class": "money"}}),
        _Row("combine.divide", {"a": {"metric": "gross_profit", "ticker": "NVDA"},
                                "b": {"metric": "total_revenues", "ticker": "NVDA"}}),
        _Row("change.yoy", {"series": "calc_aadb37f4676c",
                            "result_type": {"derived_from": "operating_income"}}),
        _Row("window_return", {"ticker": "TLT", "start": "2025-08-27", "end": "2026-08-27"}),
        _Row("portfolio.reconcile", {"run_id": "run_95ebe31c5e51", "terms_factors": 8}),
        _Row("portfolio.drawdown_episodes", {"portfolio_id": "port_001", "span": "1y"}),
        _Row("recipe.manifest", {"recipe_version": "v2", "as_of": "2026-08-29"}),
        _Row("absence.not_reported", {"tried": {"metric": "inventory"}},
             {"statement": "This desk holds no inventory for GOOGL over any period. "
                           "GOOGL's most recent filed period ends 2026-06-30."}),
        _Row("an.operation.nobody.has.written.yet", {}),
    ]
    for row in rows:
        label = ev._calc_label(row)
        assert label, f"{row.operation} produced no label"
        leaked = ID_PATTERN.findall(label)
        assert leaked == [], f"{row.operation} leaked ids into its label: {leaked} in {label!r}"


def test_an_operation_nobody_has_captioned_still_reads_as_words():
    """An unknown operation is spelled out, not left as a dotted identifier.

    Not a fallback to a lesser answer: there IS no better answer available, the
    result is legible, and it is visibly generic — which is the signal that a
    caption should be added.
    """
    class _Row:
        operation = "some.new.primitive"
        params = {}
        result = {}

    assert ev._calc_label(_Row()) == "Some new primitive"


def test_the_absence_label_is_the_services_own_sentence():
    """absence_service already wrote one, for a reader, and it is better than a
    caption: "This desk holds no depreciation_amortization for GOOGL over any
    period" says what is missing and for whom.
    """
    class _Row:
        operation = "absence.not_reported"
        params = {}
        result = {"statement": "This desk holds no inventory for GOOGL over any period. "
                               "Its most recent filed period ends 2026-06-30."}

    assert ev._calc_label(_Row()) == "This desk holds no inventory for GOOGL over any period"
