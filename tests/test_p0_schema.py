"""P0 — foundation smoke tests (offline: no DB, no network).

Verifies the Issuer Intelligence schema/config deliverables are wired up:
new ORM models register on the shared metadata, settings expose the new
fields with correct defaults, and id helpers use the planned prefixes.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    assert s.turn_tool_budget == 15
    assert s.context_soft_limit_tokens == 80_000
    assert s.embedding_model == "text-embedding-3-small"


# Settings that are declared but not yet read by any code, each because the
# phase that consumes it lands later in V3. Asserted by EQUALITY, not
# containment, so the list cannot quietly grow AND cannot quietly keep an entry
# after its consumer ships — landing B1/B2 turns this test red until the name is
# removed. It must be empty at V3 sign-off.
_PENDING_CONSUMERS: set[str] = set()   # emptied at V3-B2, as it was meant to be


def test_no_settings_field_is_declared_but_never_read():
    """submit_brief_retries and respond_retries lived here for two phases, were
    asserted by this very file, and were written up in MODULE_NOTES as an
    implemented retry budget — while no production code ever read either one.
    Five more were found the moment this check existed: a sync database URL, a
    data dir, a log level the worker actually reads straight from the
    environment, and an Anthropic key and model backing a 'switchable' provider
    that was never built.

    A declared knob that does nothing is worse than a missing one, and this
    project already says so in its own words about check_limits' dead db_limits
    argument. The same sentence applies to configuration."""
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        p.read_text() for d in ("src", "apps", "scripts") for p in (root / d).rglob("*.py")
    )
    # Anchored on the receiver rather than a bare `.name`, because settings names
    # and ORM column names legitimately collide — turn_tool_budget is both a knob
    # and a column, and a bare substring would count the column DEFINITION as a
    # read of the knob. Two indirect reads are real and must count: the quota
    # pools are looked up with getattr off a table of string literals
    # (usage_service._POOLS), and a few fields are consumed only by a derived
    # property on Settings itself (cors_origins -> cors_origins_list).
    def is_read(name: str) -> bool:
        if re.search(rf"\b(?:settings|s|self|get_settings\(\))\.{name}\b", sources):
            return True
        return f'"{name}"' in sources

    unread = {name for name in Settings.model_fields if not is_read(name)}
    assert unread == _PENDING_CONSUMERS, (
        f"declared but never read: {sorted(unread - _PENDING_CONSUMERS)}; "
        f"listed as pending but now read (remove from the list): "
        f"{sorted(_PENDING_CONSUMERS - unread)}"
    )


def test_no_credentials_baked_into_code_defaults():
    """Declared defaults must be empty — real values come from .env only.

    Asserted on the field declarations rather than an instance, since
    Settings() legitimately loads .env (which carries real keys in dev).
    """
    for field in ("tavily_api_key", "edgar_identity", "openai_api_key"):
        assert Settings.model_fields[field].default == "", f"{field} must default empty"


def test_id_prefixes():
    assert ids.new_fact_id().startswith("fact_")
    assert ids.new_chunk_id().startswith("chunk_")
    assert ids.new_calc_id().startswith("calc_")
    assert ids.new_source_id().startswith("src_")
    assert ids.new_company_id().startswith("co_")
    assert ids.new_research_run_id().startswith("rrun_")
