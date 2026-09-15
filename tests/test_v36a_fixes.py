"""V36.1 — what round A's reading of the communication changed.

Round A (docs/spikes/v36/COMMUNICATION_V36A.md) counted 326 round trips and
143 that carried nothing forward. The largest classes were tool-layer: a
refusal whose reason was lost between two tool components, a delegation verb
counted as evidence, an object one analyst built that no other could name, a
level compared in the wrong unit. Each test here is one of those, as a shape
that cannot recur rather than a number that got smaller.
"""

from __future__ import annotations

from exposure_workbench.services import digest as dg
from exposure_workbench.tools import registry as rg
from exposure_workbench.tools.definitions import build_read_registry


# ── T2 · the refusal's reason survives the trip to the analyst ───────────────

def _read_filings_tool():
    reg = build_read_registry()
    return reg.get("read_filings") if hasattr(reg, "get") else reg._tools["read_filings"]


def _registry_refusal(args: dict) -> dict:
    """What the registry hands back for these arguments, shaped exactly as
    tools/registry._invoke shapes it (the schema check, then the shapes check)."""
    tool = _read_filings_tool()
    problems = rg.validate_args(tool.json_schema, args)
    if not problems and tool.shapes is not None:
        given = [f for f in tool.shapes.fields if args.get(f) is not None]
        if len(given) > 1:
            problems = [{"field": f, "problem": tool.shapes.detail, "value": None} for f in given]
    assert problems, "the arguments must be the ones the registry refuses"
    return {"error": "invalid_arguments", "problems": problems}


def test_a_query_and_item_together_are_refused_with_the_reason_the_analyst_can_act_on():
    """Q02's analyst sent {query, item} six times in a row and read
    "invalid_arguments — ; " each time: the registry wrote the reason under
    `problem`, the digest read `fix`/`detail`/`reason`."""
    raw = _registry_refusal({"ticker": "MSFT", "item": "7", "query": "commercial paper", "k": 10, "form_type": "10-K"})
    d = dg.render(raw, mint=dg.Minter(), call={"tool": "read_filings", "args": {"ticker": "MSFT", "item": "7", "query": "commercial paper"}})
    text = d["boundaries"][0]["text"]
    assert text.startswith("read_filings(ticker='MSFT', item='7', query='commercial paper'): invalid_arguments — ")
    assert "query: query searches the passages and item reads one Item whole: give one of them, not both" in text
    assert "; item: " in text


def test_every_problem_shape_the_desk_writes_renders_with_its_words():
    assert dg._problem_text({"field": "k", "problem": "21 is more than the maximum of 20", "value": 21}) == "k: 21 is more than the maximum of 20"
    assert dg._problem_text({"reason": "type_mismatch", "fix": "op is one of > >= < <= == !=", "arg": "op"}) == "op: op is one of > >= < <= == !="
    assert dg._problem_text({"reason": "unknown_name"}) == "unknown_name"


# ── T3 · the rule is in the schema the model reads, not only in the wrapper ──

def test_read_filings_tells_the_model_it_takes_exactly_one_of_query_or_item():
    tool = _read_filings_tool()
    assert "EXACTLY ONE of query or item" in tool.description
    assert tool.shapes is not None and set(tool.shapes.fields) == {"query", "item"}


# ── T5 · a book one analyst built has a name another can read ────────────────

def test_a_built_book_declares_the_id_another_program_reads():
    """Q13: the after-book (sell half NVDA, buy TLT) lived in one analyst's
    program; the lead re-delegated "after the same trade" to two more analysts,
    who could only name port_001 and re-ran the base book under that label.
    The executor already gives a scenario a calc_ ref that `_run_ref` accepts;
    now the note says so, and the digest lists it under `made`."""
    from exposure_workbench.services import program_service as ps
    after = ps.Node("after", ps.TABLE, {"fn": "sell"})
    after.ref = "calc_after1"
    assert ps._note_of(after)["ref"] == "calc_after1"
    base = ps.Node("base", ps.RUN, {"fn": "run"})
    base.ref = "run_1"
    assert "ref" not in ps._note_of(base)            # a run is not something the analyst made
    d = dg.render({"program_id": "calc_p", "returns": ["after"], "settled": 1, "refused": [],
                   "nodes": {"base": {"kind": "run", "run": "run_1"}, "after": {"kind": "table", "ref": "calc_after1"},
                             "_scratch": {"kind": "table", "ref": "calc_x"}},
                   "facts": {"columns": [], "rows": []}}, mint=dg.Minter())
    assert d["made"] == [{"node": "after", "id": "calc_after1", "kind": "scenario"}]
