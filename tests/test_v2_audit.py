"""V2-G — the invariants that hold the multi-user story together (offline).

Each one encodes a decision that is easy to break by accident and impossible to
notice at runtime: a new write route without a gate looks fine until someone
tries it anonymously; a new table without a policy looks fine until two users
exist; a filter written for safety instead of semantics looks fine forever,
because it works — right up until the day somebody removes it as redundant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "apps" / "api" / "routes"
INIT_SQL = ROOT / "infra" / "init.sql"

# infra/init.sql line "ALTER TABLE x ENABLE ROW LEVEL SECURITY", mirroring the
# ownership table in IMPLEMENTATION_PLAN_V2 section 0.6.
TENANT_TABLES = {
    "users", "portfolios", "agent_sessions", "research_runs", "issuer_briefs",
    "positions", "risk_limits", "schedules", "exposure_runs", "daily_reports",
    "exposure_metrics", "sector_exposures", "issuer_exposures",
    "factor_attributions", "factor_residuals", "risk_alerts", "workflow_events",
    "agent_messages", "agent_steps", "evidence_packs",
}

# Shared on purpose. Each is a considered decision, not an omission:
#   company-level evidence is public fact and copying it per user would be both
#   wasteful and inconsistent; tasks is a system queue the worker must see whole;
#   usage_daily holds the cross-tenant backstop, and a tenant policy there would
#   make it count only the caller — a fail-OPEN limit, worse than none.
SHARED_TABLES = {
    "companies", "filings", "filing_documents", "filing_sections", "filing_chunks",
    "financial_facts", "research_sources", "calc_ledger", "market_prices",
    "factor_prices", "security_master", "tasks", "usage_daily",
}


def _rls_enabled() -> set[str]:
    return set(re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", INIT_SQL.read_text()))


def _declared_tables() -> set[str]:
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", INIT_SQL.read_text()))


def test_every_table_is_deliberately_tenant_scoped_or_deliberately_shared():
    """A table in neither set is a table nobody decided about."""
    undecided = _declared_tables() - TENANT_TABLES - SHARED_TABLES
    assert undecided == set(), f"tables with no ownership decision: {sorted(undecided)}"


def test_every_tenant_table_actually_has_rls_enabled():
    missing = TENANT_TABLES - _rls_enabled()
    assert missing == set(), f"listed as tenant-scoped but no RLS: {sorted(missing)}"


def test_no_shared_table_has_rls_switched_on_by_accident():
    """Turning RLS on here is not a harmless tightening. usage_daily would stop
    counting the global pool correctly, and the worker's tenant-less reaper would
    stop seeing the tasks it exists to settle."""
    wrong = SHARED_TABLES & _rls_enabled()
    assert wrong == set(), f"shared tables must not carry RLS: {sorted(wrong)}"


def _write_routes() -> list[tuple[str, str, str]]:
    found = []
    for f in sorted(ROUTES.glob("*.py")):
        src = f.read_text()
        for m in re.finditer(
            r"@router\.(post|put|patch|delete)\(.*?\)\s*\nasync def (\w+)\((.*?)\n\):",
            src, re.DOTALL,
        ):
            found.append((f.name, m.group(2), m.group(3)))
    return found


def test_there_are_write_routes_to_check():
    assert len(_write_routes()) >= 8, "the parser found suspiciously few routes"


@pytest.mark.parametrize("route", _write_routes(), ids=lambda r: f"{r[0]}:{r[1]}")
def test_every_write_route_requires_a_user(route):
    """Reads are public by design; writes are not. There is no third state."""
    _, name, signature = route
    assert "require_user" in signature, f"{name} accepts writes without authentication"


# Route modules with a POST that deliberately charges nothing. Empty, and it
# should stay that way — an entry here is a decision someone has to defend.
UNCHARGED_WRITE_MODULES: set[str] = set()


def test_every_module_with_a_write_route_charges_something():
    """The uncharged write path is the one that gets found by a reviewer rather
    than by a test. Four of them shipped this way — portfolio create, clone,
    upload and session create — and the worst could drive ~400 provider calls
    per request with nothing counting. A module with a POST either reaches the
    quota or is named here on purpose."""
    offenders = []
    for f in sorted(ROUTES.glob("*.py")):
        src = f.read_text()
        if "@router.post" not in src or f.stem in UNCHARGED_WRITE_MODULES:
            continue
        # Directly, or via a service that charges on its behalf.
        if "usage_service" in src or "create_task" in src:
            continue
        offenders.append(f.name)
    assert offenders == [], (
        f"write routes with no quota behind them: {offenders}. Charge them, or add "
        f"the module to UNCHARGED_WRITE_MODULES with a reason."
    )


def test_the_upload_gate_sits_after_the_free_checks():
    """Ordering is 401 -> 404 -> 403 -> 422 parse -> 429 -> 422 upload, and it is
    load-bearing in both directions. Billing before parse_csv would charge for a
    malformed file that cost the server nothing; billing after upload_positions
    would charge only successes, when the ~400 provider calls are already spent
    by the time the rejection is decided. It reads like an inconsistency with the
    401->404->403->429 order used elsewhere, so it is pinned rather than left to
    be tidied up."""
    src = (ROUTES / "portfolios.py").read_text()
    body = src[src.index('@router.post("/portfolios/{portfolio_id}/upload")'):]
    body = body[:body.index("@router.get")]

    forbidden = body.index('403, "not your portfolio"')
    parse = body.index("portfolio_csv.parse_csv")
    charge = body.index('"position_upload"')
    upload = body.index("portfolio_service.upload_positions")

    assert forbidden < parse < charge < upload, (
        "the position_upload charge moved; see the docstring before changing it"
    )


def test_semantic_owner_filters_are_labelled():
    """Application-layer owner checks are allowed only as business semantics —
    the database is what isolates tenants. The label is what stops the next
    reader from mistaking one for a security control and 'simplifying' the RLS
    policy away, or from deleting the check as redundant and losing the 403."""
    unlabelled = []
    for f in [*ROUTES.glob("*.py"),
              *(ROOT / "src" / "exposure_workbench").rglob("*.py")]:
        lines = f.read_text().splitlines()
        for i, line in enumerate(lines):
            if not re.search(r"\.owner_id\s*[!=]=|\.owner_user_id\s*==", line):
                continue
            window = "\n".join(lines[max(0, i - 6): i + 1])
            if "semantic, not security" not in window:
                unlabelled.append(f"{f.relative_to(ROOT)}:{i + 1}")
    assert unlabelled == [], f"owner filters with no semantic/security label: {unlabelled}"


# Import direction is one-way: apps -> tools -> services -> providers/db, and
# agents -> tools. A layer reaching upwards is how a transport detail ends up
# deciding business behaviour.
#
# The agents entry was added when the MCP face needed a home: it was written
# under apps/mcp/ first, where the agents that consume it could not have
# imported it without inverting the rule. The face belongs to the tool layer,
# and this is what says so.
_UPWARD = {
    "providers": r"exposure_workbench\.(services|tools|agents|workflow)",
    "analytics": r"exposure_workbench\.(services|tools|agents|workflow|providers)",
    "agents": r"exposure_workbench\.(providers)",
    "tools": r"exposure_workbench\.(agents|workflow)",
}


def test_no_layer_imports_upwards():
    offenders = []
    for package, upward in _UPWARD.items():
        for f in (ROOT / "src" / "exposure_workbench" / package).rglob("*.py"):
            for i, line in enumerate(f.read_text().splitlines(), 1):
                where = f"{package}/{f.name}:{i} {line.strip()}"
                if re.match(rf"\s*(from|import)\s+.*{upward}", line):
                    offenders.append(where)
                # apps/ is the top of the graph; nothing under src/ may reach it.
                if re.match(r"\s*(from|import)\s+apps[\s.]", line):
                    offenders.append(where)
    assert offenders == [], f"layers importing upwards: {offenders}"


def test_unbounded_growth_paths_carry_a_ceiling():
    """Not every write route enqueues a task, so not every one is quota-charged.
    The ones that create rows directly need their own bound, or a single free
    account can grow the shared database with nothing showing on the dashboard."""
    from exposure_workbench.services import portfolio_service
    from apps.api.routes import agent, market_data

    assert portfolio_service.MAX_PORTFOLIOS_PER_USER <= 100
    assert hasattr(portfolio_service, "TooManyPortfolios")
    assert agent.MAX_MESSAGE_CHARS <= 32_000, "one charged turn must not carry unbounded prompt"
    assert market_data.MAX_SYNC_TICKERS <= 100


# ─── The erasure script agrees with the ownership table ───────────────────────

def _deletion_order() -> list[str]:
    """The real list the script will execute, not a copy of it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_delete_user_under_test", ROOT / "scripts" / "delete_user.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # imports psycopg2, opens no connection
    return [table for table, _predicate in mod.DELETION_ORDER]


