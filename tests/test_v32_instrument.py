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
asks the producer. Where a round predates the declaration, the counter says it
cannot see rather than guessing.
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


# ── the counter asks the producer ────────────────────────────────────────────

def _turn(answer: str, steps: list[dict]) -> dict:
    return [{"tag": "T", "session_id": "s", "turns": [{"turn": 1, "answer": answer, "steps": steps}]}]


def _count(tmp_path, answer, steps) -> dict:
    import json
    p = tmp_path / "round.json"
    p.write_text(json.dumps(_turn(answer, steps)))
    return _script("battery_counters").tally([str(p)])


def _run_step(result: str) -> dict:
    return {"step_type": "tool_call", "tool_name": "run", "status": "completed",
            "result": result, "args": '{"let": [], "return": "r"}'}


A = "MSFT is the largest holding at 16.1%, then AMZN at 14.2%."


def test_a_declared_ranking_node_is_a_computed_ordering(tmp_path):
    c = _count(tmp_path, A, [_run_step("keys: nodes, settled | nodes: w=vector, r=ranking")])
    assert c["superlative_claims"] == 1
    assert c["superlative_without_rank"] == 0 and c["superlative_rank_undeclared"] == 0


def test_a_declaration_without_a_ranking_node_is_an_uncomputed_ordering(tmp_path):
    c = _count(tmp_path, A, [_run_step("keys: nodes, settled | nodes: w=vector, t=scalar")])
    assert c["superlative_without_rank"] == 1 and c["superlative_rank_undeclared"] == 0


def test_a_run_step_with_no_declaration_is_undeclared_and_never_guessed(tmp_path):
    """The V26_C3 shape: a round recorded before the producer declared. The
    program text is NOT consulted, even when it plainly holds a rank node —
    consulting it is what reported 37 where the answer is 14."""
    step = _run_step("keys: program_id, returns, nodes, settled")
    step["args"] = '{"let": [{"fn": "rank", "of": "$w"}], "return": "r"}'
    c = _count(tmp_path, A, [step])
    assert c["superlative_rank_undeclared"] == 1 and c["superlative_without_rank"] == 0


def test_one_compute_call_is_its_own_declaration(tmp_path):
    """The per-call protocol: one call is one op, and its arguments are bounded
    by the protocol — 298 characters at their longest in either V26 round — so
    nothing about this reading was ever truncated."""
    ranked = {"step_type": "tool_call", "tool_name": "compute", "status": "completed",
              "result": "keys: facts", "args": '{"op": "rank", "operands": ["f_a", "f_b"]}'}
    assert _count(tmp_path, A, [ranked])["superlative_without_rank"] == 0
    plain = {**ranked, "args": '{"op": "subtract", "operands": ["f_a", "f_b"]}'}
    assert _count(tmp_path, A, [plain])["superlative_without_rank"] == 1


def test_a_refused_run_does_not_count_as_a_computed_ordering(tmp_path):
    step = _run_step("error: invalid_params")
    step["status"] = "error"
    c = _count(tmp_path, A, [step])
    assert c["superlative_without_rank"] == 1


# ── the cap that broke three counters does not come back ─────────────────────

def test_the_battery_reads_arguments_wide_enough_for_one_program_per_question():
    """179 of 202 `run` calls in V26_C3 exceed 300 characters and the longest is
    2764; the longest `respond` payload is 4075, and the mark counter json.loads
    it — it raised on 273 of 280 turns under the old cap and fell back, silently,
    to the rendered text its own comment says not to read."""
    src = (ROOT / "scripts" / "conversation_battery.py").read_text()
    assert "left(args::text, 300)" not in src
    caps = re.search(r"_ARGS_CAP, _RESULT_CAP = (\d+), (\d+)", src)
    assert caps and int(caps.group(1)) >= 4000 and int(caps.group(2)) >= 1000


def test_the_run_adapter_carries_the_kind_declaration_into_the_summary():
    """The summary is built from the ADAPTED result, not the executor's return.
    `run_program` lifts `_facts` out and passes the rest through, so the typing
    the executor did at each node boundary reaches the trace. Pinned here because
    an adapter that rewrote or dropped `nodes` would blind the counter again
    without failing anything else — which is the shape of the defect this whole
    change exists to end."""
    from exposure_workbench.services import fact_adapters as fa

    raw = {"program_id": "calc_1", "returns": ["r"], "settled": 2, "refused": [],
           "nodes": {"w": {"kind": "vector"}, "r": {"kind": "ranking"}}, "_facts": []}
    _, note = fa.ADAPTERS["run"]({}, raw)
    assert "| nodes: w=vector, r=ranking" in _summarize(note)
