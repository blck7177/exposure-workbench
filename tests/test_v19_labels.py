"""V19 — the label beside a figure is the table's, never the model's (offline).

Three findings from the 9/2 battery, one cause: the gate proves a figure has a
source and cannot see the words written next to it. `Peak-to-trough decline |
$205.10` was the trough (`NVDA.adj_close@2026-06-05`) under a row label the
model wrote; "market cap at $919.77" was `LLY.close`. Tables and trends are the
two block kinds whose labels are structural, so there the label is now DERIVED
from the slot's name and the model has no cell to write one in. Paragraph
prose keeps its words; that is the critic's job, outside the gate.

Also here: the web on the meta face, and the two evidence dead ends.
"""

from __future__ import annotations

import inspect

import pytest

from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services import evidence_resolver_service as ev
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import resolver
from exposure_workbench.services import table as tb
from exposure_workbench.tools import definitions, faces
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.meta_tools import RESPOND_SCHEMA
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


def _fields(blocks) -> list[str]:
    return [p["field"] for p in validate_args(RESPOND_SCHEMA, {"blocks": blocks})]


S = {"ref": "calc_1", "name": "NVDA.adj_close@2026-06-05"}


# ── S1: the grammar has no cell for words ─────────────────────────────────────

def test_a_string_cell_is_refused_by_the_schema_at_the_cell():
    assert _fields([{"type": "metric_table", "rows": [["Peak-to-trough decline", S]]}]) == ["blocks.0.rows.0.0"]


def test_columns_are_refused_by_the_schema_at_the_key():
    assert _fields([{"type": "metric_table", "columns": ["Measure", "Value"], "rows": [[S]]}]) == ["blocks.0.columns"]


def test_validate_shape_names_the_cell_and_carries_the_rule():
    problems = ab.validate_shape([{"type": "metric_table", "columns": ["a"], "rows": [["x", S]]}])
    reasons = {(p["at"], p["reason"]) for p in problems}
    assert ("blocks[0].columns", "table_names_its_own_columns") in reasons
    assert ("blocks[0].rows[0][0]", "cell_not_a_slot") in reasons
    assert all(p["detail"] == ab.TABLE_RULE for p in problems)


def test_the_schema_description_and_the_refusal_say_the_same_rule():
    """One sentence, read twice — the schema before the gate, the refusal after."""
    branch = next(b for b in RESPOND_SCHEMA["properties"]["blocks"]["items"]["oneOf"]
                  if b["properties"]["type"]["enum"] == ["metric_table"])
    assert branch["properties"]["rows"]["description"] == ab.TABLE_RULE
    assert "columns" not in branch["properties"]


# ── S1: what is derived, on the three shapes the battery produced ─────────────

def test_a_ranking_table_factors_into_entity_rows_and_measure_columns():
    d = ab.derive_table([
        ["net_income.rank.GOOGL", "net_income.GOOGL"],
        ["net_income.rank.NVDA", "net_income.NVDA"],
        ["net_income.rank.AAPL", "net_income.AAPL"],
    ])
    assert d["header"] == ["net income rank", "net income"]
    assert d["labels"] == ["GOOGL", "NVDA", "AAPL"]
    assert d["explicit"] == [False, False]


def test_a_run_child_table_factors_the_ticker_out_of_the_middle():
    d = ab.derive_table([
        ["issuer_exposures.GOOGL.weight", "issuer_exposures.GOOGL.contribution"],
        ["issuer_exposures.MSFT.weight", "issuer_exposures.MSFT.contribution"],
    ])
    assert d["header"] == ["issuer exposures weight", "issuer exposures contribution"]
    assert d["labels"] == ["GOOGL", "MSFT"]


def test_the_drawdown_table_cannot_be_mislabelled_and_a_duplicate_shows_as_one():
    """The battery's shape: two dated points, the same point again under a
    different word, and a count. The names do not align, so every row says
    its whole name — and the third row now reads as what it is."""
    d = ab.derive_table([
        ["NVDA.adj_close@2026-05-14"],
        ["NVDA.adj_close@2026-06-05"],
        ["NVDA.adj_close@2026-06-05"],
        ["quality_flags.n"],
    ])
    assert d["explicit"] == [True]
    assert d["header"] == [""]
    assert d["labels"] == ["NVDA adj close 2026-05-14", "NVDA adj close 2026-06-05",
                           "NVDA adj close 2026-06-05", "quality flags n"]


