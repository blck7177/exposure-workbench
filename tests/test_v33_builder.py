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


def test_a_change_without_a_history_is_not_expressible():
    with pytest.raises(pb.NotExpressible):
        pb.build({"subjects": ["MSFT"], "want": ["net_margin"], "compare": "change"})


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
