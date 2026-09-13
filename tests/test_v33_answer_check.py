"""V33 Phase 2 — the natural-language answer against the ledger (offline).

Each case is one of the twelve reader-visible false statements the 20-question
round let through (docs/spikes/v33/FINDINGS_V33.md), rebuilt over a hand-made
ledger, and the sentence a careful analyst would have written beside it.
"""
from __future__ import annotations

from exposure_workbench.services import answer_check as ac
from exposure_workbench.services.ledger import Ledger


def _f(fid, measure, subject, value, unit="RATIO", as_of="2026-09-10", **params):
    return {"id": fid, "kind": "scalar", "measure": measure, "subject": subject, "unit": unit, "value": value,
            "as_of": as_of, "window": None, "params": params, "standalone": True, "sources": [], "group": "x"}


def _series(fid, measure, subject, points, unit="RATIO"):
    return {"id": fid, "kind": "series", "measure": measure, "subject": subject, "unit": unit, "value": None,
            "points": points, "as_of": points[-1][0], "window": {"start": points[0][0], "end": points[-1][0]},
            "params": {"node": "s_" + subject.lower()}, "standalone": True, "sources": [], "group": "x"}


def _passage(fid, subject, text):
    return {"id": fid, "kind": "passage", "measure": "10-K Item 7", "subject": subject, "unit": None, "value": None,
            "text": text, "as_of": "n/a", "window": None, "params": {}, "standalone": True, "sources": [], "group": "x"}


LEDGER = Ledger.of([
    # weights, one ranked
    _f("f_wmsft", "issuer_exposures.weight", "MSFT", 0.16039003, node="w"),
    _f("f_waapl", "issuer_exposures.weight", "AAPL", 0.15195055, node="w"),
    _f("f_wnvda", "issuer_exposures.weight", "NVDA", 0.0406405, node="w"),
    _f("f_rmsft", "issuer_exposures.weight", "MSFT", 0.16039003, node="ranked", op="rank", rank=1, label="MSFT"),
    _f("f_raapl", "issuer_exposures.weight", "AAPL", 0.15195055, node="ranked", op="rank", rank=2, label="AAPL"),
    # capex intensity latest points (no rank) and the same, ranked
    _f("f_ciamzn", "capex_intensity", "AMZN", 0.1839, as_of="2025-12-31", node="ci"),
    _f("f_cimsft", "capex_intensity", "MSFT", 0.2291, as_of="2025-06-30", node="ci"),
    _f("f_crmsft", "capex_intensity", "MSFT", 0.2291, as_of="2025-06-30", node="ci_rank", op="rank", rank=1, label="MSFT"),
    _f("f_cramzn", "capex_intensity", "AMZN", 0.1839, as_of="2025-12-31", node="ci_rank", op="rank", rank=2, label="AMZN"),
    # price statistics (Q17)
    _f("f_retamzn", "price.window_return", "AMZN", -0.0583, node="ret1m"),
    _f("f_retaapl", "price.window_return", "AAPL", 0.0876, node="ret1m"),
    _f("f_d52aapl", "price.distance_from_52w_high", "AAPL", -0.0389, node="from_high"),
    _f("f_d52amzn", "price.distance_from_52w_high", "AMZN", -0.1131, node="from_high"),
    # tiers and readings (Q11, Q15)
    _f("f_curmsft", "limit_checks.current_value", "issuer_concentration:MSFT", 0.16039003, node="curr"),
    _f("f_warnmsft", "limit_checks.warning_level", "issuer_concentration:MSFT", 0.15, node="warn"),
    _f("f_breachmsft", "limit_checks.breach_level", "issuer_concentration:MSFT", 0.20, node="breach"),
    _f("f_warnnvda", "limit_checks.warning_level", "issuer_concentration:NVDA", 0.15, node="warn"),
    _f("f_warndflt", "limit_checks.warning_level", "issuer_concentration", 0.15, node="warn"),
    _f("f_roomwmsft", "subtract(limit_checks.warning_level, limit_checks.current_value)", "issuer_concentration:MSFT", -0.01039, as_of="n/a", node="room_w", op="subtract"),
    # drawdown (Q14): depth, window return with the episode's window
    _f("f_depth1", "portfolio.deepest_depth", "drawdown_episodes", 0.1196, node="depth"),
    {**_f("f_retbook", "portfolio.window_return", "calc_ep", -0.1196, as_of="2026-03-27", node="explain", peak="2026-01-07", trough="2026-03-27"),
     "window": {"start": "2026-01-07", "end": "2026-03-27"}},
    # reconcile (Q18)
    _f("f_fs001", "portfolio.reconcile.factor_share", "calc_recon", -1.2547, node="recon"),
    _f("f_apr001", "portfolio.reconcile.alpha_plus_residual", "calc_recon", 0.00847461, node="recon"),
    _f("f_us001", "portfolio.reconcile.unexplained_share", "calc_recon", 2.2547, node="recon"),
    # scenario (Q13): money and ratio for gross exposure
    _f("f_gemoney", "exposure_metrics.gross_exposure", "calc_scn", 10629332.0, unit="MONEY", node="after"),
    _f("f_geratio", "limit_checks.current_value", "gross_exposure", 1.0, node="after"),
    _f("f_techbefore", "sector_exposures.weight", "Technology", 0.353, node="tech_before"),
    _f("f_techafter", "sector_exposures.weight", "Technology", 0.3396, node="tech_after"),
    # a change node
    _f("f_yoy001", "revenue.yoy", "AMZN", 0.124, as_of="2025-12-31", node="rev_g", op="yoy"),
    # a series and a passage
    _series("f_ocf001", "operating_cash_flow", "AMZN", [["2021-12-31", 46.3e9], ["2025-12-31", 140.0e9]], unit="MONEY"),
    _passage("f_plly", "LLY", "Gross margin as a percent of revenue in 2025 increased 1.7 percentage points compared with 2024, "
                              "primarily driven by favorable product mix and improved cost of production."),
])


