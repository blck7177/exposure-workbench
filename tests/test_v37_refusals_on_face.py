"""V37/T3 — a refusal names a verb the reader has.

A domain analyst reaches four tools (`tools/faces.FACE_META_AGENT`: run,
read_filings, search_web, start) plus two in-process ones (compile, submit).
`describe`, `read_book`, `compute`, `read_fundamentals` and `read_prices` are
registered and NOT on that face — V36 narrowed it deliberately, because a face
wider than what anything reaches through it is an audit statement nobody can
rely on.

What V36 did not do is tell the refusals. Round B's Q16 asked a run four times,
in three spellings, for `portfolio.integration.net_beta.market`; the refusal said
a run's names "are listed by describe(run_id)", the analyst could not call
describe, and the answer told the reader the book's net beta was unavailable
while `book.analysis` computes it. Advice that cannot be taken is worse than
none: it costs a round trip and it reads like the desk's fault.

So this file is a static scan, not a behaviour test. It reads the string
literals of the modules whose refusals reach a domain analyst and fails on an
off-face verb in any of them — including one added next year by somebody who
never read this file, which is the whole point of putting it here rather than in
a review checklist.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from exposure_workbench.tools import faces

SRC = Path(__file__).resolve().parents[1] / "src" / "exposure_workbench"

# Every module whose refusals and notes can reach a domain analyst: the program
# language and its executor, the typed calculator behind it, the compiler, the
# digest that renders a result, the run reader a program calls, and the two
# modules that write to the analyst directly.
ON_THE_PATH = (
    "services/program_service.py",
    "services/program_builder.py",
    "services/typed_calculator.py",
    "services/digest.py",
    "services/run_reads_service.py",
    "agents/delegation.py",
    "agents/sub_analyst.py",
)

# The verbs a domain analyst does NOT have. Subtracted from the registry's own
# face, so widening the face automatically widens what a refusal may name.
OFF_FACE = tuple(sorted(
    {"describe", "read_book", "compute", "read_fundamentals", "read_prices", "think", "respond",
     "submit_brief", "request_evidence"}
    - set(faces.FACE_META_AGENT) - {"compile", "submit"}))


def _literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal in a module, with its line — docstrings included.

    Docstrings deliberately: they are where an off-face verb is most likely to be
    copied into a message from, and a module docstring naming `describe(` as the
    way out is the same wrong instruction, one edit away from being live.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


@pytest.mark.parametrize("rel", ON_THE_PATH)
def test_no_refusal_on_the_analysts_path_names_a_verb_it_cannot_call(rel):
    found = []
    for line, text in _literals(SRC / rel):
        for verb in OFF_FACE:
            if f"{verb}(" in text:
                found.append(f"{rel}:{line} names {verb}( — not on the analyst's face")
    assert not found, "\n".join(found) + (
        f"\n\nthe face is {list(faces.FACE_META_AGENT)} plus compile and submit; say what the reader can do, "
        f"or route it to a program node (analytics.skill.call_for_yield)")


def test_the_face_this_file_reads_is_the_one_the_mount_serves():
    """If the face widens, the scan above must widen with it rather than go on
    refusing a verb that is now reachable."""
    assert set(faces.FACE_META_AGENT) == {"run", "read_filings", "search_web", "start"}
    assert "describe" in OFF_FACE and "run" not in OFF_FACE
