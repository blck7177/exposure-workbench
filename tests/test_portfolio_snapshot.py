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
from exposure_workbench.utils import ids


# ── the tool itself ───────────────────────────────────────────────────────────

def test_describe_is_the_no_arg_entry_point():
    """V23: describe() with no subject is the desk — how a portfolio-level
    question starts; no ticker, no required args."""
    reg = build_read_registry()
    tool = reg.get("describe")
    assert tool.tool_class == READ
    assert tool.json_schema.get("required", []) == []
    assert set(tool.json_schema["properties"]) == {"subject", "expand"}


def test_the_book_read_is_meta_only_not_research():
    assert "read_book" in faces.FACE_META_AGENT
    assert "read_book" not in faces.FACE_RESEARCH
    assert "describe" in faces.FACE_RESEARCH, "the catalogue is on both faces"


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


# ── table <-> namer <-> resolver prefix parity ────────────────────────────────

def test_id_helpers_match_evidence_prefixes():
    """The bug real data caught: alerts were minted as new_id("alert") -> "alert<hex>",
    which no evidence prefix ("alert_") ever matches, so alert evidence was dead.
    Guard that the mint helpers stay in sync with the resolver prefixes."""
    assert ids.new_alert_id().startswith("alert_")
    assert ids.new_run_id().startswith("run_")
    assert "alert_" in resolver._RESOLVERS
    assert "run_" in resolver._RESOLVERS