def test_erasure_covers_every_table_that_holds_user_data():
    """The way a deletion script goes wrong is by missing a table nobody
    remembers — factor_residuals was absent from the ownership table in section
    0.6 for exactly that reason, and four of these tables have no foreign key to
    their parent, so a missed row is unreachable forever afterwards."""
    expected = TENANT_TABLES | {"tasks", "usage_daily"}
    actual = set(_deletion_order())
    assert actual == expected, (
        f"missing from the erasure script: {sorted(expected - actual)}; "
        f"deleted but not owned by a user: {sorted(actual - expected)}"
    )


def test_erasure_never_touches_a_shared_table():
    """Company evidence is other tenants' data. Deleting a companies row would
    cascade seven ways out of this user's account."""
    assert set(_deletion_order()) & SHARED_TABLES == {"tasks", "usage_daily"}


def test_erasure_order_deletes_children_before_parents():
    """Two foreign keys into portfolios are NO ACTION, not CASCADE, so getting
    this order wrong is a mid-transaction integrity error rather than a silent
    partial erasure — but only for those two. The rest cascade, which is exactly
    why the order is asserted here instead of being left to the database."""
    order = _deletion_order()
    position = {table: i for i, table in enumerate(order)}

    sql = INIT_SQL.read_text()
    violations = []
    for block in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", sql, re.S):
        child, body = block.group(1), block.group(2)
        if child not in position:
            continue
        for parent in re.findall(r"REFERENCES\s+(\w+)\s*\(", body):
            if parent in position and position[child] > position[parent]:
                violations.append(f"{child} deleted after its parent {parent}")

    assert violations == [], violations


