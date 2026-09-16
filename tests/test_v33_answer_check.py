"""V33 Phase 2 / V35 — the natural-language answer against the ledger (offline).

Each case is one of the twelve reader-visible false statements the 20-question
round let through (docs/spikes/v33/FINDINGS_V33.md), rebuilt over a hand-made
ledger, and the sentence a careful analyst would have written beside it.

V35: THE FIGURES POINT. A figure is written as the desk showed it, followed by
the id it was shown under (`16.0% [f_wmsft]`); the check is a lookup on the id.
Round G (ACCEPTANCE_V33 §14) refused 51 figures it could not place by the words
of the sentence — the subject was in the previous sentence, or ten subjects
were in this one — and every refused sentence was true. Nothing here infers
identity any more.
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


# ── G1: a pointed figure is a lookup ─────────────────────────────────────────

def test_a_pointed_figure_is_looked_up_and_linked_to_the_fact_it_names():
    v = _accepted("MSFT weighs 16.0% [f_wmsft] of the book.")
    (link,) = v.links.values()
    assert link["ids"] == ["f_wmsft"] and link["primary"] == "f_wmsft" and link["as_written"] == "16.0%"


def test_a_pointer_that_does_not_hold_the_figure_is_a_mismatch_naming_what_it_holds():
    v = _refused("MSFT weighs 23.4% [f_wmsft] of the book.", "mark_mismatch")
    assert v.problems[0]["holds"] == "16.0%" and "16.0%" in v.problems[0]["fix"]
    v = _refused("MSFT weighs 16.0% [f_warnnvda] of the book.", "mark_mismatch")
    assert v.problems[0]["holds"] == "15.0%"


def test_a_pointer_the_ledger_does_not_hold_is_refused():
    _refused("MSFT weighs 16.0% [f_nope] of the book.", "not_on_ledger")


def test_a_bracket_that_is_not_an_id_is_not_a_pointer():
    """`f_` + fewer than four characters is not an id the desk mints; the figure
    before it is bare, and the bracket is prose."""
    _refused("MSFT weighs 16.0% [f_x] of the book.", "unpointed_figure")


def test_the_same_value_under_many_subjects_is_never_ambiguous_with_a_pointer():
    """Nine issuers share a 15.0% warning tier on the fixture book (round G, Q11):
    the id says whose it is; no word in the sentence has to."""
    v = _accepted("The warning tier is 15.0% [f_warndflt] for this check.")
    assert next(iter(v.links.values()))["ids"] == ["f_warndflt"]
    v = _accepted("NVDA is at 4.06% [f_wnvda] against its 15.0% [f_warnnvda] warning tier.")
    assert any(l["ids"] == ["f_warnnvda"] for l in v.links.values())


def test_round_g_14_1_the_subject_in_the_previous_sentence_is_no_longer_a_problem():
    """Q11: "MSFT is the closest … to its warning tier. On 2026-09-10 its current
    value was 16.0%, against a warning level of 15.0%" — refused twice as
    ambiguous because the second sentence held only "its"."""
    v = _accepted("MSFT is the closest issuer concentration to its warning tier. On 2026-09-10 its current value "
                  "was 16.0% [f_curmsft], against a warning level of 15.0% [f_warnmsft].")
    assert {l["ids"][0] for l in v.links.values() if l.get("how") != "identity"} == {"f_curmsft", "f_warnmsft"}


def test_round_g_14_2_an_enumeration_of_checks_in_one_sentence_is_no_longer_a_problem():
    """Q15: four issuers' readings and tiers in one sentence drew 12 tier_mismatch
    problems per attempt, every pair of a tier and another issuer's reading. A
    tier word is checked against its own pointed tier; which reading it sits
    against is the reader's to open."""
    _accepted("MSFT at 16.0% [f_curmsft] against a 15.0% [f_warnmsft] warning and 20.0% [f_breachmsft] breach, "
              "NVDA at 4.06% [f_wnvda] against a 15.0% [f_warnnvda] warning.")


# ── G2: a bare number is an identity field, the user's, a passage's — or refused ──

def test_a_bare_figure_the_ledger_holds_is_refused_with_the_ids_it_was_shown_under():
    v = _refused("MSFT weighs 16.0% of the book.", "unpointed_figure")
    assert {c["id"] for c in v.problems[0]["candidates"]} >= {"f_wmsft", "f_curmsft"}
    assert "[f_…]" in v.problems[0]["fix"]


def test_an_invented_number_is_refused_with_a_way_out():
    v = _refused("MSFT weighs 23.4% of the book.", "unsourced_figure")
    assert "request" in v.problems[0]["fix"]


def test_the_users_own_number_is_allowed():
    _accepted("At a 20% participation rate JPM takes longest to sell.", question="days to liquidate at 20% of ADV")


def test_a_bare_id_is_a_word_the_reader_must_not_see_and_a_bracket_elsewhere_is_a_citation():
    _refused("MSFT weighs f_wmsft of the book.", "id_in_prose")
    v = _refused("The tier [f_warnnvda] is 15.0%.", "unpointed_figure")
    assert v.citations == ["f_warnnvda"], "the bracket cites the tier; the bare figure after it is still bare"


# ── G3: the sentence around the figures ───────────────────────────────────────

def test_q08_a_superlative_on_an_unranked_figure_is_refused_and_on_a_ranked_one_passes():
    _refused("AAPL had the strongest month at 8.76% [f_retaapl], above AMZN at -5.83% [f_retamzn].", "superlative_without_rank")
    _accepted("Microsoft spends the most: capex intensity 22.9% [f_crmsft] against Amazon's 18.4% [f_cramzn].")


