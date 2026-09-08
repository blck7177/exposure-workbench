"""V27 — the catalogue as a directory (offline).

Three changes, each pinned: every listed entry says what it is and how it is
used; a domain opens on its own and the root does not expand; the two name
enums come from the one table, and an unknown name at any door is told which
door takes it.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import skill
from exposure_workbench.services import catalogue_service as cat
from exposure_workbench.services import concept_mapping
from exposure_workbench.services import name_table as nt
from exposure_workbench.services import quantities as qn
from exposure_workbench.tools import definitions
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


# ── the table ────────────────────────────────────────────────────────────────

def test_every_name_the_model_can_write_is_in_the_table_under_one_kind():
    for m in skill.METHODS:
        assert nt.TABLE[m].kind.endswith(" method")
    for p in skill.PROCEDURES:
        assert nt.TABLE[p].kind == "domain"
    for n in concept_mapping.SUPPORTED_METRICS:
        assert nt.TABLE[n].kind == "filed line"
    for n in nt.PORTFOLIO_SECTIONS + nt.RUN_SECTIONS:
        assert nt.TABLE[n].kind == "section"
    assert nt.TABLE["alerts"].on == ("portfolio", "run")


def test_a_name_under_two_kinds_is_an_import_time_error(monkeypatch):
    monkeypatch.setattr(nt, "FILING_ITEMS", ("1A", "capex"))
    with pytest.raises(RuntimeError, match="capex"):
        nt._build()


def test_every_domains_reads_are_names_the_desk_can_read():
    for p in skill.PROCEDURES.values():
        assert set(p.reads) <= nt.READABLE, (p.name, set(p.reads) - nt.READABLE)
        assert set(p.methods) <= set(skill.METHODS)


def test_a_domain_naming_a_method_the_registry_lacks_cannot_be_constructed():
    p = skill.PROCEDURES["book_liquidity"]
    from dataclasses import replace
    with pytest.raises(ValueError, match="nonsense"):
        replace(p, methods=("nonsense",))


# ── the rows ─────────────────────────────────────────────────────────────────

def test_a_row_says_what_it_is_and_how_it_is_called_with_the_subject_it_was_listed_under():
    rows = cat._methods("portfolio", False, "port_001")["portfolio"]
    dd = next(r for r in rows if r["name"] == "book.drawdown_episodes")
    assert dd["is"] == "portfolio method"
    assert dd["call"] == "compute(method='book.drawdown_episodes', subject='port_001')"
    assert dd["params"] == ["span"]
    ex = next(r for r in rows if r["name"] == "book.explain_episode")
    assert ex["call"] == "compute(method='book.explain_episode', subject='port_001', params={'peak': '<YYYY-MM-DD>', 'trough': '<YYYY-MM-DD>'})"


def test_above_the_subject_level_the_call_carries_a_placeholder_not_a_choice():
    rows = cat._methods("run", False)["run"]
    assert all("subject='<run_…>'" in r["call"] for r in rows)
    ps = cat._procedures("portfolio", False)
    assert all(p["open"].startswith("describe('<port_…>', expand='") for p in ps)
    ps = cat._procedures("issuer", False, "MSFT")
    assert ps[0]["open"] == f"describe('MSFT', expand='{ps[0]['name']}')"
    assert {"is", "methods", "reads", "open", "question", "asked_as"} <= set(ps[0])


# ── the levels ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_root_does_not_expand_and_says_what_does():
    out = await cat.describe(None, None, "book")
    assert out["error"] == "expand_needs_a_subject"
    assert out["next"][0] == "describe('<port_…>')"


@pytest.mark.asyncio
async def test_a_domain_is_an_expand_value_of_its_own_subject_kind():
    assert set(skill.PROCEDURES) <= set(cat.EXPANDS)
    out = await cat.describe(None, "MSFT", "book_liquidity")
    assert out["error"] == "domain_not_for_subject"
    assert "issuer_earnings_quality" in out["domains"]
    out = await cat.describe(None, "port_001", "issuer_profitability")
    assert out["error"] == "domain_not_for_subject" and "book_liquidity" in out["domains"]


@pytest.mark.asyncio
async def test_an_opened_domain_lists_its_leaves_with_their_calls(monkeypatch):
    async def fresh(_db, pid):
        return {"latest_completed_run": "run_abc"}
    from exposure_workbench.services import run_reads_service
    monkeypatch.setattr(run_reads_service, "get_run_freshness", fresh)
    out = await cat._domain(None, "portfolio", "port_001", "book_liquidity")
    assert out["domain"] == "book_liquidity" and out["question"]
    adv = out["methods"][0]
    assert adv["name"] == "price.adv" and adv["is"] == "price method"
    assert adv["call"] == "compute(method='price.adv', subject='<ticker>')"
    conc = out["reads"][0]
    assert conc["name"] == "concentration" and conc["is"] == "run figures"
    assert conc["call"] == "read_book('run_abc', names=['issuer_exposures.<label>.weight'])"
    assert out["next"][0] == "describe('port_001')"


# ── the enums ────────────────────────────────────────────────────────────────

def test_the_method_enum_is_the_faces_registry_and_the_metric_enum_the_filed_lines():
    meta = build_meta_registry().tools["compute"].json_schema
    assert meta["$defs"]["method_name"]["enum"] == list(skill.METHODS)
    research = build_research_registry().tools["compute"].json_schema
    assert "book.sell" not in research["$defs"]["method_name"]["enum"]
    assert "gross_margin" in research["$defs"]["method_name"]["enum"]
    metric = build_meta_registry().tools["read_fundamentals"].json_schema["properties"]["metric"]["enum"]
    assert metric == [*concept_mapping.SUPPORTED_METRICS, None]


def test_a_name_at_the_wrong_door_cannot_be_written_and_the_refusal_says_the_door():
    compute = build_meta_registry().tools["compute"].json_schema
    problems = validate_args(compute, {"method": "capex", "subject": "MSFT"})
    assert problems and problems[0]["value"] == "capex" and "46 names" in problems[0]["problem"]
    assert validate_args(compute, {"method": ["gross_margin", "capex"], "subject": "MSFT"})[0]["value"] == "capex"
    assert validate_args(compute, {"method": "gross_margin", "subject": "MSFT"}) == []
    assert validate_args(compute, {"method": None, "op": "add", "operands": ["f_a", "f_b"]}) == []
    fundamentals = build_meta_registry().tools["read_fundamentals"].json_schema
    problems = validate_args(fundamentals, {"ticker": "MSFT", "metric": "accruals_ratio"})
    assert problems[0]["value"] == "accruals_ratio"
    assert nt.route("accruals_ratio")["call"] == "compute(method='accruals_ratio', subject='<ticker>')"
    assert nt.route("capex", subject="MSFT")["call"] == "read_fundamentals('MSFT', metric='capex')"


@pytest.mark.asyncio
async def test_read_book_given_a_method_name_is_told_it_is_a_method_and_its_call(monkeypatch):
    async def of_ref(_db, ref):
        return qn.Resolved((qn.Quantity(0.15, qn.RATIO, "issuer_exposures.MSFT.weight", ref),), frozenset(), "run")
    monkeypatch.setattr(qn, "of_ref", of_ref)
    out = await definitions._quantities_by_name(None, "run_x", "2026-09-04", ["book.analysis", "book.drawdown_episodes"])
    assert out["route"]["book.analysis"] == {"name": "book.analysis", "is": "run method",
                                             "call": "compute(method='book.analysis', subject='run_x')"}
    assert out["route"]["book.drawdown_episodes"]["call"] == "compute(method='book.drawdown_episodes', subject='<port_…>')"
    assert "route" in out["detail"]


# ── the sizes, live ──────────────────────────────────────────────────────────

@pytest.mark.live
async def test_every_level_of_the_live_catalogue_fits_its_ceiling():
    """What the model reads at each level, measured on the real desk: the root,
    a portfolio, its latest run, a held issuer, and one opened domain of each
    kind. A level that outgrows the ceiling is a design change, not drift."""
    import os
    from dotenv import load_dotenv
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    load_dotenv(".env", override=True)
    url = os.getenv("DATABASE_URL_RLS", "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with mk() as db:
            desk = await cat.describe(db, None, None)
            assert desk.get("error") is None and cat.size_of(desk) <= cat.DEFAULT_CEILING
            pid = desk["portfolios"][0]["portfolio_id"]
            run_id = desk["portfolios"][0]["latest_completed_run"]
            for subject, expand in ((pid, None), (run_id, None), ("MSFT", None),
                                    (pid, "book_liquidity"), (run_id, "book_market_risk"), ("MSFT", "issuer_earnings_quality")):
                out = await cat.describe(db, subject, expand)
                assert out.get("error") is None, (subject, expand, out)
                assert cat.size_of(out) <= cat.DEFAULT_CEILING, (subject, expand, cat.size_of(out))
                if expand:
                    assert out["domain"] == expand and out["methods"] or out["reads"]
                    assert all("call" in r for r in out["methods"] + out["reads"])
    finally:
        await engine.dispose()
