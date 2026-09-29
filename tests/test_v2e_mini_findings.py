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
async def test_repaired_sentence_is_delivered_without_a_coverage_attempt(monkeypatch):
    _no_db_state(monkeypatch)
    chat, lead, _ = _script(
        [("", _ask(None, {})), (UNSOURCED, None), ("", _repair(ROW))],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    out = await meta_agent.handle_message(_factory([]), "sess", Q)
    assert "gate" not in out["meta"] and out["meta"]["completion"] is None
    assert len(lead) == 3 and out["text"].startswith("MSFT weighs 16.0%")
    assert "Still open" not in out["text"]


@pytest.mark.asyncio
async def test_two_refused_sentences_still_end_the_turn(monkeypatch):
    _no_db_state(monkeypatch)
    chat, _, _ = _script(
        [("", _ask(None, {})), (UNSOURCED, None), ("", _repair(UNSOURCED + " Really.")), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    out = await meta_agent.handle_message(_factory([]), "sess", Q)
    assert out["meta"]["gate"] == "exhausted"
    assert out["meta"]["delivery"] == "not_answered"
    assert out["meta"]["gate_refusals"] == ["unsourced_figure", "unsourced_figure"]
