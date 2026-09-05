"""V24 phase C: the gate (services/gate.py) — three lookups against a ledger.

The ledger here is built from real facts (the phase-0 fixtures through the
adapters) plus a few hand-made ones, offline. Each refusal class has one case;
the §7 classes of prose digits (IMPLEMENTATION_PLAN_V24) each have one case,
including the Chinese "95% 1日 VaR" that the old exemption list missed.
"""

from __future__ import annotations

import pytest

import tests.test_fact_adapters as AD
from exposure_workbench.services import fact_adapters as fa
from exposure_workbench.services import facts as F
from exposure_workbench.services import gate as G
from exposure_workbench.services import ledger as L


def _facts(name):
    tool, args = AD.CASES[name]
    return fa.ADAPTERS[tool](args, AD._load(name))[0]


@pytest.fixture(scope="module")
def world():
    facts = []
    for name in ("read_book_run_sections", "compute_book_analysis", "read_fundamentals_flow", "compute_beta",
                 "read_filings_search", "compute_formula_unavailable", "read_book_rrun", "read_prices_1y"):
        facts += _facts(name)
    var = F.fact(F.SCALAR, "exposure_metrics.var_95_1d", subject="run_b791e7985dcd", unit="RATIO", value=0.0123,
                 as_of="2026-09-03", params={"confidence": 0.95, "window": "1d"}, sources=("run_b791e7985dcd",))
    passage = F.fact(F.PASSAGE, "10-K Item 1", subject="LLY", as_of="2026-02-20", params={"form_type": "10-K"},
                     text="Mounjaro, Zepbound, Verzenio, Trulicity, Taltz, and Jardiance collectively accounted for 82 percent of our total revenues in 2025.",
                     sources=("chunk_lly1",))
    facts += [var, passage]
    led = L.Ledger.of_facts(facts)
    by = {}
    for r in led.by_id.values():
        by.setdefault((r["subject"], r["measure"]), r)
    return led, by, var, passage


def _para(*runs, cites=None):
    b = {"type": "paragraph", "runs": list(runs)}
    if cites:
        b["cites"] = cites
    return b


# ── G1 ────────────────────────────────────────────────────────────────────────

def test_G1_an_id_the_session_was_never_shown_is_refused_by_membership(world):
    led, by, *_ = world
    v = G.check([_para("The weight is ", {"fact": "f_000000000000"}, ".")], led)
    assert v.error == "not_on_ledger" and v.problems[0]["id"] == "f_000000000000"
    v2 = G.check([{"type": "table", "rows": [["run_b791e7985dcd"]]}], led)
    assert v2.error == "not_on_ledger", "a storage id is not a fact id"


# ── G2 ────────────────────────────────────────────────────────────────────────

def test_G2_a_cell_is_a_scalar_a_chart_a_series_a_cite_a_passage(world):
    led, by, var, passage = world
    series = next(r for r in led.by_id.values() if r["kind"] == F.SERIES)
    absence = next(r for r in led.by_id.values() if r["kind"] == F.ABSENCE)
    assert G.check([{"type": "table", "rows": [[series["id"]]]}], led).error == "kind_does_not_fit"
    assert G.check([{"type": "chart", "kind": "line", "fact": var.id}], led).error == "kind_does_not_fit"
    assert G.check([_para("x", cites=[var.id])], led).ok, "a cite may be any fact the block rests on (live round 1)"
    assert G.check([{"type": "chart", "kind": "line", "fact": series["id"]}], led).ok
    assert G.check([_para("Segment revenue is ", {"fact": absence["id"]}, ".")], led).ok, "an absence stands inline"
    assert G.check([_para("The filing says so.", cites=[passage.id])], led).ok


def test_G2_a_figure_the_row_says_is_not_determined_alone_may_not_stand_alone(world):
    led, *_ = world
    leg = next(r for r in led.by_id.values() if not r.get("standalone", True))
    v = G.check([_para("The rates leg is ", {"fact": leg["id"]}, ".")], led)
    assert v.error == "not_standalone" and v.problems[0]["id"] == leg["id"]
    assert G.check([{"type": "table", "rows": [[leg["id"]]]}], led).error == "not_standalone"


# ── G3: what a digit in prose may be ──────────────────────────────────────────

def test_G3_a_pointer_carries_no_digits_and_passes(world):
    led, by, *_ = world
    w = by[("MSFT", "issuer_exposures.weight")]
    v = G.check([_para("MSFT weighs ", {"fact": w["id"]}, " of the book.")], led)
    assert v.ok and v.refs == [w["id"]] and v.links == {}


