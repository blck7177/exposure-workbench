"""V33 Phase 3 — the evidence broker: request items in, a digest of ledger facts out (offline)."""
from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import evidence_broker as eb
from exposure_workbench.services import facts as F


class _Tools:
    def __init__(self, by_name: dict):
        self.by_name = by_name
        self.calls: list[tuple[str, dict]] = []

    async def call(self, name, args):
        self.calls.append((name, args))
        r = self.by_name.get(name)
        return r(args) if callable(r) else r


class _Llm:
    """A program writer that answers with the programs it is given, in order."""
    def __init__(self, programs):
        self.programs = list(programs)
        self.calls = 0

    async def chat(self, messages, tools=None, **_kw):
        self.calls += 1
        prog = self.programs.pop(0)
        return ("", [{"id": f"w{self.calls}", "function": {"name": "run_program", "arguments": json.dumps({"program": prog})}}])


def _broker(tools, llm=None):
    b = eb.Broker(tools, llm, None, "sess_x", "msg_x", {"issuers": {"MSFT": {"name": "Microsoft"}}})

    async def _no_record(*_a, **_k):
        return None
    b._record = _no_record
    return b


def _row(fid, kind, subject, measure, unit, value, as_of="2026-09-10", params=None):
    return [fid, kind, subject, measure, unit, value, as_of, None, params or {}, []]


def _run_result(rows, held_back=None):
    out = {"program_id": "calc_1", "returns": [], "nodes": {p[8].get("node", "n"): {"kind": p[1]} for p in rows}, "settled": 1, "refused": [],
           "facts": {"columns": list(F.COLUMNS), "rows": rows}}
    if held_back:
        out["held_back"] = held_back
    return out


@pytest.mark.asyncio
async def test_a_figure_comes_back_displayed_with_its_id_and_identity():
    tools = _Tools({"run": _run_result([_row("f_a1", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.1604, params={"node": "w", "rank": 1})])})
    d = await _broker(tools).fulfil([{"subjects": ["port_001"], "want": ["issuer_exposures.weight"], "compare": "rank"}])
    fig = d["items"][0]["figures"][0]
    assert fig == {"id": "f_a1", "subject": "MSFT", "measure": "issuer_exposures.weight", "value": "16.0%", "unit": "RATIO",
                   "as_of": "2026-09-10", "node": "w", "rank": 1}
    assert d["items"][0]["nodes"] == ["w"]
    assert tools.calls[0][0] == "run"


@pytest.mark.asyncio
async def test_an_absence_is_a_boundary_with_its_class():
    rows = [_row("f_x", "absence", None, "conv", None, "conv was not computed — metric_not_filed: X", as_of="n/a", params={"node": "conv", "error": "metric_not_filed"}),
            _row("f_y", "absence", None, "bad", None, "bad was not computed — type_mismatch: …", as_of="n/a", params={"node": "bad", "error": "type_mismatch"})]
    tools = _Tools({"run": _run_result(rows)})
    d = await _broker(tools).fulfil([{"subjects": ["MSFT"], "want": ["net_margin"]}])
    classes = {b["fact"]: b["class"] for b in d["items"][0]["boundaries"]}
    assert classes == {"f_x": "data_absent", "f_y": "type"}


@pytest.mark.asyncio
async def test_filings_news_and_prepare_map_to_their_tools():
    passage = _row("f_p", "passage", "XOM", "10-K Item 7", None, {"text": "Debt maturities are staggered…"}, as_of="n/a", params={"item": "Item 7"})
    tools = _Tools({"read_filings": _run_result([passage]) | {"ticker": "XOM"},
                    "search_web": {"ticker": "AAPL", "sources": [], "facts": {"columns": list(F.COLUMNS), "rows": []}},
                    "start": {"enqueued": True, "task_id": "task_1", "kind": "company_readiness", "ticker": "MRK"}})
    d = await _broker(tools).fulfil([
        {"subjects": ["XOM"], "want": ["filings:item 7"]},
        {"subjects": ["AAPL"], "want": ["news:trade secret case"], "window": "two weeks"},
        {"subjects": ["MRK"], "want": ["prepare"]},
    ])
    names = [n for n, _ in tools.calls]
    assert names == ["read_filings", "search_web", "start"]
    assert tools.calls[0][1] == {"ticker": "XOM", "item": "7"}
    assert tools.calls[1][1]["days"] == 14 and tools.calls[1][1]["query"] == "trade secret case"
    assert d["items"][0]["passages"][0]["text"].startswith("Debt maturities")
    assert d["items"][2]["started"][0]["subject"] == "MRK"