def test_the_context_check_sits_before_the_charge_and_never_releases_the_turn():
    """V3-B1, and two invariants in one test because they share a cause.

    Order: a turn the server will not run must not cost a quota unit, so the
    413 has to be decided before charge(). Both the 409 and the 429 beside it
    already work this way.

    Absence: the check lives inside `async with ... gate_db.begin()`, so raising
    rolls the claim_turn UPDATE back — and that rollback IS the release. An
    explicit release_turn would open a SECOND connection onto the row lock this
    transaction still holds, and release_turn swallows every exception, so the
    symptom would be a request that hangs for ever with nothing in any log.
    """
    src = (ROUTES / "agent.py").read_text()
    body = src[src.index("async def post_message("):]

    claim = body.index("claim_turn")
    in_flight = body.index('"turn_in_flight"')
    context = body.index('"session_context_exhausted"')
    charge = body.index('"chat_turn"')

    assert claim < in_flight < context < charge, (
        "the context check moved relative to the quota charge; see the docstring"
    )
    # Code only: the comment right beside it explains why the call must not be
    # there, and a check that cannot tell an explanation from a call is a check
    # that punishes documenting the reason.
    gate_code = "\n".join(ln for ln in body[claim:charge].splitlines()
                          if not ln.lstrip().startswith("#"))
    assert "release_turn(" not in gate_code, (
        "the gate transaction must not release the turn explicitly — the rollback does it"
    )