def _refused(text, reason, question=None):
    v = ac.check(text, LEDGER, question)
    assert not v.ok, f"accepted: {text!r}"
    reasons = {p["reason"] for p in v.problems}
    assert reason in reasons, (reason, v.problems)
    return v


def _accepted(text, question=None):
    v = ac.check(text, LEDGER, question)
    assert v.ok, v.problems
    return v


# ── G1 / G2: numbers ─────────────────────────────────────────────────────────

def test_a_number_the_ledger_holds_passes_and_is_linked_to_all_its_aliases():
    v = _accepted("MSFT weighs 16.0% of the book.")
    link = list(v.links.values())[0]
    assert set(link["ids"]) == {"f_wmsft", "f_rmsft", "f_curmsft"} and link["primary"] == "f_wmsft"


def test_an_invented_number_is_refused_with_a_way_out():
    v = _refused("MSFT weighs 23.4% of the book.", "unsourced_figure")
    assert "request" in v.problems[0]["fix"]


def test_the_users_own_number_is_allowed():
    _accepted("At a 20% participation rate JPM takes longest to sell.", question="days to liquidate at 20% of ADV")


def test_a_number_held_by_several_facts_is_pinned_by_the_subject_named():
    v = _accepted("NVDA is at 4.06% against its 15.0% warning tier.")
    assert any(l["ids"] == ["f_warnnvda"] for l in v.links.values())


def test_a_number_held_by_several_facts_and_no_subject_is_ambiguous():
    v = _refused("The warning tier is 15.0% for this check.", "ambiguous_figure")
    assert v.problems[0]["candidates"]


def test_a_mark_pins_a_number_and_a_wrong_mark_is_refused():
    _accepted("The warning tier is 15.0% [f_warnnvda] for this check.")
    _refused("The warning tier is 15.0% [f_breachmsft] for this check.", "mark_mismatch")


def test_a_bare_id_in_prose_is_refused():
    _refused("MSFT weighs f_wmsft of the book.", "id_in_prose")


# ── G3: the sentence around the figures ───────────────────────────────────────

def test_q08_a_superlative_on_an_unranked_figure_is_refused_and_on_a_ranked_one_passes():
    _refused("AAPL had the strongest month at 8.76%, above AMZN at -5.83%.", "superlative_without_rank")
    _accepted("Microsoft spends the most: capex intensity 22.9% against Amazon's 18.4%.")   # a rank node exists over these


def test_q17_a_figure_attributed_to_the_wrong_company_is_refused():
    v = _refused("AAPL sits -5.83% below its 52-week high.", "subject_mismatch")
    assert v.problems[0]["figure_subject"] == "AMZN"
    _accepted("AMZN returned -5.83% over the month; AAPL sits -3.89% below its 52-week high.")


