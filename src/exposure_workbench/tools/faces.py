"""Tool faces (M10) — declarative capability sets.

A face is just a list of tool names. "What can an agent do" is answered in one
place, as data, so an auditor sees the whole surface at a glance and skip-flags
(P6) narrow it by removing names, not by branching inside a tool.

FACE_META_AGENT and FACE_RESEARCH gain their delegation/gate tools in P6/P7;
here we define the read+reflection core they share. Every consumer of a face —
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

# Read + reflection tools available to every agent surface (V23: the data
# domains an issuer question needs, the one compute, and the pause).
READ_CORE = [
    "describe",
    "read_fundamentals",
    "read_filings",
    "read_prices",
    "compute",
    "think",
]

# The meta face adds the desk's own book (read_book), the web, delegation and
# the exit. read_book is meta-only for the reason the old portfolio reads
# were: it answers questions about THIS DESK's book, and the research face is
# issuer-scoped by construction — a brief-writing agent reading the book's
# weights would be writing about the holder, not the issuer.
META_ONLY_READS = ["read_book"]

FACE_META_AGENT = READ_CORE + META_ONLY_READS + [
    "search_web",
    "start", "respond",
]
FACE_RESEARCH = READ_CORE + ["search_web", "submit_brief"]

# What a face is CALLED, once (MCP_PLAN R1). The resident server mounts each face
# at /mcp/<name> and every token carries the name it was minted for, so the same
# string is spelled by the mount, by the minting caller and by the verifier. Three
# literals would let a token minted for "research" be spent on a mount that calls
# itself "research_face" — verify() would reject it, correctly, and the operator
# would go looking for a signature problem.
FACE_NAME_META = "meta"
FACE_NAME_RESEARCH = "research"


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
