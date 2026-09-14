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


def test_an_id_anywhere_but_after_its_figure_is_a_word_the_reader_must_not_see():
    _refused("MSFT weighs f_wmsft of the book.", "id_in_prose")
    v = _refused("The tier [f_warnnvda] is 15.0%.", "id_in_prose")
    assert "unpointed_figure" in {p["reason"] for p in v.problems}


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
