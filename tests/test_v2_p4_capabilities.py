"""V2 P4 (design v0.4 §09): the capabilities the plan could settle without round E —
a trade funded from its own sales (Q13), a typed-in constant that says whose it is,
a series row that names its filings, a name's rows that name their book, the days
convention said where the measure is read, and a revenue share told apart from a
share of the return. Offline.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import handbook, registry, scenario as sc
from exposure_workbench.services import facts as F, fact_adapters as fa
from exposure_workbench.tools import primitives as P

H = [sc.Holding("MSFT", "Technology", 1600.0), sc.Holding("TLT", "Fixed Income", 400.0), sc.Holding("AAPL", "Technology", 2000.0)]
SELL_HALF_MSFT = ("sell", [sc.Sale("MSFT", 0.5)])


def test_outside_money_is_the_engine_as_it_was():
    refused = sc.traded(H, [SELL_HALF_MSFT, ("buy", [sc.Buy("TLT", 0.25, "Fixed Income")])])
    assert refused["error"] == "already_held" and "fund the purchase from the sales' proceeds" in refused["detail"]
    book = sc.traded(H, [SELL_HALF_MSFT, ("buy", [sc.Buy("NVDA", 0.25, "Technology")])])
    assert round(book.weights["NVDA"], 6) == 0.25 and round(book.proceeds, 2) == round(800.0 - 3200.0 / 3, 2)


def test_proceeds_fund_the_purchases_and_a_held_name_is_added_to():
    book = sc.traded(H, [SELL_HALF_MSFT, ("buy", [sc.Buy("TLT", 0.25)])], funding="proceeds")
    assert not isinstance(book, dict), book
    assert round(book.market_value, 2) == round(2800.0 / 0.75, 2)            # (T0 − P − existing) ÷ (1 − w)
    assert round(book.weights["TLT"], 6) == 0.25
    tlt = next(h for h in book.holdings if h.ticker == "TLT")
    assert round(tlt.market_value, 2) == round(400.0 + 533.33, 2) and tlt.sector == "Fixed Income"
    assert [b.ticker for b in book.bought] == ["TLT"] and round(book.bought[0].market_value_added, 2) == 533.33
    assert round(book.proceeds, 2) == 266.67, "what the sales freed and the purchase did not spend leaves the book"
    assert abs(sum(book.weights.values()) - 1.0) < 1e-9


def test_the_sales_must_cover_the_purchases_and_a_purchase_only_adds():
    short = sc.traded(H, [SELL_HALF_MSFT, ("buy", [sc.Buy("TLT", 0.6)])], funding="proceeds")
    assert short["error"] == "insufficient_proceeds" and "sell more, or buy less" in short["detail"]
    above = sc.traded(H, [SELL_HALF_MSFT, ("buy", [sc.Buy("TLT", 0.10)])], funding="proceeds")
    assert above["error"] == "already_above_target"
    assert sc.traded(H, [SELL_HALF_MSFT], funding="loan")["error"] == "bad_funding"
    assert P._tools("risk")["scenario"].json_schema["properties"]["funding"]["enum"] == ["external", "proceeds", None]


def test_a_typed_in_constant_says_whose_it_is():
    assert P._constant_source("scale", 0.15, None, None)["error"] == "invalid_params"
    assert P._constant_source("scale", 0.15, None, "user_assumption") == {}
    assert P._constant_source("filter", None, "8%", None)["error"] == "invalid_params"
    assert P._constant_source("filter", None, "f_abc123456789", None) is None, "an id is a row, not a typed number"
    assert P._constant_source("add", None, None, None) is None
    assert registry.words_beside({"constant_source": "method_constant", "value": 1})["basis"] == ["method_constant"]
    assert registry.validate_means({"basis": ["user_assumption"]}) == {"basis": ["user_assumption"]}
    assert P._tools("issuer")["calc"].json_schema["properties"]["source"]["enum"] == ["user_assumption", "method_constant", None]


def test_a_series_row_names_the_filings_it_was_read_from():
    facts, _note = fa.read_fundamentals(
        {"ticker": "MSFT", "line": "revenue"},
        {"ticker": "MSFT", "metric": "revenue", "as_of": "2025-06-30", "unit_class": "money",
         "points": [{"period_end": "2024-06-30", "value": 245.1e9}, {"period_end": "2025-06-30", "value": 281.7e9}],
         "accessions": ["0000789019-24-000012", "0000789019-25-000014"]})
    series = next(f for f in facts if f.kind == F.SERIES)
    assert series.params["filed_in"] == ["0000789019-24-000012", "0000789019-25-000014"]
    assert "filed 0000789019-24-000012 and 1 more" in F.line(series)


def test_a_names_rows_in_a_book_say_which_book():
    facts, _note = fa.compute(
        {"name": "book.position", "subject": "MSFT"},
        {"subject": "MSFT", "ticker": "MSFT", "run_id": "run_x", "portfolio_id": "port_001", "as_of": "2026-09-10",
         "position": {"weight": {"value": 0.16, "ref": "run_x", "quantity": "issuer_exposures.weight", "unit_class": "ratio",
                                 "as_of": "2026-09-10"}},
         "checks": []})
    weight = next(f for f in facts if f.kind == F.SCALAR)
    assert weight.params["book"] == "run_x" and F.line(weight).endswith("on run_x")


def test_the_days_convention_and_the_revenue_share_sentence_are_in_the_handbook():
    issuer = handbook.chapter_text("issuer")
    assert "a full year's for twelve months, a quarter's for three" in issuer
    assert "a share of revenue is not a share of the return" in handbook.chapter_text("risk")
    assert "days" in registry.reads_as("days_sales_outstanding").lower()
