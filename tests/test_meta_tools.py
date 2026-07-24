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
    reg = build_meta_registry()
    schema = reg.get("respond").json_schema
    assert schema["required"] == ["text"]                # citations optional (ack needs none)
    assert "citations" in schema["properties"]


def test_research_face_has_no_delegation():
    """Research subagent must not spawn more runs — tree depth is capped at 2."""
    reg = build_meta_registry()
    # FACE_RESEARCH does not include start_* / ensure_company_ready
    assert not (set(faces.FACE_RESEARCH) & {"ensure_company_ready", "start_issuer_research", "start_exposure_run"})
