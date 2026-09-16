"""V36 Phase 1a — the digest, now a service and read by a domain analyst.

The rendering moved out of the broker unchanged except for one thing it always
computed and never showed: a figure's place in the ordering its node built.
V33J Q11 is the cost of not showing it — the desk ranked ten issuer-concentration
checks, the analyst called MSFT "closest", and the check refused the sentence
because nothing in front of the analyst said which figure held that place.

The shape tests that came with the broker (`test_v33_broker`) still cover the
rest; these are the properties the move is for.
"""

from __future__ import annotations

from exposure_workbench.services import digest as dg, facts as F


def _row(fid, kind, subject, measure, unit, value, as_of="2026-09-10", params=None):
    return [fid, kind, subject, measure, unit, value, as_of, None, params or {}, []]


def _result(rows, **extra):
    return {"program_id": "calc_1", "returns": [],
            "nodes": {(r[8] or {}).get("node", "n"): {"kind": r[1]} for r in rows},
            "settled": len(rows), "refused": [],
            "facts": {"columns": list(F.COLUMNS), "rows": rows}, **extra}


# ── what the move is for ─────────────────────────────────────────────────────

def test_a_figures_place_in_its_ordering_is_shown():
    """A superlative rests on a place the desk computed. The broker put the place
    on the fact and showed the analyst a flat list, so "closest" had no visible
    support and the answer check — reading the same fact — refused it."""
    rows = [_row("f_msft", "scalar", "issuer_concentration:MSFT", "limit_checks.current_value", "RATIO", 0.1604,
                 params={"node": "limit_checks_current_value", "label": "issuer_concentration:MSFT", "place": 3, "of": 20}),
            _row("f_nvda", "scalar", "issuer_concentration:NVDA", "limit_checks.current_value", "RATIO", 0.0406,
                 params={"node": "limit_checks_current_value", "label": "issuer_concentration:NVDA", "place": 19, "of": 20})]
    d = dg.render(_result(rows), mint=dg.Minter())
    by_id = {f["id"]: f for f in d["figures"]}
    assert (by_id["f_msft"]["place"], by_id["f_msft"]["of"]) == (3, 20)
    assert (by_id["f_nvda"]["place"], by_id["f_nvda"]["of"]) == (19, 20)


def test_a_rank_node_still_shows_its_rank():
    rows = [_row("f_r", "scalar", "issuer_concentration:MSFT", "limit_checks.current_value", "RATIO", 0.1604,
                 params={"node": "checks_ranked", "label": "issuer_concentration:MSFT", "rank": 18, "place": 3, "of": 20})]
    d = dg.render(_result(rows), mint=dg.Minter())
    assert d["figures"][0]["rank"] == 18


def test_the_value_is_shown_the_way_it_must_be_written():
    rows = [_row("f_a1", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.16039003,
                 params={"node": "w", "place": 1, "of": 10})]
    d = dg.render(_result(rows), mint=dg.Minter())
    assert d["figures"][0]["value"] == "16.0% [f_a1]"


# ── one reading is shown once, across a whole analyst's session ──────────────

def test_a_reading_fetched_twice_in_two_calls_collapses_when_the_caller_carries_seen():
    """The broker deduplicated within one digest because one request was one
    digest. A sub-analyst makes several calls, so the caller carries `seen` and
    the second showing names the first's id instead of repeating the figure."""
    seen: dict = {}
    rows = [_row("f_first", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.1604, params={"node": "w"})]
    again = [_row("f_again", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.1604, params={"node": "w2"})]

    first = dg.render(_result(rows), mint=dg.Minter(), seen=seen)
    second = dg.render(_result(again), mint=dg.Minter(), seen=seen)

    assert [f["id"] for f in first["figures"]] == ["f_first"]
    assert second["figures"] == []                       # shown once
    # V38/T4: and THIS result says so, naming the id it was shown under — the
    # earlier result is not edited after the analyst has read it
    assert second["repeated"] == [{"node": "w2", "count": 1, "shown_as": ["f_first"]}]
    assert "also" not in first["figures"][0]


