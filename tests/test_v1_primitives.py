"""V1 step 3 (docs/IMPLEMENTATION_PLAN_V1.md §2.3): twelve primitive verbs over
three resource families, every result as rows.

Offline: the trace and the budget are stubbed and the services behind a verb are
replaced by their payloads, as tests/test_tool_registry.py does; the wrapper, the
adapters, the registry vocabulary and the row renderer are real.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import registry as desk
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L
from exposure_workbench.tools import faces
from exposure_workbench.tools import primitives as P
from exposure_workbench.tools import registry as R
from exposure_workbench.tools.arg_validation import validate_args


# ── the wiring every test here needs ─────────────────────────────────────────

class _Db:
    def __init__(self):
        self.added = []

    async def rollback(self):
        pass

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass


def _wire(monkeypatch):
    log = {"steps": []}

    async def _record(db, session_id, **kw):
        log["steps"].append(kw)
        return f"step_{len(log['steps'])}"

    async def _reserve(db, session_id, is_external_search=False, message_id=None):
        pass

    monkeypatch.setattr(R.trace_service, "record_step", _record)
    monkeypatch.setattr(R.sess, "reserve", _reserve)
    return log


def _recorded(log) -> list[dict]:
    return [rec for step in log["steps"] for rec in L.facts_in(step.get("evidence_refs") or [])]


WHY = "line 2 asks how levered the name is; this is the measure for it"


# ── a face is a resource family, and it is structure ─────────────────────────

@pytest.mark.parametrize("face", P.FACES)
def test_each_analysts_registry_is_its_face_and_nothing_else(face):
    reg = P.build_analyst_registry(face)
    assert list(reg.tools) == faces.ANALYST_FACES[face] == list(P.FACE_TOOLS[face])
    assert faces.resolve(reg, faces.ANALYST_FACES[face]) == faces.ANALYST_FACES[face]
    for tool in reg.tools.values():
        assert tool.rows and tool.display, tool.name
        assert "why" in tool.json_schema["required"], f"{tool.name}: every call says why"
        assert validate_args(tool.json_schema, {}) != []          # nothing is callable with no arguments


def test_the_faces_are_the_sizes_the_plan_states():
    # plus `submit`, the in-process exit every analyst has: 9 / 6 / 7
    assert {f: len(P.FACE_TOOLS[f]) + 1 for f in P.FACES} == {"issuer": 9, "market": 6, "risk": 7}


def test_a_raw_read_belongs_to_one_family_only():
    owners = {verb: [f for f in P.FACES if verb in P.FACE_TOOLS[f]]
              for verb in ("filings_read", "filings_search", "filings_section", "web_search", "prices_read",
                           "book_read", "scenario")}
    assert owners == {"filings_read": ["issuer"], "filings_search": ["issuer"], "filings_section": ["issuer"],
                      "web_search": ["issuer"], "prices_read": ["market"], "book_read": ["risk"], "scenario": ["risk"]}


@pytest.mark.parametrize("face", P.FACES)
def test_a_faces_enums_hold_its_own_names_only(face):
    reg = P.build_analyst_registry(face)
    names = reg.tools["metric"].json_schema["properties"]["name"]["enum"]
    assert names == [m.name for m in desk.metrics_for(face)]
    assert reg.tools["list"].json_schema["properties"]["what"]["enum"] == list(P.LIST_WHAT[face])
    assert reg.tools["start"].json_schema["properties"]["kind"]["enum"] == list(P.START_KINDS[face])


def test_no_verb_takes_a_program_or_free_sql():
    for face in P.FACES:
        for tool in P.build_analyst_registry(face).tools.values():
            props = tool.json_schema["properties"]
            assert not {"program", "sql", "expression", "let"} & set(props), tool.name


# ── every result is rows ─────────────────────────────────────────────────────

COVERAGE = {"method": "ebit_interest_coverage", "subject": "XOM", "formula": "ebit_interest_coverage", "ticker": "XOM",
            "value": 18.4, "calc_id": "calc_cov", "unit_class": "multiple",
            "periods": {"intervals": [["2024-07-01", "2025-06-30"]]},
            "substituted_inputs": {"interest_expense": "interest_expense_nonoperating"}}


async def test_a_measure_comes_back_as_a_header_and_rows_with_no_legend(monkeypatch):
    log = _wire(monkeypatch)

    async def _compute(db, **kw):
        assert kw["method"] == "ebit_interest_coverage" and kw["subject"] == "XOM"
        return dict(COVERAGE)
    monkeypatch.setattr(P.compute_service, "compute", _compute)

    out = await R.invoke(P.build_analyst_registry("issuer"), _Db(), "sess", "metric",
                         {"name": "ebit_interest_coverage", "subject": "XOM", "why": WHY})
    assert set(out) == {"pull", "head", "rows"} and out["pull"].startswith("r_")
    assert out["head"].startswith(f"{out['pull']} metric(name=") and out["head"].endswith("→ 1 row")
    assert WHY not in out["head"]                                       # the log is the trace's, not the result's
    (row,) = out["rows"]
    assert row.endswith(f"18.40× — built on interest expense nonoperating in place of interest expense — "
                        f"{out['pull']} method ebit_interest_coverage")
    assert "EBIT / interest coverage, XOM, 2024-07-01 to 2025-06-30" in row
    (rec,) = _recorded(log)
    assert rec["params"]["pull"] == out["pull"] and F.line(rec) == row   # the ledger holds the row the model read
    assert log["steps"][-1]["args"]["why"] == WHY                        # …and the step holds why it was pulled


async def test_a_refusal_is_a_row_on_the_ledger_with_its_reason(monkeypatch):
    log = _wire(monkeypatch)

    async def _compute(db, **kw):
        return {"error": "not_for_financials", "detail": "net debt / EBITDA is refused for a financial issuer",
                "known": ["roe", "roa"]}
    monkeypatch.setattr(P.compute_service, "compute", _compute)

    out = await R.invoke(P.build_analyst_registry("issuer"), _Db(), "sess", "metric",
                         {"name": "net_debt_to_ebitda", "subject": "JPM", "why": WHY})
    (row,) = out["rows"]
    assert row.startswith("[f_") and "absent: net debt / EBITDA, JPM" in row and "known: roe, roa" in row
    assert row.endswith(f"— {out['pull']} boundary")
    (rec,) = _recorded(log)
    assert rec["kind"] == F.ABSENCE and rec["means"]["reason"] == "meaningless"
    assert rec["params"]["pull"] == out["pull"]


async def test_arguments_that_do_not_fit_are_refused_as_a_row_before_anything_is_spent(monkeypatch):
    log = _wire(monkeypatch)
    out = await R.invoke(P.build_analyst_registry("market"), _Db(), "sess", "prices_read", {"ticker": "AAPL"})
    assert "absent:" in out["rows"][0] and "why" in out["rows"][0]
    statuses = [(s["status"], s["step_type"]) for s in log["steps"]]
    assert statuses == [("rejected", "tool_call"), ("completed", "boundary")]   # the ledger reads completed steps
    (rec,) = _recorded(log)
    assert rec["means"]["reason"] == "param_out_of_range"


async def test_another_familys_measure_is_refused_with_whose_it_is(monkeypatch):
    log = _wire(monkeypatch)
    out = await R.invoke(P.build_analyst_registry("market"), _Db(), "sess", "metric",
                         {"name": "net_debt_to_ebitda", "subject": "XOM", "why": WHY})
    (rec,) = _recorded(log)
    assert rec["means"]["reason"] == "not_on_this_face"
    assert "net_debt_to_ebitda is a measure the issuer analyst may ask for" in rec["means"]["way_out"]
    assert "the issuer analyst" in out["rows"][0]


async def test_a_verb_of_another_family_does_not_exist_here(monkeypatch):
    _wire(monkeypatch)
    out = await R.invoke(P.build_analyst_registry("market"), _Db(), "sess", "filings_read",
                         {"ticker": "XOM", "line": "revenue", "why": WHY})
    assert out == {"error": "unknown_tool", "tool": "filings_read"}


# ── the book, off the table it sits on ───────────────────────────────────────

class _Q:
    def __init__(self, label, value, unit="RATIO", means=None, not_alone=None):
        self.label, self.value, self.unit_class, self.means, self.not_alone = label, value, unit, means, not_alone


class _Resolved:
    def __init__(self, quantities):
        self.quantities = tuple(quantities)


BOOK = [
    _Q("limit_checks.issuer_concentration:LLY.current_value", 0.16, means={"status": "warning"}),
    _Q("limit_checks.issuer_concentration:LLY.warning_level", 0.15, means={"status": "warning"}),
    _Q("limit_checks.issuer_concentration:MSFT.current_value", 0.09, means={"status": "clear"}),
    _Q("issuer_exposures.MSFT.weight", 0.09),
    _Q("factor_attributions.rates.beta", 0.4, unit="MULTIPLE", not_alone="these factors are collinear, so no single one is determined"),
]


def _book(monkeypatch):
    async def _resolve_book(db, book, which):
        return "run_1", "2026-09-10"

    async def _of_ref(db, ref):
        return _Resolved(BOOK)
    monkeypatch.setattr(P, "_resolve_book", _resolve_book)
    monkeypatch.setattr(P.qn, "of_ref", _of_ref)


async def test_a_checks_figures_say_where_the_check_stands(monkeypatch):
    log = _wire(monkeypatch)
    _book(monkeypatch)
    out = await R.invoke(P.build_analyst_registry("risk"), _Db(), "sess", "book_read",
                         {"book": "port_001", "table": "limit_checks", "column": "current_value", "why": WHY})
    assert len(out["rows"]) == 2 and out["book"] == "run_1" and out["as_of"] == "2026-09-10"
    by_subject = {r["subject"]: r for r in _recorded(log)}
    lly = by_subject["issuer_concentration:LLY"]
    assert lly["measure"] == "limit_checks.current_value" and lly["means"] == {"status": "warning"}
    assert "16.0%" in F.line(lly) and "in warning" in F.line(lly)
    assert by_subject["issuer_concentration:MSFT"]["means"] == {"status": "clear"}


async def test_a_coefficient_of_a_collinear_fit_is_withheld_as_a_row(monkeypatch):
    log = _wire(monkeypatch)
    _book(monkeypatch)
    out = await R.invoke(P.build_analyst_registry("risk"), _Db(), "sess", "book_read",
                         {"book": "run_1", "table": "factor_attributions", "why": WHY})
    (rec,) = _recorded(log)
    assert rec["kind"] == F.ABSENCE and "collinear" in rec["text"] and rec["means"]["reason"] == "meaningless"
    assert out["rows"][0].startswith(f"[{rec['id']}] absent:")


async def test_a_row_or_column_the_book_does_not_hold_is_refused_with_what_it_does(monkeypatch):
    log = _wire(monkeypatch)
    _book(monkeypatch)
    await R.invoke(P.build_analyst_registry("risk"), _Db(), "sess", "book_read",
                   {"book": "run_1", "table": "limit_checks", "row": "issuer_concentration:NVDA", "why": WHY})
    (rec,) = _recorded(log)
    assert rec["means"]["reason"] == "no_such_name"
    assert "issuer_concentration:LLY" in rec["means"]["way_out"]


# ── one operation over figures already shown ─────────────────────────────────

class _T:
    def __init__(self, value):
        self.value = value


async def test_a_filters_level_is_written_as_the_desk_shows_a_figure(monkeypatch):
    weights = {"f_a": 0.16, "f_b": 0.09, "f_c": 0.07}

    async def _resolve(db, ref):
        return _T(weights[ref])

    async def _constant(db, value, *, unit_class, invoked_by=None, **kw):
        return {"calc_id": "calc_n", "value": value, "unit_class": unit_class, "op": "constant"}
    monkeypatch.setattr(P.tc, "_resolve", _resolve)
    monkeypatch.setattr(P.tc, "constant", _constant)

    out = await P._calc(None, "filter", list(weights), cmp=">", level="8%", why=WHY)        # 8% is 0.08: nobody converts
    assert out["kept"] == ["f_a", "f_b"] and out["value"] == 2.0
    # how many it was a count OF is in the figure's name: a bare number beside the
    # count is a figure with no unit, and the adapter says so out loud (V1 smoke)
    assert "of the 3 given" in out["quantity"] and "of" not in out
    none = await P._calc(None, "filter", list(weights), cmp=">", level="20%", why=WHY)
    assert none["error"] == "no_entry_satisfies" and "0.07 to 0.16" in none["detail"]
    bad = await P._calc(None, "filter", list(weights), cmp=">", level="a lot", why=WHY)
    assert bad["error"] == "invalid_params"


async def test_top_is_a_ranking_cut_at_n(monkeypatch):
    async def _compute(db, **kw):
        assert kw["op"] == "rank" and kw["direction"] == "highest"
        return {"calc_id": "calc_r", "op": "rank", "ordering": [{"label": x, "value": v, "rank": i + 1}
                                                                 for i, (x, v) in enumerate((("A", 3), ("B", 2), ("C", 1)))]}
    monkeypatch.setattr(P.compute_service, "compute", _compute)
    out = await P._calc(None, "top", ["f_a", "f_b", "f_c"], direction="highest", n=2, why=WHY)
    assert [e["label"] for e in out["ordering"]] == ["A", "B"]


# ── the text, and the two actions ────────────────────────────────────────────

async def test_a_section_is_read_a_page_at_a_time(monkeypatch):
    text = "x" * (F.PASSAGE_CHARS + 500)

    async def _read_filings(db, ticker, query=None, item=None, k=5, form_type=None):
        return {"ticker": "MSFT", "item_code": "Item 7", "title": "MD&A", "text": text, "citation": {"form_type": "10-K"}}
    monkeypatch.setattr(P.D, "_read_filings", _read_filings)
    first = await P._filings_section(None, "MSFT", "7", why=WHY)
    assert len(first["text"]) == F.PASSAGE_CHARS and first["next_offset"] == F.PASSAGE_CHARS
    last = await P._filings_section(None, "MSFT", "7", offset=first["next_offset"], why=WHY)
    assert len(last["text"]) == 500 and "next_offset" not in last
    past = await P._filings_section(None, "MSFT", "7", offset=len(text), why=WHY)
    assert past["error"] == "invalid_params"


async def test_a_scenario_takes_a_book_and_its_trades_and_names_the_book_it_made(monkeypatch):
    """Plan V1 §2.3: scenario(run, trades). It took `sales` OR `buys` until
    2026-09-19 — the engine's two halves, one list a call."""
    async def _resolve_book(db, book, which):
        return "run_1", "2026-09-10"

    async def _trades(db, run_id, trades):
        assert run_id == "run_1" and trades == [{"sell": "LLY"}, {"buy": "TLT", "weight": 0.05}]
        return {"calc_id": "calc_after", "as_of": "2026-09-10"}
    monkeypatch.setattr(P, "_resolve_book", _resolve_book)
    monkeypatch.setattr(P.scenario_service, "hypothetical_trades", _trades)
    made = await P._scenario(None, "port_001", [{"sell": "LLY"}, {"buy": "TLT", "weight": 0.05}], why=WHY)
    assert made["made"] == "calc_after" and made["subject"] == "run_1"
    schema = P.build_analyst_registry("risk").get("scenario").json_schema
    assert set(schema["properties"]) == {"book", "trades", "why"} and "sales" not in schema["properties"]
    assert validate_args(schema, {"book": "port_001", "trades": [{"sell": "LLY", "fraction": 0.5}], "why": WHY}) == []
    assert validate_args(schema, {"book": "port_001", "trades": [{"sell": "LLY", "buy": "TLT"}], "why": WHY})   # one side a trade
    assert validate_args(schema, {"book": "port_001", "trades": [{"buy": "TLT"}], "why": WHY})                  # a purchase needs its weight


def test_a_pull_is_not_an_identity_a_sentence_can_resolve_a_number_against():
    rec = {"id": "f_1", "kind": "scalar", "measure": "roe", "value": 0.2, "params": {"pull": "r_51", "tool": "metric"}}
    assert not {"r_51", "51", "metric"} & L.identity_tokens(rec)
