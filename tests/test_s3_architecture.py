"""Cross-resource regressions from S2_mini; real boundaries, scripted provider."""
import json
from dataclasses import replace
from datetime import date

import pytest

from exposure_workbench.agents import delegation as dl, delivery, evidence_context, handoff, meta_agent, sub_analyst as sa
from exposure_workbench.services import analysis_state as AS, answer_check, facts as F, typed_calculator as tc
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.tools import faces
from tests.test_v1_analyst import _Tools, _ctx, _call, TASK, WEIGHT
from tests.test_meta_agent_gate import _factory, _stub_desk, _stub_llm, _stub_tools, _run_result, _W_MSFT

DEPTH = {**WEIGHT, "id": "f_nvda_depth", "subject": "NVDA", "measure": "NVDA.drawdown.depth",
         "value": .20214413116354196, "window": {"name": "1y"}, "sources": ["calc_nvda_depth"]}
BOOK_DEPTH = {**DEPTH, "id": "f_book_depth", "subject": "port_001", "measure": "deepest.depth",
              "value": .11956851201824671}
POSITION = {**WEIGHT, "id": "f_nvda_position", "subject": "NVDA", "measure": "issuer_exposures.market_value",
            "unit": "MONEY", "value": 436720}


async def test_cross_domain_inputs_are_real_rows_in_first_prompt_and_delivery_trace(monkeypatch):
    tools = _Tools()
    tools.records = [DEPTH]
    task = replace(TASK, input_refs=(DEPTH["id"],))
    ctx, seen, _, stored = _ctx(monkeypatch, [("", _call("submit", evidence=[DEPTH["id"]]))], tools)
    result = await sa.run_sub_analyst(task, ctx)
    text = next(m["content"] for m in seen[0]["messages"] if "<input_evidence" in m["content"])
    assert "<input_evidence" in text and F.line(DEPTH) in text
    assert '"value": 0.20214413116354196' in text and '"unit": "RATIO"' in text
    read = delivery.Delivered()
    read.project(seen[0]["messages"])
    assert DEPTH["id"] in read.note()["delivered"]["facts"]
    assert result.evidence == [DEPTH["id"]] and result.status == "returned"
    assert stored[0]["brief"]["evidence"][0]["id"] == DEPTH["id"]


async def test_unknown_input_is_rejected_before_starting_an_analyst(monkeypatch):
    session = _stub_tools(monkeypatch, {})
    _stub_desk(monkeypatch, session)
    seen = []
    async def chat(messages, **kwargs):
        if not seen:
            seen.append(True)
            return "", _call("ask", tasks=[{"analyst": "risk", "subjects": ["port_001"],
                "lines": ["convert NVDA drawdown"], "input_refs": ["f_other_session"]}])
        result = json.loads(messages[-1]["content"])
        assert result["error"] == "invalid_ask" and "f_other_session" in result["detail"]
        return "The prerequisite evidence is missing.", None
    _stub_llm(monkeypatch, chat)
    out = await meta_agent.handle_message(_factory([]), "sess", "analyse the drawdown", max_turns=2)
    assert out["meta"]["delegations"] == [] and session.faces == ["meta"]


@pytest.mark.parametrize("refs", ["f_bad", ["r_bad"], [None], ["f_a"] * 17])
def test_input_ref_schema_and_parser_agree(refs):
    with pytest.raises(dl.BadDelegation):
        dl.parse_tasks({"tasks": [{"analyst": "risk", "subjects": ["port_001"],
                                  "lines": ["convert"], "input_refs": refs}]}, lambda p: p + "test")


async def test_lead_can_read_without_delegating_and_fact_gate_still_applies(monkeypatch):
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    calls = 0
    async def chat(messages, tools, **kw):
        nonlocal calls
        calls += 1
        names = {t["function"]["name"] for t in tools}
        assert set(faces.FACE_LEAD_READ) <= names
        assert not {"start", "scenario", "web_search"} & names
        if calls == 1:
            return "", _call("book_read", book="port_001", table="issuer_exposures", column="weight", why="size the holding")
        return "MSFT weighs 16.0% [f_wmsft0001] of the book.", None
    _stub_llm(monkeypatch, chat)
    out = await meta_agent.handle_message(_factory([]), "sess", "how big is MSFT?", max_turns=2)
    assert out["meta"]["delivery"] == "answered" and out["meta"]["lead_evidence_calls"] == 1
    assert out["meta"]["delegations"] == [] and session.actors == ["meta"]


