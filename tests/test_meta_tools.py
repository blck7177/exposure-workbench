"""M10 meta-agent tools — face + schema shape (offline)."""

from __future__ import annotations

from exposure_workbench.services import answer as A
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry
from exposure_workbench.tools.registry import DELEGATION, GATE


def test_meta_registry_has_delegation_and_respond():
    reg = build_meta_registry()
    for name in ("start", "respond"):
        assert name in reg.tools, name
    assert reg.get("start").tool_class == DELEGATION
    assert reg.get("respond").tool_class == GATE


def test_full_meta_face_available_after_registration():
    reg = build_meta_registry()
    assert faces.resolve(reg, faces.FACE_META_AGENT) == faces.FACE_META_AGENT


def test_delegation_tools_require_reason():
    reg = build_meta_registry()
    for name in ("start",):
        assert "reason" in reg.get(name).json_schema["required"], name


def test_respond_requires_only_blocks():
    """V30: the answer is claims and prose, both required; evidence is not a
    field beside them — a fact reaches the gate by being NAMED IN A CLAIM, so a
    figure cannot be stated with its evidence left out. A reply stating nothing
    factual is an empty claims list, refused by nothing."""
    from exposure_workbench.services import claims
    reg = build_meta_registry()
    schema = reg.get("respond").json_schema
    assert schema["required"] == ["claims", "prose"]
    assert "citations" not in schema["properties"]
    assert schema["properties"]["claims"]["items"]["properties"]["relation"]["enum"] == list(claims.RELATIONS)

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
    assert not (set(faces.FACE_RESEARCH) & {"start", "read_book"})
