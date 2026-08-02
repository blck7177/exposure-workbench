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


def test_providers_do_not_import_upwards():
    """Import direction is one-way: apps -> tools -> services -> providers/db.
    A provider reaching back into services is how a transport detail ends up
    deciding business behaviour."""
    offenders = []
    for f in (ROOT / "src" / "exposure_workbench" / "providers").glob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if re.match(r"\s*(from|import)\s+.*exposure_workbench\.(services|tools|agents)", line):
                offenders.append(f"{f.name}:{i} {line.strip()}")
            if re.match(r"\s*(from|import)\s+apps\.", line):
                offenders.append(f"{f.name}:{i} {line.strip()}")
    assert offenders == [], f"providers importing upwards: {offenders}"


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
# faces.available() TRIMS silently by design (P5 had only READ_CORE registered),
# which is fine as a mechanism and dangerous as a habit: a declaration nobody
# checks drifts from the registry and the drift shows up as a capability the
# model was told about and cannot call.
#
# Asserted by EQUALITY, not containment, so an entry cannot outlive the drift it
# documents. The single entry here is real and is NOT this phase's to fix: the
# MCP server declares the meta-agent face while building only the read registry,
# so its four delegation/gate tools are trimmed away. That belongs to
# MCP_BOUNDARY_PLAN, which gives MCP a face of its own; pinning it here stops it
# growing a fifth in the meantime.
KNOWN_TRIMMED = {
    ("apps/mcp/server.py", "FACE_META_AGENT", "build_read_registry"):
        {"ensure_company_ready", "respond", "start_exposure_run", "start_issuer_research"},
}


def _pairings():
    from exposure_workbench.agents.meta_agent import build_meta_registry
    from exposure_workbench.tools import faces
    from exposure_workbench.tools.definitions import build_read_registry
    from exposure_workbench.workflow.issuer_research_workflow import build_research_registry
    return [
        ("apps/api (chat)", "FACE_META_AGENT", "build_meta_registry",
         faces.FACE_META_AGENT, build_meta_registry()),
        ("issuer_research_workflow", "FACE_RESEARCH", "build_research_registry",
         faces.FACE_RESEARCH, build_research_registry()),
        ("apps/mcp/server.py", "FACE_META_AGENT", "build_read_registry",
         faces.FACE_META_AGENT, build_read_registry()),
    ]


def test_no_face_declares_a_tool_its_registry_does_not_register():
    from exposure_workbench.tools import faces

    drift = {}
    for site, face_name, builder, face, registry in _pairings():
        missing = set(face) - set(faces.available(registry, face))
        if missing:
            drift[(site, face_name, builder)] = missing

    assert drift == KNOWN_TRIMMED, (
        f"new drift: { {k: v for k, v in drift.items() if k not in KNOWN_TRIMMED} }; "
        f"fixed but still listed: { {k: v for k, v in KNOWN_TRIMMED.items() if k not in drift} }"
    )
