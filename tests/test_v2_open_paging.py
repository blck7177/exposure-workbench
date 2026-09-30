"""V2 P1.3/P1.4 (design v0.4 G3): nothing the lead opens is cut in silence. A call's
rows come a page at a time with the total and the range; a thinned series says so
on its row and pages its points; a truncated message says the way back.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from exposure_workbench.agents import delegation as dl, meta_agent
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.utils import json as ejson


def _row(i: int) -> dict:
    return {"id": f"f_r{i:04d}abcdef", "kind": "scalar", "measure": "issuer_exposures.weight", "subject": f"T{i}",
            "unit": "RATIO", "value": 0.01, "as_of": "2026-09-10", "window": None, "params": {"pull": "r_big"},
            "standalone": True, "sources": ["run_x"], "group": "composition", "means": {}}


def _series(n: int) -> F.Fact:
    start = date(2020, 1, 1)
    return F.fact(F.SERIES, "adj_close", subject="AAPL", unit="MONEY_PER_SHARE",
                  points=tuple(((start + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(n)),
                  as_of=(start + timedelta(days=n - 1)).isoformat(), params={"pull": "r_px"}, sources=["run_x"])


@pytest.mark.asyncio
async def test_open_pages_a_calls_rows_and_says_the_total(monkeypatch):
    led = Ledger.of([_row(i) for i in range(100)])

    async def _ledger(_f, _s):
        return led

    monkeypatch.setattr(meta_agent, "_load_ledger", _ledger)
    first = await meta_agent._open(None, "sess", "r_big", [], 0)
    assert (first["total"], len(first["rows"]), first["shown"], first["next_offset"]) == (100, 80, [0, 80], 80)
    second = await meta_agent._open(None, "sess", "r_big", [], first["next_offset"])
    assert (len(second["rows"]), second["shown"]) == (20, [80, 100]) and "next_offset" not in second
    assert (await meta_agent._open(None, "sess", "r_big", [], 100))["error"] == "past_the_end"


@pytest.mark.asyncio
async def test_a_thinned_series_says_so_on_its_row_and_open_pages_its_points(monkeypatch):
    long, short = _series(90), _series(12)
    led = Ledger.of_facts([long, short])

    async def _ledger(_f, _s):
        return led

    monkeypatch.setattr(meta_agent, "_load_ledger", _ledger)
    assert "(60 of 90 points shown; every point is on the record under this id)" in F.line(long)
    assert "points shown" not in F.line(short), "a series the row shows whole says nothing about itself"
    page = await meta_agent._open(None, "sess", long.id, [], 60)
    assert (page["total"], len(page["points"]), page["shown"]) == (90, 30, [60, 90]) and "row" in page
    whole = await meta_agent._open(None, "sess", short.id, [], 0)
    assert whole["points"] == [list(p) for p in short.points]
    assert whole["total"] == 12 and whole["next_offset"] is None
    assert whole["identity"]["subject"] == "AAPL"


def test_the_open_tool_takes_an_offset_and_says_what_it_is_for():
    props = dl.OPEN_TOOL["function"]["parameters"]["properties"]
    assert set(props) == {"id", "offset"} and dl.OPEN_TOOL["function"]["parameters"]["required"] == ["id"]
    assert "next_offset" in props["offset"]["description"]
    assert "offset" in dl.OPEN_TOOL["function"]["description"]


def test_a_truncated_message_names_the_way_back():
    big = {"returns": [{"task_id": f"tsk_{i}", "lines": ["x" * 200]} for i in range(40)]}
    cut = ejson.dumps_capped(big, 2_000)
    assert "truncated" in cut and "on the record" in cut and "offset" in cut
