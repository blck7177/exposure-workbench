"""V37/A3 — every block says what it is, and every field is explained once.

`caveats` has been in the lead's payload since V36 Phase 1 and the lead's own
instructions never named it. Four of round B's false statements are an analyst
writing the truth into that field — "came back on quarter-end dates rather than
three year-end dates" — and the lead writing the finding without it. A field
nobody is told about is a field nobody reads, and nothing in the code required
anybody to be told.

So the code declares which half of each payload its reader has to act on
(`delegation.FOR_THE_LEAD_TO_READ`, `digest.FOR_THE_ANALYST_TO_READ`) and this
file holds the halves apart. A field added later is one or the other by
declaration: put it in the reading half without a sentence about it and this
fails; leave it out of both and this fails too. That is the whole mechanism — no
template engine, because what was broken is what gets SAID about a block, not how
the string is built.
"""
from __future__ import annotations

import json
import re

import pytest

from exposure_workbench.agents import delegation as dl, meta_agent, sub_analyst
from exposure_workbench.services import digest as dg, facts as F
from tests import provider_contract


def _one_result() -> dict:
    """An E10 payload with every field present — the shape a new key has to pass
    through to reach the lead."""
    task = dl.Task(task_id="tsk_1", domain="book_limits_and_triggers", subjects=("port_001",),
                   want_to_know=("which check is nearest", "how much room"))
    r = dl.AnalystResult(task=task, status="partial",
                         findings=[{"want": 1, "facts": ["f_aaaa1111"], "finding": "MSFT is nearest at 16.0% [f_aaaa1111]."}],
                         not_done=[{"want": 2, "why": "no tier came back", "boundary": "f_bbbb2222", "said": "…"}],
                         caveats=["the series came back on quarter-end dates"],
                         follow_ups=["ask for the prior run"],
                         refused=[{"want": 2, "problems": [{"reason": "mark_mismatch"}]}],
                         made=[{"node": "after", "id": "calc_1", "kind": "scenario"}],
                         shown=[{"value": "16.0% [f_aaaa1111]", "measure": "limit_checks.current_value"}],
                         coverage={"asked": 2, "done": 1, "not_done": 1, "refused": 1},
                         cost={"completions": 3, "evidence_calls": 2, "starts": 0})
    r.report_id = "rep_1"
    return dl.for_lead([r])


def test_every_field_the_lead_must_act_on_is_explained_in_its_instructions():
    surface = meta_agent._SYSTEM + dl.HOW_TO_CITE
    missing = [k for k in dl.FOR_THE_LEAD_TO_READ if k not in surface]
    assert not missing, (f"the lead is handed {missing} and told nothing about them — say what each is for in "
                         f"meta_agent._SYSTEM or delegation.HOW_TO_CITE, or declare it LEADS_BOOKKEEPING")


def test_no_field_reaches_the_lead_without_being_declared_one_or_the_other():
    [entry] = _one_result()["analysts"]
    declared = set(dl.FOR_THE_LEAD_TO_READ) | set(dl.LEADS_BOOKKEEPING)
    assert set(entry) <= declared, (f"{sorted(set(entry) - declared)} is in E10 and in neither list: a field the lead "
                                    f"has to act on goes in FOR_THE_LEAD_TO_READ (and gets a sentence), the turn's "
                                    f"own bookkeeping in LEADS_BOOKKEEPING")
    # and the reading half is not aspirational: `for_lead` really carries it
    assert set(dl.FOR_THE_LEAD_TO_READ) <= set(entry) | {"report_id"}


def test_a_caveat_is_told_to_be_written_beside_the_figure_it_qualifies():
    """Not merely named: round B's analysts wrote the truth into `caveats` four
    times and the lead's finding contradicted it in the same breath."""
    surface = (meta_agent._SYSTEM + dl.HOW_TO_CITE).lower()
    assert "beside the figure it qualifies" in surface
    assert "without its caveat is not what the analyst found" in surface


def test_every_field_of_a_result_is_explained_to_the_analyst():
    surface = sub_analyst._SYSTEM + dg.HOW_TO_CITE
    missing = [k for k in dg.FOR_THE_ANALYST_TO_READ if k not in surface]
    assert not missing, f"the analyst reads {missing} and is told nothing about them"


def test_a_result_carries_no_key_the_analyst_was_not_told_about():
    rows = [["f_w0001111", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.16, "2026-09-10", None,
             {"node": "w", "place": 1, "of": 3}, []],
            ["f_s0001111", "series", "AAPL", "days_sales_outstanding", "COUNT",
             {"points": [["2024-09-28", 31.19], ["2025-09-27", 34.89]], "n": 2}, "2025-09-27", None,
             {"node": "dso"}, []]]
    res = {"program_id": "calc_1", "nodes": {"w": {"kind": "vector"}}, "settled": 2, "refused": [],
           "held_back": {"count": 4, "measures": ["AAPL:issuer_exposures.weight"]},
           "facts": {"columns": list(F.COLUMNS), "rows": rows}}
    d = dg.render(res, mint=dg.Minter())
    declared = set(dg.FOR_THE_ANALYST_TO_READ) | set(dg.ANALYSTS_BOOKKEEPING)
    assert set(d) <= declared, sorted(set(d) - declared)


@pytest.mark.asyncio
async def test_each_block_of_context_says_where_it_came_from_and_what_it_is_for(monkeypatch):
    """A one-line heading over raw JSON leaves the reading of a block to the field
    names inside it. Both readers get a tag with `source` and `use`; the lead's two
    system blocks and the analyst's three are the whole of what is pushed."""
    seen: list[dict] = []

    class _Llm:
        def for_actor(self, actor):
            return self

        async def chat(self, messages, tools=None, **kw):
            provider_contract.check(messages)
            seen.append({"messages": list(messages)})
            return "", None

    async def _nothing(*_a, **_k):
        return None

    monkeypatch.setattr(sub_analyst, "_record", _nothing)
    monkeypatch.setattr(sub_analyst, "_ledger", _nothing)
    task = dl.Task(task_id="t", domain="book_liquidity", subjects=("port_001",),
                   want_to_know=("days to liquidate each name",))
    ctx = sub_analyst.TurnContext(tools_session=type("T", (), {"tools": []})(), llm=_Llm(),
                                  db_factory=None, session_id="s", message_id="m", briefing={})
    await sub_analyst.run_sub_analyst(task, ctx)

    content = seen[0]["messages"][1]["content"]
    tags = dict(re.findall(r"<(\w+)\s([^>]*)>", content))
    assert set(tags) == {"task", "subjects", "boundaries"}
    for name, attrs in tags.items():
        assert "source=" in attrs and "use=" in attrs, (name, attrs)
    # and the lead's two, which are the same named objects the wording sheet reads
    for tag in (meta_agent.BRIEFING_TAG, meta_agent.ROSTER_TAG,
                sub_analyst.TASK_TAG, sub_analyst.SUBJECTS_TAG, sub_analyst.BOUNDARIES_TAG):
        assert tag.startswith("<") and tag.endswith(">")
        assert "source=" in tag and "use=" in tag, tag
