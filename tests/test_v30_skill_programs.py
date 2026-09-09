"""V30 Phase C — the skill's programs are executable knowledge.

Offline: every domain has programs, every program parses, no program names a
tool or writes a measure as a binding name. Live (exposure_gold): every
program executes with the fixture's ids substituted and settles, or refuses
only for a data absence the fixture is known to have.
"""
from __future__ import annotations

import json
import os

import pytest

from exposure_workbench.analytics import skill
from exposure_workbench.services import program_service as ps

SUBST = {"<port>": "port_001", "<T>": "MSFT", "<T1>": "AAPL", "<T2>": "MSFT"}
KNOWN_DATA_REFUSALS = {"incomplete_cover", "input_unavailable", "metric_not_filed", "not_reported",
                       "not_reported_at_this_date", "no_prior_run", "insufficient_history", "series_not_derivable",
                       "self_regression", "depends_on_refused", "too_few_operands", "not_alone",
                       "no_sector"}   # companies.sector holds a SIC code for admitted names (V21 gold, KO): a data defect, recorded


def test_every_domain_carries_programs_that_parse():
    for p in skill.PROCEDURES.values():
        assert p.programs, p.name
        for title, prog in p.programs:
            assert title and isinstance(ps.parse(json.loads(prog)), ps.Program), (p.name, title)


def test_programs_name_no_tool_and_no_measure_as_a_binding():
    for p in skill.PROCEDURES.values():
        for _t, prog in p.programs:
            assert "read_book" not in prog and "compute(" not in prog and "as_quantity" not in prog
            names = [b[0] for b in json.loads(prog)["let"]]
            assert all(n not in skill.METHODS for n in names), (p.name, names)


def test_match_domains_is_lexical_and_bounded():
    got = skill.match_domains("if I had to get out of this book in a hurry, which positions hurt me? liquidity, not price")
    assert got and got[0].name == "book_liquidity"
    assert len(skill.match_domains("what share do the top five names carry", n=2)) <= 2
    assert skill.match_domains("") == []


URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_gold")


@pytest.mark.live
@pytest.mark.asyncio
async def test_every_program_executes_on_the_fixture():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.services import run_reads_service
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set("user_3IDBMeAxLTbecvGorzwV7FCeroR")
    failures = []
    try:
        async with mk() as db:
            fresh = await run_reads_service.get_run_freshness(db, "port_001")
            subst = {**SUBST, "<run>": fresh["latest_completed_run"]}
        for p in skill.PROCEDURES.values():
            for title, prog in p.programs:
                text = prog
                for k, v in subst.items():
                    text = text.replace(k, v)
                # one session per program: the RLS user id is transaction-local, and a
                # rollback after the first program left the next one seeing no portfolio
                async with mk() as db:
                    out = await ps.run(db, json.loads(text), invoked_by="test")
                    await db.rollback()
                    if out.get("error"):
                        failures.append((p.name, title, out["error"]))
                        continue
                    for name in out["refused"]:
                        err = (out["nodes"][name].get("refusal") or {}).get("error")
                        root = ((out["nodes"][name].get("refusal") or {}).get("root") or {}).get("error")
                        if err not in KNOWN_DATA_REFUSALS or (root and root not in KNOWN_DATA_REFUSALS):
                            failures.append((p.name, title, name, err, root))
    finally:
        await engine.dispose()
    assert failures == [], failures
