"""Tool faces (M10) — declarative capability sets.

A face is just a list of tool names. "What can an agent do" is answered in one
place, as data, so an auditor sees the whole surface at a glance and skip-flags
(P6) narrow it by removing names, not by branching inside a tool.

FACE_META_AGENT and FACE_RESEARCH gain their delegation/gate tools in P6/P7;
here we define the read+reflection core they share. The MCP host is handed the
meta-agent face — same tools, same enforcement, no privileged channel.
"""

from __future__ import annotations

# Read + reflection tools available to every agent surface.
READ_CORE = [
    "get_issuer_snapshot",
    "list_available_data",
    "get_fact_series",
    "compute_change",
    "compute_ratio",
    "compute_stat",
    "get_market_stats",
    "search_filing_passages",
    "get_filing_section",
    "list_alerts",
    "think",
]

# Meta-agent adds the portfolio entry point + delegation + respond (P7); research
# adds search_external_research + submit_brief (P6). Kept as names here.
# get_portfolio_snapshot is meta-only: it frames a portfolio-level question, which
# is the meta-agent's job. The research face stays issuer-scoped (adding portfolio
# weights would change brief generation and needs its own validation).
FACE_META_AGENT = READ_CORE + [
    "get_portfolio_snapshot",
    "ensure_company_ready", "start_issuer_research", "start_exposure_run", "respond",
]
FACE_RESEARCH = READ_CORE + ["search_external_research", "submit_brief"]


def available(registry, face: list[str]) -> list[str]:
    """The subset of a face that is actually registered (P5 has only READ_CORE)."""
    return [name for name in face if name in registry.tools]
