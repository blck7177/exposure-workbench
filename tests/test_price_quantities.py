"""V16 Lane C — price quantities: two prices, named estimators, typed rows (offline).

Synthetic bars, constructed rather than sampled: an estimator is judged by
whether it reproduces a value the test can derive independently, and a real
series has no independently known answer. The DB is a fake that captures what
cs._record adds — the recording path itself is REAL, so these tests also pin
that every row this lane mints survives calc_service's V16 rule (a numeric
result must state its unit and name its quantity, or _record raises).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from exposure_workbench.analytics import units as u
from exposure_workbench.analytics.units import POINT_PERIOD_KEY
from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import price_analytics_service as pas


class FakeDb:
    """add/flush/get — everything cs._record and regress() ask of a session."""

    def __init__(self):
        self.rows: list[CalcLedger] = []

    def add(self, row):
        self.rows.append(row)

    async def flush(self):
        pass

    async def get(self, model, pk):
        for r in self.rows:
            if isinstance(r, model) and r.id == pk:
                return r
        return None

    def ops(self, prefix=""):
        return [r for r in self.rows if r.operation.startswith(prefix)]


def weekdays(n: int, start: date = date(2025, 1, 6)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_bars(adj: list[float], close: list[float] | None = None,
              volumes: list[int | None] | None = None,
              start: date = date(2025, 1, 6)) -> list[pas.Bar]:
    dates = weekdays(len(adj), start)
    close = close or adj
    volumes = volumes or [None] * len(adj)
    return [pas.Bar(d, c, a, v) for d, c, a, v in zip(dates, close, adj, volumes)]


def install_bars(monkeypatch, by_ticker: dict[str, list[pas.Bar]]):
    async def _bars(_db, ticker, start=None, end=None):
        bars = by_ticker.get(ticker, [])
        return [b for b in bars
                if (start is None or b.date >= start) and (end is None or b.date <= end)]

    async def _market_bars(_db, ticker):
        return list(by_ticker.get(ticker, []))

    monkeypatch.setattr(pas, "_bars", _bars)
    monkeypatch.setattr(pas, "_market_bars", _market_bars)


# ── two prices, two names ─────────────────────────────────────────────────────

async def test_close_and_adj_close_are_two_named_quantities_in_two_rows(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"AAPL": make_bars([9.0, 10.0, 11.0], close=[10.0, 11.0, 12.0])})
    out = await pas.get_price(db, "aapl")
    assert out["close"]["value"] == 12.0
    assert out["adj_close"]["value"] == 11.0
    assert out["close"]["quantity"] == "AAPL.close"
    assert out["adj_close"]["quantity"] == "AAPL.adj_close"
    assert out["close"]["calc_id"] != out["adj_close"]["calc_id"], (
        "two quantities, two rows — an answer cites the one it used")
    for row in db.ops("price.point"):
        rt = row.params["result_type"]
        assert rt["unit_class"] == u.MONEY_PER_SHARE
        assert row.unit_class == "MONEY_PER_SHARE"


async def test_as_of_picks_the_last_session_on_or_before_the_date(monkeypatch):
    db = FakeDb()
    bars = make_bars([9.0, 10.0, 11.0], close=[10.0, 11.0, 12.0])
    install_bars(monkeypatch, {"AAPL": bars})
    out = await pas.get_price(db, "AAPL", as_of=bars[1].date.isoformat())
    assert out["close"]["value"] == 11.0
    assert out["adj_close"]["value"] == 10.0
    assert out["as_of"] == bars[1].date.isoformat()


# ── the series ────────────────────────────────────────────────────────────────

async def test_price_series_is_adj_close_keyed_by_the_one_period_key(monkeypatch):
    db = FakeDb()
    bars = make_bars([9.0, 10.0, 11.0], close=[10.0, 11.0, 12.0])
    install_bars(monkeypatch, {"AAPL": bars})
    out = await pas.get_price_series(db, "AAPL", window="3m")
    assert out["n"] == 3
    assert [p["value"] for p in out["points"]] == [9.0, 10.0, 11.0], (
        "the series is the ADJUSTED level, never close")
    for p in out["points"]:
        assert POINT_PERIOD_KEY in p
        assert "end" not in p and "as_of" not in p, "writers use one key (V16)"
    row = db.ops("price.series")[0]
    assert row.params["result_type"] == {
        "unit_class": u.MONEY_PER_SHARE, "kind": "series", "quantity": "AAPL.adj_close"}


async def test_an_unknown_window_is_named_with_the_known_set(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"AAPL": make_bars([1.0, 2.0])})
    out = await pas.get_price_series(db, "AAPL", window="37d")
    assert out["error"] == "unknown_window"
    assert "1y" in out["known"]


# ── volatility, checked by hand ───────────────────────────────────────────────

def _vol_prices() -> list[float]:
    rets = [0.011, -0.007, 0.019, -0.013, 0.002, 0.008, -0.021, 0.004,
            0.016, -0.009, 0.001, 0.012, -0.005, 0.023, -0.017, 0.006,
            -0.002, 0.009, -0.011, 0.014, 0.003, -0.008, 0.018, -0.004]
    prices = [100.0]
    for r in rets:
        prices.append(prices[-1] * (1.0 + r))
    return prices


async def test_rolling_volatility_matches_the_hand_computation(monkeypatch):
    db = FakeDb()
    prices = _vol_prices()
    install_bars(monkeypatch, {"MSFT": make_bars(prices)})
    out = await pas.rolling_volatility(db, "MSFT", window_days=20)
    # Independently: last 20 simple returns, sample std (ddof=1), × √252.
    rets = [prices[i + 1] / prices[i] - 1.0 for i in range(len(prices) - 1)][-20:]
    mean = sum(rets) / 20
    expected = math.sqrt(sum((r - mean) ** 2 for r in rets) / 19) * math.sqrt(252)
    assert out["value"] == pytest.approx(expected, rel=1e-12)
    assert out["n"] == 20
    assert out["quantity"] == "MSFT.vol.20d"
    assert out["unit_class"] == u.RATIO
    row = db.ops("price.vol")[0]
    assert row.result["quality_flags"]["n"] == 20
    assert row.unit_class == "RATIO"


# ── beta, on a constructed linear relation ────────────────────────────────────

def _linear_pair(n_prices: int = 70, beta: float = 1.5, alpha: float = 0.0005):
    x_rets = [0.001 * ((i % 7) - 3) for i in range(n_prices - 1)]
    y_rets = [alpha + beta * r for r in x_rets]
    px, py = [100.0], [50.0]
    for rx, ry in zip(x_rets, y_rets):
        px.append(px[-1] * (1.0 + rx))
        py.append(py[-1] * (1.0 + ry))
    return px, py


async def test_beta_recovers_the_constructed_slope_intercept_and_r2(monkeypatch):
    db = FakeDb()
    px, py = _linear_pair()
    install_bars(monkeypatch, {"SPY": make_bars(px), "NVDA": make_bars(py)})
    out = await pas.beta(db, "NVDA", benchmark="SPY")
    assert out["beta"]["value"] == pytest.approx(1.5, abs=1e-9)
    assert out["alpha"]["value"] == pytest.approx(0.0005, abs=1e-9)
    assert out["r2"]["value"] == pytest.approx(1.0, abs=1e-9)
    assert out["n"] == 69
    assert out["beta"]["quantity"] == "NVDA.beta.SPY"
    assert out["alpha"]["quantity"] == "NVDA.alpha.SPY"
    assert out["r2"]["quantity"] == "NVDA.r2.SPY"
    assert {out["beta"]["calc_id"], out["alpha"]["calc_id"], out["r2"]["calc_id"]} <= {
        r.id for r in db.ops("price.regress.")}, "each estimate is its own citable row"
    # The fit's inputs are ledgered return series, cited as input_refs.
    beta_row = next(r for r in db.rows if r.id == out["beta"]["calc_id"])
    assert set(beta_row.input_refs) == set(out["returns_series"].values())


async def test_beta_of_a_ticker_against_itself_is_refused(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"SPY": make_bars(_linear_pair()[0])})
    out = await pas.beta(db, "SPY", benchmark="SPY")
    assert out["error"] == "self_regression"


# ── the generic regression primitive ──────────────────────────────────────────

async def _mint_series(db, quantity: str, points: list[tuple[date, float]]) -> str:
    return await cs._record(
        db, None, "price.returns.series",
        {"result_type": {"unit_class": u.RATIO, "kind": "series", "quantity": quantity}},
        {"points": [{POINT_PERIOD_KEY: d.isoformat(), "value": v, "fact_ids": []}
                    for d, v in points]},
        [], {}, "test")


async def test_regress_aligns_by_period_key_and_counts_the_dropped_points():
    db = FakeDb()
    days = weekdays(12)
    x_pts = [(d, 0.01 * i) for i, d in enumerate(days[:10])]          # d0..d9
    y_pts = [(d, 2.0 * 0.01 * i + 1.0) for i, d in enumerate(days) if i >= 2]  # d2..d11
    sx = await _mint_series(db, "X.returns", x_pts)
    sy = await _mint_series(db, "Y.returns", y_pts)
    out = await pas.regress(db, sx, sy)
    assert out["n"] == 8, "only the shared keys d2..d9 enter the fit"
    assert out["unmatched_points"] == 4, "2 x-only + 2 y-only, dropped AND counted"
    assert out["beta"]["value"] == pytest.approx(2.0, abs=1e-12)
    assert out["alpha"]["value"] == pytest.approx(1.0, abs=1e-12)
    assert out["r2"]["value"] == pytest.approx(1.0, abs=1e-12)


async def test_regress_refuses_series_on_disjoint_dates():
    db = FakeDb()
    sx = await _mint_series(db, "X.returns", [(d, 1.0) for d in weekdays(5)])
    sy = await _mint_series(db, "Y.returns",
                            [(d, 1.0) for d in weekdays(5, start=date(2026, 6, 1))])
    out = await pas.regress(db, sx, sy)
    assert out["error"] == "misaligned_series"


async def test_regress_refuses_a_constant_regressor():
    db = FakeDb()
    days = weekdays(6)
    sx = await _mint_series(db, "X.returns", [(d, 0.5) for d in days])
    sy = await _mint_series(db, "Y.returns", [(d, float(i)) for i, d in enumerate(days)])
    out = await pas.regress(db, sx, sy)
    assert out["error"] == "degenerate_regressor"


async def test_regress_refuses_an_untyped_series():
    db = FakeDb()
    days = weekdays(6)
    row = CalcLedger(id="calc_untyped", operation="legacy.series", params={},
                     result={"points": [{POINT_PERIOD_KEY: d.isoformat(), "value": 1.0}
                                        for d in days]},
                     input_refs=[], primitive_version="v0", invoked_by="test")
    db.add(row)
    sy = await _mint_series(db, "Y.returns", [(d, float(i)) for i, d in enumerate(days)])
    out = await pas.regress(db, "calc_untyped", sy)
    assert out["error"] == "untyped_series"


# ── momentum and the 52-week distance ─────────────────────────────────────────

async def test_momentum_12_1_skips_the_most_recent_month(monkeypatch):
    db = FakeDb()
    adj = [100.0] * 101 + [150.0] * 178 + [999.0] * 21   # 300 bars
    install_bars(monkeypatch, {"TSLA": make_bars(adj)})
    out = await pas.momentum_12_1(db, "TSLA")
    # formation: bars[-252] (=100.0) .. bars[-22] (=150.0); the 999s at the end
    # sit inside the skipped month and MUST NOT touch the number.
    assert out["value"] == pytest.approx(0.5, abs=1e-12)
    assert out["n"] == 300
    assert out["skipped_recent_sessions"] == 21
    assert out["quantity"] == "TSLA.momentum_12_1"
    row = db.ops("price.momentum_12_1")[0]
    assert row.params["formation_from"] < row.params["formation_to"]


async def test_distance_from_52w_high_reports_the_ratio_and_the_high_date(monkeypatch):
    db = FakeDb()
    adj = [100.0] * 260
    adj[240] = 200.0
    adj[259] = 150.0
    bars = make_bars(adj)
    install_bars(monkeypatch, {"AMZN": bars})
    out = await pas.distance_from_52w_high(db, "AMZN")
    assert out["value"] == pytest.approx(-0.25, abs=1e-12)
    assert out["high_date"] == bars[240].date.isoformat(), (
        "a high 3 sessions old and one 300 sessions old are the same ratio "
        "and different facts — the date travels with the number")
    assert out["quantity"] == "AMZN.distance_from_52w_high"
    assert out["unit_class"] == u.RATIO


# ── ADV: two quantities ───────────────────────────────────────────────────────

async def test_adv_mints_share_count_and_dollar_value_as_two_quantities(monkeypatch):
    db = FakeDb()
    volumes = [1000 * (i + 1) for i in range(25)]
    bars = make_bars([10.0] * 25, close=[10.0] * 25, volumes=volumes)
    install_bars(monkeypatch, {"KO": bars})
    out = await pas.adv(db, "KO", window_days=20)
    assert out["adv_shares"]["value"] == pytest.approx(15500.0)   # mean of 6000..25000
    assert out["adv_dollars"]["value"] == pytest.approx(155000.0)
    assert out["adv_shares"]["unit_class"] == u.COUNT
    assert out["adv_dollars"]["unit_class"] == u.MONEY
    assert out["adv_shares"]["quantity"] == "KO.adv_shares.20d"
    assert out["adv_dollars"]["quantity"] == "KO.adv_dollars.20d"
    assert out["n"] == 20
    shares_row = next(r for r in db.rows if r.id == out["adv_shares"]["calc_id"])
    dollars_row = next(r for r in db.rows if r.id == out["adv_dollars"]["calc_id"])
    assert shares_row.unit_class == "COUNT" and dollars_row.unit_class == "MONEY"


async def test_dollar_adv_uses_the_as_traded_close_not_the_adjusted_one(monkeypatch):
    """The dollar value that crossed the tape is close × volume; the adjusted
    series is a different quantity and would restate history at every dividend."""
    db = FakeDb()
    bars = make_bars([5.0] * 25, close=[10.0] * 25, volumes=[100] * 25)
    install_bars(monkeypatch, {"KO": bars})
    out = await pas.adv(db, "KO")
    assert out["adv_dollars"]["value"] == pytest.approx(1000.0), "close (10), not adj (5)"


# ── every minted row is fully typed (Lane A's _record raises otherwise) ───────

async def test_every_result_row_carries_a_quantity_and_a_unit(monkeypatch):
    db = FakeDb()
    px, py = _linear_pair()
    install_bars(monkeypatch, {"SPY": make_bars(px), "NVDA": make_bars(py)})
    await pas.get_price(db, "NVDA")
    await pas.get_price_series(db, "NVDA", window="3m")
    await pas.rolling_volatility(db, "NVDA", window_days=20)
    await pas.beta(db, "NVDA", benchmark="SPY")
    vol_bars = make_bars([10.0] * 25, volumes=[100] * 25)
    install_bars(monkeypatch, {"NVDA": vol_bars, "SPY": make_bars(px)})
    await pas.adv(db, "NVDA")
    adj = [100.0] * 300
    install_bars(monkeypatch, {"NVDA": make_bars(adj)})
    await pas.momentum_12_1(db, "NVDA")
    await pas.distance_from_52w_high(db, "NVDA")

    assert db.rows, "the walk above minted rows"
    for row in db.rows:
        assert not row.operation.startswith("absence."), (
            f"this walk expects no refusal, got {row.operation}: {row.result}")
        rt = row.params.get("result_type")
        assert rt and rt.get("quantity"), f"{row.operation} names no quantity"
        assert rt.get("unit_class") in u.UNIT_CLASSES, (
            f"{row.operation} states no unit the algebra knows")
        assert row.unit_class is not None, f"{row.operation} left the unit column NULL"


async def test_series_rows_write_only_the_one_period_key(monkeypatch):
    db = FakeDb()
    px, py = _linear_pair()
    install_bars(monkeypatch, {"SPY": make_bars(px), "NVDA": make_bars(py)})
    await pas.get_price_series(db, "NVDA", window="1y")
    await pas.beta(db, "NVDA", benchmark="SPY")
    series_rows = [r for r in db.rows if isinstance(r.result.get("points"), list)]
    assert series_rows
    for row in series_rows:
        for p in row.result["points"]:
            assert POINT_PERIOD_KEY in p
            assert "end" not in p and "as_of" not in p
