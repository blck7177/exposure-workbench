"""The faces the resident server mounts (MCP_PLAN R4, decision N10), each one expression.

This module imports none of exposure_workbench.agents, .workflow or .llm: apps/mcp
imports it at startup, so whatever is reachable from here is in the tool container,
and the completion call and the loops around it must never be. test_v2_audit walks
the graph and fails on either.
"""

from __future__ import annotations

from exposure_workbench.tools.primitives import (  # noqa: F401 — one registry per face
    build_analyst_registry, build_desk_registry, build_lead_registry, build_research_verbs,
)
from exposure_workbench.tools.registry import ToolRegistry


def build_meta_registry() -> ToolRegistry:
    # the mount named "meta" is the debug door — every verb, no agent behind it
    return build_desk_registry()


def build_research_registry() -> ToolRegistry:
    return build_research_verbs()