def test_q17_a_figure_attributed_to_the_wrong_company_is_refused():
    v = _refused("AAPL sits -5.83% [f_retamzn] below its 52-week high.", "subject_mismatch")
    assert v.problems[0]["figure_subject"] == "AMZN"
    _accepted("AMZN returned -5.83% [f_retamzn] over the month; AAPL sits -3.89% [f_d52aapl] below its 52-week high.")


def test_q14_a_date_word_followed_by_a_percentage_is_refused_and_by_a_date_passes():
    _refused("The worst drawdown started on 12.0% [f_depth1] and troughed on 2026-03-27.", "date_expected")
    _accepted("The worst drawdown started on 2026-01-07 and troughed on 2026-03-27, a depth of 12.0% [f_depth1].")


def test_q13_a_change_between_two_units_is_refused():
    # not because the units differ — because they are two different quantities
    _refused("Selling half of NVDA lowers gross exposure from $10.63M [f_gemoney] to 100.0% [f_geratio].", "change_conflict")
    _accepted("Technology concentration moves from 35.3% [f_techbefore] before the sale to 34.0% [f_techafter] after the sale.")


def test_q11_a_tier_word_is_checked_against_the_pointed_tiers_kind():
    _refused("MSFT's room to warning is -1.04% [f_roomwmsft] against 20.0% [f_breachmsft].", "tier_mismatch")
    _accepted("MSFT is at 16.0% [f_curmsft] against a 15.0% [f_warnmsft] warning tier and a 20.0% [f_breachmsft] breach tier.")


def test_q18_a_measure_the_sentence_names_must_be_the_figures_measure():
    v = _refused("The reconciliation shows factor share 0.85% [f_apr001] and unexplained share 225.5% [f_us001].", "measure_mismatch")
    assert "factor share" in v.problems[0]["phrase"]
    _accepted("The reconciliation shows factor share -125.5% [f_fs001] and unexplained share 225.5% [f_us001].")


def test_a_direction_word_against_the_values_is_refused():
    _refused("Technology concentration rose from 35.3% [f_techbefore] to 34.0% [f_techafter] after the sale.", "direction_conflict")
    _accepted("Revenue grew 12.4% [f_yoy001] year over year.")
    _refused("Revenue fell 12.4% [f_yoy001] year over year.", "direction_conflict")


def test_the_same_reading_twice_is_not_a_change():
    _refused("MSFT moved from 16.0% [f_wmsft] to 16.0% [f_wmsft] since the run.", "change_conflict")


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

def test_the_reader_sees_the_words_the_analyst_wrote_without_the_brackets_and_the_fact_behind_them():
    """The render annotates, never substitutes: the run carries the text as written
    and the id it opens; the bracket was the writer's pointing, not the reader's
    text, and is dropped with the space before it."""
    text = "MSFT weighs 16.0% [f_wmsft] of the book; MSFT's warning tier is 15.0% [f_warnmsft]."
    v = _accepted(text)
    out = ac.accepted(text, v, LEDGER)
    runs = out["blocks"][0]["runs"]
    links = [r["link"] for r in runs if isinstance(r, dict) and "link" in r]
    assert [l["as_written"] for l in links] == ["16.0%", "15.0%"]
    assert [l["ids"][0] for l in links] == ["f_wmsft", "f_warnmsft"]
    assert not any("fact" in r for r in runs if isinstance(r, dict))
    assert out["text"] == "MSFT weighs 16.0% of the book; MSFT's warning tier is 15.0%."
    assert out["verified"]["figures"] == 2 and set(out["citations"]) == {"f_wmsft", "f_warnmsft"}


def test_all_problems_are_reported_at_once():
    v = ac.check("MSFT weighs 23.4%. AAPL sits -5.83% [f_retamzn] below its high. The drawdown started on 12.0% [f_depth1].", LEDGER)
    reasons = [p["reason"] for p in v.problems]
    assert {"unsourced_figure", "subject_mismatch", "date_expected"} <= set(reasons)
    assert v.detail.startswith(f"{len(v.problems)} problem(s)")


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


def test_a_point_of_a_series_is_written_with_the_series_id_and_renders_on_its_date():
    """V33C: 329 of 421 refused figures were points of series the digest had shown."""
    text = "Operating cash flow was $46.3B [f_ocf001] in 2021 and $140.0B [f_ocf001] in 2025."
    v = ac.check(text, _C_LEDGER)
    assert v.ok, v.problems
    points = sorted((l for l in v.links.values() if l.get("period")), key=lambda l: l["as_written"])
    assert [l["period"] for l in points] == ["2025-12-31", "2021-12-31"]
    assert all(l["ids"] == ["f_ocf001"] for l in points)
    out = ac.accepted(text, v, _C_LEDGER)
    assert out["text"] == "Operating cash flow was $46.3B in 2021 and $140.0B in 2025."
    assert "f_ocf001" in out["citations"]


def test_a_point_held_on_several_dates_needs_its_date_in_the_sentence():
    flat = Ledger.of([*_C_LEDGER.by_id.values(),
                      {**_series("f_flat", "headcount", "AMZN", [["2023-12-31", 1.5e6], ["2025-12-31", 1.5e6]], unit="COUNT"),
                       "params": {"node": "s_hc"}}])
    v = ac.check("Headcount was 1.50M [f_flat].", flat)
    assert {p["reason"] for p in v.problems} == {"ambiguous_point"}
    v = ac.check("Headcount was 1.50M [f_flat] in 2025.", flat)
    assert v.ok, v.problems
    assert next(iter(l for l in v.links.values() if l.get("period")))["period"] == "2025-12-31"


def test_two_series_sharing_a_point_are_told_apart_by_the_id_written():
    v = ac.check("Amazon made $77.67B [f_ni001] last year.", _C_LEDGER)
    assert v.ok, v.problems
    assert next(iter(v.links.values()))["ids"] == ["f_ni001"]
    v = ac.check("Free cash flow was $77.67B [f_fcf001] in 2025.", _C_LEDGER)
    assert v.ok and next(iter(v.links.values()))["primary"] == "f_fcf001"


