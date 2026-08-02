"""M10 registry — evidence extraction, schema generation, redaction (offline)."""

from __future__ import annotations

from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registry import extract_evidence_refs
from exposure_workbench.services.trace_service import redact_args


def test_extract_calc_id():
    refs = extract_evidence_refs({"calc_id": "calc_abc123", "value": 0.75})
    assert {"type": "calc", "id": "calc_abc123"} in refs


def test_extract_fact_ids_from_nested_points():
    result = {"points": [{"period_end": "2026-01-31", "value": 1.0, "fact_ids": ["fact_a", "fact_b"]}]}
    refs = extract_evidence_refs(result)
    ids = {r["id"] for r in refs}
    assert {"fact_a", "fact_b"} <= ids


def test_extract_explicit_citation_dict():
    result = {"passages": [{"chunk_id": "chunk_x", "citation": {"type": "chunk", "id": "chunk_x"}}]}
    refs = extract_evidence_refs(result)
    assert any(r["type"] == "chunk" and r["id"] == "chunk_x" for r in refs)


def test_extract_prefixed_id_strings():
    refs = extract_evidence_refs({"source": "src_99", "alert": "alert_c0nc"})
    kinds = {(r["type"], r["id"]) for r in refs}
    assert ("source", "src_99") in kinds
    assert ("alert", "alert_c0nc") in kinds


def test_an_id_the_gate_cannot_resolve_is_not_harvested():
    """Inverted in V3-A0-3, which shrank the prefix set to exactly the six the
    citation gate resolves. co_/rrun_/filing_ were harvested and never citable,
    so the model could retrieve an id, quote it, and be refused for quoting what
    the system had just handed it."""
    refs = extract_evidence_refs({"company": "co_nvda", "run": "rrun_2", "filing": "filing_x"})
    assert refs == []


def test_extract_dedupes():
    refs = extract_evidence_refs({"a": {"calc_id": "calc_1"}, "b": {"calc_id": "calc_1"}})
    assert len([r for r in refs if r["id"] == "calc_1"]) == 1


def test_extract_empty_on_no_ids():
    assert extract_evidence_refs({"value": 3.14, "note": "no ids here"}) == []


def test_schemas_are_valid_function_defs():
    reg = build_read_registry()
    schemas = reg.schemas()
    assert len(schemas) == len(reg.tools)
    for s in schemas:
        assert s["type"] == "function"
        assert s["function"]["name"] in reg.tools
        assert "parameters" in s["function"]


def test_required_judgment_fields_are_in_schema():
    """schema-as-interface: get_fact_series can't be called without ticker+metric."""
    reg = build_read_registry()
    gfs = reg.get("get_fact_series")
    assert set(gfs.json_schema["required"]) == {"ticker", "metric"}


def test_face_available_filters_to_registered():
    reg = build_read_registry()
    avail = faces.available(reg, faces.FACE_META_AGENT)
    # P5 has only read core; delegation/gate names are declared but not yet registered
    assert "get_fact_series" in avail
    assert "start_issuer_research" not in avail   # registered later, in P7


def test_redact_args_masks_key_class_fields_only():
    red = redact_args({"ticker": "NVDA", "api_key": "sk-secret", "edgar_identity": "x", "metric": "revenue"})
    assert red["ticker"] == "NVDA" and red["metric"] == "revenue"
    assert red["api_key"] == "[REDACTED]"
    assert red["edgar_identity"] == "[REDACTED]"


def test_a_gates_own_output_is_never_harvested():
    """The fabricated-id loop, closed. respond's rejection echoes the ids it just
    refused under problems[].id, and the call itself COMPLETES — so the harvester
    walked that payload and wrote the made-up ids into the evidence trail. On the
    retry they passed the trail check, leaving only the DB-existence check
    between a fabricated id and an accepted answer, and materialize_pack copied
    them into the run's evidence pack.

    Verified as executable: this exact payload is what _respond returns."""
    from exposure_workbench.tools.registry import GATE, READ, Tool, _harvestable, extract_evidence_refs

    rejection = {"error": "invalid_citations",
                 "problems": [{"id": "calc_fabricated", "reason": "not_in_evidence_trail"},
                              {"id": "fact_nope", "reason": "not_in_evidence_trail"}]}
    # The walker still finds them — that is why the decision has to be made above it.
    assert {r["id"] for r in extract_evidence_refs(rejection)} == {"calc_fabricated", "fact_nope"}

    gate = Tool(name="respond", description="", json_schema={}, fn=None, tool_class=GATE)
    read = Tool(name="get_fact_series", description="", json_schema={}, fn=None, tool_class=READ)
    assert _harvestable(gate, "completed") is False
    assert _harvestable(read, "completed") is True
    assert _harvestable(read, "error") is False
