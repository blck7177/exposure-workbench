"""V36 Phase 1c — the domain analyst (offline: no DB, no network, no LLM).

What it has to get right is not "did it call the tool": it is that the thing
V35 had no owner for — turning a line of the lead's intent into the desk's
language — happens here, and that nothing it hands back can cost the lead its
turn. So: the task reaches it whole, its budget is its own, a submission the
check refuses comes back to it once, and a brief that half passes is half a
brief rather than a lost one.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation as dl, sub_analyst as sa
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger


class _Tools:
    """The turn's tool session: what the face offers and one verb."""

    def __init__(self, by_name: dict, face=sa.EVIDENCE_TOOLS):
        self.by_name = by_name
        self.calls: list[tuple[str, dict]] = []
        self.actors: list[str | None] = []
        self.tools = [{"type": "function", "function": {"name": n, "description": n, "parameters": {}}} for n in face]

    async def call(self, name, args, *, actor=None):
        self.calls.append((name, args))
        self.actors.append(actor)
        r = self.by_name.get(name)
        return r(args) if callable(r) else r


class _Llm:
    """A scripted analyst: each entry is (content, [tool calls])."""

    def __init__(self, script):
        self.script = list(script)
        self.seen: list[dict] = []
        self.kwargs: list[dict] = []

    def for_actor(self, actor):
        self.actor = actor
        return self

    async def chat(self, messages, tools=None, **kw):
        self.seen.append({"messages": list(messages), "tools": [t["function"]["name"] for t in (tools or [])]})
        self.kwargs.append(kw)
        if not self.script:
            return "", None
        content, calls = self.script.pop(0)
        return content, [{"id": f"c{i}", "function": {"name": n, "arguments": json.dumps(a)}}
                         for i, (n, a) in enumerate(calls)] if calls else None


class _Ctx(sa.TurnContext):
    pass


def _ctx(tools, llm, ledger: Ledger | None = None, briefing: dict | None = None):
    ctx = sa.TurnContext(tools_session=tools, llm=llm, db_factory=None, session_id="sess_x",
                         message_id="msg_x", briefing=briefing or {})
    ctx._ledger = ledger or Ledger()
    return ctx


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """The two things this loop does with a database: record a step, load the
    ledger. Both are stubbed; what the test is about is above them."""
    recorded: list[dict] = []

    async def _record(ctx, actor, step_type, tool_name, args, summary, facts=None, status="completed"):
        recorded.append({"actor": actor, "step_type": step_type, "tool_name": tool_name, "args": args,
                         "summary": summary, "facts": list(facts or []), "status": status})

    async def _ledger(ctx):
        return getattr(ctx, "_ledger", Ledger())

    monkeypatch.setattr(sa, "_record", _record)
    monkeypatch.setattr(sa, "_ledger", _ledger)
    sa.RECORDED = recorded
    return recorded


def _task(**kw) -> dl.Task:
    base = dict(task_id="tsk_1", domain="book_limits_and_triggers", subjects=("port_001",),
                want_to_know=("which check is nearest its warning", "how much room is left"))
    return dl.Task(**{**base, **kw})


def _scalar(measure, subject, value, **params):
    return F.fact(F.SCALAR, measure, subject=subject, unit="RATIO", value=value, as_of="2026-09-10",
                  params=params or {"node": "n"})


def _run_result(facts):
    return {"program_id": "calc_1", "returns": [], "nodes": {"n": {"kind": "vector"}}, "settled": len(facts),
            "refused": [], "facts": {"columns": list(F.COLUMNS),
                                     "rows": [[f.id, f.kind, f.subject, f.measure, f.unit, f.value, f.as_of,
                                               None, f.params, []] for f in facts]}}


def _submit(findings, not_done=(), report_text="ok"):
    return ("submit", {"brief": {"findings": findings, "not_done": list(not_done)},
                       "report": {"title": "t", "text": report_text}})


