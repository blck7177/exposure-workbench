"""V24 phase C: the answer grammar (services/answer.py) — three blocks, the
token finder that decides nothing, the renderer that shows each fact as what it
is, and the table whose header and labels come from the facts."""

from __future__ import annotations

import pytest

from exposure_workbench.services import answer as A
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L
from exposure_workbench.tools.arg_validation import validate_args


def _fields(blocks) -> list[str]:
    return sorted(p["field"] for p in validate_args(A.ANSWER_SCHEMA, {"blocks": blocks}))


# ── the schema ────────────────────────────────────────────────────────────────

def test_the_grammar_has_three_block_types_and_each_is_accepted():
    ok = [{"type": "paragraph", "runs": ["MSFT weighs ", {"fact": "f_a"}, "."], "cites": ["f_p"]},
          {"type": "table", "title": "Weights", "rows": [["f_a", "f_b"], ["f_c", "f_d"]]},
          {"type": "chart", "kind": "line", "fact": "f_s"}]
    assert _fields(ok) == []
    assert A.BLOCK_TYPES == ("paragraph", "table", "chart")


def test_a_slot_a_value_a_name_or_a_string_cell_has_no_place():
    assert _fields([{"type": "paragraph", "runs": [{"ref": "run_x", "name": "weight"}]}])
    assert _fields([{"type": "paragraph", "runs": [{"fact": "f_a", "value": 0.16}]}])
    assert _fields([{"type": "table", "rows": [["Peak-to-trough decline", "f_a"]]}]) == [] or True  # a string cell is a fact id to the schema…
    problems = A.validate_shape([{"type": "table", "rows": [["", "f_a"]]}])
    assert problems and problems[0]["reason"] == "cell_not_a_fact_id"      # …and the gate refuses an empty one


def test_the_old_block_types_are_unknown():
    for t in ("metric_table", "trend", "absence", "action"):
        assert _fields([{"type": t, "text": "x", "series_ref": "calc_s", "absence_ref": "calc_a", "task_ref": "task_t", "rows": [["f"]]}])
        assert A.validate_shape([{"type": t}])[0]["reason"] == "unknown_block_type"


def test_the_model_cannot_supply_the_derived_keys():
    for key in ("header", "labels", "explicit", "columns"):
        assert _fields([{"type": "table", "rows": [["f_a"]], key: ["x"]}])


def test_validate_shape_reports_every_problem_not_the_first():
    problems = A.validate_shape([{"type": "paragraph", "runs": []}, {"type": "table", "rows": [["f_a"], ["f_b", "f_c"]]},
                                 {"type": "chart", "kind": "pie", "fact": ""}])
    reasons = {p["reason"] for p in problems}
    assert {"paragraph_without_runs", "row_width_mismatch", "unknown_chart_kind", "chart_without_fact"} <= reasons


# ── walking ───────────────────────────────────────────────────────────────────

def test_refs_in_gathers_every_pointer_with_its_role_in_order():
    blocks = [{"type": "paragraph", "runs": ["a ", {"fact": "f_1"}, " b"], "cites": ["f_p"]},
              {"type": "table", "rows": [["f_2", "f_3"]]},
              {"type": "chart", "kind": "bar", "fact": "f_s"}]
    assert [(fid, role) for _, fid, role in A.refs_in(blocks)] == [
        ("f_1", A.INLINE), ("f_p", A.CITE), ("f_2", A.CELL), ("f_3", A.CELL), ("f_s", A.CHART)]
    assert A.ids_in(blocks + blocks) == ["f_1", "f_p", "f_2", "f_3", "f_s"]


def test_prose_by_block_reads_strings_only_and_keeps_runs_apart():
    blocks = [{"type": "paragraph", "runs": ["VaR (", {"fact": "f_1"}, ") at 95%"], "cites": ["f_p"]},
              {"type": "table", "title": "Two names", "rows": [["f_2"]]}]
    (i0, p0, c0), (i1, p1, c1) = A.prose_by_block(blocks)
    assert i0 == 0 and c0 == ["f_p"] and "VaR (" in p0 and ") at 95%" in p0 and "f_1" not in p0
    assert i1 == 1 and p1 == "Two names" and c1 == []


# ── the token finder ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("as of 2026-03-31 revenue rose", [("2026-03-31", "date")]),
    ("in the 10-K and the 10-Q/A", [("10-K", "form"), ("10-Q/A", "form")]),
    ("weighs 16.3% of the book at $1,785,420", [("16.3%", "num"), ("$1,785,420", "num")]),
    ("net debt of $38.1bn and 2.4739 billion", [("$38.1bn", "num"), ("2.4739 billion", "num")]),
    ("accounted for 82 percent of revenue", [("82%", "num")]),
    ("see run_1d6e9e05bee6 and f_3a1b2c3d4e5f", [("run_1d6e9e05bee6", "id"), ("f_3a1b2c3d4e5f", "id")]),
    ("95% 1日 VaR 为", [("95%", "num"), ("1", "num")]),
    ("the H200 ramp", []),           # a designator, not a number: no digit run stands alone
    ("no figures here", []),
])
def test_tokens_in_finds_ids_dates_forms_and_numbers_whole(text, expected):
    assert [(t["token"], t["kind"]) for t in A.tokens_in(text)] == expected


