"""What the first live round on desk-v2-wip found (V2E_mini, 2026-09-29;
docs/spikes/v1/ACCEPTANCE_V2E_mini.md §1–§2), pinned offline.

§1 — the analysis state is a record: the catalogue hands the briefing `date`
objects, the state is a JSONB column, and every save of a book-scoped state and
every analyst report store raised `date is not JSON serializable` (swallowed:
14 of 20 turns never persisted a state, 13 of 46 reports were stored). The
offline suite was green because its transport was a mock. Here the record is
serialised the way the column serialises it.

§2 — a coverage refusal is not a sentence attempt: counted as one, with two
attempts, it ended the turn on the bar after one refused sentence on either
order — 7 of the round's 10 exhaustions. On the gate harness: the check, the
protocol, the ledger and the state are real; the provider and the tool face are
scripted.
"""

from __future__ import annotations

import datetime
import json

import pytest

from exposure_workbench.agents import meta_agent
from exposure_workbench.services import analysis_state as AS
from tests.test_meta_agent_gate import _W_MSFT, _factory, _run, _run_result, _stub_desk, _stub_llm, _stub_tools
from tests.test_v2_loop_state import Q, REQS, ROW, _ask, _no_db_state, _script, _submit

# the briefing as services/briefing.py builds it: a book's `positions_as_of` and an
# issuer's `latest_period_end`, filing dates and price span come from the rows as dates
BRIEFING = {
    "subjects": {"tickers": ["msft"], "portfolios": ["port_001"], "runs": []},
    "portfolios": {"port_001": {"name": "Core", "runs": {"latest": {"id": "run_x", "as_of": "2026-09-10"}, "prev": None},
                                "positions_as_of": datetime.date(2026, 9, 9), "holdings": [], "checks": []}},
    "issuers": {"MSFT": {"name": "Microsoft", "status": "ready", "latest_period_end": datetime.date(2026, 6, 30),
                         "filings": {"10-K": {"latest": datetime.date(2025, 7, 30)}},
                         "prices": {"from": datetime.date(2024, 1, 2), "to": datetime.datetime(2026, 9, 10, 0, 0)}}},
}


def test_the_scope_is_a_record_and_serialises_as_the_column_does():
    state = AS.new_turn("sess_1", "msg_1", "how big is MSFT in the book", BRIEFING)

    fields = AS._fields(state)
    json.dumps(fields)                                   # what the INSERT serialises; raised before
    assert json.loads(json.dumps(state.scope)) == state.scope, "a restored scope compares equal to a fresh one"
    assert state.scope["snapshots"]["port_001"]["positions_as_of"] == "2026-09-09"
    assert state.scope["issuers"]["MSFT"] == {"latest_period_end": "2026-06-30",
                                              "filings": {"10-K": {"latest": "2025-07-30"}},
                                              "prices": {"from": "2024-01-02", "to": "2026-09-10T00:00:00"}}
    # the analyst report's stamp goes through the same door (sub_analyst._store_report)
    json.dumps({"scope": AS.scope_of(BRIEFING, "q"), "validation": AS.validation_context(state.scope, [], None)})


def test_a_scope_written_now_is_the_scope_a_later_turn_reads_back():
    """`reusable` compares a stored validation's scope with this turn's; a date object on
    one side and its string on the other would never be equal, and nothing would ever
    be inherited."""
    now = AS.scope_of(BRIEFING, "the same words")
    stored = json.loads(json.dumps(now))
    assert stored == AS.scope_of(BRIEFING, "the same words")


UNSOURCED = "NVDA weighs 42% of the book."


def _repair(text: str):
    return [{"id": "r1", "function": {"name": meta_agent.REPAIR_TOOL_NAME,
                                      "arguments": json.dumps({"replacements": [{"tag": "S1", "text": text}]})}}]


@pytest.mark.asyncio
async def test_a_repair_that_passes_and_is_refused_for_coverage_still_leaves_the_lead_its_reply(monkeypatch):
    """Q01 / Q10: one refused sentence, a repair that passed every check, then the coverage
    refusal — and the turn ended on the bar. The coverage refusal is once per turn, and
    the sentence attempts are the sentence attempts."""
    _no_db_state(monkeypatch)
    chat, lead, _sub = _script(
        [("", _ask(REQS, {"for": ["R1"]})), (UNSOURCED, None), ("", _repair(ROW)), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)

    assert "gate" not in out["meta"], out["text"]
    assert out["meta"]["completion"] == "partial"
    assert out["text"].startswith("MSFT weighs 16.0%") and "Still open: “what will its weight be next year”" in out["text"]
    # four lead completions: the ask, the refused reply, the repair, the reply that went out —
    # the third was told its sentence, the fourth was told the requirement (as the tool's result)
    assert len(lead) == 4
    assert "42%" in lead[2][-1]["content"] and "partial answer" not in lead[2][-1]["content"]
    assert lead[3][-1]["role"] == "tool" and "[R2] what will its weight be next year" in lead[3][-1]["content"]


@pytest.mark.asyncio
async def test_a_coverage_refusal_first_does_not_cost_the_sentence_repair(monkeypatch):
    """Q07, Q09, Q12, Q17, Q20: refused for coverage, then one refused sentence — and no
    repair was left. With the coverage refusal outside the count, the repair is."""
    _no_db_state(monkeypatch)
    chat, lead, _sub = _script(
        [("", _ask(REQS, {"for": ["R1"]})), (ROW, None), (UNSOURCED, None), ("", _repair(ROW))],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)

    assert "gate" not in out["meta"], out["text"]
    assert out["meta"]["completion"] == "partial"
    assert out["text"].startswith("MSFT weighs 16.0%") and "Still open" in out["text"]
    # the ask, the reply refused for coverage, the reply refused for its sentence, the repair that went out
    assert len(lead) == 4
    assert lead[2][-1]["role"] == "user" and "[R2] what will its weight be next year" in lead[2][-1]["content"]
    assert lead[3][-1]["role"] == "user" and "42%" in lead[3][-1]["content"]


@pytest.mark.asyncio
async def test_two_refused_sentences_still_end_the_turn(monkeypatch):
    """The bound on sentence attempts is what it was: the coverage refusal moved out of
    the count, not the count."""
    _no_db_state(monkeypatch)
    chat, _lead, _sub = _script(
        [("", _ask(REQS, {"for": ["R1"]})), (ROW, None), (UNSOURCED, None), ("", _repair(UNSOURCED + " Really.")),
         (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)

    assert out["meta"].get("gate") == "exhausted"
    assert out["meta"]["gate_refusals"] == ["requirement_unaddressed", "unsourced_figure", "unsourced_figure"]