# ── the task reaches it whole ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_analyst_reads_its_domain_the_language_and_the_numbered_task():
    llm = _Llm([("", None)])
    await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm))
    system = llm.seen[0]["messages"][0]["content"]
    user = json.loads(llm.seen[0]["messages"][1]["content"])
    assert "book_limits_and_triggers analyst" in system
    assert "room below zero is a check already in warning" in system      # the domain's own knowledge
    assert "SIGNATURES" in system or "fn" in system                       # the language
    assert user["task"]["want_to_know"] == ["1. which check is nearest its warning", "2. how much room is left"]
    assert llm.actor == "sub:book_limits_and_triggers"


@pytest.mark.asyncio
async def test_it_is_handed_the_desks_map_for_its_own_subjects_only():
    briefing = {"portfolios": {"port_001": {"name": "book"}, "port_999": {"name": "other"}},
                "issuers": {"MSFT": {"sector": "Technology"}}}
    llm = _Llm([("", None)])
    await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, briefing=briefing))
    user = json.loads(llm.seen[0]["messages"][1]["content"])
    assert list(user["subjects"]) == ["port_001"]
    assert user["boundaries"]


@pytest.mark.asyncio
async def test_its_tools_are_compile_the_face_and_submit():
    llm = _Llm([("", None)])
    await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm))
    assert llm.seen[0]["tools"] == ["compile", *sa.EVIDENCE_TOOLS, "submit"]


