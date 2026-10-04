"""Tool faces (M10) — declarative capability sets.

A face is just a list of tool names. "What can an agent do" is answered in one
place, as data, so an auditor sees the whole surface at a glance and skip-flags
(P6) narrow it by removing names, not by branching inside a tool.

Every face is a list of the verbs below; the agents' in-process tools (ask, open)
are on no face. Every consumer of a face —
the meta-agent loop, the research session, the MCP server that fronts them — is
handed the same tools under the same enforcement, with no privileged channel.

Resolving a face is strict (P1.1). The predecessor, available(), returned the
subset that happened to be registered, which meant a caller could ask for the
meta-agent face, receive the read face, and be told nothing: the four
delegation/gate tools went missing from the MCP server on every startup for two
phases before a test caught it. A face is a promise about what an agent can do,
so a face naming a tool its registry does not have is a build error, not a
smaller face.
"""

from __future__ import annotations

# THE VERBS. `analyze` is one intent as a table (measures over a scope, compared and
# ranked; tools/analysis_tools); `list` is the catalogue, names and dates only;
# `metric` a registry method over subjects; the text reads quote filings and the web;
# `scenario` and `start` act. The per-cell reads (`filings_read`, `book_read`,
# `prices_read` by date) and `calc` over hand-picked operands are the DEBUG door's: a
# person at a terminal may want a cell, an agent expresses an intent.
FACE_META_AGENT = ["list", "analyze", "filings_read", "prices_read", "book_read", "metric", "calc",
                   "filings_search", "filings_section", "web_search", "scenario", "start"]

# The lead analyses and reads the catalogue; everything else it asks a specialist for.
FACE_LEAD = ["list", "analyze"]

# The research run writes an Issuer Risk Brief: an issuer from its filings and its
# price. It analyses, takes measures by name, reads the filings' text and the web.
FACE_RESEARCH = ["list", "analyze", "metric", "prices_read", "filings_search", "filings_section", "web_search"]

# What a face is CALLED, once (MCP_PLAN R1). The resident server mounts each face
# at /mcp/<name> and every token carries the name it was minted for, so the same
# string is spelled by the mount, by the minting caller and by the verifier.
FACE_NAME_META = "meta"
FACE_NAME_LEAD = "lead"
FACE_NAME_RESEARCH = "research"

# The three specialists. A face is a RESOURCE FAMILY — filings, prices, the book —
# and each is its own mount with its own registry (tools/primitives
# .build_analyst_registry), so what a specialist cannot reach is not refused: it is
# not there, neither the verb nor the measure's name in an enum.
FACE_NAME_ISSUER = "issuer"
FACE_NAME_MARKET = "market"
FACE_NAME_RISK = "risk"
FACE_ISSUER = ["list", "analyze", "metric", "filings_search", "filings_section", "web_search", "start"]
FACE_MARKET = ["list", "analyze", "metric", "prices_read", "start"]
FACE_RISK = ["list", "analyze", "metric", "scenario", "start"]
ANALYST_FACES: dict[str, list[str]] = {
    FACE_NAME_ISSUER: FACE_ISSUER, FACE_NAME_MARKET: FACE_MARKET, FACE_NAME_RISK: FACE_RISK,
}


class FaceNotRegistered(RuntimeError):
    """A face names a tool its registry does not register."""


def resolve(registry, face: list[str]) -> list[str]:
    """The face, in declared order, or a raise naming exactly what is absent.

    The message lists the missing names only. Printing the whole face buries the
    two that matter among the eighteen that are fine.
    """
    missing = [name for name in face if name not in registry.tools]
    if missing:
        raise FaceNotRegistered(
            f"face declares {len(missing)} tool(s) the registry does not register: "
            + ", ".join(missing)
        )
    return list(face)
