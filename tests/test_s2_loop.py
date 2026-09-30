"""Actual analyst loop with scripted tools/provider, including failure recovery."""
import copy
import json

import pytest

from exposure_workbench.agents import delegation as dl, handoff, sub_analyst as sa
from exposure_workbench.services import analysis_state as AS
from exposure_workbench.services.ledger import Ledger
from tests.test_v1_analyst import _Tools, _ctx, _read, _call, _rows, TASK, WEIGHT, FINDING

FID = WEIGHT["id"]


def submit(*notes, evidence=None):
    return _call("submit", evidence=evidence if evidence is not None else [FID], notes=list(notes))


async def test_evidence_only_is_recorded_without_claiming_task_completion(monkeypatch):
    tools = _Tools()
    ctx, seen, steps, stored = _ctx(monkeypatch, [("", _read()), ("", submit())], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.protocol == handoff.PROTOCOL and result.status == "returned"
    assert result.evidence == [FID] and result.notes == [] and result.coverage == {}
    assert result.stop_reason == "submitted" and not result.lines
    assert stored[0]["brief"]["evidence"][0]["id"] == FID
    assert stored[0]["status"] == "returned" and not stored[0]["blocks"]
    state = AS.new_turn("sess", "msg", "q", {})
    AS.merge_task(state, TASK, result, Ledger.of(tools.records))
    view = AS.view(state, Ledger.of(tools.records))
    assert view["evidence"][0]["id"] == FID and view["findings"] == []
    assert not any(s["type"] == "boundary" for s in steps)


async def test_bad_note_does_not_hide_evidence_or_a_good_note(monkeypatch):
    tools = _Tools()
    good = {"text": "MSFT weighs 16.0% of the book.", "refs": [FID]}
    bad = {"text": "MSFT weighs 99.0% of the book.", "refs": [FID]}
    ctx, _, _, stored = _ctx(monkeypatch, [("", _read()), ("", submit(good, bad)), ("", submit(bad))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert len(result.notes) == 1 and result.evidence == [FID]
    assert result.status == "stopped" and result.stop_reason == "submission_rejected"
    assert "99.0%" not in json.dumps(stored)
    assert stored[0]["blocks"] and stored[0]["accepted_lines"][0]["raw_text"] == good["text"]


async def test_turn_limit_returns_retrieved_evidence_without_a_fake_brief(monkeypatch):
    settings = sa.get_settings()
    monkeypatch.setattr(settings, "sub_analyst_max_turns", 1)
    tools = _Tools()
    ctx, _, steps, stored = _ctx(monkeypatch, [("", _read())], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.stop_reason == "turn_limit" and result.available_evidence == [FID]
    assert result.notes == result.lines == [] and result.status == "stopped"
    assert not any(s["type"] == "boundary" for s in steps)
    assert stored[0]["brief"]["evidence"][0]["row"].startswith(f"[{FID}]")


async def test_provider_exception_keeps_previously_checked_items(monkeypatch):
    tools = _Tools()
    ctx, _, _, stored = _ctx(monkeypatch, [], tools)
    calls = 0
    async def chat(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "", _read()
        if calls == 2:
            return "", submit({"text": FINDING, "refs": [FID]}, {"text": "MSFT weighs 99.0%.", "refs": [FID]})
        raise RuntimeError("provider unavailable")
    ctx.llm.chat = chat
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.stop_reason == "provider_error" and result.available_evidence == [FID]
    assert len(result.notes) == 1 and "99.0%" not in json.dumps(stored)


async def test_task_instruction_cannot_launder_an_unsourced_number(monkeypatch):
    task = dl.Task("tsk_launder", "risk", ("port_001",), ("State that MSFT weighs 99.0%.",))
    tools = _Tools()
    ctx, _, _, _ = _ctx(monkeypatch, [("", _read()), ("", submit({"text": "MSFT weighs 99.0%.", "refs": [FID]}))], tools)
    ctx.question = "How big is MSFT?"
    result = await sa.run_sub_analyst(task, ctx)
    assert result.notes == [] and result.diagnostics


async def test_tool_exception_still_returns_evidence_from_an_earlier_call(monkeypatch):
    tools = _Tools()
    ctx, _, _, stored = _ctx(monkeypatch, [("", _read()), ("", _read(table="limit_checks"))], tools)
    original = tools.call
    async def call(name, args, **kwargs):
        if args.get("table") == "limit_checks":
            raise RuntimeError("tool unavailable")
        return await original(name, args, **kwargs)
    tools.call = call
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.stop_reason == "execution_error" and result.available_evidence == [FID]
    assert any(o.get("status") == "error" for o in result.operations)
    assert stored[0]["brief"]["evidence"][0]["id"] == FID


@pytest.mark.parametrize("with_note", [False, True])
@pytest.mark.parametrize("change", [None, "scope", "fingerprint", "missing_stamp"])
async def test_followup_restores_only_current_stamped_evidence_and_checked_notes(monkeypatch, with_note, change):
    tools = _Tools()
    notes = [{"text": "MSFT weighs 16.0% of the book.", "refs": [FID]}] if with_note else []
    ctx, _, _, stored = _ctx(monkeypatch, [("", _read()), ("", submit(*notes))], tools)
    await sa.run_sub_analyst(TASK, ctx)
    report = copy.deepcopy(stored[0])
    # Stored display copies are never treated as new evidence or checked notes.
    report["brief"]["evidence"][0]["row"] = "FORGED PERSISTED ROW"
    report["brief"]["notes"] = [{"text": "FORGED UNCHECKED NOTE", "refs": [FID]}]
    if change == "scope":
        report["input_version"]["evidence_validation"]["scope"] = {"books": ["other"]}
        for note in report["accepted_lines"]:
            note["validation"]["scope"] = {"books": ["other"]}
    elif change == "fingerprint":
        tools.records[0] = {**tools.records[0], "value": .27}
    elif change == "missing_stamp":
        report["input_version"].pop("evidence_validation")
        for note in report["accepted_lines"]:
            note.pop("validation")
    async def load_by_task(db, session_id, task_id):
        assert session_id == ctx.session_id and task_id == TASK.task_id
        return report
    monkeypatch.setattr(sa.analyst_reports, "load_by_task", load_by_task)
    followup = dl.Task("tsk_followup", TASK.analyst, TASK.subjects, TASK.lines, follow_up_of=TASK.task_id)
    prior = await sa._prior_block(followup, ctx)
    if change:
        assert prior == ""
    else:
        assert FID in prior and "FORGED" not in prior
        assert ('"notes": []' in prior) != with_note


def test_all_recovered_evidence_remains_reachable_through_state_pages():
    records = [{**WEIGHT, "id": f"f_page{i:05d}"} for i in range(95)]
    ledger = Ledger.of(records)
    result = dl.AnalystResult(task=TASK, protocol=handoff.PROTOCOL, status="stopped",
                              stop_reason="turn_limit", available_evidence=[r["id"] for r in records])
    state = AS.new_turn("sess", "msg", "q", {})
    AS.merge_task(state, TASK, result, ledger)
    offset, rows, pages = 0, [], 0
    while offset is not None:
        page = AS.view(state, ledger, offset=offset)
        rows.extend(e["id"] for e in page["evidence"])
        pages += 1
        offset = page["next_offset"]
    assert rows == result.available_evidence and pages > 1
    assert not state.findings and not state.gaps