# ── the work ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compile_types_a_request_without_running_it():
    tools = _Tools({})
    llm = _Llm([("", [("compile", {"request": {"subjects": ["port_001"],
                                               "want": ["limit_checks.current_value", "limit_checks.warning_level"],
                                               "derive": ["room = limit_checks.warning_level - limit_checks.current_value"]}})]),
                ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    assert tools.calls == []                                   # compile runs nothing
    result = json.loads(llm.seen[1]["messages"][-1]["content"])
    names = [b["name"] for b in result["program"]["let"]]
    assert "room" in names                                     # the derivation the lead asked for, as a node
    assert any(s["step_type"] == "tool_call" and s["tool_name"] == "compile" for s in sa.RECORDED)


@pytest.mark.asyncio
async def test_a_name_the_desk_does_not_hold_costs_that_name_and_not_the_request():
    llm = _Llm([("", [("compile", {"request": {"subjects": ["port_001"],
                                               "want": ["limit_checks.current_value", "issuer_exposures.ticker"]}})]),
                ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm))
    out = json.loads(llm.seen[1]["messages"][-1]["content"])
    assert out["program"] is not None
    assert [s["want"] for s in out["skipped"]] == ["issuer_exposures.ticker"]


@pytest.mark.asyncio
async def test_a_tool_result_comes_back_as_figures_with_their_ids_and_places():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604,
                node="checks", label="issuer_concentration:MSFT", place=3, of=20)
    tools = _Tools({"run": _run_result([f])})
    llm = _Llm([("", [("run", {"program": {"let": []}})]), ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    shown = json.loads(llm.seen[1]["messages"][-1]["content"])
    fig = shown["figures"][0]
    assert fig["value"] == f"16.0% [{f.id}]"
    assert (fig["place"], fig["of"]) == (3, 20)


@pytest.mark.asyncio
async def test_a_boundary_the_analyst_is_shown_is_recorded_as_a_fact():
    tools = _Tools({"read_filings": {"error": "not_indexed", "detail": "KO has no Item 7 indexed"}})
    llm = _Llm([("", [("read_filings", {"ticker": "KO", "item": "7"})]), ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    step = next(s for s in sa.RECORDED if s["step_type"] == "boundary")
    assert step["facts"] and step["facts"][0].kind == F.ABSENCE
    shown = json.loads(llm.seen[1]["messages"][-1]["content"])
    assert shown["boundaries"][0]["fact"] == step["facts"][0].id


# ── its budget is its own ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_analysts_evidence_calls_are_counted_in_its_own_loop(monkeypatch):
    """V23 made the turn budget's unit the assistant MESSAGE, so it cannot bound
    one analyst of three. This counter can, and the registry is untouched."""
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_evidence_calls", 2, raising=False)
    tools = _Tools({"run": _run_result([])})
    llm = _Llm([("", [("run", {"program": {}})]), ("", [("run", {"program": {}})]),
                ("", [("run", {"program": {}})]), ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    assert len(tools.calls) == 2
    third = json.loads(llm.seen[3]["messages"][-1]["content"])
    assert third["error"] == "analyst_budget" and "not_done" in third["detail"]


@pytest.mark.asyncio
async def test_it_stops_at_its_turn_limit_and_says_so_rather_than_returning_nothing(monkeypatch):
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_max_turns", 2, raising=False)
    llm = _Llm([("thinking", None), ("still thinking", None)])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm))
    assert r.status == "refused"
    assert [d["want"] for d in r.not_done] == [1, 2]
    assert all(d["boundary"] for d in r.not_done)          # the lead can quote why
    assert r.coverage == {"asked": 2, "done": 0, "not_done": 2, "refused": 0}


# ── submitting ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_brief_that_passes_reaches_the_lead_with_its_coverage():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n", place=1, of=10)
    ledger = Ledger.of_facts([f])
    llm = _Llm([("", [_submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is nearest at 16.0% [{f.id}]."},
                               {"want": 2, "facts": [f.id], "finding": f"It reads 16.0% [{f.id}] against its tier."}],
                              report_text=f"MSFT reads 16.0% [{f.id}].")])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.status == "verified"
    assert r.coverage == {"asked": 2, "done": 2, "not_done": 0, "refused": 0}
    assert r.report["status"] == "verified"
    assert next(s for s in sa.RECORDED if s["step_type"] == "brief")["status"] == "completed"


@pytest.mark.asyncio
async def test_a_refused_submission_comes_back_once_and_the_second_is_forced_to_be_a_tool():
    # `place` is why the second submission passes: "nearest" rests on the
    # ordering the desk built, and Phase 1a is what puts it in front of the
    # analyst to rest on.
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n", place=1, of=10)
    ledger = Ledger.of_facts([f])
    bad = _submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is 1.0% [{f.id}] above warning."},
                   {"want": 2, "facts": [f.id], "finding": f"It reads 16.0% [{f.id}]."}],
                  report_text=f"MSFT reads 16.0% [{f.id}].")
    good = _submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is nearest, at 16.0% [{f.id}]."},
                    {"want": 2, "facts": [f.id], "finding": f"It reads 16.0% [{f.id}]."}],
                   report_text=f"MSFT reads 16.0% [{f.id}].")
    llm = _Llm([("", [bad]), ("", [good])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.status == "verified"
    refusal = json.loads(llm.seen[1]["messages"][-1]["content"])["refusal"]
    assert "mark_mismatch" in refusal
    assert llm.kwargs[1].get("tool_choice") == "required"
    assert [s["status"] for s in sa.RECORDED if s["step_type"] == "brief"] == ["rejected", "completed"]


@pytest.mark.asyncio
async def test_a_brief_that_half_passes_is_half_a_brief_not_a_lost_one():
    """The lead can still answer the lines that came back, and is told which
    did not."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n")
    ledger = Ledger.of_facts([f])
    bad = _submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is 1.0% [{f.id}] above warning."},
                   {"want": 2, "facts": [f.id], "finding": f"It reads 16.0% [{f.id}]."}],
                  report_text=f"MSFT reads 16.0% [{f.id}].")
    llm = _Llm([("", [bad]), ("", [bad])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.status == "partial"
    assert [x["want"] for x in r.findings] == [2]
    assert [x["want"] for x in r.refused] == [1]
    assert r.coverage["done"] == 1 and r.coverage["refused"] == 1


@pytest.mark.asyncio
async def test_a_malformed_submission_is_told_to_the_analyst_not_raised():
    llm = _Llm([("", [("submit", {"brief": {}})]), ("", None)])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, Ledger()))
    told = json.loads(llm.seen[1]["messages"][-1]["content"])
    assert told["error"] == "malformed_submission"
    assert r.status == "refused"


# ── several tasks ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tasks_run_one_after_another_until_phase_3():
    f = _scalar("limit_checks.current_value", "x", 0.1)
    ledger = Ledger.of_facts([f])
    calls: list[str] = []

    async def _one(task, ctx):
        calls.append(task.domain)
        return dl.AnalystResult(task=task, status="verified")

    import exposure_workbench.agents.sub_analyst as mod
    real, mod.run_sub_analyst = mod.run_sub_analyst, _one
    try:
        out = await mod.run_tasks([_task(), _task(domain="book_liquidity", task_id="tsk_2")],
                                  _ctx(_Tools({}), _Llm([]), ledger))
    finally:
        mod.run_sub_analyst = real
    assert calls == ["book_limits_and_triggers", "book_liquidity"]
    assert [r.task.domain for r in out] == calls


@pytest.mark.asyncio
async def test_a_brief_that_settles_nothing_is_not_called_verified():
    """It passed the check, and it answered nothing. The smoke round called that
    'verified', which is true of the check and false of the work — and the word
    is what the lead reads."""
    led = Ledger()
    llm = _Llm([("", [("submit", {"brief": {"findings": [],
                                            "not_done": [{"want": 1, "why": "no run on this desk"},
                                                         {"want": 2, "why": "no run on this desk"}]},
                                  "report": {"title": "t", "text": "The desk holds no run for this book."}})])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, led))
    assert r.status == "absent"
    assert r.coverage == {"asked": 2, "done": 0, "not_done": 2, "refused": 0}


# ── V36.1 (round A) · the desk's words travel with the id ────────────────────

def _boundary(text, measure="request"):
    return F.fact(F.ABSENCE, measure, subject=None, as_of="n/a", value=None, text=text,
                  params={"reason": "cannot", "class": "data_absent", "code": "not_indexed"}, standalone=False,
                  group="boundary")


@pytest.mark.asyncio
async def test_a_not_done_line_carries_the_desks_own_words_beside_its_id():
    """Round A lost Q05, Q06, Q14 and Q17 to the lead quoting an analyst's
    sentence as the desk's. The brief carried `why` and a boundary id and never
    the boundary's text; now the text rides beside the id, read off the ledger,
    so what the lead may quote is what the gate can look up."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n", place=1, of=10)
    b = _boundary("read_filings(ticker='MSFT', item='7'): not_indexed")
    ledger = Ledger.of_facts([f, b])
    llm = _Llm([("", [_submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is nearest at 16.0% [{f.id}]."}],
                              not_done=[{"want": 2, "why": "the desk could not read the filing", "boundary": b.id}],
                              report_text=f"MSFT reads 16.0% [{f.id}].")])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.not_done[0]["said"] == b.text
    handed = dl.for_lead([r])["analysts"][0]
    assert handed["not_done"][0]["said"] == b.text
    assert "`said`" in dl.HOW_TO_CITE


@pytest.mark.asyncio
async def test_a_finding_that_cites_a_boundary_carries_the_boundarys_words():
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n", place=1, of=10)
    b = _boundary("read_filings(ticker='MSFT', item='7'): not_indexed")
    ledger = Ledger.of_facts([f, b])
    llm = _Llm([("", [_submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is nearest at 16.0% [{f.id}]."},
                               {"want": 2, "facts": [b.id], "finding": "The filing could not be read on this desk."}],
                              report_text=f"MSFT reads 16.0% [{f.id}].")])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.findings[1]["desk_said"] == [{"id": b.id, "said": b.text}]
    assert dl.for_lead([r])["analysts"][0]["findings"][1]["desk_said"][0]["said"] == b.text


@pytest.mark.asyncio
async def test_an_analyst_that_files_nothing_still_hands_the_lead_the_desks_words(monkeypatch):
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_max_turns", 1, raising=False)
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), _Llm([("thinking", None)])))
    assert r.not_done and all(d["said"] and d["said"] == d["why"] for d in r.not_done)


