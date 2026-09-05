"""V24 phase C/§4: the answer grammar (services/answer.py).

A paragraph is a SENTENCE and a fact's id written in it is the pointer; the
array-of-strings-and-objects shape it replaces was legal and the model wrote
it wrong 28 times in 94 stored answers, always the same way. `cites` stays a
field: a fact a paragraph rests on is not a fact it states. `f_…@period`
addresses one point of a series. The rendered OUTPUT is unchanged — runs of
strings, {fact: …} and {link: …} — so the page reads new and old alike.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import answer as A
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L
from exposure_workbench.tools.arg_validation import validate_args

WEIGHT, MV, NV_W, NV_MV = "f_aaaa11112222", "f_bbbb11112222", "f_cccc11112222", "f_dddd11112222"
SERIES, PASSAGE = "f_ssss11112222", "f_pppp11112222"


def _fields(blocks) -> list[str]:
    return sorted(p["field"] for p in validate_args(A.ANSWER_SCHEMA, {"blocks": blocks}))


# ── the schema ────────────────────────────────────────────────────────────────

def test_the_grammar_has_three_block_types_and_each_is_accepted():
    ok = [{"type": "paragraph", "text": f"MSFT weighs {WEIGHT} of the book.", "cites": [PASSAGE]},
          {"type": "table", "title": "Weights", "rows": [[WEIGHT, MV], [NV_W, NV_MV]]},
          {"type": "chart", "kind": "line", "fact": SERIES}]
    assert _fields(ok) == []
    assert A.BLOCK_TYPES == ("paragraph", "table", "chart")


def test_the_shapes_the_grammar_no_longer_has():
    # the old runs array, a slot, a value beside a ref, the old block types
    assert _fields([{"type": "paragraph", "runs": ["x", {"fact": WEIGHT}]}])
    assert _fields([{"type": "paragraph", "text": "x", "runs": ["y"]}]) == ["blocks.0.runs"]
    for t in ("metric_table", "trend", "absence", "action"):
        assert A.validate_shape([{"type": t}])[0]["reason"] == "unknown_block_type"
    assert A.validate_shape([{"type": "paragraph", "text": "  "}])[0]["reason"] == "paragraph_without_text"


def test_the_model_cannot_supply_the_derived_keys():
    for key in ("header", "labels", "explicit", "columns"):
        assert _fields([{"type": "table", "rows": [[WEIGHT]], key: ["x"]}]) == [f"blocks.0.{key}"]


def test_validate_shape_reports_every_problem_not_the_first():
    problems = A.validate_shape([{"type": "paragraph", "text": ""},
                                 {"type": "table", "rows": [[WEIGHT], [MV, NV_W]]},
                                 {"type": "chart", "kind": "pie", "fact": ""}])
    reasons = {p["reason"] for p in problems}
    assert {"paragraph_without_text", "row_width_mismatch", "unknown_chart_kind", "chart_without_fact"} <= reasons


# ── pointers ──────────────────────────────────────────────────────────────────

def test_the_old_object_decoration_is_normalised_to_the_pointer_it_carries():
    for shape in ("{fact:%s}", '{"fact": "%s"}', "{fact: '%s'}", '{ "fact" : %s }'):
        assert A.normalise("a " + shape % WEIGHT + " b") == f"a {WEIGHT} b"
    assert A.normalise(f"plain {WEIGHT} stays") == f"plain {WEIGHT} stays"


def test_split_point_and_pointers_in():
    assert A.split_point(WEIGHT) == (WEIGHT, None)
    assert A.split_point(f"{SERIES}@2025-12-31") == (SERIES, "2025-12-31")
    text = f"from {SERIES}@2024-12-31 to {SERIES}@2025-12-31, and {WEIGHT}."
    assert [t for t, _s, _e in A.pointers_in(text)] == [f"{SERIES}@2024-12-31", f"{SERIES}@2025-12-31", WEIGHT]


def test_refs_in_gathers_pointers_and_cites_with_their_roles():
    blocks = [{"type": "paragraph", "text": f"a {WEIGHT} b {SERIES}@2025-12-31", "cites": [PASSAGE]},
              {"type": "table", "rows": [[MV, NV_W]]},
              {"type": "chart", "kind": "bar", "fact": SERIES}]
    assert [(t, role) for _at, t, role in A.refs_in(blocks)] == [
        (WEIGHT, A.INLINE), (f"{SERIES}@2025-12-31", A.INLINE), (PASSAGE, A.CITE),
        (MV, A.CELL), (NV_W, A.CELL), (SERIES, A.CHART)]
    assert A.ids_in(blocks) == [WEIGHT, SERIES, PASSAGE, MV, NV_W]


def test_prose_by_block_blanks_the_pointers_and_keeps_the_length():
    blocks = [{"type": "paragraph", "text": f"VaR ({WEIGHT}) at 95%", "cites": [PASSAGE]},
              {"type": "table", "title": "Two names", "rows": [[MV]]}]
    (i0, p0, c0), (i1, p1, c1) = A.prose_by_block(blocks)
    assert i0 == 0 and c0 == [PASSAGE] and len(p0) == len(blocks[0]["text"])
    assert WEIGHT not in p0 and p0.startswith("VaR (") and p0.endswith(") at 95%")
    assert i1 == 1 and p1 == "Two names" and c1 == []


# ── the token finder ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("as of 2026-03-31 revenue rose", [("2026-03-31", "date")]),
    ("in the 10-K and the 10-Q/A", [("10-K", "form"), ("10-Q/A", "form")]),
    ("weighs 16.3% of the book at $1,785,420", [("16.3%", "num"), ("$1,785,420", "num")]),
    ("net debt of $38.1bn and 2.4739 billion", [("$38.1bn", "num"), ("2.4739 billion", "num")]),
    ("accounted for 82 percent of revenue", [("82%", "num")]),
    ("95% 1日 VaR 为", [("95%", "num"), ("1", "num")]),
    ("the H200 ramp", []),
    # a clause mark is not part of the figure: "2024," could resolve against no
    # lookup, and four of the seven unsourced_figure refusals in the whole
    # stored corpus were exactly this (measured 2026-09-05)
    ("in 2024, revenue rose", [("2024", "num")]),
    ("of $1,785,420, which is", [("$1,785,420", "num")]),
    ("16.3%, and then", [("16.3%", "num")]),
])
def test_tokens_in_finds_whole_tokens_and_stops_at_the_clause(text, expected):
    assert [(t["token"], t["kind"]) for t in A.tokens_in(text)] == expected


# ── rendering ─────────────────────────────────────────────────────────────────

def _facts():
    def f(fid, **kw):
        return F.Fact(id=fid, **kw)
    a = f(WEIGHT, kind=F.SCALAR, measure="issuer_exposures.weight", subject="MSFT", unit="RATIO",
          value=0.16251671, as_of="2026-09-03", sources=("run_x",))
    b = f(MV, kind=F.SCALAR, measure="issuer_exposures.market_value", subject="MSFT", unit="MONEY",
          value=1785420.0, as_of="2026-09-03", sources=("run_x",))
    c = f(NV_W, kind=F.SCALAR, measure="issuer_exposures.weight", subject="NVDA", unit="RATIO",
          value=0.1493, as_of="2026-09-03", sources=("run_x",))
    d = f(NV_MV, kind=F.SCALAR, measure="issuer_exposures.market_value", subject="NVDA", unit="MONEY",
          value=1640000.0, as_of="2026-09-03", sources=("run_x",))
    s = f(SERIES, kind=F.SERIES, measure="operating_cash_flow", subject="MSFT", unit="MONEY",
          points=(("2022-12-31", 7.59e9), ("2023-12-31", 9.1e9), ("2025-12-31", 16.81e9)),
          window={"start": "2022-12-31", "end": "2025-12-31"}, as_of="2025-12-31", sources=("calc_s",))
    p = f(PASSAGE, kind=F.PASSAGE, measure="10-K Item 7", subject="LLY", as_of="2026-02-20",
          text="Six products accounted for 82 percent of total revenues in 2025.", sources=("chunk_1",))
    return a, b, c, d, s, p


def test_rendered_fills_each_pointer_and_a_table_derives_its_labels():
    a, b, c, d, s, p = _facts()
    led = L.Ledger.of_facts([a, b, c, d, s, p])
    blocks = [{"type": "paragraph", "text": f"MSFT weighs {a.id} of the book."},
              {"type": "table", "rows": [[a.id, b.id], [c.id, d.id]]},
              {"type": "paragraph", "text": f"Cash generation climbed: {s.id}."}]
    out = A.rendered(blocks, led.by_id)
    assert "text" not in out[0], "the rendered form is runs, as the page has always read"
    assert out[0]["runs"][0] == "MSFT weighs " and out[0]["runs"][2] == " of the book."
    assert out[0]["runs"][1]["fact"]["display"] == "16.3%" and out[0]["runs"][1]["fact"]["as_of"] == "2026-09-03"
    assert out[1]["header"] == ["issuer exposures weight", "issuer exposures market value"]
    assert out[1]["labels"] == ["MSFT", "NVDA"] and out[1]["explicit"] == [False, False]
    series = out[2]["runs"][1]["fact"]["series"]
    assert series["from"]["period"] == "2022-12-31" and series["direction"] == "up"
    text = A.prose_of(out)
    assert "MSFT weighs 16.3% of the book." in text
    assert " | issuer exposures weight | issuer exposures market value\nMSFT | 16.3% | $1.79M\nNVDA | 14.9% | $1.64M" in text


def test_a_point_of_a_series_renders_as_that_points_value_on_its_own_date():
    *_, s, _p = _facts()
    led = L.Ledger.of_facts([s])
    out = A.rendered([{"type": "paragraph", "text": f"It ran {s.id}@2022-12-31 to {s.id}@2025-12-31."}], led.by_id)
    first, last = out[0]["runs"][1]["fact"], out[0]["runs"][3]["fact"]
    assert (first["value"], first["as_of"], first["display"]) == (7.59e9, "2022-12-31", "$7.59B")
    assert (last["value"], last["as_of"], last["display"]) == (16.81e9, "2025-12-31", "$16.81B")
    assert first["id"] == s.id == last["id"], "the chip opens the series it addresses"
    assert A.prose_of(out) == "It ran $7.59B to $16.81B."


def test_a_passage_pointed_at_inline_reads_as_a_mark_not_its_text():
    *_, p = _facts()
    led = L.Ledger.of_facts([p])
    out = A.rendered([{"type": "paragraph", "text": f"Lilly says so: {p.id}."}], led.by_id)
    assert A.prose_of(out) == "Lilly says so: [10-K Item 7]."


def test_resolved_prose_tokens_become_links_beside_the_pointers():
    a, b, *_ = _facts()
    led = L.Ledger.of_facts([a, b])
    text = f"MSFT is 16.3% of the book, worth {b.id} as of 2026-09-03."
    links = {(0, text.index("16.3%")): {"to": "fact", "ids": [a.id], "as_written": "16.3%"},
             (0, text.index("2026-09-03")): {"to": "fact", "ids": [a.id, b.id], "as_written": "2026-09-03"}}
    runs = A.rendered([{"type": "paragraph", "text": text}], led.by_id, links)[0]["runs"]
    assert runs[0] == "MSFT is " and runs[1]["link"]["as_written"] == "16.3%"
    assert runs[3]["fact"]["id"] == b.id and runs[5]["link"]["ids"] == [a.id, b.id]
    assert A.prose_of([{"type": "paragraph", "runs": runs}]) == f"MSFT is 16.3% of the book, worth $1.79M as of 2026-09-03."
