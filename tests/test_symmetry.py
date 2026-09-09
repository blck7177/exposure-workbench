"""V15 — both faces are symmetric about the table: every citable quantity has a
name, a unit and a knowledge hook, and every tool says what it puts there.

Evidence is declared, not harvested. That is only a rule if every tool on a
face either declares its evidence or is on a short, explicit list of tools
whose results are not evidence; a tool registered without either is a tool
whose ids go nowhere, discovered in the first live test that cites one. The
same symmetry holds between the modules: the prefixes a tool result may put on
the table are the prefixes quantities.py can resolve, the tables a scope names
are tables a run has, and the manifest describe_run hands the model groups
every name the run actually holds.
"""

from __future__ import annotations

import inspect

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import resources
from exposure_workbench.services import quantities as qn
from exposure_workbench.tools import definitions, faces
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
RUN = "run_1d6e9e05bee6"

# Tools whose results are not evidence, by decision: state, policy, a reflection,
# the two exits. Adding to this list is adding a tool the model can call and
# never cite, so it is spelled out here rather than derived.


def _faces():
    return ((build_meta_registry(), faces.FACE_META_AGENT), (build_research_registry(), faces.FACE_RESEARCH))


async def test_an_id_of_no_known_prefix_resolves_to_nothing_without_touching_the_db():
    r = await qn.of_ref(None, "co_msft")
    assert r.kind is None and r.quantities == ()


def test_every_resource_column_has_a_display_name_and_a_unit():
    """test_resources pins the columns exist on their tables; this pins the
    other half of the promise — that each is something a reader can be shown
    and something the gate can type."""
    for r in resources.RUN_CHILDREN:
        for c in r.columns:
            assert c.display.strip(), f"{r.table}.{c.name} has no display name"
            assert c.unit in (resources.MONEY, resources.RATIO, resources.COUNT, resources.MULTIPLE), \
                f"{r.table}.{c.name}: {c.unit!r}"


def test_describe_run_and_read_quantities_are_meta_only():
    """They answer questions about THIS DESK's book; the research face is
    issuer-scoped by construction (faces.py)."""
    for name in ("read_book",):
        assert name in faces.FACE_META_AGENT
        assert name not in faces.FACE_RESEARCH


def test_run_group_patterns_are_well_formed():
    """One star at most, and every literal head is a table a run has or the
    analysis row's own prefix — so a typo in a pattern cannot match nothing forever."""
    heads = tuple(f"{t}." for t in qn.RUN_TABLES) + ("portfolio.integration.",)
    for key, _question, patterns in resources.RUN_GROUPS:
        for p in patterns:
            assert p.count("*") <= 1, (key, p)
            assert p.startswith(heads), (key, p)


def test_the_groups_live_in_resources_and_definitions_only_reads_them():
    """V16 moved RUN_GROUPS to the data layer: the manifest describe_run builds
    and the group each quantity carries on the table come from the one table,
    so they cannot drift."""
    from exposure_workbench.services import catalogue_service
    src = inspect.getsource(catalogue_service._book_names)
    assert "resources.RUN_GROUPS" in src and "resources.matches" in src


def test_the_group_vocabulary_is_closed_and_every_key_answers_a_question():
    """A group is a question the desk knows how to ask. The run groups plus the
    four non-run groups quantities.py can stamp (a fact is fundamentals or —
    per-share — price, a formula's measure is derived, the rest other) — and
    nothing else, so the payload legend can state every key it prints."""
    run_keys = {key for key, _q, _p in resources.RUN_GROUPS}
    assert set(resources.GROUP_QUESTIONS) == run_keys | {"fundamentals", "derived", "book_derived", "price", "other"}
    assert all(q.strip() for q in resources.GROUP_QUESTIONS.values())


def test_an_alerts_citable_columns_are_the_resource_declaration():
    """RiskAlert's three columns were declared twice — resources.py for the run
    child, a hand-written tuple in quantities._from_alert for the standalone
    id. The second copy is now a read of the first."""
    import inspect
    res = next(r for r in resources.RUN_CHILDREN if r.table == "risk_alerts")
    assert qn._ALERT_COLUMNS == res.columns
    src = inspect.getsource(qn)
    assert "current_value" not in src, "quantities.py spells an alert column the resources already declare"


def _expand(factored: dict | None) -> set[str]:
    """The names a factored listing stands for: the plain ones plus every
    pattern composed with every label it ranges over — exactly the composition
    the manifest tells the model to do."""
    if not factored:
        return set()
    out = set(factored.get("names") or [])
    for group in factored.get("patterns") or []:
        for pat in group["patterns"]:
            out.update(pat.replace("<label>", lb) for lb in group["labels"])
    return out


@pytest.mark.live
async def test_every_run_group_pattern_matches_a_real_name_and_every_name_is_grouped():
    """The manifest is how the model finds a name. A pattern that matches
    nothing on a real run is a group heading over an empty list; a name in no
    group and not under `other` is a figure the model cannot discover; and a
    factored pattern must compose back to names the run really holds."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            manifest = await definitions._describe_run(db, RUN)
            resolved = await qn.of_ref(db, RUN)
            derived = ((await qn.of_ref(db, manifest["analysis_calc_id"])).quantities
                       if manifest.get("analysis_calc_id") else ())
            await db.rollback()
    finally:
        await engine.dispose()
    assert "error" not in manifest, manifest
    listed = {n for g in manifest["groups"] for n in _expand(g)} | _expand(manifest.get("other"))
    withheld = _expand(manifest["not_available"]["withheld_collinear"])
    # A pattern names a family the run really holds. On THIS run every single
    # beta is collinear and withheld, so `factor_attributions.*.beta` is a real
    # family with nothing on the table — the group heading is right, the run is
    # what it is.
    for key, _question, patterns in definitions._RUN_GROUPS:
        for p in patterns:
            assert any(definitions._matches(p, n) for n in listed | withheld), (
                f"{key}: {p} names no quantity of {RUN}")
    held = {q.label for q in resolved.quantities if q.not_alone is None} | {q.label for q in derived}
    assert held <= listed, sorted(held - listed)
    assert listed <= held, f"the manifest composes names the run does not hold: {sorted(listed - held)}"
    assert withheld and withheld.isdisjoint(listed), "a withheld coefficient is listed as available"
    mandate = next(g for g in manifest["groups"] if g["group"] == "mandate")
    assert any(n.startswith("portfolio.integration.room_to_") for n in _expand(mandate)), (
        "room_to_* sits in the mandate group beside the tiers it is measured against")


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