def test_a_figure_the_cap_cut_is_not_seen_and_is_shown_when_asked_for():
    """V38/T4. `seen` was registered before `fit` cut the tail, so a figure the
    analyst never read was "already shown" and swallowed when it asked for exactly
    that figure — round C's mini Q01 asked twice for the room it had been cut, and
    read nothing both times."""
    seen: dict = {}
    wide = [_row(f"f_{i:03}", "scalar", f"T{i}", "issuer_exposures.weight", "RATIO", i / 1000.0,
                 params={"node": "w", "label": f"T{i}"}) for i in range(120)]
    first = dg.render(_result(wide), mint=dg.Minter(), seen=seen, cap=4_000)
    shown = {f["id"] for f in first["figures"]}
    cut = [r for r in wide if r[0] not in shown]
    assert shown and cut
    second = dg.render(_result(cut[:2]), mint=dg.Minter(), seen=seen)
    assert [f["id"] for f in second["figures"]] == [cut[0][0], cut[1][0]]
    assert "repeated" not in second


def test_a_result_of_nothing_new_says_so():
    seen: dict = {}
    rows = [_row("f_one", "scalar", "MSFT", "ebit_interest_coverage", "MULTIPLE", 55.65, params={"node": "c2021"})]
    dg.render(_result(rows), mint=dg.Minter(), seen=seen)
    again = dg.render(_result([_row("f_two", "scalar", "MSFT", "ebit_interest_coverage", "MULTIPLE", 55.65,
                                    params={"node": "c2022"})]), mint=dg.Minter(), seen=seen)
    assert again["figures"] == [] and again["repeated"] == [{"node": "c2022", "count": 1, "shown_as": ["f_one"]}]


def test_without_seen_each_call_stands_alone():
    rows = [_row("f_x", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.1604, params={"node": "w"})]
    a = dg.render(_result(rows), mint=dg.Minter())
    b = dg.render(_result(rows), mint=dg.Minter())
    assert len(a["figures"]) == len(b["figures"]) == 1


# ── every text an analyst reads is a fact the caller can record ──────────────

def test_a_boundary_is_minted_as_a_fact_the_caller_collects():
    """Round G refused an analyst for quoting a boundary verbatim: it had been
    shown and never recorded. The Minter exists so the collecting cannot be the
    step somebody forgets."""
    minter = dg.Minter()
    d = dg.render({"error": "not_prepared", "detail": "KO is not on the desk"}, mint=minter, subject="KO")
    b = d["boundaries"][0]
    assert (b["class"], b["code"], b["subject"]) == ("data_absent", "not_prepared", "KO")
    facts = minter.take()
    assert [f.id for f in facts] == [b["fact"]]
    assert facts[0].kind == F.ABSENCE and "KO is not on the desk" in facts[0].text
    assert minter.take() == []          # taken once


def test_held_back_figures_are_said_per_returned_node_and_recorded():
    """V38/T1: by the node the program returned; "run the same program with
    `return` naming only the nodes you need" named a lever that did nothing."""
    minter = dg.Minter()
    d = dg.render(_result([], held_back={"count": 58, "measures": ["port:weight"], "nodes": {"analysis_prev": 58}}),
                  mint=minter)
    (held,) = [b for b in d["boundaries"] if b.get("class") == "held_back"]
    assert "58 more figures of the nodes you returned" in held["text"] and "analysis_prev: 58" in held["text"]
    assert held["nodes"] == {"analysis_prev": 58} and "measures" not in held
    assert held["fact"] in {f.id for f in minter.facts}


def test_held_back_results_of_another_tool_say_how_to_ask_for_them():
    minter = dg.Minter()
    d = dg.render({"facts": {"columns": list(F.COLUMNS), "rows": []},
                   "held_back": {"count": 7, "measures": ["AAPL:Item 7"], "how": "ask for fewer passages"}},
                  mint=minter)
    (held,) = d["boundaries"]
    assert "7 more results" in held["text"] and "ask for fewer passages" in held["text"]


def test_the_cap_holds_back_rows_and_mints_a_fact_for_them():
    minter = dg.Minter()
    rows = [_row(f"f_{i:03}", "scalar", f"T{i}", "issuer_exposures.weight", "RATIO", i / 1000.0,
                 params={"node": "w", "label": f"T{i}"}) for i in range(400)]
    d = dg.render(_result(rows), mint=minter, cap=4_000)
    note = next(b for b in d["boundaries"] if b.get("by") == "digest")
    assert 0 < len(d["figures"]) < 400
    assert note["count"] == 400 - len(d["figures"])
    assert note["fact"] in {f.id for f in minter.facts}


# ── the entry point ──────────────────────────────────────────────────────────

