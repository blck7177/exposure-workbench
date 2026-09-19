"""V33 Phase 4 — the catalogue tells prepared from preparing, and the section a
describe call opened is the last the result cap drops.

The B round (docs/spikes/v33) saw `start` register MRK/BAC/GS as investigable
and another session's describe() list them as prepared the same minute, with
nothing filed; and describe(ticker, expand='methods') reach the model as
`methods: {}` because expanding made that section the largest and the cap
emptied the largest section first.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from exposure_workbench.agents import research_session as rs
from exposure_workbench.services import briefing, catalogue_service as cat, company_service


def _companies():
    return [SimpleNamespace(id="c_msft", ticker="MSFT"), SimpleNamespace(id="c_mrk", ticker="MRK"),
            SimpleNamespace(id="c_bac", ticker="BAC")]


async def _list(db, investigable_only=False):
    return _companies()


async def _ready(db, ids):
    return {"c_msft"} & set(ids)


async def _no_books(db):
    return []


@pytest.mark.asyncio
async def test_the_desk_lists_prepared_and_preparing_issuers_apart(monkeypatch):
    monkeypatch.setattr(cat.portfolio_service, "snapshot_all", _no_books)
    monkeypatch.setattr(company_service, "list_companies", _list)
    monkeypatch.setattr(company_service, "ready_company_ids", _ready)
    out = await cat._desk(None)
    assert out["issuers_prepared"] == ["MSFT"]
    assert out["issuers_preparing"] == ["BAC", "MRK"]


@pytest.mark.asyncio
async def test_the_briefing_reads_the_same_split(monkeypatch):
    monkeypatch.setattr(company_service, "list_companies", _list)
    monkeypatch.setattr(company_service, "ready_company_ids", _ready)
    desk = await briefing._desk(None)
    assert desk["issuers_on_desk"] == ["MSFT"]
    assert desk["issuers_preparing"] == ["BAC", "MRK"]
    # V1: what the desk does not hold is the ROSTER's to say, once (analytics/handbook);
    # the domains and their method names were the desk's vocabulary, and the lead has none
    assert set(desk) == {"issuers_on_desk", "issuers_preparing"}


@pytest.mark.asyncio
async def test_no_company_is_ready_when_none_is_asked_about():
    assert await company_service.ready_company_ids(None, []) == set()


def test_the_opened_section_is_what_the_research_cap_keeps():
    assert rs._keep_for("describe", {"subject": "MSFT", "expand": "methods"}) == ("methods",)
    assert rs._keep_for("describe", {"subject": "MSFT"}) == ()
    assert rs._keep_for("run", {"expand": "methods"}) == ()
    assert rs._keep_for("describe", "not a dict") == ()


# ── live: the gold snapshot ───────────────────────────────────────────────────

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_gold")


@pytest.mark.live
@pytest.mark.asyncio
async def test_on_the_gold_desk_msft_is_prepared_and_the_two_lists_partition_the_investigable():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.auth.context import current_user_ctx
    engine = create_async_engine(URL)
    current_user_ctx.set("user_3IDBMeAxLTbecvGorzwV7FCeroR")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            desk = await cat.describe(db, None)
            msft = await cat.describe(db, "MSFT")
            companies = await company_service.list_companies(db, investigable_only=True)
            ready = await company_service.ready_company_ids(db, [c.id for c in companies])
    finally:
        await engine.dispose()
    assert "MSFT" in desk["issuers_prepared"]
    assert msft["identity"]["prepared"] is True
    assert sorted(desk["issuers_prepared"] + desk["issuers_preparing"]) == sorted(c.ticker for c in companies)
    assert {c.ticker for c in companies if c.id in ready} == set(desk["issuers_prepared"])