def test_a_single_row_table_says_every_name_in_full():
    d = ab.derive_table([["total_debt", "cash_and_equivalents", "net_debt"]])
    assert d["labels"] == ["total debt"]
    assert d["explicit"] == [True, True, True]


def test_rendered_attaches_the_derivation_and_prose_reads_the_labels():
    blocks = [{"type": "metric_table", "rows": [
        [{"ref": "calc_r", "name": "net_income.rank.GOOGL"}, {"ref": "calc_r", "name": "net_income.GOOGL"}],
        [{"ref": "calc_r", "name": "net_income.rank.NVDA"}, {"ref": "calc_r", "name": "net_income.NVDA"}],
    ]}]
    resolved = [
        ab.Resolved("calc_r", "net_income.rank.GOOGL", 1, "COUNT"),
        ab.Resolved("calc_r", "net_income.GOOGL", 244e9, "MONEY"),
        ab.Resolved("calc_r", "net_income.rank.NVDA", 2, "COUNT"),
        ab.Resolved("calc_r", "net_income.NVDA", 193e9, "MONEY"),
    ]
    filled = ab.rendered(blocks, resolved)
    assert filled[0]["header"] == ["net income rank", "net income"]
    assert filled[0]["labels"] == ["GOOGL", "NVDA"]
    assert ab.prose_of(filled) == (" | net income rank | net income\n"
                                   "GOOGL | 1 | $244B\n"
                                   "NVDA | 2 | $193B")


def test_the_model_cannot_supply_the_derived_keys_itself():
    """`header`, `labels`, `explicit` are the renderer's; a block carrying them
    is refused like any unknown key, so the derivation is the only writer."""
    for key in ("header", "labels", "explicit"):
        assert _fields([{"type": "metric_table", "rows": [[S]], key: ["x"]}]) == [f"blocks.0.{key}"]


# ── S1: a trend's series states its own direction ─────────────────────────────

def _table_with_series() -> tb.Table:
    t = tb.Table()
    t.refs.add("calc_s")
    t.rows["calc_s"] = "series"
    t.quantities["calc_s"] = {
        f"operating_cash_flow@{p}": qn.Quantity(v, "MONEY", f"operating_cash_flow@{p}", "calc_s")
        for p, v in (("2023-12-31", 4.24e9), ("2022-12-31", 7.59e9), ("2025-12-31", 16.81e9), ("2024-12-31", 8.82e9))
    }
    t.quantities["calc_s"]["quality_flags.n"] = qn.Quantity(4, "COUNT", "quality_flags.n", "calc_s")
    return t


def test_the_resolver_hands_the_series_points_to_the_renderer():
    v = resolver.resolve_against([{"type": "trend", "text": "cash generation climbed", "series_ref": "calc_s"}],
                                 _table_with_series())
    assert v.ok
    s = v.series["calc_s"]
    assert s["label"] == "operating_cash_flow" and s["unit_class"] == "MONEY"
    assert sorted(s["points"])[0] == ("2022-12-31", 7.59e9)


def test_a_trend_is_rendered_with_first_last_and_a_computed_direction():
    v = resolver.resolve_against([{"type": "trend", "text": "cash generation climbed", "series_ref": "calc_s"}],
                                 _table_with_series())
    out = resolver.accepted([{"type": "trend", "text": "cash generation climbed", "series_ref": "calc_s"}], v)
    s = out["blocks"][0]["series"]
    assert s["from"] == {"period": "2022-12-31", "value": 7.59e9}
    assert s["to"] == {"period": "2025-12-31", "value": 16.81e9}
    assert s["direction"] == "up" and s["n"] == 4
    assert out["text"].startswith("operating cash flow: $7.59B (2022-12-31) → $16.81B (2025-12-31), up\n")