def test_q14_a_date_word_followed_by_a_percentage_is_refused_and_by_a_date_passes():
    _refused("The worst drawdown started on 12.0% and troughed on 2026-03-27.", "date_expected")
    _accepted("The worst drawdown started on 2026-01-07 and troughed on 2026-03-27, a depth of 12.0%.")


def test_q13_a_change_between_two_units_is_refused():
    # not because the units differ — because they are two different quantities
    _refused("Selling half of NVDA lowers gross exposure from $10.63M to 100.0%.", "change_conflict")
    _accepted("Technology concentration moves from 35.3% before the sale to 34.0% after the sale.")


def test_q11_room_to_warning_stated_against_the_breach_tier_is_refused():
    _refused("MSFT's room to warning is -1.04% against 20.0%.", "tier_mismatch")
    _accepted("MSFT is at 16.0% against a 15.0% warning tier and a 20.0% breach tier.")


def test_q18_a_measure_the_sentence_names_must_be_the_figures_measure():
    v = _refused("The reconciliation shows factor share 0.85% and unexplained share 225.5%.", "measure_mismatch")
    assert "factor share" in v.problems[0]["phrase"]
    _accepted("The reconciliation shows factor share -125.5% and unexplained share 225.5%.")


def test_a_direction_word_against_the_values_is_refused():
    _refused("Technology concentration rose from 35.3% to 34.0% after the sale.", "direction_conflict")
    _accepted("Revenue grew 12.4% year over year.")
    _refused("Revenue fell 12.4% year over year.", "direction_conflict")


def test_the_same_reading_twice_is_not_a_change():
    _refused("MSFT moved from 16.0% to 16.0% since the run.", "change_conflict")


# ── G4 / G5: quotes and marks ────────────────────────────────────────────────

def test_a_verbatim_quote_carries_its_own_digits_and_a_paraphrase_is_refused():
    _accepted("Lilly says gross margin “increased 1.7 percentage points compared with 2024, primarily driven by favorable product mix” in 2025.")
    _refused("Lilly says gross margin “increased 1.7 percentage points thanks to pricing power” in 2025.", "unverified_quote")


def test_table_and_chart_marks_name_program_nodes_and_render_as_blocks():
    v = _accepted("Weights by name are in the table below. [table: w] Operating cash flow is charted. [chart: s_amzn]")
    out = ac.accepted("Weights by name are in the table below. [table: w] Operating cash flow is charted. [chart: s_amzn]", v, LEDGER)
    kinds = [b["type"] for b in out["blocks"]]
    assert kinds == ["paragraph", "table", "chart"]
    assert "[table: w]" not in out["text"] and "[chart: s_amzn]" not in out["text"]
    _refused("See [table: nope].", "unknown_node")


# ── the render ────────────────────────────────────────────────────────────────

def test_the_reader_sees_the_words_the_analyst_wrote_and_the_fact_behind_them():
    """The render annotates, never substitutes: the run carries the text as written
    and the ids it opens. Substituting the fact's display was the placeholder
    grammar's job and V33 deleted the placeholders; it only made true sentences
    false (V33D: "1-year" came out "$251.89 (2026-09-10)-year")."""
    text = "MSFT weighs 16.0% of the book [f_wmsft]; the warning tier is 15.0% [f_warnmsft]."
    v = _accepted(text)
    out = ac.accepted(text, v, LEDGER)
    runs = out["blocks"][0]["runs"]
    links = [r["link"] for r in runs if isinstance(r, dict) and "link" in r]
    assert [l["as_written"] for l in links] == ["16.0%", "15.0%"]
    assert [l["ids"][0] for l in links] == ["f_wmsft", "f_warnmsft"]
    assert not any("fact" in r for r in runs if isinstance(r, dict))
    assert out["text"] == "MSFT weighs 16.0% of the book; the warning tier is 15.0%."
    assert out["verified"]["figures"] == 2 and set(out["citations"]) == {"f_wmsft", "f_warnmsft"}


def test_all_problems_are_reported_at_once():
    v = ac.check("MSFT weighs 23.4%. AAPL sits -5.83% below its high. The drawdown started on 12.0%.", LEDGER)
    reasons = [p["reason"] for p in v.problems]
    assert {"unsourced_figure", "subject_mismatch", "date_expected"} <= set(reasons)
    assert v.detail.startswith("3 problem(s)") or v.detail.startswith(f"{len(v.problems)} problem(s)")


