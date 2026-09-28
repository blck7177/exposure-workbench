"""V2 P3.1 (design v0.4 §06–§07): the question's requirements are declared once, each
as a verbatim span of the user's words, and every task says which it serves. The
one mechanical half of "对照用户原文核实". Offline, protocol only.
"""

from __future__ import annotations

import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.utils.ids import new_id

Q = "How big is MSFT in the book, and  what will its weight be next year?"
REQS = [{"id": "R1", "anchor": "How big is MSFT in the book"}, {"id": "R2", "anchor": "what will its weight be next year"}]


def test_anchors_are_the_users_words_and_ids_are_r_numbers():
    declared = dl.parse_requirements({"requirements": REQS}, Q)
    assert [r["id"] for r in declared] == ["R1", "R2"] and declared[0]["status"] == "unresolved"
    assert declared[1]["anchor"] == "what will its weight be next year", "whitespace is squeezed, words are not touched"
    with pytest.raises(dl.BadDelegation, match="not a span of the user's words"):
        dl.parse_requirements({"requirements": [{"id": "R1", "anchor": "MSFT's forecast weight"}]}, Q)
    with pytest.raises(dl.BadDelegation, match="R1, R2"):
        dl.parse_requirements({"requirements": [{"id": "req-1", "anchor": "How big is MSFT"}]}, Q)
    with pytest.raises(dl.BadDelegation, match="declared twice"):
        dl.parse_requirements({"requirements": [REQS[0], REQS[0]]}, Q)
    with pytest.raises(dl.BadDelegation, match="first ask"):
        dl.parse_requirements({"tasks": []}, Q)
    assert dl.parse_requirements({"tasks": []}, Q, known=declared) == []


def test_requirements_are_declared_once():
    with pytest.raises(dl.BadDelegation, match="declared once"):
        dl.parse_requirements({"requirements": REQS}, Q, known=dl.parse_requirements({"requirements": REQS}, Q))


def test_every_task_says_which_requirements_it_serves_once_they_exist():
    declared = dl.parse_requirements({"requirements": REQS}, Q)
    task = {"analyst": "risk", "subjects": ["port_001"], "lines": ["how big MSFT is"]}
    [t] = dl.parse_tasks({"tasks": [{**task, "for": ["r1"]}]}, new_id, requirements=declared)
    assert t.requirement_ids == ("R1",) and t.as_dict()["for"] == [{"id": "R1", "anchor": "How big is MSFT in the book"}]
    with pytest.raises(dl.BadDelegation, match="says which requirement"):
        dl.parse_tasks({"tasks": [task]}, new_id, requirements=declared)
    with pytest.raises(dl.BadDelegation, match="not a declared requirement"):
        dl.parse_tasks({"tasks": [{**task, "for": ["R9"]}]}, new_id, requirements=declared)
    with pytest.raises(dl.BadDelegation, match="no requirement has been declared"):
        dl.parse_tasks({"tasks": [{**task, "for": ["R1"]}]}, new_id)
    [plain] = dl.parse_tasks({"tasks": [task]}, new_id)
    assert plain.requirements == () and "for" not in plain.as_dict(), "a turn without declared requirements asks as before"


def test_lines_that_serve_different_requirements_say_so_one_list_per_line():
    declared = dl.parse_requirements({"requirements": REQS}, Q)
    two = {"analyst": "risk", "subjects": ["port_001"], "lines": ["how big MSFT is", "MSFT's weight next year"]}
    [t] = dl.parse_tasks({"tasks": [{**two, "for": [["R1"], ["R2"]]}]}, new_id, requirements=declared)
    assert t.requirement_ids == ("R1", "R2") and t.requirements_of_line(2) == ("R2",)
    assert t.as_dict()["line_for"] == {"1": ["R1"], "2": ["R2"]}
    [whole] = dl.parse_tasks({"tasks": [{**two, "for": ["R1", "R2"]}]}, new_id, requirements=declared)
    assert whole.requirements_of_line(2) == ("R1", "R2") and "line_for" not in whole.as_dict()
    with pytest.raises(dl.BadDelegation, match="one list per line"):
        dl.parse_tasks({"tasks": [{**two, "for": [["R1"]]}]}, new_id, requirements=declared)
    with pytest.raises(dl.BadDelegation, match="serves no requirement"):
        dl.parse_tasks({"tasks": [{**two, "for": [["R1"], []]}]}, new_id, requirements=declared)
    with pytest.raises(dl.BadDelegation, match="not a mix"):
        dl.parse_tasks({"tasks": [{**two, "for": ["R1", ["R2"]]}]}, new_id, requirements=declared)