# ── V37 (round B) · T1: what the lead is handed, the ledger holds ─────────────

@pytest.mark.asyncio
async def test_the_boundary_of_an_analyst_that_files_nothing_is_on_the_ledger(monkeypatch, _no_db):
    """Round B lost Q10 and Q18 here, and lost them to V36.1's own T1.

    An analyst out of turns states one boundary — "the domain analyst did not
    file a brief within its turns" — and T1 hands the lead its id and its
    words, to be quoted like any other thing the desk said. The fact rode on
    the `brief` step, whose status is `rejected` because no brief was filed,
    and `ledger.load` reads the facts of COMPLETED steps only. So the lead
    quoted an id the gate could not look up, twice per turn, and two otherwise
    answerable questions ended on the gate-exhausted text.

    The boundary is a completed piece of work — the analyst did say what
    stopped it — and is recorded the way the other forty-eight of round B were.
    What this pins is the invariant, not the arrangement: rebuild the ledger
    from the steps the loader would read, and the id the lead was handed is on
    it."""
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_max_turns", 1, raising=False)

    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), _Llm([("thinking", None)])))

    handed = {d["boundary"] for d in r.not_done}
    assert len(handed) == 1 and r.status == "refused"
    # the ledger as services/ledger.load builds it: the facts of completed steps
    led = Ledger.of_facts([f for s in _no_db if s["status"] == "completed" for f in s["facts"]])
    assert led.holds(next(iter(handed)))
    assert all(led.kind(d["boundary"]) == F.ABSENCE for d in r.not_done)
    # and the brief step still says no brief was filed, carrying no facts
    brief = [s for s in _no_db if s["step_type"] == "brief"]
    assert [s["status"] for s in brief] == ["rejected"] and not brief[0]["facts"]