# ── V33C: what the first acceptance round refused that the ledger held ───────

_C_LEDGER = Ledger.of([
    *LEDGER.by_id.values(),
    {**_series("f_ni001", "net_income", "AMZN", [["2021-12-31", 33.36e9], ["2025-12-31", 77.67e9]], unit="MONEY"), "params": {"node": "s_ni"}},
    {**_series("f_fcf001", "free_cash_flow", "AMZN", [["2021-12-31", -9.07e9], ["2025-12-31", 77.67e9]], unit="MONEY"), "params": {"node": "s_fcf"}},
    _f("f_advmsft", "price.adv", "MSFT", 13.27e9, unit="MONEY_PER_DAY", node="adv"),
    {"id": "f_abs001", "kind": "absence", "measure": "book.liquidation_days", "subject": "port_001", "unit": None,
     "value": "the desk does not compute liquidation days; days to liquidate is market value over a share of ADV",
     "as_of": "n/a", "window": None, "params": {"error": "no_such_method"}, "standalone": False, "sources": [], "group": "x"},
])


def test_a_point_of_a_series_is_a_figure_the_ledger_holds_and_renders_on_its_date():
    """V33C: 329 of 421 refused figures were points of series the digest had shown."""
    v = ac.check("Operating cash flow was $46.3B in 2021 and $140.0B in 2025.", _C_LEDGER)
    assert v.ok, v.problems
    # the two money figures are points; the years resolve as identity (a series' own dates)
    points = sorted((l for l in v.links.values() if l.get("period")), key=lambda l: l["as_written"])
    assert [l["period"] for l in points] == ["2025-12-31", "2021-12-31"]
    assert all(l["ids"] == ["f_ocf001"] for l in points)
    out = ac.accepted("Operating cash flow was $46.3B in 2021 and $140.0B in 2025.", v, _C_LEDGER)
    assert out["text"] == "Operating cash flow was $46.3B in 2021 and $140.0B in 2025."
    assert "f_ocf001" in out["citations"]


def test_a_series_marked_after_its_point_is_the_source_and_a_wrong_mark_is_not():
    assert ac.check("Operating cash flow reached $140.0B [f_ocf001].", _C_LEDGER).ok
    v = ac.check("Operating cash flow reached $140.0B [f_wmsft].", _C_LEDGER)
    assert {p["reason"] for p in v.problems} == {"mark_mismatch"}


def test_two_series_sharing_a_point_are_one_reading_and_the_measure_named_leads():
    """One subject, one date, one number: whichever fact the reader opens, the
    sentence says the same thing. The page shows a chooser for the two ids and
    never guesses; the measure the sentence names leads the list."""
    v = ac.check("Amazon made $77.67B last year.", _C_LEDGER)
    assert v.ok, v.problems
    assert set(next(iter(v.links.values()))["ids"]) == {"f_ni001", "f_fcf001"}
    v = ac.check("Net income was $77.67B in 2025.", _C_LEDGER)
    assert v.ok and next(iter(v.links.values()))["primary"] == "f_ni001"


def test_a_flows_dollars_a_day_match_with_or_without_the_day():
    """V33C Q15: every ADV figure was refused because the display is "$13.27B/day"."""
    assert ac.check("MSFT trades $13.27B a day.", _C_LEDGER).ok
    assert ac.check("MSFT trades $13.27B/day.", _C_LEDGER).ok


def test_a_comparison_across_units_is_prose_and_a_change_across_units_is_not():
    """V33D refused 15 comparisons for holding two units. A comparison is prose; a
    CHANGE across units is two different quantities, which the measure test refuses."""
    assert ac.check("MSFT weighs 16.0% of the book against $13.27B of daily volume.", _C_LEDGER).ok
    v = ac.check("MSFT rose from $13.27B to 16.0%.", _C_LEDGER)
    assert "change_conflict" in {p["reason"] for p in v.problems}


