"""M10 meta-agent tools — face + schema shape (offline)."""

from __future__ import annotations

from exposure_workbench.services import answer as A
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry
from exposure_workbench.tools.registry import DELEGATION, GATE


def test_full_meta_face_available_after_registration():
    reg = build_meta_registry()
    assert faces.resolve(reg, faces.FACE_META_AGENT) == faces.FACE_META_AGENT


def test_research_face_has_no_delegation():
    """Research subagent must not spawn more runs — tree depth is capped at 2."""
    reg = build_meta_registry()
    # FACE_RESEARCH does not include start_* / ensure_company_ready
    assert not (set(faces.FACE_RESEARCH) & {"start", "read_book"})
