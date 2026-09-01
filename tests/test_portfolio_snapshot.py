"""Portfolio snapshot tool + portfolio-level evidence plumbing (offline).

The tool gives the meta-agent an entry point for "my portfolio" questions, and
its run_/alert_ ids must be citable — so this file guards three seams:
  1. the tool is registered, no-arg, and meta-only (not on the research face);
  2. the tool's declaration puts run_/alert_ ids on the table off a
     snapshot-shaped result (a clean alert ref, not one typed by the alert
     category; the run with the scope the registration states);
  3. the table's prefixes stay in sync with the namer's and the resolver's —
     an id the agent can retrieve and drill through is one it can cite.
"""

from __future__ import annotations

from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registry import READ
from exposure_workbench.services import evidence_resolver_service as resolver
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import table as tb
from exposure_workbench.services import table as tbl
from exposure_workbench.utils import ids


# ── the tool itself ───────────────────────────────────────────────────────────

def test_get_portfolio_snapshot_registered_no_arg_read():
    reg = build_read_registry()
    tool = reg.get("get_portfolio_snapshot")
    assert tool.tool_class == READ
    # no ticker, no required args — this is how a portfolio-level question starts
    assert tool.json_schema.get("required", []) == []
    assert tool.json_schema["properties"] == {}


def test_snapshot_is_meta_only_not_research():
    assert "get_portfolio_snapshot" in faces.FACE_META_AGENT
    assert "get_portfolio_snapshot" not in faces.FACE_RESEARCH
    # and it is actually registered, so the read registry resolves it
    reg = build_read_registry()
    assert "get_portfolio_snapshot" in faces.resolve(reg, faces.META_ONLY_READS)


# ── what the snapshot declares onto the table ─────────────────────────────────

def _snapshot_result() -> dict:
    """Mirrors portfolio_service._snapshot_one's output shape."""
    return {"portfolios": [{
        "portfolio_id": "port_001", "name": "US Growth & Income",
        "run_id": "run_abc123", "as_of_date": "2026-07-24",
        "metrics": {"market_value": 10_260_000.0, "daily_return": -0.0159},
        "top_sectors": [{"sector": "Technology", "weight": 0.41, "market_value": 4_200_000.0}],
        "top_issuers": [{"ticker": "NVDA", "sector": "Technology", "weight": 0.18}],
        "alerts": [{"id": "alert_c0nc", "alert_type": "concentration", "severity": "warning",
                    "entity_id": "NVDA", "message": "NVDA weight 18%", "utilization": 0.9}],
    }]}


def _declared() -> list[dict]:
    """The snapshot's declaration, as the wrapper builds it from the registration."""
    scope = build_read_registry().get("get_portfolio_snapshot").evidence.scope
    return tbl.declare(_snapshot_result(), scope=scope)["evidence"]


def test_the_snapshot_declares_its_run_with_the_tables_it_read():
    """V15-S2a: a run is on the table with a scope — the child tables this tool
    read — not as a bare id, so the 235 quantities of a run do not all become
    citable because one tool touched it."""
    run = [e for e in _declared() if e["type"] == "run"]
    assert len(run) == 1 and run[0]["id"] == "run_abc123"
    assert set(run[0]["scope"]) >= {"exposure_metrics", "issuer_exposures", "sector_exposures", "risk_alerts"}


def test_alert_declared_cleanly_not_typed_by_category():
    kinds = {(e["type"], e["id"]) for e in _declared()}
    assert ("alert", "alert_c0nc") in kinds
    # the alert_type value ("concentration") must NOT become a ref type: the
    # snapshot uses key "alert_type", not "type", precisely to avoid that.
    assert not any(e["type"] == "concentration" for e in _declared())


def test_run_prefix_does_not_collide_with_research_run():
    """run_ is declared; rrun_ is not, and the longer prefix must not be read as
    the shorter one wearing an extra letter. rrun_ reaches the table only as a
    task row, through a delegation's `tasks_from`."""
    refs = tbl.declare({"a": "run_1", "b": "rrun_2"}, scope=("count",))["evidence"]
    kinds = {(e["type"], e["id"]) for e in refs}
    assert ("run", "run_1") in kinds
    assert not any(e["id"] == "rrun_2" for e in refs)
    assert not any(e["id"] == "run_2" for e in refs)      # not silently re-prefixed


# ── table <-> namer <-> resolver prefix parity ────────────────────────────────

def test_the_table_places_run_and_alert_prefixes():
    # without these, a portfolio-level citation is refused as not_on_table
    assert "run_" in tb._PREFIX_TYPE
    assert "alert_" in tb._PREFIX_TYPE


def test_every_table_prefix_is_resolvable():
    """A citable id (on the table) must also resolve for the drawer."""
    for prefix in tb._PREFIX_TYPE:
        assert prefix in resolver._RESOLVERS, prefix


def test_table_namer_and_resolver_agree_on_exactly_one_prefix_set():
    """Three lists that must be one list. The table wider than the namer gives
    the model ids that hold nothing; the table wider than the resolver gives the
    user a citation whose drawer is empty. Asserted together so the next prefix
    is added in three places or in none."""
    assert set(tb._PREFIX_TYPE) == set(qn.SOURCES) == set(resolver._RESOLVERS)


def test_a_holding_is_citable_evidence():
    """V3-R4. C3 gave the agent a tool that reads back every holding, and the
    first question anyone asks it — "how many shares of AAPL do I hold" — could
    not be answered: the quantity is real, it is on a positions row, and that
    row had no evidence identity, so the number had nothing to cite and A1
    refused it by construction. The acceptance query for the memory component
    failed on the memory component's own output.

    Asserted in all three places at once because that is the invariant: table,
    namer and resolver are one list, and pos_ arriving in two of them would be
    a hole with a test signing it off."""
    assert "pos_" in tb._PREFIX_TYPE
    assert "pos_" in qn.SOURCES
    assert "pos_" in resolver._RESOLVERS


def test_id_helpers_match_evidence_prefixes():
    """The bug real data caught: alerts were minted as new_id("alert") -> "alert<hex>",
    which no evidence prefix ("alert_") ever matches, so alert evidence was dead.
    Guard that the mint helpers stay in sync with the resolver prefixes."""
    assert ids.new_alert_id().startswith("alert_")
    assert ids.new_run_id().startswith("run_")
    assert "alert_" in resolver._RESOLVERS
    assert "run_" in resolver._RESOLVERS
