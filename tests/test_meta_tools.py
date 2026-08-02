"""M10 meta-agent tools — face + schema shape (offline)."""

from __future__ import annotations

from exposure_workbench.agents.meta_agent import build_meta_registry
from exposure_workbench.tools import faces
from exposure_workbench.tools.registry import DELEGATION, GATE


def test_meta_registry_has_delegation_and_respond():
    reg = build_meta_registry()
    for name in ("ensure_company_ready", "start_issuer_research", "start_exposure_run", "respond"):
        assert name in reg.tools, name
    assert reg.get("start_issuer_research").tool_class == DELEGATION
    assert reg.get("respond").tool_class == GATE


def test_full_meta_face_available_after_registration():
    reg = build_meta_registry()
    avail = faces.available(reg, faces.FACE_META_AGENT)
    assert set(avail) == set(faces.FACE_META_AGENT)      # every declared name now registered


def test_delegation_tools_require_reason():
    reg = build_meta_registry()
    for name in ("ensure_company_ready", "start_issuer_research", "start_exposure_run"):
        assert "reason" in reg.get(name).json_schema["required"], name


def test_respond_requires_only_text():
    """Schema-optional on purpose. The rule "a reply stating a number must cite"
    is enforced in the gate (V3-A0-1), not by making citations a required field:
    required-in-schema would also block the number-free replies — greetings,
    clarifying questions — that are legitimately uncited. See
    test_the_gate_refuses_a_number_without_a_citation for the enforced half."""
    reg = build_meta_registry()
    schema = reg.get("respond").json_schema
    assert schema["required"] == ["text"]
    assert "citations" in schema["properties"]


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
