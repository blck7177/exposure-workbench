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
    assert _harvestable(gate, "completed", rejection) is False
    assert _harvestable(read, "completed", {"calc_id": "calc_real"}) is True
    assert _harvestable(read, "error", {"error": "tool_error"}) is False


async def test_a_tool_that_echoes_its_argument_is_not_evidence():
    """V3-R2, the second blocker the adversarial review reproduced, and the same
    defect as the gate above seen from one level up: the harvester was deciding
    what counts as evidence from the tool's CLASS and status, when the property
    it actually needs is that the value was RETRIEVED. Three live tools return
    the model's own input straight back, and each one let the model write any id
    it liked into its own evidence trail:

      - think echoes the thought verbatim (definitions.py:_think)
      - get_task_status echoes an unknown job_id (definitions.py:146)
      - get_portfolio_positions echoes an unknown portfolio_id (:153)

    A poisoned trail is not a fabricated-number problem — A1 still checks the
    figures — it is a PROVENANCE problem, which is the one thing the trail
    exists to guarantee: "cited ids come from tool results you called this
    session" was false, and an answer could claim to rest on a calc it never
    read. Two orthogonal rules close all three vectors and any tool written
    later that shares their shape: a reflection is the model talking, and an
    error payload is not a retrieval."""
    from exposure_workbench.tools.definitions import _think
    from exposure_workbench.tools.registry import READ, REFLECTION, Tool, _harvestable

    think = Tool(name="think", description="", json_schema={}, fn=None, tool_class=REFLECTION)
    read = Tool(name="get_task_status", description="", json_schema={}, fn=None, tool_class=READ)

    # Executable, not transcribed: this is what the tool really returns. The
    # walker recognises a string that IS an id, so the thought has to be one —
    # a one-token note is a perfectly ordinary thing for a model to write, and
    # it is the only shape of the three that needs any care at all to trigger.
    echoed = await _think(None, thought="calc_deadbeefcafe")
    assert {r["id"] for r in extract_evidence_refs(echoed)} == {"calc_deadbeefcafe"}
    assert _harvestable(think, "completed", echoed) is False

    # The near miss is its own small defect, fixed by the same rule: a thought
    # that merely BEGINS with an id was harvested as an evidence ref whose id is
    # the entire sentence — an unresolvable 400-character row in the audit
    # trail, written under the model's control.
    sentence = await _think(None, thought="calc_deadbeefcafe is the YoY change; cite it")
    assert extract_evidence_refs(sentence)[0]["id"] == sentence["thought"]
    assert _harvestable(think, "completed", sentence) is False

    for payload in ({"error": "unknown_job", "job_id": "run_notmine"},
                    {"error": "unknown_portfolio", "portfolio_id": "run_notmine"}):
        assert extract_evidence_refs(payload), "the walker still finds it — hence the decision above it"
        assert _harvestable(read, "completed", payload) is False

    # And the successful read this is not allowed to break.
    assert _harvestable(read, "completed", {"job_id": "run_real", "state": "completed"}) is True
