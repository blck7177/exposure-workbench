"""V19 — the label beside a figure is the table's, never the model's (offline).

Three findings from the 9/2 battery, one cause: the gate proves a figure has a
source and cannot see the words written next to it. `Peak-to-trough decline |
$205.10` was the trough (`NVDA.adj_close@2026-06-05`) under a row label the
model wrote; "market cap at $919.77" was `LLY.close`. Tables and trends are the
two block kinds whose labels are structural, so there the label is now DERIVED
from the slot's name and the model has no cell to write one in. Paragraph
prose keeps its words; that is the critic's job, outside the gate.

Also here: the web on the meta face, and the two evidence dead ends.
"""

from __future__ import annotations

import inspect

import pytest

from exposure_workbench.services import evidence_resolver_service as ev
from exposure_workbench.services import quantities as qn
from exposure_workbench.tools import definitions, faces
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.meta_tools import RESPOND_SCHEMA
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


def _fields(claim) -> list[str]:
    """V30: the grammar is claims + prose; a table is a claim with rows of ids."""
    return [p["field"] for p in validate_args(RESPOND_SCHEMA, {"claims": [{"id": "c1", "relation": "table", **claim}], "prose": ["{c1}"]})]


S = {"ref": "calc_1", "name": "NVDA.adj_close@2026-06-05"}


# ── S1: the grammar has no cell for words ─────────────────────────────────────

def test_a_slot_cell_is_refused_by_the_schema_at_the_cell():
    """V24: a cell is a fact id; a slot object has no place."""
    assert _fields({"rows": [[S, "f_a"]]}) == ["claims.0.rows.0.0"]


def test_columns_are_refused_by_the_schema_at_the_key():
    assert _fields({"columns": ["Measure", "Value"], "rows": [["f_a"]]}) == ["claims.0.columns"]


def test_the_schema_description_and_the_refusal_say_the_same_rule():
    """One sentence, read twice — the schema before the gate, the refusal after."""
    props = RESPOND_SCHEMA["properties"]["claims"]["items"]["properties"]
    assert "one row per thing compared" in props["rows"]["description"]
    assert "columns" not in props and "header" not in props and "labels" not in props


# ── S1: what is derived, on the three shapes the battery produced ─────────────

def test_the_model_cannot_supply_the_derived_keys_itself():
    """`header`, `labels`, `explicit` are the renderer's; a block carrying them
    is refused like any unknown key, so the derivation is the only writer."""
    for key in ("header", "labels", "explicit"):
        assert _fields({"rows": [["f_a"]], key: ["x"]}) == [f"claims.0.{key}"]


# ── S1: a trend's series states its own direction ─────────────────────────────


# ── S2: the web is on the meta face ───────────────────────────────────────────

def test_search_external_research_is_on_both_faces_from_one_registration():
    from exposure_workbench.tools import research_tools
    meta, research = build_meta_registry(), build_research_registry()
    assert "search_web" in faces.resolve(meta, faces.FACE_META_AGENT)
    assert "search_web" in faces.resolve(research, faces.FACE_RESEARCH)
    assert meta.get("search_web").budget_key == "external_search"
    from exposure_workbench.services import fact_adapters as fa
    assert fa.ADAPTERS["search_web"] is fa.search_web, "its sources become passage facts"
    src = inspect.getsource(research_tools)
    assert src.count('name="search_web"') == 1


def test_the_capability_statement_says_the_web_is_here():
    from exposure_workbench.services import catalogue_service
    src = inspect.getsource(catalogue_service._desk)
    assert "search_web" in src
    assert not any("web" in c for c in catalogue_service.CANNOT.values())


def test_the_search_tool_admits_a_listed_issuer_rather_than_refusing_it():
    from exposure_workbench.tools import research_tools
    src = inspect.getsource(research_tools._search_external_research)
    assert "company_service.admit" in src
    assert "company_not_found" in src and "not_investigable" in src


# ── S3: the chain reaches the filing and the holdings ─────────────────────────

def test_a_fact_card_carries_the_filing_url_and_a_run_card_its_holdings():
    fact = inspect.getsource(ev._fact)
    assert '"source_url": source_url' in fact
    assert "Filing.accession_number == row.source_accession" in fact, "a fact with no filing_id still reaches its filing"
    assert "_edgar_index(cik, accession)" in fact, "a fact whose filing was never ingested still points at EDGAR"
    assert ev._edgar_index("0000789019", "0001564590-21-020891") == \
        "https://www.sec.gov/Archives/edgar/data/789019/000156459021020891/"
    run = inspect.getsource(ev._run)
    assert "positions_for_run" in run and '"type": "position"' in run


def test_the_run_and_its_card_resolve_holdings_through_one_function():
    from exposure_workbench.workflow import exposure_workflow as wf
    src = inspect.getsource(wf.ExposureWorkflow._positions_for)
    assert "positions_for_run" in src
    assert "get_positions_latest" not in src, "the two-step lives in portfolio_service only"


# ── S2: the engine is told the issuer, and the window is a parameter ──────────

def test_the_search_query_carries_the_issuer_the_model_named():
    """First live turn: "latest news from the past week" reached Tavily with no
    issuer in it and came back as five front pages. The ticker is an argument
    of the tool; binding it into the query is the tool's job."""
    from exposure_workbench.services import research_search_service as rss
    assert rss.compose_query("NVIDIA Corp", "NVDA", "latest news from the past week") == \
        "NVIDIA Corp (NVDA): latest news from the past week"
    assert rss.compose_query(None, "NVDA", " earnings ") == "NVDA: earnings"
    assert rss.compose_query("NVDA", "NVDA", "x") == "NVDA: x"


def test_a_day_window_is_a_request_parameter_not_a_phrase():
    from exposure_workbench.tools import research_tools
    schema = build_meta_registry().get("search_web").json_schema
    assert schema["properties"]["days"]["type"] == ["integer", "null"]
    assert "days" not in schema["required"]
    src = inspect.getsource(research_tools._search_external_research)
    assert "compose_query(company.name, tk, query)" in src and "days=days" in src


# ── a filed metric asked for as a formula is pointed at its tool ─────────────

async def test_evaluate_formula_names_the_tool_that_holds_a_filed_metric():
    from exposure_workbench.services import formula_service as fsvc
    out = await fsvc.evaluate_formula(None, "NVDA", "net_income", invoked_by="test")
    assert out["error"] == "unknown_formula"
    assert "fundamentals(ticker, metric='net_income'" in out["detail"]
    assert "read_fundamentals" not in out["detail"]
    out = await fsvc.evaluate_formula(None, "NVDA", "not_a_thing", invoked_by="test")
    assert out["error"] == "unknown_formula" and "detail" not in out


# ── the subject of a row reaches the label when the name does not carry it ───

def test_a_calc_rows_subject_is_the_ledgers_company_column():
    """`flow.series` rows record no ticker in params (473 of 473 live rows); the
    column does. A get_flow slot therefore reaches the table with its issuer."""
    src = inspect.getsource(qn._from_calc)
    assert 'getattr(row, "company_id", None)' in src and "subject=" in src


