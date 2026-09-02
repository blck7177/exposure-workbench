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

# Read + reflection tools available to every agent surface.
READ_CORE = [
    # V9-A2/A3. Any window, and one instant — the two primitives report analysis
    # is composed from. On both faces: an issuer's filings are issuer-scoped
    # facts, which is what the research face is for too.
    "get_flow",
    "get_balance_sheet",
    # V10-S2. The series axis of the same two primitives, and the one operator
    # over a series; describe_issuer is the single locating tool.
    "get_balance_series",
    "series_stat",
    "describe_issuer",
    # V9-A5. The four operators, typed: they refuse the combinations the
    # citation gate cannot see and allow every other one.
    "calculate",
    "rank",
    # V9-D/P. The method map, one measure, and all of them at once — the last
    # being a batch of the second, with no privileged path of its own.
    "evaluate_formula",
    "get_fundamental_panel",
    "get_market_stats",
    # V16 — the price side of price × fundamentals (H1) and the single-name
    # price analytics the book already had at portfolio level (H3). On both
    # faces for the same reason get_market_stats is: an issuer's market data
    # is issuer-scoped.
    "get_price",
    "get_price_series",
    "get_rolling_volatility",
    "get_beta",
    "regress_series",
    "get_momentum_12_1",
    "get_distance_from_52w_high",
    "get_adv",
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
# get_task_status, get_portfolio_positions and read_issuer_brief are meta-only for
# the same reason get_portfolio_snapshot is: they answer questions ABOUT this
# desk's own work rather than about an issuer's filings. read_issuer_brief is also
# kept off the research face deliberately — letting a brief-writing agent cite a
# previous brief's ids is a citation loop, not a source.
META_ONLY_READS = [
    "get_portfolio_snapshot", "get_task_status", "get_portfolio_positions", "read_issuer_brief",
    # V8-A. The run's own findings. Meta-only for the same reason as the four
    # above: they answer questions about THIS DESK's portfolios, and the research
    # face is issuer-scoped by construction. A brief-writing agent that could
    # read the book's attribution would be writing about the holder, not the
    # issuer.
    "get_attribution", "get_risk_state", "list_run_alerts", "list_risk_limits",
    "get_run_freshness",
    # V8-B. One call that reconciles a day's move, built on get_attribution's
    # own service rather than a second copy of the query.
    "reconcile_move",
    # V14-A. The ordering, the netting and the distances, done once server-side.
    # Meta-only for the same reason as the rest of this block: it answers a
    # question about THIS DESK's book. It sits beside reconcile_move rather than
    # inside get_portfolio_snapshot deliberately — the snapshot frames a
    # question and is called first every time, and putting a run's whole
    # analysis into it would make every conversation pay for one.
    "get_portfolio_analysis",
    # V15-S2b. The book's own manifest and its read-by-name: what a run holds,
    # named the way the exit takes it, and the exact quantities a question
    # needs in one call. Meta-only like everything about THIS DESK's book.
    "describe_run", "read_quantities",
    # V8-D. When the book fell and what the window between two dates held. Both
    # are about a portfolio, so both are meta-only.
    "get_drawdown_episodes", "explain_episode",
]

FACE_META_AGENT = READ_CORE + META_ONLY_READS + [
    "ensure_company_ready", "start_issuer_research", "start_exposure_run", "respond",
]
FACE_RESEARCH = READ_CORE + ["search_external_research", "submit_brief"]

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
