"""The two faces the resident server mounts (MCP_PLAN R4, decision N10).

A face's registry is one expression — the read registry plus one register_*_tools
— and it used to be written twice. build_meta_registry() lived in
agents/meta_agent.py, where R4 left it with no production caller, while
apps/mcp/http.py spelled register_meta_tools(build_read_registry()) inline; two
spellings of "what is the meta face made of" agree until somebody registers a
tool against one of them. They could not be collapsed by having one import the
other, because a face's consumer (agents) and its server (apps/mcp) sit on
opposite sides of the mount by construction and neither may reach across it. So
the answer is stated where the tools themselves are, and both sides read it here.

build_research_registry had the mirror-image problem, and it was not only
cosmetic. Defined in the workflow layer, it made http.py import
workflow/issuer_research_workflow to get at it — which imports
agents/research_session, which calls llm_client.chat_with_tools. The research
LOOP and its completion call were being imported into the resident tool container
as a side effect of asking what the research face is made of. Nothing invoked
them there, so nothing failed; N10 was untrue in the import graph while being
true in behaviour, which is the state that lasts longest.

So this module imports none of exposure_workbench.agents, .workflow or .llm, and
that is a rule about the graph rather than about these four lines: apps/mcp
imports this module at startup, so whatever is reachable from here is in the tool
container.
Stated precisely, because what is below is not already free of the model:
tools/definitions reaches llm.client for embed_texts, the retrieval tool
embedding its own query, which is the carve-out N10 names. What may never arrive
is the COMPLETION call and the loop around it. test_v2_audit walks this graph and
fails on either.
"""

from __future__ import annotations

from exposure_workbench.tools.definitions import register_think
from exposure_workbench.tools.primitives import (  # noqa: F401 — one registry per analyst face
    build_analyst_registry, build_desk_registry, build_research_verbs,
)
from exposure_workbench.tools.registry import ToolRegistry
from exposure_workbench.tools.research_tools import register_research_tools


def build_meta_registry() -> ToolRegistry:
    # V1: the mount named "meta" is the debug door — every verb, no agent behind
    # it. The lead analyst holds no face (agents/meta_agent).
    return build_desk_registry()


def build_research_registry() -> ToolRegistry:
    # V1: the issuer analyst's verbs with the price read and both families'
    # measures, the pause, and the brief's gate.
    return register_research_tools(register_think(build_research_verbs()))