# ── V36.1 (round A) · a start is not evidence ─────────────────────────────────

@pytest.mark.asyncio
async def test_a_start_is_counted_apart_from_evidence_and_once_per_subject(monkeypatch):
    """Q14's book_events analyst spent all eight evidence calls starting
    readiness for eight held names and filed nothing; Q04's started MRK four
    times. A start returns an id, not a figure: it has its own count, and the
    same start twice is answered without a second task."""
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_start_calls", 2, raising=False)
    monkeypatch.setattr(st.get_settings(), "sub_analyst_evidence_calls", 1, raising=False)
    tools = _Tools({"start": lambda a: {"enqueued": True, "task_id": f"task_{a['subject']}", "kind": a["kind"],
                                        "ticker": a["subject"], "facts": {"columns": [], "rows": []}},
                    "run": lambda a: _run_result([])})
    llm = _Llm([("", [("start", {"kind": "readiness", "subject": "AAPL", "reason": "r"}),
                      ("start", {"kind": "readiness", "subject": "aapl", "reason": "r"}),
                      ("start", {"kind": "readiness", "subject": "MSFT", "reason": "r"}),
                      ("start", {"kind": "readiness", "subject": "NVDA", "reason": "r"}),
                      ("run", {"program": {}})]),
                ("", None)])
    r = await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    # AAPL and MSFT reach the desk; the repeat and the fourth do not; the run still has its evidence call
    assert [n for n, _ in tools.calls] == ["start", "start", "run"]
    replies = [json.loads(m["content"]) for m in llm.seen[1]["messages"] if m.get("role") == "tool"]
    assert replies[1]["already_started"] == "task_AAPL"
    assert replies[3]["error"] == "analyst_budget" and "background" in replies[3]["detail"]
    assert replies[4].get("error") is None
    assert r.cost["starts"] == 2 and r.cost["evidence_calls"] == 1


