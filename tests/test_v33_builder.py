"""V33 Phase 3 — the program builder compiles decision-level requests (offline)."""
from __future__ import annotations

import pytest

from exposure_workbench.services import program_builder as pb, program_service as ps


def _ok(item):
    prog = pb.build(item)
    assert ps.typecheck(prog) == [], prog
    return prog


def _names(prog):
    return [b["name"] for b in prog["let"]]


def test_several_subjects_over_a_history_become_series_latest_vector_rank():
    prog = _ok({"subjects": ["MSFT", "GOOGL", "AMZN"], "want": ["capex_intensity", "roic"], "window": "last 3 fiscal years", "compare": "rank"})
    names = _names(prog)
    assert "capex_intensity_latest_ranked" in names and "roic_latest_ranked" in names
    assert any(b["expr"]["fn"] == "latest" for b in prog["let"])
    assert all(b["expr"].get("params", {}).get("last_n") == 3 for b in prog["let"] if b["expr"]["fn"] == "method")


def test_a_threshold_is_a_filter_over_the_book_column():
    prog = _ok({"subjects": ["port_001"], "want": ["issuer_exposures.weight"], "compare": "filter:>0.08"})
    f = [b for b in prog["let"] if b["expr"]["fn"] == "filter"][0]["expr"]
    assert (f["op"], f["level"]) == (">", 0.08)


def test_vs_prev_run_is_a_difference_of_two_columns():
    prog = _ok({"subjects": ["port_001"], "want": ["issuer_exposures.weight"], "window": "vs prev run", "compare": "rank"})
    names = _names(prog)
    assert "issuer_exposures_weight_change" in names and "issuer_exposures_weight_change_ranked" in names
    assert any(b["expr"].get("which") == "prev" for b in prog["let"])


def test_a_scenario_reads_before_and_after():
    prog = _ok({"subjects": ["port_001"], "want": ["scenario:sell NVDA 0.5", "sector_exposures.weight", "exposure_metrics.gross_exposure"]})
    names = _names(prog)
    assert "after_sell_nvda" in names and "sector_exposures_weight_after" in names and "sector_exposures_weight_before" in names
    sell = [b for b in prog["let"] if b["expr"]["fn"] == "sell"][0]["expr"]
    assert sell["sales"] == [{"ticker": "NVDA", "fraction": 0.5}]


def test_share_of_divides_each_want_by_the_named_line():
    prog = _ok({"subjects": ["NVDA"], "want": ["capex", "buybacks"], "window": "12m", "compare": "share_of:operating_cash_flow"})
    divs = [b for b in prog["let"] if b["expr"]["fn"] == "div"]
    assert len(divs) == 2 and all(d["expr"]["b"] == "$operating_cash_flow_nvda" for d in divs)


def test_price_methods_take_their_windows_and_benchmark():
    prog = _ok({"subjects": ["JPM"], "want": ["price.volatility", "price.beta", "price.window_return"], "window": "30d 1y vs SPY"})
    by = {b["name"]: b["expr"] for b in prog["let"]}
    assert by["price_volatility_jpm"]["params"] == {"window_days": 30}
    assert by["price_beta_jpm"]["params"] == {"window": "1y", "benchmark": "SPY"} and by["price_beta_jpm"]["key"] == "beta"
    assert by["price_window_return_jpm"]["params"] == {"window": "1y", "benchmark": "SPY"}


def test_the_user_participation_rate_is_the_programs_not_an_examples():
    """Q15: the example program in the skill scales ADV by 0.25 and the model kept
    it when the user said 20%. The builder writes the request's number."""
    prog = _ok({"subjects": ["port_001", "AAPL", "JPM"], "want": ["issuer_exposures.market_value", "price.adv"], "window": "20d"})
    adv = [b for b in prog["let"] if b["expr"]["fn"] == "method"][0]["expr"]
    assert adv["params"] == {"window_days": 20} and adv["key"] == "dollars"
    assert "0.25" not in str(prog)


def test_a_name_the_desk_does_not_hold_is_not_expressible_with_the_nearest():
    with pytest.raises(pb.NotExpressible) as e:
        pb.build({"subjects": ["MSFT"], "want": ["gross_margn"]})
    assert "gross_margin" in e.value.nearest


