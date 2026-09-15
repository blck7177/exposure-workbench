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


# ── T6 · a level in the wrong unit is told what the entries are ──────────────

async def _filter(of, op, level):
    from exposure_workbench.services import program_service as ps
    return await ps._p_filter(None, ps.Node("out", ps.ABSENCE, {}), of, op, level)


def _weights():
    from exposure_workbench.services import program_service as ps
    return ps.Node("issuer_weights", ps.VECTOR, {}, unit="RATIO", measure="issuer_exposures.weight",
                   entries=[("MSFT", "f_1", 0.1604, "RATIO"), ("AAPL", "f_2", 0.152, "RATIO"),
                            ("NVDA", "f_3", 0.0406, "RATIO")])


async def test_a_filter_at_8_over_fractions_is_told_that_a_ratio_is_a_fraction():
    """Q11 wrote filter(weights, >, 8) four times over weights that run 0.04 to
    0.16 and read the silence as the digest holding the answer back."""
    from exposure_workbench.services import program_service as ps
    out = await _filter(_weights(), ">", 8)
    assert out.kind == ps.ABSENCE and out.refusal["error"] == "no_entry_satisfies"
    assert "its entries run 0.0406 to 0.1604" in out.refusal["detail"]
    assert "a RATIO is a fraction here: 8% is 0.08" in out.refusal["detail"]
    ok = await _filter(_weights(), ">", 0.08)
    assert ok.kind == ps.VECTOR and [e[0] for e in ok.entries] == ["MSFT", "AAPL"]


async def test_a_level_that_could_be_satisfied_gets_the_range_and_no_lecture():
    out = await _filter(_weights(), ">", 0.5)
    assert "its entries run 0.0406 to 0.1604" in out.refusal["detail"] and "8% is 0.08" not in out.refusal["detail"]


def test_the_limits_procedure_says_a_level_is_a_fraction():
    from exposure_workbench.analytics import skill
    assert "a weight is a fraction: 8% is 0.08" in " ".join(skill.PROCEDURES["book_limits_and_triggers"].desk)


# ── T7 · a run id where the book goes is a type problem, before anything runs ──

def test_a_run_id_given_as_the_portfolio_is_refused_by_the_typecheck_with_the_fix():
    """Q13's first program: run(portfolio="run_e2945c5ebd5a") — eight absences
    downstream and a completion spent on each. The wrong kind of id is a type
    problem, and a type problem is reported once, with the way to say it."""
    from exposure_workbench.services import program_service as ps
    problems = ps.typecheck({"let": [["base", {"fn": "run", "portfolio": "run_e2945c5ebd5a"}],
                                     ["w", {"fn": "column", "run": "$base", "table": "issuer_exposures", "col": "weight"}]],
                             "return": ["w"]})
    (p,) = [p for p in problems if p.get("at") == "base"]
    assert p["arg"] == "portfolio" and p["got"] == "run_e2945c5ebd5a"
    assert "which: 'run_e2945c5ebd5a'" in p["fix"] and "column(run='run_e2945c5ebd5a'" in p["fix"]
    assert not [p for p in ps.typecheck({"let": [["base", {"fn": "run", "portfolio": "port_001"}]]}) if p.get("at") == "base"]