@pytest.mark.asyncio
async def test_a_spent_budget_stops_the_rest_of_the_request():
    tools = _Tools({"run": {"error": "budget_exceeded", "kind": "turn_tool", "used": 15, "limit": 15}})
    d = await _broker(tools).fulfil([{"subjects": ["MSFT"], "want": ["net_margin"]}, {"subjects": ["AAPL"], "want": ["net_margin"]}])
    assert len(tools.calls) == 1
    assert d["items"][0]["boundaries"][0]["class"] == "budget"
    assert d["items"][1]["boundaries"][0]["class"] == "budget"


@pytest.mark.asyncio
async def test_what_the_builder_cannot_say_goes_to_the_writer_with_the_type_report():
    good = {"let": [{"name": "m", "expr": {"fn": "method", "name": "net_margin", "subject": "MSFT"}}]}
    bad = {"let": [{"name": "m", "expr": {"fn": "vector", "entries": {"MSFT": 1}}}]}
    seen = []

    def run(args):
        seen.append(args["program"])
        if args["program"] == bad:
            return {"error": "type_errors", "problems": [{"at": "m", "reason": "type_mismatch", "fix": "…"}]}
        return _run_result([_row("f_m", "scalar", "MSFT", "net_margin", "RATIO", 0.39, params={"node": "m"})])

    tools = _Tools({"run": run})
    llm = _Llm([bad, good])
    d = await _broker(tools, llm).fulfil([{"subjects": ["MSFT"], "want": ["net margin please"], "ask": "MSFT's net margin"}])
    assert llm.calls == 2 and seen == [bad, good]
    assert d["items"][0]["figures"][0]["value"] == "39.0%"


@pytest.mark.asyncio
async def test_without_a_writer_an_inexpressible_item_is_a_boundary_with_the_nearest_names():
    tools = _Tools({})
    d = await _broker(tools, None).fulfil([{"subjects": ["MSFT"], "want": ["gross_margn"]}])
    b = d["items"][0]["boundaries"][0]
    assert b["class"] == "boundary" and b["want"] == "gross_margn"
    assert "gross_margin" in " ".join(b.get("nearest") or []) or "gross_margin" in b["text"]
    assert tools.calls == []


@pytest.mark.asyncio
async def test_held_back_figures_are_said_not_hidden():
    tools = _Tools({"run": _run_result([_row("f_a1", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.16, params={"node": "w"})],
                                       held_back={"count": 3, "measures": ["AAPL:issuer_exposures.weight"]})})
    d = await _broker(tools).fulfil([{"subjects": ["port_001"], "want": ["issuer_exposures.weight"]}])
    assert any(b["class"] == "held_back" and "3 more" in b["text"] for b in d["items"][0]["boundaries"])


# ── V33C ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_item_that_asks_for_a_method_and_a_passage_goes_through_both_doors():
    """V33C Q04: margins and the Item 7 passage in one item; the item was sent whole
    to the program writer, which read the margins as filed lines."""
    tools = _Tools({"run": _run_result([_row("f_gm", "scalar", "LLY", "gross_margin", "RATIO", 0.81, params={"node": "gross_margin_lly"})]),
                    "read_filings": {"ticker": "LLY", "item_code": "7", "facts": {"columns": list(F.COLUMNS),
                                     "rows": [["f_p7", "passage", "LLY", "10-K Item 7", None, {"text": "Gross margin rose."}, "2026-02-01", None, {"item": "7"}, []]]}}})
    out = await _broker(tools).fulfil([{"subjects": ["LLY"], "want": ["gross_margin", "filings:Item 7"]}])
    names = [c[0] for c in tools.calls]
    assert names == ["read_filings", "run"]
    (entry,) = out["items"]
    assert [f["id"] for f in entry["figures"]] == ["f_gm"] and [p["id"] for p in entry["passages"]] == ["f_p7"]


@pytest.mark.asyncio
async def test_prepare_does_not_start_what_is_on_the_desk():
    tools = _Tools({"start": {"enqueued": True, "kind": "readiness", "ticker": "GS", "task_id": "task_1", "facts": {"columns": list(F.COLUMNS), "rows": []}}})
    b = eb.Broker(tools, None, None, "sess_x", "msg_x", {"desk": {"issuers_on_desk": ["JPM"], "issuers_preparing": ["BAC"]}})

    async def _no_record(*_a, **_k):
        return None
    b._record = _no_record
    out = await b.fulfil([{"subjects": ["JPM", "BAC", "GS"], "want": ["prepare"]}])
    assert [a["subject"] for _n, a in tools.calls] == ["GS"]
    (entry,) = out["items"]
    notes = {x["subject"]: x["text"] for x in entry["boundaries"] if x.get("class") == "note"}
    assert "already on the desk" in notes["JPM"] and "being prepared" in notes["BAC"]
    assert entry["started"] and entry["started"][0]["task"] == "task_1"


