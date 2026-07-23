"""P0 — foundation smoke tests (offline: no DB, no network).

Verifies the Issuer Intelligence schema/config deliverables are wired up:
new ORM models register on the shared metadata, settings expose the new
fields with correct defaults, and id helpers use the planned prefixes.
"""

from __future__ import annotations

from exposure_workbench.db import models  # noqa: F401  (registers models on Base)
from exposure_workbench.db.session import Base
from exposure_workbench.app_state.settings import Settings
from exposure_workbench.utils import ids


NEW_TABLES = {
    "companies", "filings", "filing_documents", "filing_sections",
    "filing_chunks", "financial_facts", "research_sources", "calc_ledger",
    "research_runs", "agent_sessions", "agent_messages", "agent_steps",
    "evidence_packs", "issuer_briefs",
}


def test_new_models_registered():
    registered = set(Base.metadata.tables.keys())
    missing = NEW_TABLES - registered
    assert not missing, f"models not registered: {missing}"


def test_filing_chunks_has_vector_embedding():
    cols = Base.metadata.tables["filing_chunks"].columns
    assert "embedding" in cols
    # pgvector column type name is 'VECTOR'
    assert "VECTOR" in str(cols["embedding"].type).upper()


def test_financial_facts_keeps_raw_and_normalized():
    cols = Base.metadata.tables["financial_facts"].columns
    assert "raw_concept" in cols and "normalized_metric" in cols


def test_settings_new_fields_defaults():
    s = Settings()
    assert s.session_tool_budget == 40
    assert s.external_search_budget == 5
    assert s.submit_brief_retries == 2
    assert s.respond_retries == 1
    assert s.embedding_model == "text-embedding-3-small"
    # provider keys default empty (fail-loud, no baked-in creds)
    assert s.tavily_api_key == ""
    assert s.edgar_identity == ""


def test_id_prefixes():
    assert ids.new_fact_id().startswith("fact_")
    assert ids.new_chunk_id().startswith("chunk_")
    assert ids.new_calc_id().startswith("calc_")
    assert ids.new_source_id().startswith("src_")
    assert ids.new_company_id().startswith("co_")
    assert ids.new_research_run_id().startswith("rrun_")