def test_a_flows_dollars_a_day_match_with_or_without_the_day():
    """V33C Q15: every ADV figure was refused because the display is "$13.27B/day".
    The desk's own unit tail may sit between the figure and its bracket."""
    assert ac.check("MSFT trades $13.27B [f_advmsft] a day.", _C_LEDGER).ok
    v = ac.check("MSFT trades $13.27B/day [f_advmsft].", _C_LEDGER)
    assert v.ok, v.problems
    assert ac.accepted("MSFT trades $13.27B/day [f_advmsft].", v, _C_LEDGER)["text"] == "MSFT trades $13.27B/day."


def test_a_comparison_across_units_is_prose_and_a_change_across_units_is_not():
    """V33D refused 15 comparisons for holding two units. A comparison is prose; a
    CHANGE across units is two different quantities, which the measure test refuses."""
    assert ac.check("MSFT weighs 16.0% [f_wmsft] of the book against $13.27B [f_advmsft] of daily volume.", _C_LEDGER).ok
    v = ac.check("MSFT rose from $13.27B [f_advmsft] to 16.0% [f_wmsft].", _C_LEDGER)
    assert "change_conflict" in {p["reason"] for p in v.problems}


def test_a_quotation_is_its_words_and_the_nesting_marks_may_change():
    """V33D Q09: 381 verbatim characters refused because the source's inner `"`
    had to become `'` to sit inside the analyst's own quotation."""
    led = Ledger.of([*_C_LEDGER.by_id.values(),
                     _passage("f_q9", "AAPL", 'can be found in "Management’s Discussion and Analysis" in Part II')])
    assert ac.check('The filing says it “can be found in ‘Management’s Discussion and Analysis’ in Part II”.', led).ok


def test_one_series_fetched_twice_is_one_reading_under_either_id():
    """V33D: the analyst asked twice, the ledger held the same series under two ids,
    and 240 figures were refused as ambiguous. Whichever id the analyst copies is
    the one it was shown."""
    twice = Ledger.of([*_C_LEDGER.by_id.values(),
                       {**_series("f_ocf002", "operating_cash_flow", "AMZN", [["2021-12-31", 46.3e9], ["2025-12-31", 140.0e9]], unit="MONEY"),
                        "params": {"node": "ocf_again"}}])
    for fid in ("f_ocf001", "f_ocf002"):
        v = ac.check(f"Operating cash flow reached $140.0B [{fid}] in 2025.", twice)
        assert v.ok, v.problems
        (link,) = [l for l in v.links.values() if l.get("period")]
        assert link["period"] == "2025-12-31" and link["ids"] == [fid]


def test_a_measure_named_in_the_sentence_may_be_the_series_point_beside_it():
    """V33D: 'operating cash flow' named, the figure a point of that series, and the
    check compared the phrase against the sentence's scalars only."""
    assert ac.check("Amazon's operating cash flow was $140.0B [f_ocf001] beside a capex intensity of 18.4% [f_ciamzn].", _C_LEDGER).ok


# ── V33D ─────────────────────────────────────────────────────────────────────

_D_LEDGER = Ledger.of([
    *_C_LEDGER.by_id.values(),
    _f("f_hygret", "price.window_return", "HYG", 0.0107, node="ret1y", window="1y"),
    {**_f("f_ddhyg", "price.drawdown", "HYG", 0.0234, unit="RATIO", node="dd"), "window": {"start": "2026-02-20", "end": "2026-03-27"}},
    _f("f_divshare", "divide(dividends_paid, operating_cash_flow)", "AMZN", 0.12, node="div_share"),
])


def test_a_bare_integer_is_not_a_percentage():
    """V33D Q18: '1y window return' rendered as '1.07%y' — the 1 matched 0.0107."""
    v = ac.check("HYG's 1-year window return is 1.07% [f_hygret], and 2 episodes were found.", _D_LEDGER, question="two episodes?")
    assert v.ok, v.problems
    figures = [l for l in v.links.values() if l["to"] == "fact" and l.get("how") != "identity"]
    assert [l["as_written"] for l in figures] == ["1.07%"]
    assert "f_hygret" not in _D_LEDGER.resolve_number("1")
    assert _D_LEDGER.readings("1.07%") == [("f_hygret", None)]


def test_an_identity_link_keeps_the_words_as_written():
    """V33D Q19: 'in 2023' rendered as 'in $717B (2025-12-31)'; Q18: 'over 2026-02-20 to
    2026-03-27' rendered as 'over 2.34% to 2.34%'."""
    text = "HYG drew down 2.34% [f_ddhyg] over 2026-02-20 to 2026-03-27. Amazon's operating cash flow was $140.0B [f_ocf001] in 2025."
    v = ac.check(text, _D_LEDGER)
    assert v.ok, v.problems
    out = ac.accepted(text, v, _D_LEDGER)
    assert out["text"] == "HYG drew down 2.34% over 2026-02-20 to 2026-03-27. Amazon's operating cash flow was $140.0B in 2025."


def test_a_measure_phrase_may_name_an_operand_of_the_figure():
    """V33D Q03: 'dividends paid were 12% of operating cash flow' beside the share fact."""
    assert ac.check("Dividends paid took 12.0% [f_divshare] of operating cash flow.", _D_LEDGER).ok


