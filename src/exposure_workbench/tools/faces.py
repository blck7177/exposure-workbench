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

# V1: EVERY FACE IS MADE OF THE SAME TWELVE VERBS (tools/primitives). Until V1 the
# faces were cut out of one read registry — describe, read_fundamentals, compute,
# run, … — and `run` took a program in a language of its own; that language and
# the tools it replaced are retired, and the verbs below are what remains.
#
# The lead analyst holds NO face: it asks analysts (agents/delegation) and reads
# the record, in-process. The mount named "meta" survives as the debug door a
# person opens from a terminal (apps/mcp/server): every verb, no agent behind it.
FACE_META_AGENT = ["list", "filings_read", "prices_read", "book_read", "metric", "calc",
                   "filings_search", "filings_section", "web_search", "scenario", "start"]

# The research run writes an Issuer Risk Brief: an issuer from its filings and
# its price. The issuer analyst's verbs, the price read, both families' measures
# by name, the pause, and its exit. It starts nothing — the workflow that runs it
# prepared the name — and it never reads the book: a brief is about the issuer,
# not about whoever holds it.
FACE_RESEARCH = ["list", "filings_read", "prices_read", "metric", "calc",
                 "filings_search", "filings_section", "web_search", "think", "submit_brief"]

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