@pytest.mark.asyncio
async def test_a_derivation_is_compiled_with_the_reads_and_costs_no_writer_call():
    """V33C Q11: four columns compiled and ran, the ask said "the room to warning",
    and the analyst subtracted in prose and was refused twice. A heuristic then
    guessed whether to spend a second writer call on it; `derive` says it outright."""
    seen: list = []
    tools = _Tools({"run": lambda args: seen.append(args) or _run_result(
        [_row("f_room", "scalar", "issuer_concentration:MSFT",
              "subtract(limit_checks.warning_level, limit_checks.current_value)", "RATIO", -0.01,
              params={"node": "room", "op": "subtract"})])})
    llm = _Llm([])
    out = await _broker(tools, llm).fulfil([{"subjects": ["port_001"],
                                             "want": ["limit_checks.current_value", "limit_checks.warning_level"],
                                             "derive": ["limit_checks.warning_level - limit_checks.current_value"]}])
    assert llm.calls == 0 and len(seen) == 1
    names = [b["name"] for b in seen[0]["program"]["let"]]
    assert any(b["expr"]["fn"] == "sub" for b in seen[0]["program"]["let"]), names
    assert [f["id"] for f in out["items"][0]["figures"]] == ["f_room"]


@pytest.mark.asyncio
async def test_a_name_the_desk_does_not_hold_costs_that_name_and_the_rest_still_runs():
    tools = _Tools({"run": _run_result([_row("f_w", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.16,
                                              params={"node": "issuer_exposures_weight"})])})
    out = await _broker(tools).fulfil([{"subjects": ["port_001"],
                                        "want": ["issuer_exposures.weight", "issuer_exposures.ticker"]}])
    (entry,) = out["items"]
    assert [f["id"] for f in entry["figures"]] == ["f_w"]
    assert [b["want"] for b in entry["boundaries"]] == ["issuer_exposures.ticker"]


@pytest.mark.asyncio
async def test_the_digest_fits_its_cap_by_holding_back_rows_not_items(monkeypatch):
    """V33D: two items past the cap, dumps_capped dropped an item whole, and the analyst
    wrote 'the desk truncated both requests'."""
    rows = [_row(f"f_{i:04d}", "scalar", f"T{i}", "issuer_exposures.weight", "RATIO", i / 1000, params={"node": "w"}) for i in range(60)]
    tools = _Tools({"run": _run_result(rows)})
    monkeypatch.setattr(eb, "DIGEST_CHAR_LIMIT", 4_000)
    out = await _broker(tools).fulfil([{"subjects": ["port_001"], "want": ["issuer_exposures.weight"]}])
    (entry,) = out["items"]
    assert 5 <= len(entry["figures"]) < 60
    assert len(json.dumps(out)) <= 4_000
    (held,) = [b for b in entry["boundaries"] if b.get("class") == "held_back"]
    assert held["count"] == 60 - len(entry["figures"]) and held["measures"]


@pytest.mark.asyncio
async def test_the_writer_reads_the_domains_worked_programs():
    seen = {}

    class _Llm2(_Llm):
        async def chat(self, messages, tools=None, **_kw):
            seen["user"] = messages[1]["content"]
            return await super().chat(messages, tools=tools)
    tools = _Tools({"run": _run_result([_row("f_x", "scalar", "port_001", "portfolio.deepest_depth", "RATIO", 0.12, params={"node": "depth"})])})
    llm = _Llm2([{"let": [["depth", {"fn": "method", "name": "book.drawdown_episodes", "subject": "port_001"}]]}])
    b = eb.Broker(tools, llm, None, "sess_x", "msg_x", {}, examples=[("the worst episode", '{"let": [["episodes", {"fn": "method", "name": "book.drawdown_episodes", "subject": "<port>"}]]}')])

    async def _no_record(*_a, **_k):
        return None
    b._record = _no_record
    await b.fulfil([{"subjects": ["port_001"], "want": ["book.explain_episode"], "ask": "the worst episode explained"}])
    assert "worked_examples" in seen["user"] and "book.drawdown_episodes" in seen["user"]