def test_a_quotation_may_come_from_any_text_the_ledger_holds():
    """V33E: the desk's own words for what it could not do, and the question's own
    words, are texts of this turn and verbatim-checkable like a passage. V35: the
    domain is every text on the ledger — a boundary the broker minted included —
    not an enumeration of sources (round G refused the desk's own boundary words
    because they had been shown and never recorded)."""
    led = Ledger.of([*_C_LEDGER.by_id.values(),
                     {"id": "f_bnd001", "kind": "absence", "measure": "derive", "subject": "port_001", "unit": None,
                      "text": "'derive' is not a name this desk holds", "value": None, "as_of": "n/a", "window": None,
                      "params": {"reason": "cannot", "class": "boundary"}, "standalone": False, "sources": [], "group": "boundary"}])
    assert ac.check('The desk says it "does not compute liquidation days", so I give the inputs.', led).ok
    assert ac.check('The desk said "\'derive\' is not a name this desk holds", so the days figure is not here.', led).ok
    assert ac.check('You asked for "days to liquidate at 20% of ADV"; the desk does not hold it.', led,
                    question="days to liquidate at 20% of ADV, which names take longest").ok
    v = ac.check('The desk said "liquidation here is a matter of weeks".', led)
    assert {p["reason"] for p in v.problems} == {"unverified_quote"}


def test_a_figure_a_passage_states_resolves_through_the_passage():
    """V33E Q19 marked each segment revenue with the filing it came from and was
    refused 25 times. The passage states the figure; no pointer is needed."""
    led = Ledger.of([*_C_LEDGER.by_id.values(),
                     _passage("f_seg01", "AMZN", "Net sales: AWS 90,757 and 107,556 in the two years shown.")])
    assert ac.check("Amazon's filings show AWS net sales of $90,757.", led).ok
    v = ac.check("Amazon's filings show AWS net sales of $91,999.", led)
    assert {p["reason"] for p in v.problems} == {"unsourced_figure"}


# ── V34: the gate says what it checked, and a repair keeps what passed ───────

def test_every_sentence_is_labelled_checked_or_judgement():
    """V33F: 223 of 443 sentences in the round's answers held no figure at all and
    the gate had nothing to say about them — silently."""
    text = "MSFT weighs 16.0% [f_wmsft] of the book. The book looks concentrated to me."
    v = ac.check(text, LEDGER)
    assert v.ok, v.problems
    assert [x["tag"] for x in v.sentences] == ["S1", "S2"]
    assert [x["checked"] for x in v.sentences] == [True, False]
    out = ac.accepted(text, v, LEDGER)
    assert out["verified"]["sentences"] == {"checked": 1, "unchecked": 1,
                                            "judgement": ["The book looks concentrated to me."]}


def test_a_repair_replaces_only_the_sentences_it_names():
    text = "MSFT weighs 23.4% of the book. AAPL sits -3.89% [f_d52aapl] below its high. That is a concentrated book."
    v = ac.check(text, LEDGER)
    assert not v.ok and [x["tag"] for x in v.failed] == ["S1"]
    fixed = ac.repair(text, v, {"S1": "MSFT weighs 16.0% [f_wmsft] of the book."})
    assert fixed == "MSFT weighs 16.0% [f_wmsft] of the book. AAPL sits -3.89% [f_d52aapl] below its high. That is a concentrated book."
    assert ac.check(fixed, LEDGER).ok


def test_a_sentence_the_analyst_cannot_support_is_dropped():
    text = "MSFT weighs 23.4% of the book. AAPL sits -3.89% [f_d52aapl] below its high."
    v = ac.check(text, LEDGER)
    assert ac.repair(text, v, {"S1": ""}) == "AAPL sits -3.89% [f_d52aapl] below its high."


def test_a_superlative_is_a_lookup_on_the_figures_own_place():
    """V34 invariant B: a vector's entries carry their place the moment the desk
    builds them, so the check never scans and never guesses."""
    led = Ledger.of([
        _f("f_ci01", "capex_intensity", "MSFT", 0.2291, node="ci", place=1, of=3),
        _f("f_ci02", "capex_intensity", "GOOGL", 0.2210, node="ci", place=2, of=3),
        _f("f_ci03", "capex_intensity", "AMZN", 0.1839, node="ci", place=3, of=3),
    ])
    assert ac.check("Microsoft has the highest capex intensity at 22.9% [f_ci01].", led).ok
    assert ac.check("Amazon has the lowest capex intensity at 18.4% [f_ci03].", led).ok
    v = ac.check("Alphabet has the highest capex intensity at 22.1% [f_ci02].", led)
    assert "superlative_without_rank" in {p["reason"] for p in v.problems}


def test_invariant_C_a_repair_never_shrinks_the_accepted_set():
    """The property the sentence repair rests on: whatever the model sends back for
    the sentences that failed, the sentences that passed still pass."""
    text = ("MSFT weighs 23.4% of the book. AAPL sits -3.89% [f_d52aapl] below its high. "
            "NVDA weighs 99.9%. The book leans on its largest names.")
    v = ac.check(text, LEDGER)
    passed = {x["tag"] for x in v.sentences if not x["problems"]}
    assert {x["tag"] for x in v.failed} == {"S1", "S3"}
    for repl in ({"S1": "MSFT weighs 16.0% [f_wmsft] of the book.", "S3": ""},
                 {"S1": "", "S3": "NVDA weighs 4.06% [f_wnvda]."},
                 {"S1": "MSFT weighs 16.0% [f_wmsft].", "S3": "NVDA weighs 23.4% [f_wnvda]."}):
        after = ac.check(ac.repair(text, v, repl), LEDGER)
        still = {x["text"] for x in after.sentences if not x["problems"]}
        kept = {x["text"] for x in v.sentences if x["tag"] in passed}
        assert kept <= still, (repl, kept - still)


# ── V35 properties: identity is never inferred ───────────────────────────────