# ── V36.1 (round A) · what an analyst built reaches the lead by id ───────────

@pytest.mark.asyncio
async def test_the_books_an_analyst_built_reach_the_lead_and_a_calc_subject_is_explained():
    res = {**_run_result([]), "nodes": {"base": {"kind": "run", "run": "run_1"},
                                        "after": {"kind": "table", "ref": "calc_after1"}}}
    tools = _Tools({"run": lambda a: res})
    llm = _Llm([("", [("run", {"program": {}})]), ("", None)])
    r = await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    assert r.made == [{"node": "after", "id": "calc_after1", "kind": "scenario"}]
    assert dl.for_lead([r])["analysts"][0]["made"] == r.made
    assert "`made`" in dl.HOW_TO_CITE
    # the next analyst, handed that id as a subject, is told what it is
    llm2 = _Llm([("", None)])
    await sa.run_sub_analyst(_task(subjects=("calc_after1",)), _ctx(_Tools({}), llm2))
    user = json.loads(llm2.seen[0]["messages"][1]["content"])
    assert user["subjects"]["calc_after1"]["kind"] == "scenario"
    assert dl.parse_tasks({"tasks": [{"domain": "book_limits_and_triggers", "subjects": ["calc_after1"],
                                      "want_to_know": ["re-run every check on that book"]}]},
                          {"book_limits_and_triggers"}, lambda p: p + "1")[0].subjects == ("calc_after1",)


@pytest.mark.asyncio
async def test_the_analyst_files_lines_and_the_lead_reads_findings_and_not_done():
    """The canonical V36.1 brief through the loop: one list, each entry settled
    or not; what the lead reads keeps its shape."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n", place=1, of=10)
    b = _boundary("run(portfolio='port_001', which='prev'): no_prior_run")
    ledger = Ledger.of_facts([f, b])
    llm = _Llm([("", [("submit", {"brief": {"lines": [
        {"want": 1, "finding": f"MSFT is nearest at 16.0% [{f.id}].", "facts": [f.id]},
        {"want": 2, "why": "the desk has no earlier run to compare with", "boundary": b.id}]},
        "report": {"title": "t", "text": f"MSFT reads 16.0% [{f.id}]."}})])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.status == "verified" and r.coverage == {"asked": 2, "done": 1, "not_done": 1, "refused": 0}
    assert r.findings[0]["want"] == 1 and r.not_done[0]["said"] == b.text


# ── V36.1 (round A) · one bar for the brief and the report ───────────────────

@pytest.mark.asyncio
async def test_a_report_is_verified_only_when_the_whole_brief_passed():
    """Q11: the handoff refused "nearest" twice; the report said the same thing
    without a figure, passed the text check, was stored verified, and the lead
    read it from there into the answer. A report whose brief was refused in
    part is on the record as refused, with the brief's problems."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="n")   # no place: "nearest" has no support
    ledger = Ledger.of_facts([f])
    bad = _submit([{"want": 1, "facts": [f.id], "finding": f"MSFT is nearest at 16.0% [{f.id}]."},
                   {"want": 2, "facts": [f.id], "finding": f"It reads 16.0% [{f.id}]."}],
                  report_text="The ranked output shows MSFT as the nearest check.")
    llm = _Llm([("", [bad]), ("", [bad])])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({}), llm, ledger))
    assert r.status == "partial" and [x["want"] for x in r.refused] == [1]
    assert r.report["status"] == "refused"
    assert any(p["reason"] == "superlative_without_rank" for p in r.report["problems"])


# ── V37/T5: one completion's reading is bounded, and the rule is said once ─────

