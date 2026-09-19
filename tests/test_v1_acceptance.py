"""V1 §6 验收总表: the rows of the acceptance table that no test held (found 2026-09-19 when the
code was read against the plan).

    工具只认资源不认问题    a tool's text holds no question of the handbook's section 1
    log 由 why 长出          the log rebuilt from `agent_steps` IS the log the analyst kept
    每个动词三类单元测试     every verb: what it gives, what it refuses with a way out, whose it is
    主分析师无词汇          everything the lead is sent, not only its role text

Offline, like tests/test_v1_primitives.py: services are replaced by the payloads they return, and
the registry wrapper — validation, budget, adapter, ledger, trace — is the real one.
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.agents import meta_agent, sub_analyst as sa
from exposure_workbench.analytics import handbook, registry as desk
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L
from exposure_workbench.tools import primitives as P
from exposure_workbench.tools import registry as R

WHY = "line 1 asks where the book is concentrated; the weights are on the holdings table"


def _descriptions(schema) -> list[str]:
    out = []
    if isinstance(schema, dict):
        out += [schema["description"]] if isinstance(schema.get("description"), str) else []
        for v in schema.values():
            out += _descriptions(v)
    elif isinstance(schema, list):
        for v in schema:
            out += _descriptions(v)
    return out


def _tool_text(face: str) -> dict[str, str]:
    return {name: " ".join([t.description, *_descriptions(t.json_schema)]).lower()
            for name, t in P.build_analyst_registry(face).tools.items()}


# ── a tool knows a resource, never a question ────────────────────────────────

QUESTIONS = [a.lower() for c in handbook.CHAPTERS.values() for t in c.topics for a in t.asked]
# a topic that is itself a question ("whether it is already in the price"); "sensitivity" is a word
QUESTION_TOPICS = [t.name.lower() for c in handbook.CHAPTERS.values() for t in c.topics
                   if t.name.lower().startswith(("whether", "how ", "where ", "what "))]


@pytest.mark.parametrize("face", P.FACES)
def test_no_tool_says_a_question_of_the_handbooks_first_section(face):
    assert len(QUESTIONS) >= 40 and len(QUESTION_TOPICS) >= 4
    for name, text in _tool_text(face).items():
        assert not [q for q in QUESTIONS if q in text], name
        assert not [q for q in QUESTION_TOPICS if q in text], name


def test_the_scan_can_go_red():
    text = "a name's closes over a window. use it to see whether it has become more volatile."
    assert [q for q in QUESTION_TOPICS if q in text] == ["whether it has become more volatile"]


# ── everything the lead is sent, not only its role text ─────────────────────

def test_nothing_the_lead_is_sent_holds_a_verb_a_measure_key_or_the_old_words():
    sent = "\n".join([meta_agent._SYSTEM, meta_agent.BRIEFING_TAG, meta_agent.ROSTER_TAG, meta_agent.READINGS_TAG,
                      json.dumps(handbook.roster(), ensure_ascii=False), handbook.meaning_layer(),
                      json.dumps([dl.ASK_TOOL, dl.OPEN_TOOL, meta_agent.REPAIR_TOOL], ensure_ascii=False),
                      meta_agent._WRITE_OR_ASK, meta_agent._REPAIR_ONLY])
    verbs = {v for face in P.FACES for v in P.FACE_TOOLS[face]} - {"list", "start", "metric", "calc", "scenario"}   # plain English too
    assert not [v for v in verbs if re.search(rf"(?<![\w.]){v}(?![\w.])", sent)]
    keys = [k for k in desk.METHODS if "_" in k or "." in k]
    assert not [k for k in keys if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w.])", sent)]
    assert not re.search(r"\b(?:[Dd]elegate|program|node|digest|legend)\b", sent)


# ── the log grows out of the calls ───────────────────────────────────────────

class _Db:
    def add(self, row): pass
    async def flush(self): pass
    async def commit(self): pass
    async def rollback(self): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


def _call(name: str, **args) -> dict:
    return {"id": f"c{abs(hash((name, json.dumps(args, sort_keys=True)))) % 10**8}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


TASK = dl.Task(task_id="tsk_log", analyst="risk", subjects=("port_001",),
               lines=("where is the book concentrated", "what does the book look like after selling half of MSFT"))


async def test_the_log_rebuilt_from_agent_steps_is_the_log_the_analyst_kept(monkeypatch):
    """Five calls: a look at what is there, a read, a read whose arguments do not fit (refused
    before it runs), a scenario that makes a book, and the first read again unchanged (answered
    from before: never sent, so in neither log). Then the brief."""
    steps: list[dict] = []

    async def _record(db, session_id, **kw):
        steps.append(kw)
        return f"step_{len(steps)}"

    async def _reserve(db, session_id, is_external_search=False, message_id=None):
        pass

    async def _book_read(db, book, table, column=None, row=None, which=None, *, why):
        return {"book": "run_1", "as_of": "2026-09-10", "table": table, "withheld": [],
                "figures": [{"name": "issuer_exposures.MSFT.weight", "value": 0.16, "unit_class": "ratio", "means": {}}]}

    async def _list(db, what, subject=None, *, why):
        return {"catalogue": ["port_001 — US Growth & Income Portfolio", "run run_1 — as of 2026-09-10, completed"]}

    async def _scenario(db, book, trades, *, why):
        return {"calc_id": "calc_aaaabbbbcccc", "made": "calc_aaaabbbbcccc", "subject": "run_1", "as_of": "2026-09-10",
                "proceeds": 800.0, "market_value": 9200.0,
                "sold": [{"ticker": "MSFT", "fraction": 0.5, "market_value_sold": 800.0, "exited": False}]}

    monkeypatch.setattr(R.trace_service, "record_step", _record)
    monkeypatch.setattr(R.sess, "reserve", _reserve)
    reg = P.build_analyst_registry("risk")
    for name, fn in (("book_read", _book_read), ("list", _list), ("scenario", _scenario)):
        monkeypatch.setitem(reg.tools, name, R.Tool(**{**reg.tools[name].__dict__, "fn": fn}))

    class _Face:
        tools = reg.schemas()

        async def call(self, name, args, *, actor=None):
            return await R.invoke(reg, _Db(), "sess", name, args, message_id="msg_1", actor=actor)

    @asynccontextmanager
    async def _open(face):
        yield _Face()

    read = dict(book="port_001", table="issuer_exposures", column="weight", why=WHY)
    script = iter([
        [_call("list", what="book", subject="port_001", why="line 1: which runs the book has")],
        [_call("book_read", **read)],
        [_call("book_read", book="port_001", table="holdings", why="line 1: the same, by another name")],   # not a table
        [_call("scenario", book="port_001", trades=[{"sell": "MSFT", "fraction": 0.5}], why="line 2: the book after the sale")],
        [_call("book_read", **{**read, "why": "line 1 again"})],                                           # the same call: not sent
        "submit",
    ])
    ledger_facts: list[dict] = []

    async def _chat(messages, tools, **kw):
        nxt = next(script)
        if nxt == "submit":
            ledger_facts[:] = [rec for s in steps for rec in L.facts_in(s.get("evidence_refs") or [])]
            weight = next(r for r in ledger_facts if r["measure"] == "issuer_exposures.weight")
            boundary = next(r for r in ledger_facts if r["kind"] == F.ABSENCE)
            return "", [_call("submit", lines=[
                {"n": 1, "settled": True, "finding": f"MSFT is 16.0% [{weight['id']}] of the book.", "facts": [weight["id"]]},
                {"n": 2, "settled": False, "why": "the after-book was built and not read", "boundary": boundary["id"]}])]
        return "", nxt

    async def _ledger(ctx):
        return L.Ledger.of(ledger_facts)

    async def _store(*a, **k):
        return "rep_1"
    monkeypatch.setattr(sa, "_ledger", _ledger)
    monkeypatch.setattr(sa.analyst_reports, "store", _store)
    ctx = sa.TurnContext(open_tools=_open, llm=SimpleNamespace(chat=_chat), db_factory=lambda: _Db(),
                         session_id="sess", message_id="msg_1", briefing={})
    result = await sa.run_sub_analyst(TASK, ctx)

    assert [c["tool"] for c in result.log] == ["list", "book_read", "book_read", "scenario"]        # the repeat was never sent
    assert [c["got"] for c in result.log] == ["2 names", "1 row", "1 row", "4 rows; made calc_aaaabbbbcccc"]
    assert all(c["why"] for c in result.log)
    assert dl.log_from_steps(TASK, steps, result.status) == dl.log_text(result)
    # and the trace tells a refusal from a reading, which a counter needs: the step says what the call got
    said = [s["result_summary"] for s in steps if s.get("step_type") in ("tool_call", "boundary") and s.get("tool_name") == "book_read"]
    assert said[0].endswith("→ 1 row") and said[1].startswith("invalid arguments") and said[2].endswith("→ 1 row | refused: invalid_arguments")
    # a second task of the same analyst does not inherit the first one's calls
    later = dl.Task(task_id="tsk_later", analyst="risk", subjects=("port_001",), lines=("x",))
    assert dl.log_from_steps(later, steps, "refused").splitlines()[1:] == ["brief: refused"]


# ── every verb: what it gives, what it refuses with a way out, whose it is ──

def _wire(monkeypatch) -> list[dict]:
    steps: list[dict] = []

    async def _record(db, session_id, **kw):
        steps.append(kw)
        return f"step_{len(steps)}"

    async def _reserve(db, session_id, is_external_search=False, message_id=None):
        pass
    monkeypatch.setattr(R.trace_service, "record_step", _record)
    monkeypatch.setattr(R.sess, "reserve", _reserve)
    return steps


def _with(reg: R.ToolRegistry, monkeypatch, name: str, payload: dict) -> None:
    async def _fn(db, **args):
        return dict(payload)
    monkeypatch.setitem(reg.tools, name, R.Tool(**{**reg.tools[name].__dict__, "fn": _fn}))


# one well-formed call of every verb, the payload its service returns, and what a row of it must say
GIVES = {
    "list": ("issuer", dict(what="filings", subject="MSFT"),
             {"catalogue": ["10-K filed 2025-07-30, period to 2025-06-30 — accession 0000950170-25-100235"]}, "1 name"),
    "filings_read": ("issuer", dict(ticker="MSFT", line="revenue", period={"fy": 2025}),
                     {"calc_id": "calc_000000000001", "ticker": "MSFT", "metric": "revenue", "value": 2.82e11, "unit_class": "MONEY",
                      "period": {"start": "2024-07-01", "end": "2025-06-30"}, "accessions": ["0000950170-25-100235"]},
                     "Revenue, MSFT, 2024-07-01 to 2025-06-30: $282B"),
    "prices_read": ("market", dict(ticker="MSFT", field="close"),
                    {"ticker": "MSFT", "as_of": "2026-09-10", "close": {"value": 492.44, "calc_id": "calc_000000000002", "unit_class": "MONEY_PER_SHARE"}},
                    "MSFT, as of 2026-09-10: $492.44"),
    "book_read": ("risk", dict(book="port_001", table="limit_checks", row="issuer_concentration:MSFT"),
                  {"book": "run_1", "as_of": "2026-09-10", "table": "limit_checks", "withheld": [],
                   "figures": [{"name": "limit_checks.issuer_concentration:MSFT.current_value", "value": 0.16, "unit_class": "ratio",
                                "means": {"status": "warning"}}]}, "16.0% — in warning"),
    "metric": ("market", dict(name="price.volatility", subject="MSFT", params={"window_days": 30}),
               {"method": "price.volatility", "ticker": "MSFT", "calc_id": "calc_000000000003", "value": 0.31, "unit_class": "ratio",
                "quantity": "MSFT.vol.30d", "window_days": 30, "as_of": "2026-09-10"}, "31.0% — over the adjusted close"),
    "calc": ("risk", dict(op="subtract", inputs=["f_aaaa11112222", "f_bbbb33334444"]),
             {"op": "subtract", "calc_id": "calc_000000000004", "value": 0.04, "unit_class": "ratio", "as_of": "2026-09-10",
              "quantity": "limit_checks.breach_level.subtract.limit_checks.current_value"},
             "limit checks: breach tier − limit checks: measured"),
    "filings_search": ("issuer", dict(ticker="MSFT", query="supply constraints"),
                       {"ticker": "MSFT", "query": "supply constraints", "passages": [
                           {"chunk_id": "chunk_000000000001", "text": "Supply was constrained in the quarter.", "item": "Item 7",
                            "section_title": "MD&A", "citation": {"form_type": "10-K", "accession": "0000950170-25-100235",
                                                                   "filing_date": "2025-07-30", "char_span": [120, 158]}}]},
                       "accession 0000950170-25-100235, chars 120–158 of the Item"),
    "web_search": ("issuer", dict(ticker="MSFT", query="antitrust ruling"),
                   {"ticker": "MSFT", "sources": [{"source_id": "src_000000000001", "title": "Regulator opens review", "url": "https://example.org/a",
                                                   "snippet": "The regulator said it had opened a review.", "published_at": "2026-09-01", "publisher": "Example"}]},
                   "\"The regulator said it had opened a review.\""),
    "scenario": ("risk", dict(book="port_001", trades=[{"sell": "MSFT", "fraction": 0.5}]),
                 {"calc_id": "calc_aaaabbbbcccc", "made": "calc_aaaabbbbcccc", "subject": "run_1", "as_of": "2026-09-10", "proceeds": 800.0,
                  "market_value": 9200.0, "sold": [{"ticker": "MSFT", "fraction": 0.5, "market_value_sold": 800.0, "exited": False}]},
                 "sold market value sold, MSFT, as of 2026-09-10: $800"),
    "start": ("market", dict(kind="readiness", subject="COST"),
              {"enqueued": True, "task_id": "task_000000000001", "kind": "company_readiness", "ticker": "COST"}, None),
}
# filings_section shares an adapter with filings_search and is read a page at a time (test_v1_primitives)
GIVES["filings_section"] = ("issuer", dict(ticker="MSFT", item="7", filing="0000950170-25-100235"),
                            {"ticker": "MSFT", "item_code": "Item 7", "title": "MD&A", "text": "Revenue rose on cloud demand.",
                             "char_span": [0, 29], "citation": {"form_type": "10-K", "accession": "0000950170-25-100235",
                                                                "filing_date": "2025-07-30"}},
                            "accession 0000950170-25-100235, chars 0–29 of the Item")


def test_every_verb_of_every_face_is_covered_here():
    assert set(GIVES) == {v for face in P.FACES for v in P.FACE_TOOLS[face]} == set(REFUSES)


@pytest.mark.parametrize("verb", sorted(GIVES))
async def test_a_verb_gives_rows_a_reader_needs_no_legend_for(monkeypatch, verb):
    face, args, payload, says = GIVES[verb]
    steps = _wire(monkeypatch)
    reg = P.build_analyst_registry(face)
    _with(reg, monkeypatch, verb, payload)
    out = await R.invoke(reg, _Db(), "sess", verb, {**args, "why": WHY})
    assert set(out) <= {"pull", "head", "rows", "catalogue", "made", "kept", "task_id", "run_id", "next_offset", "as_of", "book",
                        "held_back"}, "a header, rows, and ids to read on with — no note, no legend"
    assert out["head"].startswith(f"{out['pull']} {verb}(") and "why" not in out["head"]
    if verb == "start":
        assert out["rows"] == [] and out["task_id"] == "task_000000000001" and "returns nothing" in out["head"]
        assert not [rec for s in steps for rec in L.facts_in(s.get("evidence_refs") or [])]          # an id is not evidence
    elif verb == "list":
        assert out["rows"] == [] and out["catalogue"] == payload["catalogue"] and out["head"].endswith(says)
    else:
        assert any(says in row for row in out["rows"]), out["rows"]
        assert all(row.startswith("[f_") and out["pull"] in row for row in out["rows"])


# what each verb's service refuses, the way it says it, and the way out a row must carry
REFUSES = {
    "list": ("issuer", dict(what="filings", subject="ZZZZ"),
             {"error": "not_indexed", "detail": "ZZZZ has no filings indexed on this desk", "hint": "start(kind='readiness') prepares it"},
             "start(kind='readiness') prepares it"),
    "filings_read": ("issuer", dict(ticker="KO", line="revenue"),
                     {"error": "metric_not_filed", "detail": "KO has no filed facts under 'revenue'", "nearest": ["total_revenues"],
                      "available": ["accounts_receivable", "total_revenues"]}, "nearest: total_revenues"),
    "prices_read": ("market", dict(ticker="ZZZZ", field="close"),
                    {"error": "no_price_data", "detail": "ZZZZ has no price history on this desk",
                     "data_covers": {"from": "2021-01-04", "to": "2026-09-10"}}, "data covers: from: 2021-01-04"),
    "book_read": ("risk", dict(book="port_001", table="limit_checks", column="room"),
                  {"error": "unknown_name", "detail": "limit_checks has no column 'room' on run_1",
                   "columns_of_table": ["breach_level", "current_value", "warning_level"]}, "columns of table: breach_level"),
    "metric": ("issuer", dict(name="net_debt_to_ebitda", subject="JPM"),
               {"error": "not_for_financials", "detail": "refused for a financial issuer", "known": ["roe", "roa"]}, "known: roe, roa"),
    "calc": ("risk", dict(op="add", inputs=["f_aaaa11112222", "f_bbbb33334444"]),
             {"error": "incompatible_units", "detail": "a weight and a market value do not add", "allowed": ["multiply", "divide"]},
             "allowed: multiply, divide"),
    "filings_search": ("issuer", dict(ticker="COST", query="supply constraints"),
                       {"error": "not_indexed", "detail": "COST has no filings indexed", "hint": "start(kind='readiness') indexes them"},
                       "start(kind='readiness') indexes them"),
    "filings_section": ("issuer", dict(ticker="MSFT", item="9Z"),
                        {"error": "section_not_found", "detail": "MSFT has no Item 9Z", "items_indexed": ["Item 1A", "Item 7"]},
                        "items indexed: Item 1A, Item 7"),
    "web_search": ("issuer", dict(ticker="TLT", query="rate path"),
                   {"error": "not_an_sec_filer", "detail": "TLT is listed but files with no SEC CIK", "hint": "its price history is on the market analyst's face"},
                   "its price history is on the market analyst's face"),
    "scenario": ("risk", dict(book="port_001", trades=[{"sell": "COST"}]),
                 {"error": "not_held", "detail": "COST is not a position of this book", "available": ["AAPL", "MSFT"]}, "available: AAPL, MSFT"),
    "start": ("risk", dict(kind="exposure_run", subject="port_001"),
              {"error": "active_run_exists", "detail": "a run of port_001 is already in flight", "hint": "its id is run_2; it returns after this turn"},
              "its id is run_2"),
}


@pytest.mark.parametrize("verb", sorted(REFUSES))
async def test_a_verbs_refusal_is_an_absence_row_with_its_way_out(monkeypatch, verb):
    face, args, payload, way_out = REFUSES[verb]
    steps = _wire(monkeypatch)
    reg = P.build_analyst_registry(face)
    _with(reg, monkeypatch, verb, payload)
    out = await R.invoke(reg, _Db(), "sess", verb, {**args, "why": WHY})
    (row,) = out["rows"]
    assert "absent:" in row and payload["detail"] in row and way_out in row, row
    (rec,) = [rec for s in steps for rec in L.facts_in(s.get("evidence_refs") or [])]
    assert rec["kind"] == F.ABSENCE and rec["means"]["reason"] in desk.ABSENCE_REASONS and rec["means"]["way_out"]
    assert steps[-1]["result_summary"].endswith(f"| refused: {payload['error']}")                     # the trace says it was one


@pytest.mark.parametrize("verb", sorted(GIVES))
async def test_a_verb_is_its_own_families_and_is_not_there_for_another(monkeypatch, verb):
    _wire(monkeypatch)
    owners = [f for f in P.FACES if verb in P.FACE_TOOLS[f]]
    for face in P.FACES:
        reg = P.build_analyst_registry(face)
        assert (verb in reg.tools) == (face in owners)
        if face not in owners:
            out = await R.invoke(reg, _Db(), "sess", verb, {**GIVES[verb][1], "why": WHY})
            assert out == {"error": "unknown_tool", "tool": verb}                                     # not refused: it does not exist here
    # the verbs every analyst has are told apart by what their enums hold, not by a sentence
    if verb == "metric":
        names = {f: set(P.build_analyst_registry(f).get("metric").json_schema["properties"]["name"]["enum"]) for f in P.FACES}
        assert "net_debt_to_ebitda" in names["issuer"] and "net_debt_to_ebitda" not in names["market"] | names["risk"]
        assert "book.analysis" in names["risk"] and "book.analysis" not in names["issuer"] | names["market"]