def test_property_no_bare_figure_the_ledger_holds_is_ever_accepted():
    """Whatever the sentence around it says — the subject named, the measure
    named, the date named — a bare figure the ledger holds is refused: the
    check does not infer which fact it meant."""
    for text in ("MSFT weighs 16.0% of the book.",
                 "MSFT's issuer_exposures weight is 16.0% as of 2026-09-10.",
                 "NVDA's warning tier is 15.0%.",
                 "On 2026-09-10 the NVDA check's warning level stood at 15.0%."):
        v = ac.check(text, LEDGER)
        assert not v.ok and {p["reason"] for p in v.problems} == {"unpointed_figure"}, (text, v.problems)


def test_property_a_pointed_figure_passes_or_fails_on_its_fact_alone():
    """The sentence's other words never decide a pointed figure's link: the same
    figure and id in three sentences link the same way."""
    for text in ("MSFT weighs 16.0% [f_wmsft].",
                 "It weighs 16.0% [f_wmsft].",
                 "AAPL, JPM and the rest aside, the book's largest line weighs 16.0% [f_wmsft]."):
        v = ac.check(text, LEDGER)
        links = [l for l in v.links.values() if l.get("how") != "identity"]
        assert links and links[0]["ids"] == ["f_wmsft"], (text, v.problems)


# ── V35 round H: the writer's natural shapes ─────────────────────────────────

def test_above_and_below_compare_and_claim_no_change():
    """Round H Q11 twice: "16.0% against a warning level of 15.0% … above warning"
    refused as a change between two quantities."""
    _accepted("MSFT is at 16.0% [f_curmsft] against a warning level of 15.0% [f_warnmsft], so it is already above warning.")
    _accepted("NVDA at 4.06% [f_wnvda] sits well below its 15.0% [f_warnnvda] warning tier.")
    _refused("MSFT rose from 15.0% [f_warnmsft] to 16.0% [f_curmsft].", "change_conflict")


def test_a_unit_word_may_sit_between_the_figure_and_its_bracket():
    """Round H Q11: "1.0 percentage point [f_…]" — the bracket was read as a word and
    the figure as bare. The pointer is read, and judged: the tier does not hold 1.0."""
    v = _refused("So it is already 1.0 percentage point [f_breachmsft] above warning.", "mark_mismatch")
    assert v.problems[0]["holds"] == "20.0%"
    led = Ledger.of([*LEDGER.by_id.values(), _f("f_dso00001", "days_sales_outstanding", "AAPL", 97.36, unit="COUNT", node="dso")])
    v = ac.check("AAPL's DSO is 97.36 days [f_dso00001] at the latest quarter.", led)
    assert v.ok, v.problems
    assert next(iter(v.links.values()))["ids"] == ["f_dso00001"]
    assert ac.accepted("AAPL's DSO is 97.36 days [f_dso00001].", ac.check("AAPL's DSO is 97.36 days [f_dso00001].", led), led)["text"] == "AAPL's DSO is 97.36 days."


def test_a_bracket_after_a_quotation_or_a_name_cites_that_fact():
    """Round H put eleven brackets after a quotation or a noun: a citation, no
    figure to check; the fact is on the ledger or the bracket is refused."""
    text = "Lilly says gross margin “increased 1.7 percentage points compared with 2024, primarily driven by favorable product mix.” [f_plly] That is all."
    v = _accepted(text)
    assert v.citations == ["f_plly"] and "f_plly" in v.refs
    out = ac.accepted(text, v, LEDGER)
    assert out["text"] == "Lilly says gross margin “increased 1.7 percentage points compared with 2024, primarily driven by favorable product mix.” That is all."
    assert "f_plly" in out["citations"]
    _accepted("AAPL's 10-K Item 7 passage [f_plly] discusses margins.")
    _refused("AAPL's 10-K Item 7 passage [f_nothere] discusses margins.", "not_on_ledger")
    _refused("A figure the bracket does not follow: 16.0% of the book [f_wmsft].", "unpointed_figure")


def test_the_punctuation_that_closes_the_writers_sentence_inside_the_marks_is_not_the_sources():
    """Round H: nine boundary quotations refused for a full stop inside the marks."""
    assert ac.check('The desk said "does not compute liquidation days." and stopped.', _C_LEDGER).ok
    assert ac.check('The desk said "does not compute liquidation days," and stopped.', _C_LEDGER).ok
    v = ac.check('The desk said "does not compute liquidation days for banks".', _C_LEDGER)
    assert {p["reason"] for p in v.problems} == {"unverified_quote"}


def test_a_quotation_keeps_its_thousands_separators_and_the_digests_escaped_newlines():
    """V33E/H Q19: 'AWS net sales $90,757 …' never verified — the ledger keeps a
    passage with separators dropped for the number lookup, and the digest shows a
    newline JSON-escaped, which the analyst copied as two characters."""
    led = Ledger.of([*_C_LEDGER.by_id.values(), _passage("f_seg01", "AMZN", "AWS\n\nNet sales$90,757 $107,556 $128,725\nOther")])
    assert ac.check("The AWS passage says “Net sales$90,757 $107,556 $128,725” in the table.", led).ok
    assert ac.check("The AWS passage says “AWS\\n\\nNet sales$90,757 $107,556 $128,725” in the table.", led).ok


def test_a_series_bracket_names_its_point():
    """Round H Q01: one value on two dates, both dates named in one sentence. The
    bracket the desk shows carries the date; a bare series bracket needs the
    date in the sentence, or is refused with the dated brackets to write."""
    flat = Ledger.of([*_C_LEDGER.by_id.values(),
                      {**_series("f_flat0001", "headcount", "AMZN", [["2023-12-31", 1.5e6], ["2025-12-31", 1.5e6]], unit="COUNT"), "params": {"node": "s_hc"}}])
    v = ac.check("Headcount was 1.50M [f_flat0001@2023-12-31] and 1.50M [f_flat0001@2025-12-31].", flat)
    assert v.ok, v.problems
    assert sorted(l["period"] for l in v.links.values()) == ["2023-12-31", "2025-12-31"]
    assert ac.accepted("Headcount was 1.50M [f_flat0001@2023-12-31].", ac.check("Headcount was 1.50M [f_flat0001@2023-12-31].", flat), flat)["text"] == "Headcount was 1.50M."
    v = ac.check("Headcount was 1.50M [f_flat0001] in 2023 and 1.50M [f_flat0001] in 2025.", flat)
    assert {p["reason"] for p in v.problems} == {"ambiguous_point"} and "[f_flat0001@2023-12-31]" in v.problems[0]["fix"]
    v = ac.check("Operating cash flow was $46.3B [f_ocf001@2025-12-31].", _C_LEDGER)
    assert [p["reason"] for p in v.problems] == ["mark_mismatch"] and "on 2025-12-31" in v.problems[0]["fix"]