def test_render_echoes_the_request_and_leaves_the_citing_rule_to_the_system_text():
    """V37/T5: the rule is standing knowledge, not a per-result repetition. Those
    726 characters rode on every result — `book_market_risk` read them nine times
    in one turn of round B — which dilutes the reading and breaks the prompt's
    stable prefix without saying anything new. The analyst's system text carries
    them once (agents/sub_analyst), and a caller that wants them inline asks."""
    req = {"subjects": ["port_001"], "want": ["issuer_exposures.weight"], "compare": "rank lowest"}
    d = dg.render(_result([]), request=req, mint=dg.Minter())
    assert d["request"] == req and "how_to_cite" not in d
    with_rule = dg.render(_result([]), request=req, mint=dg.Minter(), how_to_cite=True)
    assert "bracket included" in with_rule["how_to_cite"]
    assert "place" in with_rule["how_to_cite"]      # V36: the support a superlative rests on


def test_a_series_says_how_it_is_spaced_and_how_far_it_reaches():
    """The entry showed `n`, a first point and a last, and left the analyst to
    work the cadence out of the dates — which it got wrong five times in round B,
    calling six annual points "the last twelve quarter readings" with those six
    annual dates printed in its own sentence. It is a lookup, and it is the same
    lookup the answer check makes: the analyst reads what the gate will read."""
    rows = [["f_dso0001", "series", "AAPL", "days_sales_outstanding", "COUNT",
             {"points": [["2020-09-26", 21.43], ["2021-09-25", 26.22], ["2022-09-24", 26.09],
                         ["2023-09-30", 28.10], ["2024-09-28", 31.19], ["2025-09-27", 34.89]], "n": 6},
             "2025-09-27", None, {"node": "dso"}, []]]
    d = dg.render(_result(rows), mint=dg.Minter())
    (s_,) = d["series"]
    assert s_["spacing"] == "annual" and s_["span"] == "2020-09-26..2025-09-27" and s_["n"] == 6


def test_a_series_point_carries_its_date_in_the_bracket():
    rows = [["f_s", "series", "AMZN", "operating_cash_flow", "MONEY",
             {"points": [["2025-12-31", 5.446e10], ["2026-03-31", 2.603e10]], "n": 2},
             None, None, {"node": "ocf"}, []]]
    d = dg.render(_result(rows), mint=dg.Minter())
    s = d["series"][0]
    assert s["last"] == ["2026-03-31", "$26.03B [f_s@2026-03-31]"]
    assert s["points"][0][1].endswith("[f_s@2025-12-31]")


# ── V36.1 (round A) · the desk's words are sentences ─────────────────────────

def test_an_absence_rows_own_sentence_reaches_the_analyst():
    """Round A's Q11: the filter's level was written as 8 against weights that
    are fractions, and the executor said so — "no entry of $issuer_weights is
    > 8". For an absence the row's value IS that sentence; a boundary shown with
    an empty text and a code alone is one the analyst cannot act on."""
    a = F.fact(F.ABSENCE, "over_8pct", subject=None, as_of="n/a", value=None,
               text="over_8pct was not computed — no_entry_satisfies: no entry of $issuer_weights is > 8",
               params={"node": "over_8pct", "error": "no_entry_satisfies", "reason": "cannot"}, standalone=False)
    d = dg.render({"program_id": "calc_1", "returns": [], "nodes": {"over_8pct": {"kind": "absence"}}, "settled": 0,
                   "refused": ["over_8pct"], "facts": F.block_for_model([a])}, mint=dg.Minter())
    b = d["boundaries"][0]
    assert b["fact"] == a.id and b["code"] == "no_entry_satisfies"
    assert "no entry of $issuer_weights is > 8" in b["text"]


def test_a_tool_refusal_names_the_call_it_answers():
    """`not_indexed` was the whole text of a boundary in round A (Q14), and the
    lead was refused for quoting the analyst's paraphrase of it. The desk's
    words say what was asked and what the desk answered — a sentence the lead
    may quote, and the gate can look up."""
    m = dg.Minter()
    d = dg.render({"error": "not_indexed", "ticker": "MSFT"}, mint=m,
                  call={"tool": "read_filings", "args": {"ticker": "MSFT", "item": "7", "query": None}})
    b = d["boundaries"][0]
    assert b["text"] == "read_filings(ticker='MSFT', item='7'): not_indexed"
    assert b["class"] == "data_absent" and b["code"] == "not_indexed"
    assert m.take()[0].text == b["text"]            # the same sentence is on the ledger