def test_a_comparison_the_request_cannot_support_costs_the_comparison_only():
    """V33C Q15 named one unknown line beside two it knew and lost the whole item,
    `compare: rank` included; the answer then had no ordering for its superlatives."""
    skipped = []
    prog = pb.build({"subjects": ["MSFT"], "want": ["net_margin"], "compare": "change"}, skipped=skipped)
    assert ps.typecheck(prog) == [] and any(b["expr"].get("name") == "net_margin" for b in prog["let"])
    assert [x["want"] for x in skipped] == ["compare:change"] and "history" in skipped[0]["reason"]


def test_a_name_the_desk_does_not_hold_costs_that_name_and_nothing_else():
    skipped = []
    prog = pb.build({"subjects": ["port_001"],
                     "want": ["issuer_exposures.market_value", "issuer_exposures.ticker", "issuer_exposures.weight"],
                     "compare": "rank"}, skipped=skipped)
    assert ps.typecheck(prog) == []
    assert [x["want"] for x in skipped] == ["issuer_exposures.ticker"]
    assert sum(1 for b in prog["let"] if b["expr"]["fn"] == "rank") == 2, "the ordering the analyst asked for survives"


def test_nothing_expressible_is_still_not_expressible():
    with pytest.raises(pb.NotExpressible):
        pb.build({"subjects": ["MSFT"], "want": ["no_such_line"]})


def test_a_derivation_is_arithmetic_over_the_names_the_request_asked_for():
    """V33C Q11 asked for the four limit columns and said 'the room to warning' in
    `ask`; the room was the analyst's own subtraction in prose, and refused."""
    prog = _ok({"subjects": ["port_001"],
                "want": ["limit_checks.current_value", "limit_checks.warning_level"],
                "derive": ["limit_checks.warning_level - limit_checks.current_value"]})
    (room,) = [b for b in prog["let"] if b["expr"]["fn"] == "sub"]
    assert room["expr"]["a"] == "$limit_checks_warning_level" and room["expr"]["b"] == "$limit_checks_current_value"
    assert room["name"] in prog["return"]


def test_a_derivation_may_scale_by_a_number_and_an_unknown_name_is_reported():
    skipped = []
    prog = pb.build({"subjects": ["port_001"], "want": ["issuer_exposures.market_value"],
                     "derive": ["issuer_exposures.market_value * 0.2", "price.adv / nonsense"]}, skipped=skipped)
    assert ps.typecheck(prog) == []
    assert any(b["expr"]["fn"] == "mul" and b["expr"]["b"] == 0.2 for b in prog["let"])
    assert [x["want"] for x in skipped] == ["derive:price.adv / nonsense"]


@pytest.mark.parametrize("text,expect", [
    ("last 8 quarters", {"last_n": 8, "months": 3}),
    ("last 5 years", {"last_n": 5, "months": 12}),
    ("12m", {"months": 12}),
    ("at 2025-06-30", {"at": "2025-06-30"}),
    ("1y vs SPY", {"span": "1y", "benchmark": "SPY"}),
    ("vs prev run", {"vs_prev": True}),
    ("two weeks", {"days": 14}),
])
def test_windows_parse(text, expect):
    w = pb.parse_window(text)
    for k, v in expect.items():
        assert getattr(w, k) == v, (text, k, getattr(w, k))


# ── V33C ─────────────────────────────────────────────────────────────────────

def test_a_name_written_with_its_domain_is_the_method():
    prog = _ok({"subjects": ["JPM", "BAC"], "want": ["issuer_profitability: roe"], "window": "last 3 years", "compare": "rank"})
    assert any(b["expr"].get("name") == "roe" for b in prog["let"])


def test_a_book_want_with_only_a_ticker_reads_the_book_that_holds_it():
    item = {"subjects": ["AMZN"], "want": ["issuer_exposures.weight", "limit_checks.current_value"]}
    with pytest.raises(pb.NotExpressible) as e:
        pb.build(item)
    assert "held_in" in str(e.value.reason)
    prog = pb.build(item, held_in={"AMZN": ["port_001"]})
    assert ps.typecheck(prog) == []
    runs = [b["expr"] for b in prog["let"] if b["expr"]["fn"] == "run"]
    assert runs == [{"fn": "run", "portfolio": "port_001"}]


def test_a_filings_want_is_not_a_program():
    with pytest.raises(pb.NotExpressible) as e:
        pb.build({"subjects": ["LLY"], "want": ["filings:Item 7"]})
    assert "tools" in e.value.reason


# ── V35: a derivation may be named, and a later line may use the name ────────

_HELD = {"MSFT": ["port_001"], "AAPL": ["port_001"]}


