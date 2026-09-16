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
import os
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


# ── V37/T4: one verb, three kinds of id ───────────────────────────────────────

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_gold")


def test_the_typecheck_accepts_a_book_a_run_and_a_scenario_where_the_book_goes():
    """Q13's first program was run(portfolio="run_e2945c5ebd5a") — eight absences
    downstream and a completion spent on each. V36.1 answered with a static type
    refusal naming the rewriting; round B's analysts wrote it eleven more times,
    the hypothetical-trades analyst on both of its two attempts, in a turn where
    that domain filed nothing at all.

    The lead names subjects out of the BRIEFING and out of another analyst's
    `made`, so run_ and calc_ ids are what it hands down. A message cannot make
    two vocabularies one; the verb reads whichever kind it is given, which is
    what `_run_ref` has always done everywhere else in the language."""
    from exposure_workbench.services import program_service as ps
    for rid in ("port_001", "run_e2945c5ebd5a", "calc_7c1f2a0b9d4e"):
        problems = ps.typecheck({"let": [["base", {"fn": "run", "portfolio": rid}],
                                         ["w", {"fn": "column", "run": "$base", "table": "issuer_exposures",
                                                "col": "weight"}]], "return": ["w"]})
        assert not [p for p in problems if p.get("at") == "base"], rid


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_run_and_a_scenario_id_read_as_that_one_run():
    """Measured, because a typecheck that accepts an id it cannot execute is
    worse than the refusal it replaced. All three settle, and `column` and `pick`
    read all three."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.services import program_service as ps
    from sqlalchemy import text as sql

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    try:
        async with mk() as db:
            run_id = (await db.execute(sql(
                "select id from exposure_runs where status = 'completed' order by as_of_date desc limit 1"))).scalar()
            calc_id = (await db.execute(sql(
                "select id from calc_ledger where operation = 'book.scenario' order by created_at desc limit 1"))).scalar()
            assert run_id, "the fixture has a completed run"
            for rid in [pid for pid in ("port_001", run_id, calc_id) if pid]:
                out = await ps.run(db, {"let": [
                    ["book", {"fn": "run", "portfolio": rid}],
                    ["w", {"fn": "column", "run": "$book", "table": "issuer_exposures", "col": "weight"}],
                    ["mv", {"fn": "pick", "of": "$book", "key": "exposure_metrics.portfolio_market_value"}]],
                    "return": ["w", "mv"]}, invoked_by="test_v37_t4")
                kinds = {n: d.get("kind") for n, d in (out.get("nodes") or {}).items()}
                assert not out.get("refused"), (rid, out.get("refused"))
                assert kinds["w"] == "vector" and kinds["mv"] == "scalar", (rid, kinds)
            # and `which` on an id that is already one run says so rather than guessing
            out = await ps.run(db, {"let": [["b", {"fn": "run", "portfolio": run_id, "which": "prev"}]]},
                               invoked_by="test_v37_t4")
            assert out.get("refused") == ["b"]
    finally:
        await engine.dispose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_a_quotient_the_registry_defines_comes_back_under_its_own_name():
    """V37/T7, measured: the program's quotient and the registry's method are one
    measure and one value, so a ledger cannot hold the same reading under two
    names with only one of them carrying a place."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.services import program_service as ps

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    try:
        async with mk() as db:
            out = await ps.run(db, {"let": [
                ["cx", {"fn": "fundamentals", "ticker": "MSFT", "metric": "capex", "months": 12}],
                ["rv", {"fn": "fundamentals", "ticker": "MSFT", "metric": "revenue", "months": 12}],
                ["divided", {"fn": "div", "a": "$cx", "b": "$rv"}],
                ["method", {"fn": "method", "name": "capex_intensity", "subject": "MSFT"}],
                ["ocf", {"fn": "fundamentals", "ticker": "MSFT", "metric": "operating_cash_flow", "months": 12}],
                ["ni", {"fn": "fundamentals", "ticker": "MSFT", "metric": "net_income", "months": 12}],
                ["conversion", {"fn": "div", "a": "$ocf", "b": "$ni"}]],
                "return": ["divided", "method", "conversion"]}, invoked_by="test_v37_t7")
            nodes = out["nodes"]
            assert nodes["divided"]["measure"] == nodes["method"]["measure"] == "capex_intensity"
            assert nodes["divided"]["value"] == nodes["method"]["value"]
            # and a quotient the registry does not define keeps its lineage name
            assert nodes["conversion"]["measure"].startswith("divide(")
    finally:
        await engine.dispose()