@pytest.mark.asyncio
async def test_one_completions_reading_is_shared_by_the_results_it_reads(monkeypatch):
    """The cap was per RESULT, so three calls in one completion could hand the
    analyst three times it: round B did 43.5k characters once and answered with
    three tokens, and five of its empty replies came straight after a read of more
    than 9k. The budget belongs to the completion."""
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_result_chars", 9_000, raising=False)
    wide = [_scalar("issuer_exposures.weight", f"T{i:04d}", i / 1000, node="w") for i in range(300)]
    tools = _Tools({"run": lambda a: _run_result(wide)})
    llm = _Llm([("", [("run", {"program": {"let": []}}) for _ in range(3)]), ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(tools, llm))
    read = [m for m in llm.seen[1]["messages"] if m.get("role") == "tool"]
    assert len(read) == 3
    assert sum(len(m["content"]) for m in read) <= 9_000 * 1.05, "three results, one completion's budget"


@pytest.mark.asyncio
async def test_the_citing_rule_is_in_the_system_text_and_not_on_every_result():
    """726 characters that said nothing new: `book_market_risk` read them nine
    times in one turn of round B."""
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="c", place=1, of=3)
    llm = _Llm([("", [("run", {"program": {"let": []}})]), ("", None)])
    await sa.run_sub_analyst(_task(), _ctx(_Tools({"run": lambda a: _run_result([f])}), llm))
    system = llm.seen[0]["messages"][0]["content"]
    assert "bracket included" in system, "the rule is standing knowledge"
    result = next(m for m in llm.seen[1]["messages"] if m.get("role") == "tool")
    assert "how_to_cite" not in result["content"]


# ── V37/T2: an analyst that files nothing still hands over what it was shown ───

@pytest.mark.asyncio
async def test_an_analyst_out_of_turns_hands_over_the_figures_it_was_shown(monkeypatch):
    """Round B had three analysts run their eight turns out and file nothing, one
    of them after nine tool calls, and all the lead was told is "the domain
    analyst did not file a brief within its turns". The figures were on the
    ledger; the most expensive part of the turn fell on the floor.

    It is not a brief and is not offered as one — no line is claimed answered —
    and every figure reads exactly as the desk showed it, so the lead may write
    them."""
    from exposure_workbench.app_state import settings as st
    monkeypatch.setattr(st.get_settings(), "sub_analyst_max_turns", 2, raising=False)
    f = _scalar("limit_checks.current_value", "issuer_concentration:MSFT", 0.1604, node="cur", place=1, of=3)
    series = {"id": "f_dso001", "kind": "series", "subject": "AAPL", "measure": "days_sales_outstanding",
              "unit": "COUNT", "value": {"points": [["2024-09-28", 31.19], ["2025-09-27", 34.89]], "n": 2},
              "as_of": "2025-09-27", "params": {"node": "dso"}}
    result = {"program_id": "calc_1", "returns": [], "nodes": {"cur": {"kind": "vector"}}, "settled": 2,
              "refused": [], "facts": {"columns": list(F.COLUMNS),
                                       "rows": [[f.id, f.kind, f.subject, f.measure, f.unit, f.value, f.as_of,
                                                 None, f.params, []],
                                                [series["id"], "series", series["subject"], series["measure"],
                                                 series["unit"], series["value"], series["as_of"], None,
                                                 series["params"], []]]}}
    llm = _Llm([("", [("run", {"program": {"let": []}})]), ("thinking", None)])
    r = await sa.run_sub_analyst(_task(), _ctx(_Tools({"run": lambda a: result}), llm))

    assert r.status == "refused" and not r.findings, "nothing is claimed answered"
    assert [d["want"] for d in r.not_done] == [1, 2]
    values = [x.get("value") for x in r.shown if "value" in x]
    assert any(str(v).endswith(f"[{f.id}]") for v in values), "written as the desk showed it"
    assert any(x.get("measure") == "days_sales_outstanding" and x.get("spacing") == "annual" for x in r.shown)
    # and it reaches the lead
    for_lead = dl.for_lead([r])["analysts"][0]
    assert for_lead["shown"] == r.shown and "shown" in dl.HOW_TO_CITE
