"""V1 step 4 (docs/IMPLEMENTATION_PLAN_V1.md §2.1, §2.4): one analyst, start to
brief, on its own face. Offline: a scripted provider and a fake tool session; the
protocol, the handoff check, the ledger and the row renderer are real.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from exposure_workbench.agents import delegation as dl, sub_analyst as sa
from exposure_workbench.analytics import handbook, registry
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.tools import faces

WHY = "line 1 asks how big the name is; its weight is on the holdings table"
WEIGHT = {"id": "f_w1a2b3c4d5e6", "kind": "scalar", "measure": "issuer_exposures.weight", "subject": "MSFT",
          "unit": "RATIO", "value": 0.16, "as_of": "2026-09-10", "window": None, "params": {"pull": "r_1"},
          "standalone": True, "sources": ["run_x"], "group": "composition", "means": {}}
FINDING = "MSFT weighs 16.0% [f_w1a2b3c4d5e6] of the book."
TASK = dl.Task("tsk_1", "risk", ("port_001",), ("how big MSFT is in the book",))


def _rows(*records, **more):
    return {"pull": "r_1", "head": f"r_1 book_read(…) → {len(records)} rows", "rows": [F.line(r) for r in records],
            "_records": [dict(r) for r in records], **more}


class _Tools:
    """An analyst's tool session: every verb of every face is OFFERED, so a test
    can see which of them the analyst is actually given."""

    def __init__(self, result=None, by_name=None):
        self.tools = [{"type": "function", "function": {"name": n, "description": n, "parameters": {}}}
                      for n in sorted({n for f in faces.ANALYST_FACES.values() for n in f})]
        self.result, self.by_name = result or _rows(WEIGHT), by_name or {}
        self.calls, self.records, self.opened = [], [], []

    async def call(self, name, args, *, actor=None):
        self.calls.append((name, args, actor))
        res = dict(self.by_name.get(name, self.result))
        self.records += res.pop("_records", [])
        return res


def _ctx(monkeypatch, replies, tools: _Tools):
    seen: list[dict] = []
    script = iter(replies)

    async def _chat(**kw):
        seen.append({"tools": [t["function"]["name"] for t in kw["tools"]], "messages": list(kw["messages"]),
                     "tool_choice": kw.get("tool_choice")})
        return next(script, ("", None))

    steps: list[dict] = []

    async def _record(ctx, actor, step_type, tool_name, args, summary, facts=None, status="completed"):
        steps.append({"actor": actor, "type": step_type, "tool": tool_name, "args": args, "status": status,
                      "facts": list(facts or [])})
        tools.records += [F.for_record(f) for f in facts or []]

    async def _ledger(ctx):
        return Ledger.of(tools.records)

    stored: list[dict] = []

    async def _store(db, session_id, **cols):
        stored.append(cols)
        return "rep_1"

    monkeypatch.setattr(sa, "_record", _record)
    monkeypatch.setattr(sa, "_ledger", _ledger)
    monkeypatch.setattr(sa.analyst_reports, "store", _store)

    @asynccontextmanager
    async def _open(face):
        tools.opened.append(face)
        yield tools

    @asynccontextmanager
    async def _db():
        yield SimpleNamespace(commit=_noop)

    async def _noop():
        return None

    llm = SimpleNamespace(chat=_chat)
    ctx = sa.TurnContext(open_tools=_open, llm=llm, db_factory=_db, session_id="sess", message_id="msg", briefing={})
    return ctx, seen, steps, stored


def _call(name, **args):
    return [{"id": f"c_{name}", "function": {"name": name, "arguments": json.dumps(args)}}]


def _read(**args):
    return _call("book_read", **{"book": "port_001", "table": "issuer_exposures", "column": "weight", "why": WHY, **args})


def _submit(*lines, **more):
    return _call("submit", lines=list(lines), **more)


SETTLED = {"n": 1, "settled": True, "finding": FINDING, "facts": ["f_w1a2b3c4d5e6"]}


# ── what an analyst knows before it starts ───────────────────────────────────

@pytest.mark.parametrize("analyst", handbook.ANALYSTS)
def test_the_standing_text_is_the_role_and_the_chapter_and_no_language(analyst):
    text = sa.system_text(analyst)
    assert text.startswith(f"You are {handbook.CHAPTERS[analyst].title[0].lower()}{handbook.CHAPTERS[analyst].title[1:]}")
    assert handbook.chapter_text(analyst) in text
    assert all(p["id"] in text for p in registry.POLICY_ABSENCES)           # the boundary a policy line points at
    for gone in ("compile", "program", "THE LANGUAGE", "HOW EVERY RESULT IS READ", "node", "$"):
        assert gone not in text, gone
    other = [handbook.CHAPTERS[a].title.upper() for a in handbook.ANALYSTS if a != analyst]
    assert not [t for t in other if t in text]                               # no other family's chapter


async def test_it_opens_its_own_face_and_is_given_that_faces_verbs_only(monkeypatch):
    tools = _Tools()
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert tools.opened == ["risk"]
    assert seen[0]["tools"] == [*faces.FACE_RISK, "submit"]                 # offered every verb; given its own
    assert "filings_read" not in seen[0]["tools"] and "prices_read" not in seen[0]["tools"]
    user = seen[0]["messages"][1]["content"]
    assert sa.TASK_TAG in user and sa.COVERAGE_TAG in user and '"1. how big MSFT is in the book"' in user
    assert result.status == "settled" and result.lines == [SETTLED]
    assert tools.calls[0][2] == "sub:risk"


# ── the log is its calls ─────────────────────────────────────────────────────

async def test_every_call_says_why_and_the_log_is_made_of_those(monkeypatch):
    tools = _Tools()
    ctx, _seen, _steps, stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.log == [{"step": 1, "tool": "book_read",
                           "asked": 'book="port_001", table="issuer_exposures", column="weight"',
                           "why": WHY, "got": "1 rows"}]
    (record,) = stored                                           # what the page and `open` read
    assert record["domain"] == "risk" and record["status"] == "verified" and record["task_id"] == "tsk_1"
    assert record["brief"]["findings"] == [{"want": 1, "finding": FINDING}]
    assert record["text"] == dl.log_text(result) and f"why: {WHY}" in record["text"]


async def test_the_same_call_again_is_answered_from_before_and_not_charged(monkeypatch):
    tools = _Tools()
    again = _read(why="line 1 again, to be sure of the weight")          # the why changed; the call did not
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", _read()), ("", again), ("", _submit(SETTLED))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert len(tools.calls) == 1 and result.cost["evidence_calls"] == 1
    told = json.loads([m for m in seen[2]["messages"] if m.get("role") == "tool"][-1]["content"])
    assert "not charged" in told["repeated"] and told["rows"] == [F.line(WEIGHT)]


async def test_an_analyst_out_of_calls_is_told_to_file_what_it_has(monkeypatch):
    monkeypatch.setattr(get_settings(), "sub_analyst_evidence_calls", 1, raising=False)
    tools = _Tools()
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _read(column="market_value")),
                                                    ("", _submit(SETTLED))], tools)
    await sa.run_sub_analyst(TASK, ctx)
    told = json.loads([m for m in seen[2]["messages"] if m.get("role") == "tool"][-1]["content"])
    assert told["error"] == "analyst_budget" and len(tools.calls) == 1


async def test_a_start_is_not_evidence_and_is_made_once_per_subject(monkeypatch):
    issuer = dl.Task("tsk_2", "issuer", ("SNOW",), ("how levered it is",))
    tools = _Tools(by_name={"start": {"pull": "r_s", "head": "r_s start(…) → 0 rows", "rows": [], "task_id": "task_9"}})
    start = _call("start", kind="readiness", subject="SNOW", why="SNOW is not prepared; line 1 needs its filings")
    boundary = {"n": 1, "settled": False, "why": "SNOW is being prepared", "boundary": "f_policy_no_estimate"}
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", start), ("", start), ("", _submit(boundary))], tools)
    result = await sa.run_sub_analyst(issuer, ctx)
    assert [c[0] for c in tools.calls] == ["start"] and result.cost == {"completions": 3, "evidence_calls": 0, "starts": 1}
    told = json.loads([m for m in seen[2]["messages"] if m.get("role") == "tool"][-1]["content"])
    assert told["already_started"] == "task_9"
    assert result.status == "unsettled"                         # a brief that passed and settled nothing is not a success


async def test_a_book_a_scenario_built_travels_back_by_its_id(monkeypatch):
    tools = _Tools(by_name={"scenario": _rows(WEIGHT, made="calc_after")})
    sell = _call("scenario", book="port_001", sales=[{"ticker": "LLY"}], why="line 1 asks the book after the sale")
    ctx, _seen, _steps, _stored = _ctx(monkeypatch, [("", sell), ("", _submit(SETTLED))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.made == ["calc_after"] and result.log[0]["got"].endswith("made calc_after")
    assert dl.for_lead([result], Ledger.of(tools.records))["returns"][0]["made"] == ["calc_after"]


# ── the brief ────────────────────────────────────────────────────────────────

async def test_an_entry_in_neither_state_is_sent_back_without_spending_an_attempt(monkeypatch):
    tools = _Tools()
    neither = {"n": 1, "settled": True, "finding": FINDING}                      # settled, and no ids under it
    ctx, seen, steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _submit(neither)), ("", _submit(SETTLED))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    told = json.loads([m for m in seen[2]["messages"] if m.get("role") == "tool"][-1]["content"])
    assert told["error"] == "malformed_brief" and "ids of the rows" in told["detail"]
    assert [s["status"] for s in steps if s["type"] == "brief"] == ["completed"]     # one attempt, and it passed
    assert result.status == "settled"


async def test_a_refused_brief_gets_one_repair_and_then_the_lead_is_told_what_failed(monkeypatch):
    tools = _Tools()
    wrong = {**SETTLED, "finding": "MSFT weighs 23.4% of the book."}
    ctx, seen, steps, stored = _ctx(monkeypatch, [("", _read()), ("", _submit(wrong)),
                                                  ("", _submit({**wrong, "finding": "MSFT weighs 24.4% of the book."}))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert seen[2]["tool_choice"] == "required"                        # while a verdict stands the turn is a tool call
    assert [s["status"] for s in steps if s["type"] == "brief"] == ["rejected", "rejected"]
    assert result.status == "refused" and result.refused[0]["n"] == 1
    assert stored[0]["status"] == "refused" and stored[0]["blocks"] == []   # kept, marked, never rendered as passed


async def test_an_analyst_that_files_nothing_leaves_a_boundary_the_lead_can_point_at(monkeypatch):
    monkeypatch.setattr(get_settings(), "sub_analyst_max_turns", 2, raising=False)
    tools = _Tools()
    ctx, _seen, steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _read(column="market_value"))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.status == "refused" and len(result.lines) == 1 and not result.lines[0]["settled"]
    boundary, brief = [s for s in steps if s["type"] in ("boundary", "brief")]
    assert boundary["status"] == "completed" and brief["status"] == "rejected"   # the ledger reads completed steps
    fid = result.lines[0]["boundary"]
    assert boundary["facts"][0].id == fid and boundary["facts"][0].kind == F.ABSENCE
    line = dl.for_lead([result], Ledger.of(tools.records))["returns"][0]["lines"][0]
    assert line["boundary"].startswith(f"[{fid}] absent:") and "did not file a brief" in line["boundary"]
    assert "shown" not in dl.for_lead([result], Ledger.of(tools.records))["returns"][0]   # no bypass around the brief


async def test_a_verb_it_does_not_have_is_answered_not_dispatched(monkeypatch):
    tools = _Tools()
    other = _call("filings_read", ticker="MSFT", line="revenue", why="line 1")
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", other), ("", _read()), ("", _submit(SETTLED))], tools)
    await sa.run_sub_analyst(TASK, ctx)
    told = json.loads([m for m in seen[1]["messages"] if m.get("role") == "tool"][-1]["content"])
    assert told["error"] == "unknown_tool" and "book_read" in told["detail"] and "filings_read" not in told["detail"]
    assert [c[0] for c in tools.calls] == ["book_read"]