# ── V3-C5: a face may not promise a tool the registry does not have ──────────
# A declaration nobody checks drifts from the registry, and the drift shows up as
# a capability the model was told about and cannot call.
#
# P1.1 moved the enforcement into faces.resolve(), which raises. This test used to
# MEASURE the drift with available() and carry a KNOWN_TRIMMED entry for the one
# real instance — apps/mcp/server.py declaring the meta face over the read
# registry. Both are gone: the mechanism that made that state reachable was
# deleted, and the server now declares the face it builds. What is left is the
# structural sweep — every shipped (site, face, registry) triple, resolved.
#
# MCP_PLAN R4 moved the sites. The agents no longer pair a face with a registry
# at all: they hold a face NAME and a minted token, and the pairing happens in
# the container. So the two mounts are read out of apps/mcp/http.py's own MOUNTS
# table rather than restated here — a copy of it would agree until somebody
# edited one of them.
def _pairings(monkeypatch):
    from tests.mcp_mount import use_secret

    # http.py refuses to import without a signing key, deliberately: an
    # unverified tool face must not be able to come up. That is asserted where
    # it belongs (test_internal_token); here it is just a precondition.
    use_secret(monkeypatch)
    from apps.mcp import http

    from exposure_workbench.tools import faces
    from exposure_workbench.tools.definitions import build_read_registry
    from exposure_workbench.tools.meta_tools import register_meta_tools

    return [
        (f"apps/mcp/http.py mount /mcp/{name}", name, registry, face)
        for name, (registry, face) in http.MOUNTS.items()
    ] + [
        ("apps/mcp/server.py (stdio)", "FACE_META_AGENT",
         register_meta_tools(build_read_registry()), faces.FACE_META_AGENT),
    ]


def test_no_face_declares_a_tool_its_registry_does_not_register(monkeypatch):
    from exposure_workbench.tools import faces

    drift = {}
    for site, face_name, registry, face in _pairings(monkeypatch):
        try:
            faces.resolve(registry, face)
        except faces.FaceNotRegistered as e:
            drift[(site, face_name)] = str(e)

    assert drift == {}, f"a shipped face no longer resolves: {drift}"


def test_the_shipped_mounts_are_the_two_agent_faces(monkeypatch):
    """N9 is a claim about how many doors there are, and it is only true while
    the mount table says so. A third mount, or one face served at two paths,
    would make 'the face is physical' a sentence rather than a fact."""
    from exposure_workbench.tools import faces

    mounts = {name: face for _site, name, _registry, face in _pairings(monkeypatch)
              if name in (faces.FACE_NAME_META, faces.FACE_NAME_RESEARCH)}
    assert mounts == {
        faces.FACE_NAME_META: faces.FACE_META_AGENT,
        faces.FACE_NAME_RESEARCH: faces.FACE_RESEARCH,
    }


def test_no_agent_reaches_a_tool_except_through_the_transport():
    """MCP_PLAN P3/P4: there is one way from a model to a tool.

    The claim is easy to state and easy to erode — the next loop, or a
    'temporary' shortcut inside an existing one, calls invoke() directly and
    everything still passes, because invoke() is where the enforcement is. What
    would be lost is not enforcement but singularity: two ways in means the face
    can differ between them, and the face is what caps agent depth at two and
    keeps the meta-only reads away from the brief writer.

    Read as an import graph rather than as text: tool_session's docstring names
    invoke() to explain what it returns.
    """
    import ast

    agents = ROOT / "src" / "exposure_workbench" / "agents"
    offenders = []
    for f in agents.glob("*.py"):
        if f.name == "tool_session.py":
            continue          # the one module whose job is to be that way in
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == "invoke" for a in node.names):
                offenders.append(f"{f.name}:{node.lineno} imports invoke")
            if isinstance(node, ast.Attribute) and node.attr == "invoke":
                offenders.append(f"{f.name}:{node.lineno} calls .invoke")
    assert offenders == [], f"an agent reaching a tool outside the transport: {offenders}"


def test_no_agent_imports_the_in_memory_transport():
    """R4/N11: there is one production transport, and it is the resident face.

    The in-memory helper is not gone — tests still build a server and talk to it
    without a container, which is the right way to assert what a handler does.
    What it must never be again is a second way for a LOOP to reach tools. It
    would work, too: same constructor, same wrapper, same trace. That is exactly
    what makes it dangerous — a turn served in-process is a turn whose tools ran
    under the api's own database role and whose identity never crossed a door,
    and nothing in its output would say so.

    An import graph rather than a call graph: the helper cannot be used without
    being imported, and naming it in agents/ is the moment to stop.
    """
    import ast

    agents = ROOT / "src" / "exposure_workbench" / "agents"
    offenders = []
    for f in agents.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            mod = getattr(node, "module", None) or ""
            if isinstance(node, ast.ImportFrom) and mod.startswith("mcp.shared.memory"):
                offenders.append(f"{f.name}:{node.lineno}")
            if isinstance(node, ast.Import):
                offenders += [f"{f.name}:{node.lineno}" for a in node.names
                              if a.name.startswith("mcp.shared.memory")]
    assert offenders == [], (
        f"an agent loop reaching tools in-process instead of through the face: {offenders}"
    )