def test_a_refusal_names_the_ids_the_desk_showed_the_figure_under():
    v = _refused("MSFT weighs 16.0% [f_nope] of the book.", "not_on_ledger")
    assert {c["id"] for c in v.problems[0]["candidates"]} >= {"f_wmsft", "f_curmsft"}
    v = _refused("MSFT weighs 16.0% [f_warnnvda] of the book.", "mark_mismatch")
    assert {c["id"] for c in v.problems[0]["candidates"]} >= {"f_wmsft"} and "f_warnnvda" not in {c["id"] for c in v.problems[0]["candidates"]}
    v = _refused("MSFT is the largest issuer concentration at 16.0% [f_curmsft].", "superlative_without_rank")
    assert [c["id"] for c in v.problems[0]["candidates"]] == ["f_rmsft"] and "[f_rmsft]" in v.problems[0]["fix"]


def test_a_filings_form_name_is_a_word_not_a_figure():
    _accepted("The 10-K and the 10-Q say little; see the DEF 14A.")


def test_a_figure_a_passage_states_may_point_at_the_passage():
    """Round I Q04/Q19: "$65,179 million [f_passage]" — the passage states it; the
    pointer is a lookup in that passage. A figure the passage does not state is
    a mismatch that says so."""
    led = Ledger.of([*_C_LEDGER.by_id.values(), _passage("f_seg01", "AMZN", "Net sales: AWS 90,757 and 107,556 in the two years shown.")])
    v = ac.check("AWS net sales were $107,556 [f_seg01] million in the later year.", led)
    assert v.ok, v.problems
    link = next(iter(v.links.values()))
    assert link["to"] == "passage" and link["ids"] == ["f_seg01"] and "f_seg01" in v.refs
    v = ac.check("AWS net sales were $91,999 [f_seg01] million.", led)
    assert [p["reason"] for p in v.problems] == ["mark_mismatch"] and v.problems[0]["holds"] == "passage"


def test_a_trajectory_naming_both_directions_is_not_judged_for_direction():
    """Round I Q03, twice: "went from 10.7% to 32.5%, then down to 3.81%, then back
    up to 5.05%" — the first two figures moved up, the sentence also says down."""
    led = Ledger.of([*_C_LEDGER.by_id.values(),
                     {**_series("f_cap0001", "capex_share", "NVDA", [["2023-01-29", 0.107], ["2024-01-28", 0.325], ["2025-01-26", 0.0381]]), "params": {"node": "s_cap"}}])
    v = ac.check("Capex share went from 10.7% [f_cap0001@2023-01-29] to 32.5% [f_cap0001@2024-01-28], then down to 3.81% [f_cap0001@2025-01-26].", led)
    assert v.ok, v.problems
    v = ac.check("Capex share fell from 10.7% [f_cap0001@2023-01-29] to 32.5% [f_cap0001@2024-01-28].", led)
    assert "direction_conflict" in {p["reason"] for p in v.problems}


def test_a_direction_verb_in_the_present_tense_is_read_too():
    """Round J accepted "Technology sector concentration falls to 35.3% from 35.0%":
    the reading rose between the two runs, and "falls" was not on the list."""
    led = Ledger.of([_f("f_techcur0", "limit_checks.current_value", "sector_concentration:Technology", 0.353, as_of="2026-09-10", node="cur"),
                     _f("f_techprv0", "limit_checks.current_value", "sector_concentration:Technology", 0.3498, as_of="2026-09-09", node="prev")])
    v = ac.check("Technology sector concentration falls to 35.3% [f_techcur0] from 35.0% [f_techprv0].", led)
    assert "direction_conflict" in {p["reason"] for p in v.problems}
    assert ac.check("Technology sector concentration rises to 35.3% [f_techcur0] from 35.0% [f_techprv0].", led).ok


# ── V37/V6: a date spelled out is a date ──────────────────────────────────────

def test_a_date_spelled_out_resolves_against_the_facts_own_date():
    """Round B refused six briefs for the day-of-month of a spelled date, two of
    them inside a quotation the check had already verified. "As of June 30, 2025"
    was read as the numbers 30 and 2025: the year resolved against a fact's
    as-of and the day was a figure no ledger could account for, so the same
    sentence was refused as an unsourced figure AND as a date word with no date
    after it.

    The day and the year are one identity field, so the finder reads them as one
    token and the check resolves it against the ISO form the facts carry. The
    spelling is the reader's; the identity is the fact's."""
    _accepted("The episode troughed on March 27, 2026 after a drawdown of 12.0% [f_depth1].")
    _accepted("The episode troughed on 27 March 2026.")
    _accepted("The episode troughed on 2026-03-27.")            # unchanged
    # a date word is answered by a date, whichever way it is written
    v = ac.check("The worst drawdown started on January 7, 2026.", LEDGER, None)
    assert v.ok, v.problems
    # and a figure in a date's slot is still a figure in a date's slot
    _refused("The worst drawdown started on 12.0% [f_depth1] and troughed on 2026-03-27.", "date_expected")


