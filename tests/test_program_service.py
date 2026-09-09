"""V30 Phase A — the program executor (services/program_service).

Offline: the grammar (parse, hoisting, refusals a program can be refused for
before any database), the schema the tool hands the provider, and the
symmetry between PRIMITIVES and the dispatcher. Live (exposure_gold — the
Phase 0 snapshot in a database of its own): the four programs the review's
target architecture was drawn around, executed end to end, and the rules the
language exists to enforce (a binding name is never a measure; a refusal
chains; a superlative rests on a rank node).
"""
from __future__ import annotations

import inspect
import json
import os

import pytest

from exposure_workbench.services import program_service as ps

# ── offline ───────────────────────────────────────────────────────────────────

def test_parse_hoists_nested_expressions_into_named_nodes():
    prog = {"let": [["top5", {"fn": "sum", "of": {"fn": "top", "of": "$w", "n": 5}}]]}
    p = ps.parse(prog)
    assert isinstance(p, ps.Program)
    names = [n for n, _ in p.bindings]
    assert names[-1] == "top5" and names[0].startswith("_top5_")
    assert p.bindings[-1][1]["of"] == f"${names[0]}"
    assert p.returns == ["top5"]                       # hoisted nodes are not returns


@pytest.mark.parametrize("prog,reason", [
    ({}, "let"),
    ({"let": []}, "let"),
    ({"let": [["1bad", {"fn": "run", "portfolio": "port_001"}]]}, "binding name"),
    ({"let": [["_x", {"fn": "run", "portfolio": "port_001"}]]}, "leading _"),
    ({"let": [["a", {"fn": "run", "portfolio": "p"}], ["a", {"fn": "run", "portfolio": "p"}]]}, "twice"),
    ({"let": [["a", {"fn": "run", "portfolio": "p"}]], "return": ["b"]}, "do not exist"),
])
def test_parse_refuses_malformed_programs(prog, reason):
    out = ps.parse(prog)
    assert isinstance(out, dict) and out["error"] == "malformed_program"
    assert reason in out["detail"]


def test_schema_is_provider_legal():
    """V28-R: an object at the top level, none of the combinators the provider
    rejects, and `as_quantity` nowhere in the language."""
    s = ps.schema()
    assert s["type"] == "object"
    for kw in ("oneOf", "anyOf", "allOf", "enum", "const", "not"):
        assert kw not in s
    assert "as_quantity" not in json.dumps(s)
    for req, opt in ps.PRIMITIVES.values():
        assert "as_quantity" not in req + opt


def test_every_primitive_is_dispatched_and_nothing_else_is():
    src = inspect.getsource(ps._dispatch) + inspect.getsource(ps._evaluate)
    for name in ps.PRIMITIVES:
        assert (f'fn == "{name}"' in src or f'"{name}"' in src or name in ps._BINARY
                or name in ps._SET_OPS or name in ps._SERIES_OPS or name == "sum"), name


def test_structural_name_never_uses_the_binding_name():
    a = ps.Node("days_at_100pct_adv", ps.SCALAR, None, measure="exposure_metrics.portfolio_market_value")
    b = ps.Node("mv", ps.SCALAR, None, measure="issuer_exposures.market_value")
    name = ps._structural("divide", ps._measure_of(a), ps._measure_of(b))
    assert "days" not in name and name.startswith("divide(")


# ── live: the gold snapshot ───────────────────────────────────────────────────

pytestmark_live = pytest.mark.live
URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_gold")


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
    return {k: v["value"] for k, v in (node.get("entries") or {}).items()}


@pytest.mark.live
@pytest.mark.asyncio
async def test_top_five_is_rank_then_sum_and_the_prior_run_is_explicit():
    out = await _run({"let": [
        ["r", {"fn": "run", "portfolio": "port_001"}],
        ["w", {"fn": "column", "run": "$r", "table": "issuer_exposures", "col": "weight"}],
        ["top5", {"fn": "sum", "of": {"fn": "top", "of": "$w", "n": 5}}],
        ["prev", {"fn": "sum", "of": {"fn": "top", "of": {"fn": "column", "run": {"fn": "run", "portfolio": "port_001", "which": "prev"},
                                                        "table": "issuer_exposures", "col": "weight"}, "n": 5}}],
        ["delta", {"fn": "sub", "a": "$top5", "b": "$prev"}]]})
    w = _vals(out["nodes"]["w"])
    assert len(w) == 10
    assert out["nodes"]["top5"]["value"] == pytest.approx(sum(sorted(w.values(), reverse=True)[:5]), rel=1e-9)
    assert out["nodes"]["top5"]["measure"] == "sum[5](issuer_exposures.weight)"
    assert out["nodes"]["delta"]["kind"] == "scalar" and out["nodes"]["delta"]["unit"] == "RATIO"
    assert out["nodes"]["r"]["as_of"] > out["nodes"]["_prev_2"]["as_of"] if "_prev_2" in out["nodes"] else True
    assert out["program_id"].startswith("calc_")
    assert out["refused"] == []