def test_a_derivation_may_be_named_and_a_later_line_may_use_the_name():
    """Round G Q15: days to liquidate at 20% of ADV is mv / (adv × 0.2) — two
    operators, which one line cannot say. A named line, used by the next, can."""
    prog = pb.build({"subjects": ["port_001", "MSFT", "AAPL"], "want": ["issuer_exposures.market_value", "price.adv"],
                     "window": "20d", "derive": ["adv20 = price.adv * 0.2", "days = issuer_exposures.market_value / adv20"]},
                    held_in=_HELD, skipped=[])
    by = {b["name"]: b["expr"] for b in prog["let"]}
    assert by["adv20"]["fn"] == "mul" and by["adv20"]["b"] == 0.2
    assert by["days"]["fn"] == "div" and by["days"]["b"] == "$adv20"
    assert "days" in prog["return"]
    assert ps.typecheck(prog) == []


def test_the_name_before_the_equals_is_the_lines_name_not_an_operand():
    """Round G Q11 wrote `room_to_warning = a - b` and the whole left side was read
    as an operand; the room was then the analyst's own subtraction, refused."""
    skipped = []
    prog = pb.build({"subjects": ["port_001"], "want": ["limit_checks.current_value", "limit_checks.warning_level"],
                     "derive": ["room_to_warning = limit_checks.warning_level - limit_checks.current_value"]}, skipped=skipped)
    assert skipped == []
    (room,) = [b for b in prog["let"] if b["expr"]["fn"] == "sub"]
    assert room["name"] == "room_to_warning" and room["expr"]["a"] == "$limit_checks_warning_level"


def test_a_derivation_is_an_expression_with_parentheses_and_the_line_carries_its_name():
    """Round H Q15 wrote `days = mv / (adv * 0.2)`; the inner operation is a binding
    of its own, not returned; the outer one carries the line's name."""
    prog = pb.build({"subjects": ["port_001", "MSFT", "AAPL"], "want": ["issuer_exposures.market_value", "price.adv"], "window": "20d",
                     "derive": ["days = issuer_exposures.market_value / (price.adv * 0.2)"]}, held_in=_HELD, skipped=[])
    by = {b["name"]: b["expr"] for b in prog["let"]}
    assert by["days"]["fn"] == "div" and by["days"]["b"] == "$days_1"
    assert by["days_1"] == {"fn": "mul", "a": "$price_adv", "b": 0.2}
    assert "days" in prog["return"] and "days_1" not in prog["return"]
    assert ps.typecheck(prog) == []
    three = pb.build({"subjects": ["port_001"], "want": ["limit_checks.current_value", "limit_checks.warning_level", "limit_checks.breach_level"],
                      "derive": ["limit_checks.breach_level - limit_checks.current_value + limit_checks.warning_level * 2"]}, skipped=[])
    assert ps.typecheck(three) == [] and sum(1 for b in three["let"] if b["expr"]["fn"] in ("add", "sub", "mul")) == 3


def test_a_derivation_that_cannot_be_read_is_skipped_and_says_where():
    skipped = []
    pb.build({"subjects": ["port_001"], "want": ["limit_checks.current_value"],
              "derive": ["limit_checks.current_value / (nonsense", "limit_checks.current_value"]}, skipped=skipped)
    assert [x["want"] for x in skipped] == ["derive:limit_checks.current_value / (nonsense", "derive:limit_checks.current_value"]
    assert "nonsense" in skipped[0]["reason"] and "operator" in skipped[1]["reason"]


def test_a_window_with_words_the_desk_does_not_read_is_said_not_trimmed():
    """Round H Q02: "same 4 quarters a year earlier" was read as the last 4 quarters,
    the desk returned the same series twice, and the analyst wrote that a year
    earlier the sequence was the same — a falsehood no check can see."""
    assert pb.unreadable_window("same 4 quarters a year earlier") == "same earlier"
    for ok in ("last 8 quarters", "last 5 years", "12m", "at 2025-06-30", "1y vs SPY", "vs prev run", "two weeks", "latest", "20d",
               "as of 2026-09-10", "trailing twelve months", "last 4 quarters ended 2025-12-31", "the latest run"):
        assert pb.unreadable_window(ok) is None, ok
    skipped = []
    with pytest.raises(pb.NotExpressible) as exc:
        pb.build({"subjects": ["XOM"], "want": ["net_debt_to_ebitda"], "window": "same 4 quarters a year earlier"}, skipped=skipped)
    assert "same earlier" in exc.value.reason and "at YYYY-MM-DD" in exc.value.reason
    assert pb.parse_window("last 4 quarters ended 2025-12-31").at == "2025-12-31"
