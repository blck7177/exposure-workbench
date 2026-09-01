"""V15-S4/S5 — one resolver, one projection point, one namer (source-level pins).

The old gate was the second implementation of a rule the desk wanted to hold
once: respond verified prose one way, submit_brief another, the daily report a
third, and `not_alone` was checked in each. Two copies of a judgement agree
until the day one changes. These tests read the source and pin that the exits
call the same function, that the collinearity projection has one execution
point, that only quantities.py spells a name, and that the deleted mechanisms
(the harvester, the trajectory gate) stayed deleted.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "exposure_workbench"


def _src(rel: str) -> str:
    return (SRC / rel).read_text()


def _names(rel: str) -> set[str]:
    """Identifiers in the code — comments and strings (docstrings included) excluded."""
    return {t.string for t in tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
            if t.type == tokenize.NAME}


def test_both_exits_resolve_through_the_one_resolver():
    for rel in ("tools/meta_tools.py", "tools/research_tools.py"):
        src = _src(rel)
        assert "resolver.resolve" in src, f"{rel} does not call the resolver"
        assert "numeric_verification" not in src, f"{rel} still reads figures out of prose"
        assert "validate_citations" not in src, f"{rel} still checks citations against the old trail"
        assert "evidence_trail_service" not in src, rel


def test_not_alone_is_a_projection_decided_in_the_table_builder_only():
    """quantities.py SETS it (the row said so); the daily report's v1 path reads
    it in numeric_verification; the block exit decides it once, in table.py.
    The resolver, the exits and the grammar never mention it in code."""
    assert "not_alone" in _names("services/table.py")
    for rel in ("services/resolver.py", "tools/meta_tools.py", "tools/research_tools.py",
                "services/answer_blocks.py"):
        assert "not_alone" not in _names(rel), f"{rel} decides collinearity a second time"


def test_only_quantities_py_builds_a_quantity_name():
    """`_row_label` is the row half of `<table>.<row>.<column>`; a second copy
    anywhere is a second spelling that will drift from the table the model reads."""
    hits = [p for p in SRC.rglob("*.py") if "def _row_label" in p.read_text()]
    assert [p.relative_to(SRC).as_posix() for p in hits] == ["services/quantities.py"], hits
    assert _src("services/quantities.py").count("def _row_label") == 1


def test_the_trajectory_gate_no_longer_exists():
    """R1 moved into the rubric and R2 became the `task_ref` predicate (§3-D)."""
    assert not (SRC / "services" / "trajectory_gate.py").exists()


def test_the_registry_no_longer_harvests_evidence():
    src = _src("tools/registry.py")
    assert "extract_evidence_refs" not in src
    assert "_harvestable" not in src
    assert "tbl.declare(" in src and "tbl.build(" in src, "the wrapper builds the table from the declaration"
