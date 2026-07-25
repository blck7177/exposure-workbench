"""Security-master universe provider parsing (V2-D, offline).

Fixtures mirror the real NASDAQ Trader pipe files + SEC json. Covers the sharp
edges: Test-Issue rows dropped, the 'File Creation Time' trailer dropped, BRK.A's
dot preserved, ETF flag, exchange-code mapping, and CIK enrichment.
"""

from __future__ import annotations

from exposure_workbench.providers import security_master_provider as smp

_NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N
ZAZZT|Nasdaq Test Stock|G|Y|N|100|N|N
File Creation Time: 0724202615:41|||||||
"""

_OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.A|Berkshire Hathaway Inc. Common Stock|N|BRK.A|N|1|N|BRK.A
TLT|iShares 20+ Year Treasury Bond ETF|Z|TLT|Y|100|N|TLT
TESTX|NYSE Test|N|TESTX|N|100|Y|TESTX
File Creation Time: 0724202615:41||||||
"""

_SEC = '{"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."},"1":{"cik_str":886982,"ticker":"QQQ","title":"x"}}'


def test_parse_nasdaq_drops_test_and_trailer():
    rows = smp._parse_pipe(_NASDAQ, "Symbol")
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"AAPL", "QQQ"}          # ZAZZT (Test Issue) + trailer dropped
    etf = {r["ticker"]: r["is_etf"] for r in rows}
    assert etf["QQQ"] is True and etf["AAPL"] is False


def test_parse_other_preserves_dot_and_maps_exchange():
    rows = smp._parse_pipe(_OTHER, "ACT Symbol")
    by = {r["ticker"]: r for r in rows}
    assert "BRK.A" in by                        # dot preserved, not BRK-A
    assert "TESTX" not in by                     # Test Issue dropped
    assert by["TLT"]["is_etf"] is True
    assert by["BRK.A"]["exchange_code"] == "N"


def test_cik_map():
    m = smp._cik_map(_SEC)
    assert m["AAPL"] == "0000320193"            # zero-padded to 10
    assert m["QQQ"] == "0000886982"


def test_fetch_universe_merges_dedups_enriches(monkeypatch):
    def fake_get(client, url, headers=None):
        if "nasdaqlisted" in url:
            return _NASDAQ
        if "otherlisted" in url:
            return _OTHER
        return _SEC
    monkeypatch.setattr(smp, "_get", fake_get)
    universe = {s.ticker: s for s in smp.fetch_universe()}
    assert set(universe) == {"AAPL", "QQQ", "BRK.A", "TLT"}
    assert universe["AAPL"].cik == "0000320193"          # enriched
    assert universe["BRK.A"].cik is None                  # SEC uses dash form; no match, OK
    assert universe["AAPL"].exchange == "NASDAQ"
    assert universe["BRK.A"].exchange == "NYSE"           # code N -> NYSE
    assert universe["TLT"].is_etf is True


def test_fetch_universe_fails_loud_on_bad_source(monkeypatch):
    def boom(client, url, headers=None):
        raise smp.UniverseFetchError("network down")
    monkeypatch.setattr(smp, "_get", boom)
    import pytest
    with pytest.raises(smp.UniverseFetchError):
        smp.fetch_universe()
