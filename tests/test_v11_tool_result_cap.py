"""The cap on a tool result drops whole entries and says which (V11-T, G3).

A byte slice of serialized JSON was the first version. It cost the fundamental
panel four of its sixteen lines on every NVDA call — net_debt among them — and
nothing in the payload said so, which is how the citation gate came to refuse
-3.767bn while the panel held a calc id for exactly that number.
"""

from __future__ import annotations

import json

from exposure_workbench.utils.json import dumps_capped


def _obj(n: int, pad: int = 60) -> dict:
    return {"ticker": "NVDA",
            "lines": {f"f{i}": {"value": i, "pad": "x" * pad} for i in range(n)}}


def test_a_payload_that_fits_is_untouched():
    small = {"ticker": "NVDA", "value": 1}
    assert json.loads(dumps_capped(small, 6000)) == small
    assert "truncated" not in dumps_capped(small, 6000)


def test_entries_come_off_the_tail_and_are_named():
    out = json.loads(dumps_capped(_obj(10), 700))
    assert list(out["lines"]) == ["f0", "f1", "f2", "f3", "f4"]
    assert out["truncated"] == {
        "container": "lines",
        "dropped": ["f5", "f6", "f7", "f8", "f9"],
        "detail": out["truncated"]["detail"],
    }
    assert "requested individually" in out["truncated"]["detail"]


def test_the_declaration_itself_fits_inside_the_limit():
    # The `truncated` field grows with the list of names it carries, so a cap
    # measured before adding it is not a cap. Every entry count is checked, not
    # just the one this payload happens to need.
    for limit in range(300, 1200, 50):
        assert len(dumps_capped(_obj(12), limit)) <= limit


def test_the_largest_container_is_the_one_that_gives():
    obj = {"note": "n" * 100,
           "small": {"a": 1},
           "lines": {f"f{i}": "y" * 40 for i in range(8)}}
    out = json.loads(dumps_capped(obj, 500))
    assert out["truncated"]["container"] == "lines"
    assert out["small"] == {"a": 1}, "a container that was not the biggest is intact"


def test_a_list_container_reports_positions():
    obj = {"points": [{"v": i, "pad": "y" * 50} for i in range(10)]}
    out = json.loads(dumps_capped(obj, 400))
    assert out["truncated"]["container"] == "points"
    assert out["truncated"]["dropped"][0].startswith("[")
    assert len(out["points"]) + len(out["truncated"]["dropped"]) == 10


def test_a_shell_too_big_to_trim_says_it_was_cut_by_bytes():
    # The terminal case still has to be visible rather than look whole.
    out = dumps_capped({"note": "z" * 400, "lines": {"a": {"v": 1}}}, 120)
    assert len(out) <= 120
    assert "byte_cut" in out or out.startswith("{")


def test_a_bare_list_is_cut_by_bytes_because_it_cannot_carry_the_field():
    assert dumps_capped([1, 2, 3, 4, 5], 6) == "[1, 2,"
