"""P1.3 — the stdio door has an identity, and no connection of its own (offline).

The MCP server opened its own engine on DATABASE_URL. That URL is the OWNER
role, which bypasses row-level security entirely, and it then ran every call
under one process-global session with owner_id=None. So the one path in this
system where a tool call reached the database outside the tenant mechanism was
the agent-facing one — the same shape as the incident that made `service_role`
a byword: an agent path holding a credential that RLS does not apply to.

The door is now local-dev debugging only, and it says whose it is:
MCP_STDIO_USER_ID is required, checked against the users table at startup, with
no demo fallback. What makes that stick is not the check but the import graph —
a module that cannot construct an engine cannot acquire the owner role by a
later plausible-looking edit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "apps" / "mcp" / "server.py"


def _names_used(tree: ast.AST) -> set[str]:
    """Imported names plus attribute/callable names, so both

        from sqlalchemy.ext.asyncio import create_async_engine
        sqlalchemy.ext.asyncio.create_async_engine(...)

    are visible. Read as a graph rather than as text: the module docstring names
    the very things it forbids, and a substring check would call the explanation
    a violation.
    """
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                used.add(a.name)
                used.add(a.asname or a.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            used.add(node.module or "")
            for a in node.names:
                used.add(a.name)
                used.add(a.asname or a.name)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Name):
            used.add(node.id)
    return used


def test_the_mcp_module_cannot_build_a_database_connection():
    used = _names_used(ast.parse(SERVER.read_text()))
    forbidden = {"create_async_engine", "async_sessionmaker", "create_engine", "sessionmaker"}
    offenders = sorted(used & forbidden)
    assert not offenders, (
        "the agent-facing door must borrow the app's app_rls factory, not open a "
        f"connection whose role RLS does not bind: {offenders}"
    )


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Every string constant that is a docstring, by identity.

    Needed because this module's docstring names DATABASE_URL in order to say it
    is forbidden — the first version of the test below read that sentence as the
    violation, which is the failure mode the module's own comment warns about.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def test_the_mcp_module_does_not_read_a_database_url():
    """The owner role arrived through DATABASE_URL, so the name goes too.

    get_session_factory() reads settings.database_url_app internally; this module
    naming a URL at all means it is choosing a role, which is the decision it is
    no longer allowed to make.
    """
    tree = ast.parse(SERVER.read_text())
    docstrings = _docstring_nodes(tree)
    offenders = sorted(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and ("DATABASE_URL" in node.value or node.value.startswith("postgresql"))
    )
    assert not offenders, f"the door must not select its own database role: {offenders}"


def test_missing_stdio_user_is_a_startup_failure_naming_the_variable():
    from apps.mcp import server

    with pytest.raises(RuntimeError) as exc:
        server.stdio_user_id(env={})
    assert "MCP_STDIO_USER_ID" in str(exc.value)


def test_a_blank_stdio_user_is_not_an_identity():
    """An empty env var is how a shell hands over a variable it does not have."""
    from apps.mcp import server

    with pytest.raises(RuntimeError):
        server.stdio_user_id(env={"MCP_STDIO_USER_ID": "   "})


def test_there_is_no_demo_fallback_identity():
    """The worker has DEMO_SYSTEM_USER for tasks with no enqueuer. A debug door
    is always opened by somebody, so borrowing that default would only mean a
    trace nobody can attribute."""
    source = SERVER.read_text()
    assert "DEMO_SYSTEM_USER" not in source
    assert "user_demo" not in source


def test_the_dead_http_app_is_gone():
    """build_http_app() derived its schemas through FastMCP's signature
    inspection of a **kwargs handler, so every tool it published had a single
    string parameter called kwargs. It was never mounted, and a second transport
    implementation that disagrees with the first is the error class, not the bug.
    """
    from apps.mcp import server

    assert not hasattr(server, "build_http_app")


def test_the_door_states_its_identity_the_way_a_request_would():
    """R2. The constructor stopped taking an identity, so this door has to bind
    the same InternalClaims an HTTP request arrives with — once, at startup,
    because a stdio process is exactly one caller for its whole life.

    Read as a graph for the usual reason: the module docstring explains the
    binding, and a substring check would count the explanation.
    """
    used = _names_used(ast.parse(SERVER.read_text()))
    assert {"InternalClaims", "bind"} <= used, (
        "the stdio door must bind the claims its handlers read, or the first tool "
        "call raises NoMcpRequestBound"
    )


def test_the_door_does_not_issue_itself_a_bearer():
    """There is no request to authenticate here and no second party to prove
    anything to. A self-minted token would let the process hand itself an
    identity other than the one it just checked against the users table — a
    second source of truth about who is at the door, in the one place the answer
    is already known for certain."""
    used = _names_used(ast.parse(SERVER.read_text()))
    forbidden = sorted(used & {"mint", "verify", "bearer_identity", "require_secret"})
    assert not forbidden, f"the stdio door has no bearer to mint or verify: {forbidden}"