def test_quotation_marks_hold_a_passages_words_and_nothing_else():
    """What the desk could not do is said in the analyst's own words; quotation
    marks claim a passage read this turn. Trying the absence texts and the
    question when a passage misses was a fallback, and it let a paraphrase of the
    desk's refusal read as a quotation."""
    v = ac.check("The desk said it \"does not compute liquidation days\", so I give the inputs.", _C_LEDGER)
    assert {p["reason"] for p in v.problems} == {"unverified_quote"}
    assert ac.check("The desk does not compute liquidation days, so I give the inputs.", _C_LEDGER).ok


def test_a_quotation_is_its_words_and_the_nesting_marks_may_change():
    """V33D Q09: 381 verbatim characters refused because the source's inner `"`
    had to become `'` to sit inside the analyst's own quotation."""
    led = Ledger.of([*_C_LEDGER.by_id.values(),
                     _passage("f_q9", "AAPL", 'can be found in "Management\u2019s Discussion and Analysis" in Part II')])
    assert ac.check('The filing says it \u201ccan be found in \u2018Management\u2019s Discussion and Analysis\u2019 in Part II\u201d.', led).ok


def test_one_series_fetched_twice_is_one_reading_not_an_ambiguity():
    """V33D: the analyst asked twice, the ledger held the same series under two ids,
    and 240 figures were refused as ambiguous."""
    twice = Ledger.of([*_C_LEDGER.by_id.values(),
                       {**_series("f_ocf002", "operating_cash_flow", "AMZN", [["2021-12-31", 46.3e9], ["2025-12-31", 140.0e9]], unit="MONEY"),
                        "params": {"node": "ocf_again"}}])
    v = ac.check("Operating cash flow reached $140.0B in 2025.", twice)
    assert v.ok, v.problems
    (link,) = [l for l in v.links.values() if l.get("period")]
    assert link["period"] == "2025-12-31" and set(link["ids"]) == {"f_ocf001", "f_ocf002"}


def test_a_measure_named_in_the_sentence_may_be_the_series_point_beside_it():
    """V33D: 'operating cash flow' named, the figure a point of that series, and the
    check compared the phrase against the sentence's scalars only."""
    assert ac.check("Amazon's operating cash flow was $140.0B beside a capex intensity of 18.4%.", _C_LEDGER).ok


# ── V33D ─────────────────────────────────────────────────────────────────────

_D_LEDGER = Ledger.of([
    *_C_LEDGER.by_id.values(),
    _f("f_hygret", "price.window_return", "HYG", 0.0107, node="ret1y", window="1y"),
    {**_f("f_ddhyg", "price.drawdown", "HYG", 0.0234, unit="RATIO", node="dd"), "window": {"start": "2026-02-20", "end": "2026-03-27"}},
    _f("f_divshare", "divide(dividends_paid, operating_cash_flow)", "AMZN", 0.12, node="div_share"),
])


def test_a_bare_integer_is_not_a_percentage():
    """V33D Q18: '1y window return' rendered as '1.07%y' — the 1 matched 0.0107."""
    v = ac.check("HYG's 1-year window return is 1.07%, and 2 episodes were found.", _D_LEDGER, question="two episodes?")
    assert v.ok, v.problems
    figures = [l for l in v.links.values() if l["to"] == "fact" and l.get("how") != "identity"]
    assert [l["as_written"] for l in figures] == ["1.07%"]
    # the desk showed that figure as "1.07%": a bare "1" is not a rounding of it at
    # the precision the desk used, and the hyphenated "1-year" is not a figure at all
    assert "f_hygret" not in _D_LEDGER.resolve_number("1")
    assert _D_LEDGER.readings("1.07%") == [("f_hygret", None)]


def test_an_identity_link_keeps_the_words_as_written():
    """V33D Q19: 'in 2023' rendered as 'in $717B (2025-12-31)'; Q18: 'over 2026-02-20 to
    2026-03-27' rendered as 'over 2.34% to 2.34%'."""
    text = "HYG drew down 2.34% over 2026-02-20 to 2026-03-27. Amazon's operating cash flow was $140.0B in 2025."
    v = ac.check(text, _D_LEDGER)
    assert v.ok, v.problems
    out = ac.accepted(text, v, _D_LEDGER)
    prose = out["text"]
    assert prose == text, prose


def test_a_measure_phrase_may_name_an_operand_of_the_figure():
    """V33D Q03: 'dividends paid were 12% of operating cash flow' beside the share fact."""
    assert ac.check("Dividends paid took 12.0% of operating cash flow.", _D_LEDGER).ok
