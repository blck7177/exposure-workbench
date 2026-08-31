"""M10 meta-agent tools — face + schema shape (offline)."""

from __future__ import annotations

from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry
from exposure_workbench.tools.registry import DELEGATION, GATE


def test_meta_registry_has_delegation_and_respond():
    reg = build_meta_registry()
    for name in ("ensure_company_ready", "start_issuer_research", "start_exposure_run", "respond"):
        assert name in reg.tools, name
    assert reg.get("start_issuer_research").tool_class == DELEGATION
    assert reg.get("respond").tool_class == GATE


def test_full_meta_face_available_after_registration():
    reg = build_meta_registry()
    assert faces.resolve(reg, faces.FACE_META_AGENT) == faces.FACE_META_AGENT


def test_delegation_tools_require_reason():
    reg = build_meta_registry()
    for name in ("ensure_company_ready", "start_issuer_research", "start_exposure_run"):
        assert "reason" in reg.get(name).json_schema["required"], name


def test_respond_requires_only_blocks():
    """V14-C. The answer is the only required field, and evidence is no longer a
    field beside it: an id reaches the gate by being NAMED IN A SLOT, so there is
    no way to write a figure whose evidence was left out of a separate list. The
    property the old `citations`-optional schema protected — that a reply stating
    nothing factual needs no evidence — survives as an answer with no slots in
    it, which needs no ids and is refused by nothing."""
    reg = build_meta_registry()
    schema = reg.get("respond").json_schema
    assert schema["required"] == ["blocks"]
    assert "citations" not in schema["properties"]
    assert set(schema["properties"]["blocks"]["items"]["properties"]["type"]["enum"]) == set(
        ab.BLOCK_TYPES)


def test_respond_description_states_the_rule_the_gate_enforces():
    """The tool description is the model's only contract with the gate. It used
    to say an acknowledgement needs no citations, which after A0-1 is true only
    when the acknowledgement states no number — and a description that is half
    true is a rejection the model cannot learn from."""
    desc = build_meta_registry().get("respond").description
    assert "number" in desc.lower()


def test_research_face_has_no_delegation():
    """Research subagent must not spawn more runs — tree depth is capped at 2."""
    reg = build_meta_registry()
    # FACE_RESEARCH does not include start_* / ensure_company_ready
    assert not (set(faces.FACE_RESEARCH) & {"ensure_company_ready", "start_issuer_research", "start_exposure_run"})