def test_G3_a_number_equal_to_a_fact_is_linked_not_refused(world):
    led, by, *_ = world
    w = by[("MSFT", "issuer_exposures.weight")]
    written = f"{w['value'] * 100:.1f}%"
    v = G.check([_para(f"MSFT weighs {written} of the book.")], led)
    assert v.ok
    (link,) = v.links.values()
    assert link["to"] == "fact" and w["id"] in link["ids"] and link["as_written"] == written


def test_G3_a_value_shared_by_several_facts_links_to_all_of_them(world):
    led, by, *_ = world
    # the concentration threshold is on every issuer_concentration check row
    thr = next(r for r in led.by_id.values() if r["measure"] == "limit_checks.warning_level" and (r["subject"] or "").startswith("issuer_concentration"))
    written = f"{thr['value'] * 100:.1f}%"
    v = G.check([_para(f"against a {written} warning limit.")], led)
    assert v.ok
    (link,) = v.links.values()
    assert len(link["ids"]) > 1 and thr["id"] in link["ids"]


def test_G3_an_as_of_date_its_year_a_benchmark_and_a_confidence_level_are_identity(world):
    led, by, var, passage = world
    v = G.check([_para("As of 2026-09-03 the book's 1-day 95% VaR is ", {"fact": var.id}, ", and in 2026 the beta to SPY held.")], led)
    assert v.ok, v.problems
    written = {l["as_written"] for l in v.links.values()}
    assert {"2026-09-03", "95%", "2026", "1"} <= written


def test_G3_the_chinese_confidence_level_the_old_exemption_missed(world):
    led, by, var, passage = world
    v = G.check([_para("95% 1日 VaR 为 ", {"fact": var.id}, "。")], led)
    assert v.ok, v.problems


def test_G3_a_figure_a_cited_passage_states_links_to_the_passage(world):
    led, by, var, passage = world
    v = G.check([_para("Lilly says its six biggest products accounted for 82 percent of total revenues in 2025.", cites=[passage.id])], led)
    assert v.ok, v.problems
    assert any(l["to"] == "passage" and l["ids"] == [passage.id] for l in v.links.values())
    uncited = G.check([_para("Six products accounted for 82 percent of total revenues in 2025.")], led)
    assert uncited.error == "unsourced_figure" and uncited.problems[0]["figure"] == "82%"


def test_G3_the_models_own_arithmetic_has_no_source_and_is_refused(world):
    led, *_ = world
    v = G.check([_para("From that peak to that trough the close fell from 225.47 to 205.10, a decline of about 9.03.")], led)
    assert v.error == "unsourced_figure"
    assert {p["figure"] for p in v.problems} == {"225.47", "205.10", "9.03"}
    assert "compute it" in v.detail.lower() or "Compute it" in v.detail


def test_G3_an_id_in_prose_is_a_pointer_in_the_wrong_place(world):
    led, by, *_ = world
    w = by[("MSFT", "issuer_exposures.weight")]
    v = G.check([_para("See run_b791e7985dcd for the weight.")], led)
    assert v.error == "id_in_prose"
    v2 = G.check([_para(f"See {w['id']} for the weight.")], led)
    assert v2.ok and next(iter(v2.links.values()))["ids"] == [w["id"]], "a fact id in prose is linked to its fact"


def test_G3_a_measures_name_written_as_words_is_refused_and_a_plain_word_is_not(world):
    led, by, *_ = world
    v = G.check([_para("issuer_exposures.weight is high.")], led)
    assert v.error == "name_in_prose" and v.problems[0]["names"] == ["issuer_exposures.weight"]
    assert G.check([_para("Its weight and capex are high.")], led).ok


def test_G3_a_quotation_is_verbatim_in_a_cited_passage_or_refused(world):
    led, by, var, passage = world
    assert G.check([_para('The filing says the products "collectively accounted for 82 percent of our total revenues in 2025".', cites=[passage.id])], led).ok
    v = G.check([_para('The filing says the products "collectively accounted for most of our total revenues".', cites=[passage.id])], led)
    assert v.error == "unverified_quote"


def test_the_gate_refuses_for_one_of_seven_reasons_and_nothing_else():
    import inspect
    src = inspect.getsource(G)
    reasons = {"malformed_answer", "not_on_ledger", "kind_does_not_fit", "not_standalone",
               "unsourced_figure", "id_in_prose", "name_in_prose", "unverified_quote"}
    found = {m for m in reasons if f'"{m}"' in src}
    assert found == reasons
    # the only patterns in the gate are whitespace and quotation marks; no digit class, no exemption
    assert "_NOT_A_FIGURE" not in src and "_DIGIT_RUN" not in src, "no digit class list in the gate"