def test_the_direction_is_the_series_word_not_the_models():
    """A sentence saying "climbed" over a falling series renders both — the
    disagreement is visible, and nothing here judges the sentence (9/1: the
    gate is closed; a critic outside it reads prose)."""
    t = _table_with_series()
    t.quantities["calc_s"]["operating_cash_flow@2025-12-31"] = qn.Quantity(1.0, "MONEY", "operating_cash_flow@2025-12-31", "calc_s")
    blocks = [{"type": "trend", "text": "cash generation climbed", "series_ref": "calc_s"}]
    v = resolver.resolve_against(blocks, t)
    assert v.ok, "the sentence is not judged"
    assert resolver.accepted(blocks, v)["blocks"][0]["series"]["direction"] == "down"


# ── S2: the web is on the meta face ───────────────────────────────────────────

def test_search_external_research_is_on_both_faces_from_one_registration():
    from exposure_workbench.tools import research_tools
    meta, research = build_meta_registry(), build_research_registry()
    assert "search_external_research" in faces.resolve(meta, faces.FACE_META_AGENT)
    assert "search_external_research" in faces.resolve(research, faces.FACE_RESEARCH)
    assert meta.get("search_external_research").budget_key == "external_search"
    assert meta.get("search_external_research").evidence is not None
    src = inspect.getsource(research_tools)
    assert src.count('name="search_external_research"') == 1


def test_the_capability_statement_says_the_web_is_here():
    caps = definitions._FACE_CAPABILITIES
    assert any("search_external_research" in c for c in caps["can"])
    assert not any("web" in c for c in caps["cannot"])


def test_the_search_tool_admits_a_listed_issuer_rather_than_refusing_it():
    from exposure_workbench.tools import research_tools
    src = inspect.getsource(research_tools._search_external_research)
    assert "company_service.admit" in src
    assert "company_not_found" in src and "not_investigable" in src


# ── S3: the chain reaches the filing and the holdings ─────────────────────────

def test_a_fact_card_carries_the_filing_url_and_a_run_card_its_holdings():
    fact = inspect.getsource(ev._fact)
    assert '"source_url": source_url' in fact
    assert "Filing.accession_number == row.source_accession" in fact, "a fact with no filing_id still reaches its filing"
    assert "_edgar_index(cik, accession)" in fact, "a fact whose filing was never ingested still points at EDGAR"
    assert ev._edgar_index("0000789019", "0001564590-21-020891") == \
        "https://www.sec.gov/Archives/edgar/data/789019/000156459021020891/"
    run = inspect.getsource(ev._run)
    assert "positions_for_run" in run and '"type": "position"' in run


def test_the_run_and_its_card_resolve_holdings_through_one_function():
    from exposure_workbench.workflow import exposure_workflow as wf
    src = inspect.getsource(wf.ExposureWorkflow._positions_for)
    assert "positions_for_run" in src
    assert "get_positions_latest" not in src, "the two-step lives in portfolio_service only"


# ── S2: the engine is told the issuer, and the window is a parameter ──────────

def test_the_search_query_carries_the_issuer_the_model_named():
    """First live turn: "latest news from the past week" reached Tavily with no
    issuer in it and came back as five front pages. The ticker is an argument
    of the tool; binding it into the query is the tool's job."""
    from exposure_workbench.services import research_search_service as rss
    assert rss.compose_query("NVIDIA Corp", "NVDA", "latest news from the past week") == \
        "NVIDIA Corp (NVDA): latest news from the past week"
    assert rss.compose_query(None, "NVDA", " earnings ") == "NVDA: earnings"
    assert rss.compose_query("NVDA", "NVDA", "x") == "NVDA: x"


def test_a_day_window_is_a_request_parameter_not_a_phrase():
    from exposure_workbench.tools import research_tools
    schema = build_meta_registry().get("search_external_research").json_schema
    assert schema["properties"]["days"]["type"] == ["integer", "null"]
    assert "days" not in schema["required"]
    src = inspect.getsource(research_tools._search_external_research)
    assert "compose_query(company.name, tk, query)" in src and "days=days" in src


# ── a filed metric asked for as a formula is pointed at its tool ─────────────