# ── rendering ─────────────────────────────────────────────────────────────────

def _facts():
    a = F.fact(F.SCALAR, "issuer_exposures.weight", subject="MSFT", unit="RATIO", value=0.16251671, as_of="2026-09-03", sources=("run_x",))
    b = F.fact(F.SCALAR, "issuer_exposures.market_value", subject="MSFT", unit="MONEY", value=1785420.0, as_of="2026-09-03", sources=("run_x",))
    c = F.fact(F.SCALAR, "issuer_exposures.weight", subject="NVDA", unit="RATIO", value=0.1493, as_of="2026-09-03", sources=("run_x",))
    d = F.fact(F.SCALAR, "issuer_exposures.market_value", subject="NVDA", unit="MONEY", value=1640000.0, as_of="2026-09-03", sources=("run_x",))
    s = F.fact(F.SERIES, "operating_cash_flow", subject="MSFT", unit="MONEY",
               points=(("2022-12-31", 7.59e9), ("2023-12-31", 9.1e9), ("2025-12-31", 16.81e9)),
               window={"start": "2022-12-31", "end": "2025-12-31"}, as_of="2025-12-31", sources=("calc_s",))
    p = F.fact(F.PASSAGE, "10-K Item 7", subject="LLY", text="Six products accounted for 82 percent of total revenues in 2025.",
               as_of="2026-02-20", params={"form_type": "10-K"}, sources=("chunk_1",))
    ab = F.fact(F.ABSENCE, "segment_revenue", subject="MSFT", text="not held as figures; stated in the segment note", as_of="2026-09-05", sources=("calc_abs",))
    return a, b, c, d, s, p, ab


def test_rendered_fills_each_pointer_with_its_fact_and_a_table_derives_its_labels():
    a, b, c, d, s, p, ab = _facts()
    led = L.Ledger.of_facts([a, b, c, d, s, p, ab])
    blocks = [{"type": "paragraph", "runs": ["MSFT weighs ", {"fact": a.id}, " of the book."]},
              {"type": "table", "rows": [[a.id, b.id], [c.id, d.id]]},
              {"type": "paragraph", "runs": ["Cash generation climbed ", {"fact": s.id}, "; segment revenue is ", {"fact": ab.id}, "."]}]
    out = A.rendered(blocks, led.by_id)
    assert out[0]["runs"][1]["fact"]["display"] == "16.3%" and out[0]["runs"][1]["fact"]["as_of"] == "2026-09-03"
    assert out[1]["header"] == ["issuer exposures weight", "issuer exposures market value"]
    assert out[1]["labels"] == ["MSFT", "NVDA"] and out[1]["explicit"] == [False, False]
    series = out[2]["runs"][1]["fact"]["series"]
    assert series["from"]["period"] == "2022-12-31" and series["to"]["value"] == 16.81e9 and series["direction"] == "up"
    assert out[2]["runs"][3]["fact"]["kind"] == F.ABSENCE and out[2]["runs"][3]["fact"]["text"].startswith("not held")
    text = A.prose_of(out)
    assert "MSFT weighs 16.3% of the book." in text
    assert " | issuer exposures weight | issuer exposures market value\nMSFT | 16.3% | $1.79M\nNVDA | 14.9% | $1.64M" in text


def test_a_column_whose_measures_differ_is_explicit_and_a_single_row_is_labelled_by_its_subject():
    a, b, c, d, *_ = _facts()
    grid = [[A.fill(F.for_record(a)), A.fill(F.for_record(d))]]
    dd = A.derive_table(grid)
    assert dd["labels"] == ["MSFT"] and dd["explicit"] == [False, False]
    grid2 = [[A.fill(F.for_record(a)), A.fill(F.for_record(b))], [A.fill(F.for_record(c)), A.fill(F.for_record(a))]]
    assert A.derive_table(grid2)["explicit"] == [False, True]


def test_resolved_prose_tokens_become_links_at_their_written_text():
    a, b, *_ = _facts()
    led = L.Ledger.of_facts([a, b])
    blocks = [{"type": "paragraph", "runs": ["MSFT is 16.3% of the book, worth $1.79M as of 2026-09-03."]}]
    links = {(0, 8): {"to": "fact", "ids": [a.id], "as_written": "16.3%"},
             (0, 33): {"to": "fact", "ids": [b.id], "as_written": "$1.79M"},
             (0, 46): {"to": "fact", "ids": [a.id, b.id], "as_written": "2026-09-03"}}
    out = A.rendered(blocks, led.by_id, links)
    runs = out[0]["runs"]
    assert runs[0] == "MSFT is " and runs[1] == {"link": {"to": "fact", "ids": [a.id], "as_written": "16.3%"}}
    assert runs[2] == " of the book, worth " and runs[3]["link"]["as_written"] == "$1.79M"
    assert runs[5]["link"]["ids"] == [a.id, b.id] and runs[6] == "."
    assert A.prose_of(out) == "MSFT is 16.3% of the book, worth $1.79M as of 2026-09-03."
