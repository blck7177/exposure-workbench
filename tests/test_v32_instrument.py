"""V32 — the instrument reads a declaration, not a spelling.

`battery_counters.superlative_without_rank` decided whether a turn had computed
an ordering by searching the serialised program for '"fn": "rank"', and
`conversation_battery` stored `args` to 300 characters. That cap was sized for
the per-call protocol — `compute`'s longest argument list across both V26 rounds
is 298 characters — and V30 replaced it with one program per question, of which
179 of 202 run past 300. A rank node comes after the vector it orders, so the cut
removed exactly the thing the counter read: it reported 37 of 52 on V26_C3 where
the full arguments, never truncated at the write, say 14.

Two changes, tested here. The producer declares what it built, and the counter
asks the producer. (scripts/battery_counters.py left with the retired batteries
and its tests went with it; what remains is the producer's declaration and the
battery reader's width.)
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from exposure_workbench.tools.registry import _declared_nodes, _summarize

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the producer declares ────────────────────────────────────────────────────

def test_a_run_result_records_the_kind_of_every_node_it_built():
    out = _summarize({"program_id": "calc_1", "returns": ["r"], "settled": 3,
                      "nodes": {"w": {"kind": "vector"}, "r": {"kind": "ranking"},
                                "t": {"kind": "scalar"}}})
    assert "| nodes: w=vector, r=ranking, t=scalar" in out


def test_the_summary_still_opens_with_keys_because_classify_reads_the_front():
    """`classify()` matches '^error: ', 'not attempted', 'invalid arguments';
    `is_pool_empty` reads the payload. The declaration is appended, never
    prepended."""
    assert _summarize({"nodes": {"w": {"kind": "vector"}}, "settled": 1}).startswith("keys: ")
    assert _summarize({"error": "invalid_params"}) == "error: invalid_params"


def test_a_result_that_declares_nothing_is_summarised_as_before():
    assert _summarize({"rows": [1, 2], "as_of": "2026-09-04"}) == "keys: rows, as_of"
    assert _declared_nodes({"nodes": "not a mapping"}) == ""
    assert _declared_nodes({"nodes": {"_scratch": {"kind": "scalar"}}}) == ""


# ── the cap that broke three counters does not come back ─────────────────────

def test_the_battery_reads_arguments_wide_enough_for_one_program_per_question():
    """179 of 202 `run` calls in V26_C3 exceed 300 characters and the longest is
    2764; the longest `respond` payload is 4075, and the mark counter json.loads
    it — it raised on 273 of 280 turns under the old cap and fell back, silently,
    to the rendered text its own comment says not to read."""
    src = (ROOT / "scripts" / "conversation_battery.py").read_text()
    assert "left(args::text, 300)" not in src
    from tests.test_v32_instrument import _script
    query = str(_script("conversation_battery")._STEPS).lower()
    assert "left(" not in query and "substring(" not in query
    assert "args::text as args" in query and "result_summary as result" in query