async def test_evaluate_formula_names_the_tool_that_holds_a_filed_metric():
    from exposure_workbench.services import formula_service as fsvc
    out = await fsvc.evaluate_formula(None, "NVDA", "net_income", invoked_by="test")
    assert out["error"] == "unknown_formula"
    assert "get_flow(metric='net_income'" in out["detail"]
    out = await fsvc.evaluate_formula(None, "NVDA", "not_a_thing", invoked_by="test")
    assert out["error"] == "unknown_formula" and "detail" not in out


# ── the subject of a row reaches the label when the name does not carry it ───

def test_per_issuer_rows_with_identical_names_are_labelled_by_their_subject():
    """Eight get_flow reads are eight refs all named `net_income@2025-12-31`;
    the issuer sits on the ledger row, so the table carries it as the ref's
    subject and the derivation prefixes it."""
    blocks = [{"type": "metric_table", "rows": [
        [{"ref": "calc_g", "name": "net_income@2025-12-31"}],
        [{"ref": "calc_n", "name": "net_income@2025-12-31"}],
    ]}]
    resolved = [ab.Resolved("calc_g", "net_income@2025-12-31", 244e9, "MONEY"),
                ab.Resolved("calc_n", "net_income@2025-12-31", 193e9, "MONEY")]
    filled = ab.rendered(blocks, resolved, None, {"calc_g": "GOOGL", "calc_n": "NVDA"})
    assert filled[0]["header"] == ["net income 2025-12-31"]
    assert filled[0]["labels"] == ["GOOGL", "NVDA"]
    # A name that already carries the subject is not prefixed twice.
    assert ab._derivation_name("issuer_exposures.MSFT.weight", "MSFT") == "issuer_exposures.MSFT.weight"


def test_the_subject_travels_from_the_row_to_the_verdict_and_not_into_the_gate():
    t = tb.Table()
    for ref, who in (("calc_g", "GOOGL"), ("calc_n", "NVDA")):
        t.refs.add(ref); t.rows[ref] = "series"; t.subjects[ref] = who
        t.quantities[ref] = {"net_income@2025-12-31": qn.Quantity(1.0, "MONEY", "net_income@2025-12-31", ref)}
    blocks = [{"type": "metric_table", "rows": [[{"ref": "calc_g", "name": "net_income@2025-12-31"}],
                                                [{"ref": "calc_n", "name": "net_income@2025-12-31"}]]}]
    v = resolver.resolve_against(blocks, t)
    assert v.ok and v.subjects == {"calc_g": "GOOGL", "calc_n": "NVDA"}
    assert resolver.accepted(blocks, v)["blocks"][0]["labels"] == ["GOOGL", "NVDA"]
    src = inspect.getsource(resolver.resolve_against)
    assert src.count("v.subjects[") == 1 and "subjects" not in inspect.getsource(resolver._series_of), \
        "read once into the verdict; no check consults it"


def test_a_calc_rows_subject_is_the_ledgers_company_column():
    """`flow.series` rows record no ticker in params (473 of 473 live rows); the
    column does. A get_flow slot therefore reaches the table with its issuer."""
    src = inspect.getsource(qn._from_calc)
    assert 'getattr(row, "company_id", None)' in src and "subject=" in src


def test_an_unfactored_cell_carries_its_subject_in_the_caption():
    """Three issuers laid out as three columns of one row: nothing factors, and
    the transcript said `net income: $123B` for AAPL's cell with no AAPL in it.
    The caption is the derivation name, subject included."""
    blocks = [{"type": "metric_table", "rows": [[{"ref": "calc_m", "name": "net_income"},
                                                {"ref": "calc_a", "name": "net_income"}]]}]
    resolved = [ab.Resolved("calc_m", "net_income", 125e9, "MONEY"), ab.Resolved("calc_a", "net_income", 123e9, "MONEY")]
    filled = ab.rendered(blocks, resolved, None, {"calc_m": "MSFT", "calc_a": "AAPL"})
    assert [c["slot"]["caption"] for c in filled[0]["rows"][0]] == ["MSFT net income", "AAPL net income"]
    assert ab.prose_of(filled) == "MSFT net income | $125B | AAPL net income: $123B"
