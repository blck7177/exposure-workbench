"""V8-P4 — a run's own findings can be counted (offline).

The gate resolves `run_` through the run's children, and every value it produces
is a MEASUREMENT one of those rows holds: a weight, a loss, a beta. What no child
row holds is HOW MANY of them there are — so the two sentences

    "three limits are breached"
    "twenty-seven checks ran and twenty-four were clear"

were unciteable while every number inside them was fine. The counts are facts
about the run, held by the run, and nothing but arithmetic on rows the resolver
already reads.

The boundary is deliberate and enumerated in code (DP1): DIRECT children only,
each counted whole or split by the one boolean/enum that the table exists to
record. No filtering by value, no grouping by ticker, no aggregation the caller
chooses — that would be the portfolio-arithmetic surface this desk decided not
to open, reachable through a citation id instead of through a tool.
"""

from __future__ import annotations

import inspect

from exposure_workbench.services import numeric_verification as nv


def test_the_count_map_is_a_literal_enumeration():
    """Not a query builder. The set of countable things is written down, so
    reading this module tells an auditor the whole surface — the same property
    _RUN_CHILDREN has, for the same reason."""
    assert isinstance(nv._RUN_COUNTS, tuple)
    assert nv._RUN_COUNTS, "at least the alerts, the checks and the scenarios"
    for entry in nv._RUN_COUNTS:
        model, label, split = entry
        assert isinstance(label, str)
        # split is either None (count the lot) or a column name whose distinct
        # values partition the rows. Anything else would be a predicate, and a
        # predicate is where arbitrary aggregation starts.
        assert split is None or isinstance(split, str)


def test_counts_are_declared_over_direct_children_only():
    """Every counted model must also be a model the resolver already reads as a
    child of the run. A count over something the gate cannot otherwise see would
    be a second, weaker path to the same evidence."""
    children = {model for model, *_ in nv._RUN_CHILDREN}
    for model, _label, _split in nv._RUN_COUNTS:
        assert model in children, f"{model.__name__} is counted but is not a run child"


def test_a_count_is_a_count_not_a_ratio():
    """`_COMPATIBLE` lets a bare written number meet a stored COUNT, and lets a
    percent meet only a RATIO. Emitting these as RATIO would make "3 alerts"
    verify a claim of "3%"."""
    src = inspect.getsource(nv._from_run)
    assert "COUNT" in src, "row counts must be emitted in the COUNT unit class"
