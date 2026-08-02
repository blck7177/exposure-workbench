"""Portfolio snapshot tool + portfolio-level evidence plumbing (offline).

The tool gives the meta-agent an entry point for "my portfolio" questions, and
its run_/alert_ ids must be citable — so this file guards three seams:
  1. the tool is registered, no-arg, and meta-only (not on the research face);
  2. the evidence walker harvests run_/alert_ ids off a snapshot-shaped result
     (a clean alert ref, not one typed by the alert category);
  3. the citation gate's DB-existence prefixes stay in sync with the resolver's —
     an id the agent can retrieve and drill through is one it can cite.
"""

from __future__ import annotations

from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registry import READ, extract_evidence_refs
from exposure_workbench.services import evidence_trail_service as trail
from exposure_workbench.services import evidence_resolver_service as resolver
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
    # and it is actually registered, so the meta face resolves it
    reg = build_read_registry()
    assert "get_portfolio_snapshot" in faces.available(reg, faces.FACE_META_AGENT)


# ── evidence harvesting off the snapshot shape ────────────────────────────────

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


def test_run_id_harvested_as_run_ref():
    refs = extract_evidence_refs(_snapshot_result())
    assert {"type": "run", "id": "run_abc123"} in refs


def test_alert_harvested_cleanly_not_typed_by_category():
    refs = extract_evidence_refs(_snapshot_result())
    ids = {(r["type"], r["id"]) for r in refs}
    assert ("alert", "alert_c0nc") in ids
    # the alert_type value ("concentration") must NOT become a ref type: the
    # snapshot uses key "alert_type", not "type", precisely to avoid that.
    assert not any(r["type"] == "concentration" for r in refs)


def test_run_prefix_does_not_collide_with_research_run():
    """run_ is harvested; rrun_ is not, and the longer prefix must not be read as
    the shorter one wearing an extra letter. V3-A0-3 dropped rrun_ from the
    harvest set (the gate cannot resolve it), so the collision now has to be
    checked as an absence rather than as a second type."""
    refs = extract_evidence_refs({"a": "run_1", "b": "rrun_2"})
    kinds = {(r["type"], r["id"]) for r in refs}
    assert ("run", "run_1") in kinds
    assert not any(r["id"] == "rrun_2" for r in refs)
    assert not any(r["id"] == "run_2" for r in refs)      # not silently re-prefixed


# ── citation gate <-> resolver prefix parity ──────────────────────────────────

def test_gate_recognizes_run_and_alert_prefixes():
    # without these, a portfolio-level citation is rejected as "unresolved_in_db"
    assert "run_" in trail._RESOLVERS
    assert "alert_" in trail._RESOLVERS


def test_every_gate_prefix_is_resolvable():
    """A citable id (passes the gate) must also resolve for the drawer."""
    for prefix in trail._RESOLVERS:
        assert prefix in resolver._RESOLVERS, prefix


def test_harvest_gate_and_resolver_agree_on_exactly_one_prefix_set():
    """Three lists that must be one list. Harvest wider than the gate gives the
    model ids it can never cite; the gate wider than the resolver gives the user
    a citation whose drawer is empty. V3-A0-3 made the first equality true; this
    asserts all three together so the next prefix is added in three places or in
    none."""
    from exposure_workbench.tools import registry as R
    assert set(R._ID_PREFIXES) == set(trail._RESOLVERS) == set(resolver._RESOLVERS)


def test_id_helpers_match_evidence_prefixes():
    """The bug real data caught: alerts were minted as new_id("alert") -> "alert<hex>",
    which no evidence prefix ("alert_") ever matches, so alert evidence was dead.
    Guard that the mint helpers stay in sync with the resolver prefixes."""
    assert ids.new_alert_id().startswith("alert_")
    assert ids.new_run_id().startswith("run_")
    assert "alert_" in resolver._RESOLVERS
    assert "run_" in resolver._RESOLVERS
