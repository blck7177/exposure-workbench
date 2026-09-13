"""V33 Phase 1 — the language runs what it types (live, on the gold snapshot).

The static side (signatures, typecheck, the facts a node's declared dates
reach) is tests/test_v33_typecheck.py. This file executes: a program with a type
problem does not run; a number is an operand with an id; filter is a primitive;
the panel is a table; a service refusing a value is that node's refusal; `at`
on a flow is refused rather than dropped (the V32 line-405 mechanism in its
date form — the Phase 1 probe found revenue coming back as of 2026-03-31 for
at="2025-13-45").

Read-only: every program runs inside a transaction that is rolled back.
"""
from __future__ import annotations

import os

import pytest

from exposure_workbench.services import program_service as ps

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_gold")

BOOK = [["r", {"fn": "run", "portfolio": "port_001"}],
        ["w", {"fn": "column", "run": "$r", "table": "issuer_exposures", "col": "weight"}],
        ["m", {"fn": "max", "of": "$w"}]]


async def _run(prog: dict) -> dict:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.auth.context import current_user_ctx
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set("user_3IDBMeAxLTbecvGorzwV7FCeroR")
    try:
        async with mk() as db:
            out = await ps.run(db, prog, invoked_by="test")
            await db.rollback()
            return out
    finally:
        await engine.dispose()


def _vals(node: dict) -> dict:
    return {k: v["value"] for k, v in node["entries"].items()}


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_program_with_a_type_problem_does_not_run():
    out = await _run({"let": [["x", {"fn": "fundamentals", "ticker": "MSFT", "metric": "revenue", "at": "prev"}]]})
    assert out["error"] == "type_errors"
    assert "program_id" not in out and "nodes" not in out
    (p,) = out["problems"]
    assert p["at"] == "x" and p["arg"] == "at" and p["expected"] == ["date"]
    assert "run(which='prev')" in p["fix"]


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_number_is_an_operand_and_the_result_names_it():
    out = await _run({"let": BOOK + [["room", {"fn": "sub", "a": "$m", "b": 0.08}],
                                     ["dbl", {"fn": "mul", "a": "$m", "b": 2}]]})
    assert out["refused"] == []
    m = out["nodes"]["m"]["value"]
    room, dbl = out["nodes"]["room"], out["nodes"]["dbl"]
    assert room["kind"] == "scalar" and room["value"] == pytest.approx(m - 0.08)
    assert room["measure"] == "subtract(max[10](issuer_exposures.weight), 0.08)" and room["unit"] == "RATIO"
    assert dbl["value"] == pytest.approx(2 * m)
    assert dbl["measure"] == "scale(max[10](issuer_exposures.weight), 2)"


@pytest.mark.live
@pytest.mark.asyncio
async def test_filter_keeps_the_entries_that_satisfy_and_an_empty_result_is_an_absence_that_lists_them():
    out = await _run({"let": BOOK + [["over", {"fn": "filter", "of": "$w", "op": ">", "level": 0.08}],
                                     ["none", {"fn": "filter", "of": "$w", "op": ">", "level": 10}]]})
    w = _vals(out["nodes"]["w"])
    over = out["nodes"]["over"]
    assert over["kind"] == "vector" and over["measure"] == "issuer_exposures.weight"
    assert _vals(over) == {k: v for k, v in w.items() if v > 0.08}
    assert 0 < len(over["entries"]) < len(w)
    assert out["refused"] == ["none"]
    none = out["nodes"]["none"]
    assert none["kind"] == "absence" and none["refusal"]["error"] == "no_entry_satisfies"
    assert len(none["refusal"]["available"]) == len(w)


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_vector_takes_a_number_as_an_entry():
    out = await _run({"let": BOOK + [["v", {"fn": "vector", "entries": {"a": "$m", "b": 0.5}}]]})
    assert out["refused"] == []
    v = out["nodes"]["v"]
    assert v["kind"] == "vector"
    assert _vals(v) == {"a": out["nodes"]["m"]["value"], "b": 0.5}


@pytest.mark.live
@pytest.mark.asyncio
async def test_the_issuer_panel_is_a_table_of_figures_with_ids():
    out = await _run({"let": [["p", {"fn": "method", "name": "issuer.panel", "subject": "MSFT"}]]})
    assert out["refused"] == []
    p = out["nodes"]["p"]
    assert p["kind"] == "table" and len(p["entries"]) >= 20
    assert "capex_intensity" in p["entries"] and "accruals_ratio" in p["entries"]
    assert all(e["fact"].startswith("f_") for e in p["entries"].values())


@pytest.mark.live
@pytest.mark.asyncio
async def test_at_on_a_flow_is_refused_with_the_window_to_ask_for_instead():
    out = await _run({"let": [["x", {"fn": "fundamentals", "ticker": "MSFT", "metric": "revenue", "at": "2025-06-30"}]]})
    assert out["refused"] == ["x"]
    r = out["nodes"]["x"]["refusal"]
    assert r["error"] == "invalid_params" and "flow" in r["detail"] and "months" in r["detail"]


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_date_the_service_cannot_read_is_that_nodes_refusal_not_the_programs_crash():
    out = await _run({"let": [["x", {"fn": "fundamentals", "ticker": "MSFT", "metric": "total_assets", "at": "2025-13-45"}],
                              ["ok", {"fn": "fundamentals", "ticker": "MSFT", "metric": "total_assets"}]]})
    assert out["refused"] == ["x"]
    assert out["nodes"]["x"]["refusal"]["error"] == "invalid_params"
    assert out["nodes"]["ok"]["kind"] == "scalar" and out["nodes"]["ok"]["value"] > 0


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_methods_name_at_the_filed_line_door_is_refused_as_the_writers_error_not_absent_data():
    """V33C Q04: `fundamentals(metric='gross_margin')` came back metric_not_filed and
    the analyst told the reader Lilly has no filed facts under gross margin."""
    out = await _run({"let": [["gm", {"fn": "fundamentals", "ticker": "LLY", "metric": "gross_margin"}]]})
    assert out["error"] == "type_errors" and out["problems"][0]["reason"] == "metric_is_a_method"


@pytest.mark.live
@pytest.mark.asyncio
async def test_invariant_B_every_vector_entry_carries_its_place_in_the_ordering():
    """A vector is one measure in one unit per label, so its order is settled the
    moment it is built. A superlative in prose is then always a lookup."""
    out = await _run({"let": [["ci", {"fn": "method", "name": "capex_intensity", "subject": ["MSFT", "GOOGL", "AMZN"]}],
                              ["w", {"fn": "column", "run": {"fn": "run", "portfolio": "port_001"},
                                     "table": "issuer_exposures", "col": "weight"}]]})
    assert out["refused"] == []
    for node in ("ci", "w"):
        facts = [f for f in out["_facts"] if (f["params"] or {}).get("node") == node]
        assert facts, node
        places = {f["params"]["place"]: float(f["value"]) for f in facts}
        assert sorted(places) == list(range(1, len(facts) + 1)), node
        assert all(f["params"]["of"] == len(facts) for f in facts), node
        assert [places[k] for k in sorted(places)] == sorted(places.values(), reverse=True), node
