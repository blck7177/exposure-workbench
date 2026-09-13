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
    _refused("Selling half of NVDA lowers gross exposure from $10.63M to 100.0%.", "unit_conflict")
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

def test_a_linked_number_is_rendered_as_the_ledgers_fact():
    text = "MSFT weighs 16.0% of the book [f_wmsft]; the warning tier is 15.0% [f_warnmsft]."
    v = _accepted(text)
    out = ac.accepted(text, v, LEDGER)
    runs = out["blocks"][0]["runs"]
    facts = [r["fact"] for r in runs if isinstance(r, dict) and "fact" in r]
    assert [f["id"] for f in facts] == ["f_wmsft", "f_warnmsft"]
    assert "[f_" not in out["text"] and "16.0%" in out["text"]
    assert out["verified"]["figures"] == 2 and set(out["citations"]) == {"f_wmsft", "f_warnmsft"}


def test_all_problems_are_reported_at_once():
    v = ac.check("MSFT weighs 23.4%. AAPL sits -5.83% below its high. The drawdown started on 12.0%.", LEDGER)
    reasons = [p["reason"] for p in v.problems]
    assert {"unsourced_figure", "subject_mismatch", "date_expected"} <= set(reasons)
    assert v.detail.startswith("3 problem(s)") or v.detail.startswith(f"{len(v.problems)} problem(s)")