# ── accepted ──────────────────────────────────────────────────────────────────

def test_accepted_carries_filled_blocks_prose_the_facts_used_and_what_was_verified(world):
    led, by, var, passage = world
    w = by[("MSFT", "issuer_exposures.weight")]
    mv = by[("MSFT", "issuer_exposures.market_value")]
    blocks = [_para("MSFT weighs ", {"fact": w["id"]}, f" of the book, worth ${mv['value']:,.0f}.", cites=[passage.id]),
              {"type": "table", "rows": [[w["id"], mv["id"]]]}]
    v = G.check(blocks, led)
    assert v.ok, v.problems
    out = G.accepted(blocks, v, led)
    # the written market value equals MSFT's market_value on two results (the run's
    # sections and book.analysis both carry it), so the link and the citations name both
    assert {w["id"], passage.id, mv["id"]} <= set(out["citations"])
    assert out["verified"]["figures"] >= 2 and out["verified"]["sources"] == 1
    assert {w["id"], mv["id"]} <= {m["source_id"] for m in out["verified"]["matches"]}
    assert out["blocks"][0]["runs"][1]["fact"]["display"] == "16.3%"
    assert any(isinstance(r, dict) and "link" in r for r in out["blocks"][0]["runs"])
    assert out["blocks"][1]["labels"] == ["MSFT"]
    assert "MSFT weighs 16.3% of the book" in out["text"]


def test_an_answer_that_states_nothing_factual_verifies_nothing_and_says_so(world):
    led, *_ = world
    blocks = [_para("Nothing changed.")]
    v = G.check(blocks, led)
    out = G.accepted(blocks, v, led)
    assert out["verified"] == {"figures": 0, "sources": 0, "matches": []} and out["citations"] == []


# ── from the first live round (2026-09-05) ────────────────────────────────────

def test_a_cite_may_be_any_fact_the_block_rests_on(world):
    """Eight of eleven live refusals were the model listing the scalars it had
    used under `cites`. Nothing is lost by accepting it: the quote check reads
    the passage cites, and the rest render as footnotes to the facts."""
    led, by, var, passage = world
    w = by[("MSFT", "issuer_exposures.weight")]
    v = G.check([_para("MSFT weighs ", {"fact": w["id"]}, ".", cites=[w["id"], passage.id])], led)
    assert v.ok, v.problems


def test_a_pointer_written_inside_a_string_is_named_as_that_not_linked(world):
    led, by, *_ = world
    w = by[("MSFT", "issuer_exposures.weight")]
    for shape in ("{fact:%s}", '{"fact": "%s"}', "{fact: '%s'}"):
        v = G.check([_para("MSFT weighs " + shape % w["id"] + " of the book.")], led)
        assert v.error == "pointer_written_as_text", shape
        assert v.problems[0]["pointers"] == [shape % w["id"]]
        assert not any(p["reason"] == "id_in_prose" for p in v.problems), "the id inside is not reported twice"


def test_verified_counts_a_written_value_once_however_many_facts_share_it(world):
    led, by, *_ = world
    thr = next(r for r in led.by_id.values() if r["measure"] == "limit_checks.warning_level" and (r["subject"] or "").startswith("issuer_concentration"))
    blocks = [_para(f"against a {thr['value'] * 100:.1f}% warning limit.")]
    v = G.check(blocks, led)
    out = G.accepted(blocks, v, led)
    assert out["verified"]["figures"] == 1 and len(out["citations"]) > 1


def test_a_number_the_user_wrote_rests_on_the_question(world):
    led, *_ = world
    q = "rates back up 100bp from here — and if I sell half our NVDA and put 5% into KO?"
    v = G.check([_para("On a +100bp move the book loses; a 5% KO position would sit under its limit.")], led, question=q)
    assert v.ok, v.problems
    by_written = {l["as_written"]: l["to"] for l in v.links.values()}
    assert by_written["+100"] == "question"
    assert by_written["5%"] in ("question", "fact"), "5% is the user's figure, and also a scenario input on the ledger"
    out = G.accepted([_para("On a +100bp move the book loses.")], G.check([_para("On a +100bp move the book loses.")], led, question=q), led)
    assert out["blocks"][0]["runs"] == ["On a +100bp move the book loses."], "the question's number renders as plain text"
    assert G.check([_para("On a +100bp move the book loses.")], led).error == "unsourced_figure"