# MCP_PLAN N11: one production path to the tool face, and it is HTTP.
#
# mcp.shared.memory.create_connected_server_and_client_session built every agent
# tool session from P3 until R4. It did its job — it made "the agent path IS the
# MCP path" literally true before the topology moved — and R4 replaced it with a
# client against the resident mount. What is left of it is a TEST FIXTURE: the
# stdio door's live tests drive a server object that has no socket, which is
# exactly what an in-memory pair is for.
#
# The reason it needs a guard rather than a note is that it is the perfect
# shortcut. It is one import away, it needs no container, and a loop rebuilt on
# it would pass every functional test in this repo while running the tools back
# inside api or worker — no bearer, no door, no single place the tool face lives.
# Two transports is the shape this plan exists to prevent, and the second one
# would arrive looking like a convenience.
_IN_MEMORY_TRANSPORT = "mcp.shared.memory"
_IN_MEMORY_HELPER = "create_connected_server_and_client_session"


def _production_modules():
    """Everything that ships, which is src/ plus the three app entry points.

    apps/web is a Next app; it has no Python and its node_modules would make
    this sweep a filesystem walk of somebody else's dependencies.
    """
    yield from (ROOT / "src" / "exposure_workbench").rglob("*.py")
    for package in ("api", "mcp", "worker"):
        yield from (ROOT / "apps" / package).rglob("*.py")


def test_no_shipped_module_reaches_the_tools_through_the_in_memory_helper():
    """N11's guard. Named for the agents layer, swept over the whole production
    tree, because the helper has no legitimate caller anywhere outside tests and
    a second production transport is no better for being in workflow/."""
    import ast

    offenders = []
    for f in _production_modules():
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            module = getattr(node, "module", None) or ""
            if isinstance(node, ast.ImportFrom) and module.startswith(_IN_MEMORY_TRANSPORT):
                offenders.append(f"{f.relative_to(ROOT)}:{node.lineno} imports {module}")
            if isinstance(node, ast.Import) and any(
                a.name.startswith(_IN_MEMORY_TRANSPORT) for a in node.names
            ):
                offenders.append(f"{f.relative_to(ROOT)}:{node.lineno} imports the helper's module")
            if isinstance(node, ast.Name) and node.id == _IN_MEMORY_HELPER:
                offenders.append(f"{f.relative_to(ROOT)}:{node.lineno} calls {_IN_MEMORY_HELPER}")
    assert offenders == [], f"a second, in-process transport to the tool face: {offenders}"


def test_the_agents_hold_a_face_name_and_a_token_and_nothing_else():
    """The other half of R4, and the reason the guard above can be absolute.

    A client that still held a registry would be holding the thing it is
    supposed to be reaching through, and a client holding a db_factory would be
    the tools' database open inside api and worker — the two duplications the
    resident face exists to remove. Both are absences now, and an absence is
    what a test has to keep.
    """
    import ast
    import inspect

    from exposure_workbench.agents.tool_session import tool_session

    parameters = inspect.signature(tool_session).parameters
    assert list(parameters) == ["face_name", "session_id", "user_id", "message_id", "deny"]

    agents = ROOT / "src" / "exposure_workbench" / "agents"
    offenders = []
    for f in agents.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("tools.registry"):
                offenders.append(f"{f.name}:{node.lineno} imports the registry")
            if isinstance(node, ast.ImportFrom) and any(
                a.name in ("build_mcp_server", "get_session_factory") for a in node.names
            ):
                offenders.append(f"{f.name}:{node.lineno} imports {node.names[0].name}")
    assert offenders == [], f"an agent still holding what lives behind the mount: {offenders}"
