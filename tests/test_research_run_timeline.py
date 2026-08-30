"""V7-U1/U3 — the research run tells the person waiting what it is doing (offline).

A cold issuer spends minutes in EDGAR ingest and embedding before the agent ever
starts, and the page showed one spinner for all of it — the steps were already
in the database, and nothing on the wire carried them. The regressions this file
guards are all silent ones: dropping the field leaves a page that still renders,
still polls, and is a spinner again; losing the id tie-break leaves a finished
step spinning forever; putting the demo portfolio id back attributes a signed-in
user's run to a book they do not own, and the brief reads correct while
reasoning about somebody else's holdings.

No database and no network: the handler is called directly over a session stub
that answers the two calls it makes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from apps.api.routes import research
from apps.api.schemas import WorkflowEventOut
from exposure_workbench.db.models import ResearchRun, WorkflowEvent

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
ISSUER_PAGE = WEB / "app" / "issuer" / "[ticker]" / "page.tsx"
ISSUER_LIB = WEB / "lib" / "issuer.ts"


class _StubResult:
    """Exactly the two calls the handler makes on a Result, and no others."""

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _StubSession:
    def __init__(self, rows):
        self._rows = rows
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _StubResult(self._rows)


def _run(**kw) -> ResearchRun:
    return ResearchRun(id="rrun_1", company_id="co_nvda", status="running",
                       triggered_by="manual", **kw)


def _event(**kw) -> WorkflowEvent:
    base = dict(id=7, run_id="rrun_1", step_name="ingest_filings", status="running",
                message="Ingesting 10-K/10-Q for NVDA", duration_ms=None,
                payload_summary={}, created_at=datetime.now(timezone.utc))
    return WorkflowEvent(**{**base, **kw})


def _patch_get_run(monkeypatch, run):
    async def _get_run(db, run_id):
        return run
    monkeypatch.setattr(research.research_run_service, "get_run", _get_run)


async def test_get_returns_the_steps_with_their_sentences(monkeypatch):
    """The step messages ARE the narrative — 'Ingesting 10-K/10-Q for NVDA' is
    what the page shows instead of a spinner, so the message has to survive the
    trip, not just the step name."""
    _patch_get_run(monkeypatch, _run())
    out = await research.get_research_run("rrun_1", db=_StubSession([_event()]))
    assert [(e.step_name, e.message) for e in out.workflow_events] == [
        ("ingest_filings", "Ingesting 10-K/10-Q for NVDA")
    ]


async def test_events_are_read_by_run_id_and_ordered_with_id_as_the_tie_break(monkeypatch):
    """workflow_events has no FK and is polymorphic over three parents, so this
    is a hand-written query — and the client keeps only the LAST row per step
    name. Two rows of one step ('running', then 'completed') can share a
    created_at; without the id tie-break the finished step renders as running."""
    _patch_get_run(monkeypatch, _run())
    db = _StubSession([])
    await research.get_research_run("rrun_1", db=db)
    sql = str(db.statements[0])
    assert "FROM workflow_events" in sql
    assert "workflow_events.run_id = " in sql
    assert "ORDER BY workflow_events.created_at, workflow_events.id" in sql


async def test_a_missing_run_still_404s(monkeypatch):
    _patch_get_run(monkeypatch, None)
    with pytest.raises(HTTPException) as e:
        await research.get_research_run("rrun_nope", db=_StubSession([]))
    assert e.value.status_code == 404


def test_the_field_is_the_shared_event_model():
    """Two definitions of one shape agree until somebody adds a field to one of
    them; the exposure route and this one answer with the same class."""
    field = research.ResearchRunOut.model_fields["workflow_events"]
    assert field.annotation == list[WorkflowEventOut]


def test_a_freshly_enqueued_run_serializes_with_no_events():
    """POST answers from the ORM row directly — a run that was just created has
    no events yet, and that has to be an empty timeline rather than a 500 on a
    missing attribute."""
    out = research.ResearchRunOut.model_validate(_run())
    assert out.workflow_events == []


def test_research_runs_have_no_events_relationship_to_load_instead():
    """The reason the handler queries by hand. If this ever grows a
    relationship, the query above becomes the wrong way to do it — and until
    then, 'simplifying' it into a selectinload silently returns nothing."""
    assert not hasattr(ResearchRun, "workflow_events")


def _web_sources() -> list[Path]:
    skip = {"node_modules", ".next"}
    return [p for p in WEB.rglob("*")
            if p.suffix in {".ts", ".tsx", ".js", ".jsx", ".json"}
            and not skip & set(p.parts)]


def test_the_demo_portfolio_id_is_not_written_down_in_the_web_app():
    """`portfolio_id: "port_001"` was sent on every research run, so a signed-in
    user researching from their own book had it recorded against the shared demo
    and the brief's portfolio implications written about the wrong holdings. The
    API takes the field as optional; absent is the correct thing to send."""
    hits = [str(p.relative_to(WEB)) for p in _web_sources() if "port_001" in p.read_text()]
    assert hits == [], f"the demo portfolio id is hardcoded in: {hits}"


def test_the_issuer_page_takes_the_portfolio_from_the_url():
    src = ISSUER_PAGE.read_text()
    assert "useSearchParams" in src and '"portfolio"' in src
    assert "startResearch(tk, portfolioId)" in src


def test_both_run_views_share_one_step_collapse_and_say_why_a_run_stopped():
    """Two copies of the step collapse drift the moment one page meets a step
    type the other has not; and error_message is a written sentence (V4-S1) that
    reached the API and stopped at the screen, where the run said only 'failed'.

    The component that used to hold the collapse was retired in V13-S6c — the
    exposure run is a folded record at the foot of the book and the research run
    is a live panel on an issuer, and they no longer look alike. What they must
    still share is the collapse itself, so this names the module rather than the
    component: the guard is about there being ONE of it, not about where it is
    drawn.
    """
    shared = WEB / "app" / "components" / "steps.ts"
    assert shared.exists(), "the shared step collapse is gone; two pages will drift"

    readers = [p for p in _web_sources() if "collapseSteps" in p.read_text()
               and p.name != "steps.ts"]
    assert len(readers) >= 2, (
        f"only {[p.name for p in readers]} uses the shared collapse — the other run "
        "view has grown its own copy"
    )

    issuer = ISSUER_PAGE.read_text()
    assert "collapseSteps" in issuer, "the issuer page must collapse steps the shared way"
    # The failure sentence: explainRunError is what turns a code into it, and it
    # is given error_message so a message the API vouched for wins over wording.
    assert "explainRunError(run.error_code, run.error_message)" in issuer
