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

# V36: the face is the SURFACE, and a surface wider than what anything reaches
# through it is an audit statement nobody can rely on. The lead analyst has no
# tools on this face at all now — it delegates, in-process — and a domain
# analyst reaches exactly four: one computes (`run`, every node typed and on the
# ledger), two read text, one puts an issuer on the desk. `describe` went with
# the pull-catalogue it served (the BRIEFING is pushed), `read_book` with it;
# `respond` and `think` were the old exit and the old pause, and V33 replaced
# the first with prose against the answer check and never needed the second.
# They stay REGISTERED — a read registry is what it is — but a face names what
# can actually be reached.
FACE_META_AGENT = [
    "run", "read_filings", "search_web", "start",
]

# V31 (Phase 2): so does the research face, and it files its brief in the same
# grammar the reply uses. `read_fundamentals`, `read_prices` and `compute` are
# off it — every issuer measure, price statistic, series and piece of arithmetic
# they offered is a program (docs/PROGRAM_LANGUAGE.md), and a program is one
# call whose every node is typed and recorded. They stay registered because
# READ_CORE is what a read registry builds; what a face NAMES is the surface.
FACE_RESEARCH = ["describe", "run", "read_filings", "search_web", "think", "submit_brief"]

# What a face is CALLED, once (MCP_PLAN R1). The resident server mounts each face
# at /mcp/<name> and every token carries the name it was minted for, so the same
# string is spelled by the mount, by the minting caller and by the verifier. Three
# literals would let a token minted for "research" be spent on a mount that calls
# itself "research_face" — verify() would reject it, correctly, and the operator
# would go looking for a signature problem.
FACE_NAME_META = "meta"
FACE_NAME_RESEARCH = "research"

# V1: the three analysts. A face is a RESOURCE FAMILY — filings, prices, the book
# — and each is its own mount with its own registry (tools/primitives
# .build_analyst_registry), so what an analyst cannot reach is not refused: it is
# not there, neither the verb nor the measure's name in an enum. `submit`, the
# analyst's exit, is in-process (agents/delegation) and on no face.
FACE_NAME_ISSUER = "issuer"
FACE_NAME_MARKET = "market"
FACE_NAME_RISK = "risk"
FACE_ISSUER = ["list", "filings_read", "metric", "calc", "filings_search", "filings_section", "web_search", "start"]
FACE_MARKET = ["list", "prices_read", "metric", "calc", "start"]
FACE_RISK = ["list", "book_read", "metric", "calc", "scenario", "start"]
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