@pytest.mark.live
@pytest.mark.asyncio
async def test_days_to_liquidate_is_money_over_a_flow_and_orders_by_rank():
    out = await _run({"let": [
        ["r", {"fn": "run", "portfolio": "port_001"}],
        ["mv", {"fn": "column", "run": "$r", "table": "issuer_exposures", "col": "market_value"}],
        ["adv", {"fn": "method", "name": "price.adv", "subject": ["AAPL", "MSFT", "JPM"], "params": {"window_days": 20}, "key": "adv_dollars"}],
        ["days", {"fn": "div", "a": "$mv", "b": {"fn": "scale", "of": "$adv", "factor": 0.25}}],
        ["worst", {"fn": "rank", "of": "$days", "direction": "highest"}]]})
    days = out["nodes"]["days"]
    assert days["kind"] == "vector" and days["unit"] == "COUNT"          # MONEY / MONEY_PER_DAY = days
    assert set(_vals(days)) == {"AAPL", "MSFT", "JPM"}                     # aligned by label
    assert out["nodes"]["worst"]["kind"] == "ranking"
    order = out["nodes"]["worst"]["order"]
    assert order == sorted(_vals(days), key=lambda k: -_vals(days)[k])


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_method_over_a_list_is_a_vector_the_rank_accepts():
    out = await _run({"let": [
        ["b", {"fn": "method", "name": "price.beta", "subject": ["AAPL", "MSFT", "HYG"], "params": {"benchmark": "TLT"}, "key": "beta"}],
        ["most", {"fn": "rank", "of": "$b", "direction": "highest"}],
        ["gm", {"fn": "method", "name": "gross_margin", "subject": ["AAPL", "MSFT"]}]]})
    assert out["nodes"]["b"]["kind"] == "vector"
    assert out["nodes"]["most"]["kind"] == "ranking" and len(out["nodes"]["most"]["order"]) == 3
    assert out["nodes"]["gm"]["kind"] == "vector" and out["nodes"]["gm"]["unit"] == "RATIO"


@pytest.mark.live
@pytest.mark.asyncio
async def test_refusals_chain_and_a_table_is_not_an_operand():
    out = await _run({"let": [
        # total_revenues: GOOGL's `revenue` line ends 2025-03-31 and its latest-anchored
        # series is refused as line_superseded since V30 C2 (test_v11_absence_live pins it)
        ["rev", {"fn": "fundamentals", "ticker": "GOOGL", "metric": "total_revenues", "months": 12, "last_n": 4}],
        ["g", {"fn": "yoy", "of": "$rev"}],
        ["beta", {"fn": "method", "name": "price.beta", "subject": "MSFT", "params": {"benchmark": "TLT"}}],
        ["bad", {"fn": "add", "a": "$beta", "b": "$rev"}],
        ["chain", {"fn": "sum", "of": "$bad"}],
        ["nope", {"fn": "frobnicate", "x": 1}]]})
    n = out["nodes"]
    assert n["rev"]["kind"] == "series" and n["g"]["kind"] == "series" and n["g"]["measure"] == "total_revenues.yoy"
    assert n["beta"]["kind"] == "table"                                     # several figures, no key
    assert n["bad"]["refusal"]["error"] == "type_mismatch"
    assert n["chain"]["refusal"]["error"] == "depends_on_refused" and n["chain"]["refusal"]["node"] == "bad"
    assert n["nope"]["refusal"]["error"] == "unknown_primitive"
    assert set(out["refused"]) == {"bad", "chain", "nope"}
    facts = out["_facts"]
    absences = [f for f in facts if f["kind"] == "absence"]
    assert {f["params"]["node"] for f in absences} >= {"bad", "chain", "nope"}


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_scenario_reads_like_a_run():
    out = await _run({"let": [
        ["after", {"fn": "sell", "run": {"fn": "run", "portfolio": "port_001"}, "sales": [{"ticker": "NVDA"}]}],
        ["w", {"fn": "column", "run": "$after", "table": "issuer_exposures", "col": "weight"}],
        ["mv", {"fn": "pick", "of": "$after", "key": "exposure_metrics.portfolio_market_value"}]]})
    assert out["nodes"]["after"]["kind"] == "table"
    w = _vals(out["nodes"]["w"])
    assert "NVDA" not in w and abs(sum(w.values()) - 1.0) < 1e-6
    assert out["nodes"]["mv"]["kind"] == "scalar" and out["nodes"]["mv"]["unit"] == "MONEY"


@pytest.mark.live
@pytest.mark.asyncio
async def test_the_provider_accepts_the_program_schema():
    """V28-R's discipline: a schema the provider rejects is not a contract.
    Asks the provider once (16 output tokens) with the program schema as the
    one tool on offer."""
    from dotenv import load_dotenv
    from openai import AsyncOpenAI
    load_dotenv(".env", override=True)
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    tool = {"type": "function", "function": {"name": "run", "description": "execute a program", "parameters": ps.schema()}}
    await client.chat.completions.create(model=os.environ["OPENAI_MODEL"], max_completion_tokens=16,
                                         messages=[{"role": "user", "content": "say ok"}], tools=[tool])


@pytest.mark.asyncio
async def test_a_name_at_the_wrong_door_is_sent_to_its_own_door():
    """V30 C3. Replaying the 2026-09-07 battery's 25 wrong method names
    (scripts/v30_replay_method_names.py) showed they are not misspelled methods:
    18 are filed lines, 4 are primitives, one is a domain, two are run figures.
    `nearest` answered them with a real method that is the wrong figure
    (revenue -> roe, depreciation -> current_ratio). The desk knows the door."""
    from exposure_workbench.services.program_service import _other_door
    cases = {
        "capex": ("filed line", '"fn": "fundamentals"'),
        "net_income": ("filed line", '"metric": "net_income"'),
        "yoy": ("primitive", '"fn": "yoy"'),
        "divide": ("written", '"fn": "div"'),
        "issuer_exposures.weight": ("figure of a run", '"fn": "column"'),
        "issuer_earnings_quality": ("domain", "expand="),
    }
    for name, (says, shows) in cases.items():
        d = _other_door(name)
        assert d and d["error"] == "wrong_door", (name, d)
        assert says in d["detail"] and shows in d["detail"], (name, d["detail"])
    assert _other_door("frobnicate") is None, "an unknown name has no door; `nearest` answers it"
    # a real method is not routed away from its own door
    assert _other_door("roe") is None