async def test_lead_token_narrows_server_capability_and_counts_budget(monkeypatch):
    from contextlib import asynccontextmanager
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    @asynccontextmanager
    async def opened(face, **kw):
        assert face == "meta"
        assert set(kw["deny"]) == {"start", "scenario", "web_search", "filings_search", "filings_section", "metric"}
        yield session
    monkeypatch.setattr(meta_agent, "tool_session", opened)
    monkeypatch.setattr(meta_agent, "LEAD_EVIDENCE_CALLS", 1)
    calls = 0
    async def chat(messages, tools, **kw):
        nonlocal calls
        calls += 1
        assert "metric" not in {t["function"]["name"] for t in tools}
        if calls <= 2:
            return "", _call("book_read", why="read")
        assert json.loads(messages[-1]["content"])["error"] == "lead_budget"
        return "MSFT weighs 16.0% [f_wmsft0001].", None
    _stub_llm(monkeypatch, chat)
    out = await meta_agent.handle_message(_factory([]), "sess", "MSFT", max_turns=3, deny=("metric",))
    assert len(session.calls) == out["meta"]["lead_evidence_calls"] == 1


def test_old_selected_input_outranks_new_bulk_unselected_rows():
    records = [DEPTH] + [{**WEIGHT, "id": f"f_bulk_{i:04d}"} for i in range(100)]
    ledger = Ledger.of(records)
    state = AS.new_turn("sess", "msg", "NVDA loss", {})
    older = replace(TASK, task_id="tsk_older")
    newer = replace(TASK, task_id="tsk_newer")
    AS.merge_task(state, older, dl.AnalystResult(task=older, protocol=handoff.PROTOCOL,
                  status="returned", evidence=[DEPTH["id"]]), ledger)
    AS.merge_task(state, newer, dl.AnalystResult(task=newer, protocol=handoff.PROTOCOL,
                  status="stopped", available_evidence=[r["id"] for r in records[1:]]), ledger)
    page = AS.view(state, ledger)
    assert page["evidence"][0]["id"] == DEPTH["id"] and page["next_offset"]
    ids = {r["id"] for r in page["evidence"]}
    while page["next_offset"]:
        page = AS.view(state, ledger, offset=page["next_offset"])
        ids.update(r["id"] for r in page["evidence"])
    assert ids == {r["id"] for r in records}


def test_input_preview_can_be_opened_without_losing_points_or_passage_text():
    for kind, field, items in [(F.PASSAGE, "text", "x" * 15001),
                               (F.SERIES, "points", [[f"{y}-01-01", y] for y in range(1900, 2026)])]:
        rec = {**DEPTH, "kind": kind, field: items}
        ledger = Ledger.of([rec])
        page = evidence_context.fact_page(ledger, rec["id"], preview=True)
        assembled = page[field]
        while page["next_offset"]:
            page = evidence_context.fact_page(ledger, rec["id"], page["next_offset"])
            assembled += page[field]
        assert assembled == items


def test_corrected_note_need_not_reuse_rejected_id_and_good_note_survives():
    s = handoff.Submission()
    led = Ledger.of([WEIGHT])
    good = {"text": "MSFT weighs 16.0%.", "refs": [WEIGHT["id"]]}
    bad = {**good, "text": "MSFT weighs 99.0%."}
    first = s.apply({"evidence": [WEIGHT["id"]], "notes": [good, bad]}, led, "")
    assert not first["accepted"] and len(s.notes) == 1
    second = s.apply({"evidence": [], "notes": [{**good, "text": "MSFT's weight is 16.0%."}]}, led, "")
    assert second["accepted"] and len(s.notes) == 2 and s.evidence == [WEIGHT["id"]]
    original = next(iter(s.notes))
    failed = s.apply({"evidence": [], "notes": [{**bad, "id": original}]}, led, "")
    assert not failed["accepted"] and "99.0" not in json.dumps(s.notes)
    assert s.apply({"evidence": [], "notes": []}, led, "")["accepted"]


async def test_x07_operand_subjects_reject_wrong_basis_but_preserve_valid_math(monkeypatch):
    records = {r["id"]: r for r in (DEPTH, BOOK_DEPTH, POSITION)}
    from exposure_workbench.services import ledger as ledger_svc
    async def record(db, fid):
        return records[fid]
    monkeypatch.setattr(ledger_svc, "record", record)
    depth, book, position = [await tc._resolve_fact_ref(None, r["id"]) for r in (DEPTH, BOOK_DEPTH, POSITION)]
    assert tc._check("multiply", position, book)["error"] == "subject_mismatch"
    assert tc._check("multiply", book, position)["error"] == "subject_mismatch"
    assert tc._check("multiply", position, depth) is None
    assert position.value * depth.value == pytest.approx(88280.38496174205)
    assert tc._check("divide", position, replace(position, subject="MSFT", issuers=("MSFT",))) is None
    assert tc._check("multiply", position, replace(book, quantity="assumed_shock")) is None


@pytest.mark.parametrize("token,text,ok", [
    ("16%", "$16.5 billion", False), ("16%", "160%", False), ("16%", "16.5%", False),
    ("16%", "116%", False), ("16%", "16%", True), ("16%", "16 percent", True),
    ("14.0%", "(percent)20252024\nDebt to capital14.0 13.4", True),
    ("$90757", "AWS 90,757", False), ("$90,757", "AWS $90,757", True),
    ("$16", "$16.5 billion", False),
])
def test_passage_whole_number_and_unit(token, text, ok):
    rec = {**DEPTH, "kind": F.PASSAGE, "text": text}
    led = Ledger.of([rec])
    assert bool(led.resolve_in_passages(token, [rec["id"]])) is ok


