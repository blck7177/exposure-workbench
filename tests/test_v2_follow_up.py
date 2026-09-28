"""V2 P2.3 (design v0.4 G4): follow_up_of restores the task it names — what it
settled, with the rows, and what stopped it — and never a refused entry (A3).
Offline, on the analyst-loop harness.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation as dl, sub_analyst as sa
from tests.test_v1_analyst import FINDING, SETTLED, WEIGHT, _Tools, _ctx, _read, _submit

FOLLOW = dl.Task("tsk_2", "risk", ("port_001",), ("and the sector it sits in",), follow_up_of="tsk_1")
PRIOR = {"id": "rep_1", "task_id": "tsk_1", "domain": "risk", "status": "verified",
         "accepted_lines": [SETTLED, {"n": 2, "settled": False, "why": "the desk does not forecast", "boundary": "f_policy_no_forecast"}],
         "brief": {"refused": [{"want": 3, "reason": "unsourced_figure"}]},
         "problems": [{"where": "line 3", "reason": "unsourced_figure", "sentence": "MSFT will weigh 20.0% next year."}]}


@pytest.mark.asyncio
async def test_the_follow_up_reads_what_the_prior_task_settled_and_not_what_was_refused(monkeypatch):
    tools = _Tools()
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED))], tools)
    tools.records.append(dict(WEIGHT))                      # the prior task's row is on the session ledger

    async def _load_by_task(db, session_id, task_id):
        return PRIOR if task_id == "tsk_1" else None

    monkeypatch.setattr(sa.analyst_reports, "load_by_task", _load_by_task)
    await sa.run_sub_analyst(FOLLOW, ctx)
    first = seen[0]["messages"][1]["content"]
    assert sa.PRIOR_TAG in first and first.rstrip().endswith("</prior>")
    prior = json.loads(first.split(sa.PRIOR_TAG, 1)[1].rsplit("</prior>", 1)[0])
    assert prior["task_id"] == "tsk_1"
    assert prior["settled"][0]["finding"] == FINDING and prior["settled"][0]["rows"][0].startswith("[f_w1a2b3c4d5e6]")
    assert prior["not_settled"][0]["boundary"].startswith("[f_policy_no_forecast] absent:")
    assert "20.0%" not in first, "A3: the refused entry is on the record and not in the context"


@pytest.mark.asyncio
async def test_a_follow_up_of_an_unknown_task_reads_as_a_plain_task(monkeypatch):
    tools = _Tools()
    ctx, seen, _steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED))], tools)

    async def _none(db, session_id, task_id):
        return None

    monkeypatch.setattr(sa.analyst_reports, "load_by_task", _none)
    await sa.run_sub_analyst(FOLLOW, ctx)
    assert sa.PRIOR_TAG not in seen[0]["messages"][1]["content"]