def test_a_date_no_fact_carries_is_refused_as_a_date_and_not_as_a_figure():
    """The three maturity dates round B wrote out of a 10-K's prose were refused
    — correctly, nothing on the ledger carries them — and told to "request the
    figure", which is not a thing anybody can do about a date. What it can do is
    quote the words that state it."""
    v = _refused("The notes mature on December 31, 2031.", "unsourced_figure")
    [p] = [p for p in v.problems if p["reason"] == "unsourced_figure"]
    assert p["figure"] == "December 31, 2031", "the whole date is named, not its day"
    assert "quote the words that state this one" in p["fix"] and "request the figure" not in p["fix"]


def test_a_month_without_a_day_and_a_year_is_prose():
    """Nothing to resolve and nothing to refuse: "through June and July" makes no
    claim a fact could settle, and a finder that called it a date would invent
    one."""
    _accepted("Operating cash flow ran through June and July at its usual seasonal shape.")


# ── V37/V4: the period a sentence claims is the period its readings have ──────

def test_a_sentence_that_names_a_period_its_readings_do_not_have_is_refused():
    """Round B's Q04 wrote "over the last twelve quarters" of five ANNUAL points
    and, in the same sentence, called them "the intervening annual points". The
    dates were in its own brackets. A series carries its points, so which period
    it has is a lookup, and the check compares two periods rather than judging
    one."""
    annual = Ledger.of([_series("f_lly5y", "net_margin", "LLY",
                                [["2021-12-31", .197], ["2022-12-31", .219], ["2023-12-31", .154],
                                 ["2024-12-31", .235], ["2025-12-31", .317]])])
    v = ac.check("Net margin over the last twelve quarters was 19.7% [f_lly5y@2021-12-31] "
                 "and 31.7% [f_lly5y@2025-12-31].", annual, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"period_mismatch"}
    assert ac.check("Net margin over the last five fiscal years was 19.7% [f_lly5y@2021-12-31] "
                    "and 31.7% [f_lly5y@2025-12-31].", annual, None).ok


def test_quarter_end_readings_are_not_three_years():
    """Q12's analyst wrote the truth into a caveat — "came back on quarter-end
    dates rather than three year-end dates" — and "over the last three years"
    into the finding, where the count matched by coincidence: three readings,
    three claimed years, six months of dates."""
    quarters = Ledger.of([_series("f_jpm3q", "equity_multiplier", "JPM",
                                  [["2025-09-30", 12.66], ["2025-12-31", 12.21], ["2026-03-31", 13.46]],
                                  unit="MULTIPLE")])
    v = ac.check("Its equity multiplier over the last three years was 12.66× [f_jpm3q@2025-09-30], "
                 "12.21× [f_jpm3q@2025-12-31], and 13.46× [f_jpm3q@2026-03-31].", quarters, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"period_mismatch"}
    assert ac.check("Its equity multiplier over the last three quarters was 12.66× [f_jpm3q@2025-09-30], "
                    "12.21× [f_jpm3q@2025-12-31], and 13.46× [f_jpm3q@2026-03-31].", quarters, None).ok


def test_a_span_claim_reads_how_far_the_readings_reach():
    """Q09 called a six-point annual series spanning five years "the three-year
    low and the three-year high". The hyphenated form claims a span and not a
    cadence — a "one-year beta" is a statistic over a year, not a yearly reading
    — so it is answered by how far the points reach."""
    five_years = Ledger.of([_series("f_ccc6y", "cash_conversion_cycle", "AAPL",
                                    [["2020-09-26", -60.87], ["2021-09-25", -56.36], ["2022-09-24", -70.52],
                                     ["2023-09-30", -67.83], ["2024-09-28", -75.83], ["2025-09-27", -71.07]],
                                    unit="COUNT")])
    v = ac.check("The cycle sits between the three-year low of -75.83 [f_ccc6y@2024-09-28] and the "
                 "three-year high of -56.36 [f_ccc6y@2021-09-25].", five_years, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"period_mismatch"}
    assert ac.check("The cycle sits between the five-year low of -75.83 [f_ccc6y@2024-09-28] and the "
                    "five-year high of -56.36 [f_ccc6y@2021-09-25].", five_years, None).ok


def test_a_relative_phrase_and_a_window_name_claim_no_period():
    """"One year earlier" says which series this is, not how it is spaced;
    "year-over-year" is a change; a period word beside a figure that is not a
    series point has no readings to be wrong about. Round B's Q02 put a relative
    phrase and a false claim in one sentence, and only the second is this rule's
    business."""
    annual = Ledger.of([_series("f_xom4y", "net_debt_to_ebitda", "XOM",
                                [["2022-12-31", -.05], ["2023-12-31", -.29], ["2024-12-31", -.38],
                                 ["2025-12-31", -.25]], unit="MULTIPLE")])
    assert ac.check("One year earlier the reading was -0.05× [f_xom4y@2022-12-31].", annual, None).ok
    assert ac.check("Receivables grew faster than revenue in the latest year-over-year comparison, "
                    "at -0.25× [f_xom4y@2025-12-31].", annual, None).ok
    # the same sentence with the claim round B actually wrote
    v = ac.check("One year earlier, the same four quarter-ends were -0.05× [f_xom4y@2022-12-31] "
                 "and -0.25× [f_xom4y@2025-12-31].", annual, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"period_mismatch"}
    # and with no series beside it a period word has no readings to be wrong
    # about: a scalar's window is its own parameter, and "the one-year figure" is
    # the measure's name rather than a claim about how often it was read
    assert ac.check("The one-year figure is 18.4% [f_ciamzn].", LEDGER, None).ok


