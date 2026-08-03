"""P1.1 — a face is a promise, and resolve() makes breaking it loud (offline).

faces.available() trimmed a face down to whatever happened to be registered and
returned it without a word. That is a silent capability edit: the caller asked
for the meta-agent face and got the read face, and the only way to notice was to
count the tools. It hid a real drift for two phases — apps/mcp/server.py declared
FACE_META_AGENT while building the read registry, so its four delegation/gate
tools were dropped every startup (test_v2_audit pinned it as KNOWN_TRIMMED).

resolve() replaces it and raises instead, naming what is missing. available() is
gone rather than deprecated: leaving the trimming mechanism in the module is
leaving the next caller a way to reintroduce exactly this.
"""

from __future__ import annotations

import pytest

from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registry import ToolRegistry


def test_resolve_returns_the_face_in_declared_order():
    registry = build_read_registry()
    assert faces.resolve(registry, faces.READ_CORE) == faces.READ_CORE


def test_resolve_raises_and_names_every_missing_tool():
    registry = build_read_registry()
    face = faces.READ_CORE + ["no_such_tool", "another_missing_one"]

    with pytest.raises(faces.FaceNotRegistered) as exc:
        faces.resolve(registry, face)

    message = str(exc.value)
    assert "no_such_tool" in message and "another_missing_one" in message
    # The tools that WERE present are not the story; the message must not bury
    # the two names in a list of eighteen.
    assert "get_fact_series" not in message


def test_resolve_on_an_empty_registry_names_the_whole_face():
    with pytest.raises(faces.FaceNotRegistered) as exc:
        faces.resolve(ToolRegistry(), ["get_fact_series", "think"])
    assert "get_fact_series" in str(exc.value) and "think" in str(exc.value)


def test_the_trimming_helper_is_gone():
    """Named so a future reader understands the deletion was the point."""
    assert not hasattr(faces, "available")


@pytest.mark.parametrize(
    "face_name, face, builder_name",
    [
        ("FACE_META_AGENT", faces.FACE_META_AGENT, "build_meta_registry"),
        ("FACE_RESEARCH", faces.FACE_RESEARCH, "build_research_registry"),
    ],
)
def test_every_shipped_face_resolves_against_its_own_registry(face_name, face, builder_name):
    """The structural guard: what an agent is told it can do, it can call.

    This is test_v2_audit's drift check restated as the behaviour rather than a
    measurement — after P1.1 the drift cannot be observed, it raises.
    """
    from exposure_workbench.agents.meta_agent import build_meta_registry
    from exposure_workbench.workflow.issuer_research_workflow import build_research_registry

    builder = {"build_meta_registry": build_meta_registry,
               "build_research_registry": build_research_registry}[builder_name]
    resolved = faces.resolve(builder(), face)
    assert resolved == face
