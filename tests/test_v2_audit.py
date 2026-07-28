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