def test_one_point_and_an_uneven_series_say_nothing_about_a_period():
    """A rule that fires on a guess refuses true sentences. One point has no
    spacing; gaps that are not one cadence have none either."""
    one = Ledger.of([_series("f_one1p", "revenue", "MSFT", [["2025-06-30", 1.0]], unit="MONEY")])
    assert ac.check("Revenue over the last four quarters was $1 [f_one1p@2025-06-30].", one, None).ok


def test_the_latest_year_end_names_a_date_and_not_a_cadence():
    """Round B's Q10 report wrote "net debt at $14.05B and $12.91B, indicating
    modest improvement into the latest year-end" over two QUARTERLY readings —
    and the second of them is Microsoft's fiscal year-end, so the sentence is
    true. A singular year-end names one date; "the four quarter-ends were …"
    claims a cadence. Measured on the round, not imagined: the wider rule refused
    this sentence twice."""
    quarterly = Ledger.of([_series("f_msftnd", "net_debt", "MSFT",
                                   [["2025-03-31", 14.05e9], ["2025-06-30", 12.91e9]], unit="MONEY")])
    assert ac.check("Net debt stood at $14.05B [f_msftnd@2025-03-31] and $12.91B [f_msftnd@2025-06-30], "
                    "the second of them the latest year-end.", quarterly, None).ok
    v = ac.check("The same two quarter-ends were $14.05B [f_msftnd@2025-03-31] and "
                 "$12.91B [f_msftnd@2025-06-30].", quarterly, None)
    assert v.ok, "two quarterly readings ARE two quarter-ends"


# ── V37/V1: a superlative with no figure beside it ────────────────────────────

def test_a_superlative_with_no_figure_is_checked_when_it_names_a_reading():
    """Round B's Q11 opened with "The closest issuer-concentration warning is for
    LLY." — no figure, so the sentence linked nothing, so the superlative rule did
    not run and the render counted it as the analyst's judgement. The desk had
    computed the ordering: LLY's room to warning is 19th of 20, which is the
    SECOND smallest, and fifty-one placed facts for LLY hold no end place at all.
    """
    led = Ledger.of([
        _f("f_roomlly", "subtract(limit_checks.warning_level, limit_checks.current_value)",
           "issuer_concentration:LLY", -0.0054, node="room_warning", op="subtract", place=19, of=20),
        _f("f_roommsft", "subtract(limit_checks.warning_level, limit_checks.current_value)",
           "issuer_concentration:MSFT", -0.0104, node="room_warning", op="subtract", place=20, of=20),
        _f("f_curlly2", "limit_checks.current_value", "issuer_concentration:LLY", 0.1254,
           node="current", place=8, of=20),
    ])
    v = ac.check("The closest issuer-concentration warning is for LLY.", led, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"superlative_without_rank"}
    # the subject that does hold the place passes, with no figure either
    assert ac.check("The closest issuer-concentration warning is for MSFT.", led, None).ok


def test_a_judgement_about_something_the_desk_does_not_order_is_still_a_judgement():
    """"The most important news is already in the tape for AAPL, LLY and GOOGL"
    names companies the desk holds placed facts for, and orders nothing that
    sentence is about. A rule that guessed an ordering would refuse the analyst's
    own reasoning, which is half of every answer."""
    led = Ledger.of([
        _f("f_waapl2", "issuer_exposures.weight", "AAPL", 0.152, node="w", place=2, of=10),
        _f("f_wlly2", "issuer_exposures.weight", "LLY", 0.125, node="w", place=4, of=10),
    ])
    assert ac.check("The most important news is already in the tape for AAPL and LLY.", led, None).ok
    assert ac.check("The best read is that nothing here forces a trade.", led, None).ok
    # but naming the reading brings the ordering back into it
    v = ac.check("The largest issuer exposures weight is LLY.", led, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"superlative_without_rank"}


def test_an_ordinal_before_a_superlative_names_its_own_place():
    """"The run also shows XOM as the 9th-largest issuer by weight" is a precise
    claim, and the desk's ordering puts XOM 9th of ten. Round B wrote two of
    these and both are true; a rule that reads only the superlative refuses
    them."""
    led = Ledger.of([
        _f("f_wxom9", "issuer_exposures.weight", "XOM", 0.0461, node="w", place=9, of=10),
        _f("f_wmsft1", "issuer_exposures.weight", "MSFT", 0.1604, node="w", place=1, of=10),
    ])
    assert ac.check("XOM is the 9th-largest issuer by weight at 4.61% [f_wxom9].", led, None).ok
    assert ac.check("MSFT is the largest issuer by weight at 16.0% [f_wmsft1].", led, None).ok
    # counted from the other end, and wrong either way
    assert ac.check("XOM is the second-smallest issuer by weight at 4.61% [f_wxom9].", led, None).ok
    v = ac.check("XOM is the 3rd-largest issuer by weight at 4.61% [f_wxom9].", led, None)
    assert not v.ok and {p["reason"] for p in v.problems} == {"superlative_without_rank"}


def test_a_superlative_mentioned_inside_something_else_is_not_predicated_of_a_subject():
    """Two shapes round B wrote, both refused by the wider rule and both fine:
    "I attempted to isolate the AMZN issuer concentration check … then determine
    the smallest-room concentration check" describes what was tried, and "The
    worst drawdown episode did have filings for AAPL, JPM, and LLY during the
    relevant window" says something about an episode. Neither asserts a place of
    the company it names."""
    led = Ledger.of([
        _f("f_curamzn2", "limit_checks.current_value", "issuer_concentration:AMZN", 0.0703,
           node="current", place=14, of=20),
        _f("f_retaapl2", "holdings.window_return", "AAPL", -0.12, node="by_name", place=4, of=10),
    ])
    assert ac.check("I attempted to isolate the AMZN issuer concentration check, then determine the "
                    "smallest-room concentration check.", led, None).ok
    assert ac.check("The worst drawdown episode did have filings for AAPL during the relevant window.",
                    led, None).ok