def test_explicit_passage_citation_cannot_borrow_a_number_from_another_passage():
    a = {**DEPTH, "id": "f_actual", "kind": F.PASSAGE, "text": "AWS share 17% in the stated year."}
    b = {**a, "id": "f_unrelated", "text": "Guidance margin 16%."}
    v = answer_check.check("AWS was 16% in the earlier year [f_actual].", Ledger.of([a, b]))
    assert not v.ok


def test_beta_retains_its_benchmark_instead_of_becoming_any_beta():
    beta = {**WEIGHT, "id": "f_rates_beta", "measure": "net_beta.rates_up", "subject": "port_001", "unit": "BETA", "value": .01}
    led = Ledger.of([beta])
    wrong = answer_check.check("The book's net beta to SPY is 0.01× [f_rates_beta].", led)
    assert "benchmark_mismatch" in {p["reason"] for p in wrong.problems}
    assert answer_check.check("The book's net beta to rates up is 0.01× [f_rates_beta].", led).ok


async def test_report_handles_are_scoped_and_method_chapters_are_readable():
    from tests.test_v36_reports import _Db, _store
    db = _Db()
    rid = await _store(db, task_id="tsk_real", text="1. book_read: inspected holdings")
    assert (await meta_agent._open(lambda: db, "sess_a", rid, []))["task_id"] == "tsk_real"
    assert (await meta_agent._open(lambda: db, "sess_b", rid, []))["error"] == "unknown_report"
    assert "chapter" in await meta_agent._open(None, "sess_a", "handbook:market", [])


def test_new_metrics_include_direct_work_and_bound_inputs():
    from tests.test_v1_counters import _script, _call as traced_call
    counters = _script("battery_counters")
    steps = [{"step_type": "delegate", "status": "completed", "result": "risk [port_001] 1 line(s)",
              "args": {"tasks": [{"analyst": "risk", "subjects": ["port_001"], "lines": ["convert drawdown"],
                                    "input_refs": ["f_ab123456"]}]}},
             traced_call("calc", {}, "r_test calc(op=multiply) → 1 row", actor="meta")]
    tally = counters.handoff_of("X07", {"steps": steps, "meta": {"lead_evidence_calls": 2}})
    assert tally["ids_carried"] == tally["bound_input_refs"] == 1
    assert tally["evidence_calls"] == tally["lead_evidence_calls"] == 2
    assert counters.calls_by_analyst(steps)["meta"]["calls"] == 1


async def test_bound_passage_preview_and_open_report_actual_page_ranges(monkeypatch):
    passage = {**DEPTH, "kind": F.PASSAGE, "text": "Source text " * 1500}
    tools = _Tools()
    tools.records = [passage]
    task = replace(TASK, input_refs=(passage["id"],))
    ctx, seen, _, _ = _ctx(monkeypatch, [("", _call("open", id=passage["id"], offset=1024)),
                                      ("", _call("submit", evidence=[passage["id"]]))], tools)
    result = await sa.run_sub_analyst(task, ctx)
    read = delivery.Delivered()
    read.project(seen[0]["messages"])
    assert read.ranges == [{"id": passage["id"], "shown": [0, 1024], "total": len(passage["text"])}]
    opened = json.loads(next(m["content"] for m in seen[1]["messages"] if m["role"] == "tool"))
    assert opened["text"] == passage["text"][1024:13024] and opened["shown"] == [1024, 13024]
    assert result.status == "returned"


def test_beta_comparison_keeps_each_explicit_benchmark_local():
    spy = {**WEIGHT, "id": "f_beta_spy", "measure": "MSFT.beta.SPY", "unit": "BETA", "value": .7}
    qqq = {**spy, "id": "f_beta_qqq", "measure": "MSFT.beta.QQQ", "value": .8}
    verdict = answer_check.check("MSFT beta to SPY is 0.70× [f_beta_spy] and to QQQ is 0.80× [f_beta_qqq].",
                                 Ledger.of([spy, qqq]))
    assert verdict.ok, verdict.problems


def test_prior_validation_stamp_does_not_certify_new_boundary_rules():
    ledger = Ledger.of([WEIGHT])
    scope = AS.scope_of({}, "MSFT")
    stamp = AS.validation_context(scope, [WEIGHT["id"]], ledger)
    text = "MSFT weighs 16.0% [f_w1a2b3c4d5e6]."
    assert AS.reusable(text, [WEIGHT["id"]], stamp, scope, ledger, "MSFT")
    assert not AS.reusable(text, [WEIGHT["id"]], {**stamp, "version": 1}, scope, ledger, "MSFT")
