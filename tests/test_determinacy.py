"""V16 Lane C — determinacy (M3): an under-observed estimate is refused, loudly.

Every estimator in price_analytics_service carries the number of observations
it rests on, and each producer declares the minimum below which its estimate
is not minted. These tests pin the three properties that make that a contract
rather than a habit:

  * the refusal CARRIES ITS REASON — the producer parameter's name and both
    numbers (needs / have) — in the payload and in the statement the model
    transcribes;
  * the refusal is CITABLE — an absence row with an id, holding the statement
    and no numeric value, exactly the shape absence_service mints;
  * no path SILENTLY SHRINKS a window — a 30-day vol over 25 returns is not a
    25-day vol wearing the wrong name, it is nothing, and the ledger holds no
    result row for it.
"""

from __future__ import annotations

from datetime import date, timedelta

from exposure_workbench.analytics.units import POINT_PERIOD_KEY
from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.services import quantities as qn


class FakeDb:
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


def make_bars(adj, volumes=None):
    volumes = volumes or [None] * len(adj)
    return [pas.Bar(d, a, a, v) for d, a, v in zip(weekdays(len(adj)), adj, volumes)]


def install_bars(monkeypatch, by_ticker):
    async def _bars(_db, ticker, start=None, end=None):
        bars = by_ticker.get(ticker, [])
        return [b for b in bars
                if (start is None or b.date >= start) and (end is None or b.date <= end)]

    async def _market_bars(_db, ticker):
        return list(by_ticker.get(ticker, []))

    monkeypatch.setattr(pas, "_bars", _bars)
    monkeypatch.setattr(pas, "_market_bars", _market_bars)


def assert_reasoned_refusal(db, out, *, parameter: str, needs: int, have: int):
    """The whole M3 shape in one place: reason in the payload, reason in the
    statement, and a citable absence row behind the id."""
    assert out["error"] == "insufficient_observations"
    assert out["parameter"] == parameter
    assert out["needs"] == needs and out["have"] == have
    # The statement is composed by the server and transcribable: it names the
    # producer parameter and carries both numbers.
    assert parameter in out["statement"]
    assert str(needs) in out["statement"] and str(have) in out["statement"]
    # Citable: the id resolves to an absence row holding that same statement.
    assert out["absence_id"].startswith("calc_")
    row = next(r for r in db.rows if r.id == out["absence_id"])
    assert row.operation == "absence.insufficient_observations"
    assert qn.calc_kind(row) == qn.KIND_ABSENCE
    assert row.result["statement"] == out["statement"]
    assert "value" not in row.result, "an absence supports a sentence, never a figure"
    assert "result_type" not in row.params, "the resolver must find no quantity here"
    assert row.params["stopped_at"] == {"parameter": parameter, "needs": needs, "have": have}


# ── the producer parameters are pinned, with their documented values ──────────

def test_the_minimum_observation_constants_hold_their_documented_values():
    """Producer parameters, not gate thresholds — changing one is changing what
    the estimator claims to need, and takes a new source in the module comment."""
    assert pas.VOL_MIN_OBS == 20
    assert pas.BETA_MIN_OBS == 60
    assert pas.ADV_MIN_OBS == 20
    assert pas.MOMENTUM_MIN_OBS == 200


# ── volatility ────────────────────────────────────────────────────────────────

async def test_a_window_below_vol_min_obs_is_refused_as_asked_for_noise(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"AAPL": make_bars([100.0] * 50)})
    out = await pas.rolling_volatility(db, "AAPL", window_days=10)
    assert_reasoned_refusal(db, out, parameter="VOL_MIN_OBS", needs=20, have=10)
    assert db.ops("price.vol") == [], "no vol row exists for a refused request"


async def test_a_window_the_history_cannot_fill_is_refused_not_shrunk(monkeypatch):
    """26 prices hold 25 returns. A 30-day vol over them would be a 25-day vol
    wearing the requested window's name — the ledger must hold a refusal and
    NO price.vol row."""
    db = FakeDb()
    install_bars(monkeypatch, {"AAPL": make_bars([100.0 + i for i in range(26)])})
    out = await pas.rolling_volatility(db, "AAPL", window_days=30)
    assert_reasoned_refusal(db, out, parameter="window_days", needs=30, have=25)
    assert db.ops("price.vol") == []


# ── beta ──────────────────────────────────────────────────────────────────────

async def test_beta_below_beta_min_obs_is_refused_and_no_estimate_rows_exist(monkeypatch):
    db = FakeDb()
    x = [100.0 * (1.01 ** i) for i in range(40)]
    y = [50.0 * (1.02 ** i) for i in range(40)]
    install_bars(monkeypatch, {"SPY": make_bars(x), "CSCO": make_bars(y)})
    out = await pas.beta(db, "CSCO", benchmark="SPY")
    assert_reasoned_refusal(db, out, parameter="BETA_MIN_OBS", needs=60, have=39)
    assert db.ops("price.regress") == [], (
        "no beta/alpha/r2 row is minted from an under-observed fit")


# ── momentum and the 52-week distance ─────────────────────────────────────────

async def test_momentum_below_its_floor_is_refused(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"IPO": make_bars([100.0] * 150)})
    out = await pas.momentum_12_1(db, "IPO")
    assert_reasoned_refusal(db, out, parameter="MOMENTUM_MIN_OBS", needs=200, have=150)
    assert db.ops("price.momentum_12_1") == []


async def test_the_52w_distance_shares_the_one_year_floor(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"IPO": make_bars([100.0] * 100)})
    out = await pas.distance_from_52w_high(db, "IPO")
    assert_reasoned_refusal(db, out, parameter="MOMENTUM_MIN_OBS", needs=200, have=100)
    assert db.ops("price.distance_from_52w_high") == []


# ── ADV ───────────────────────────────────────────────────────────────────────

async def test_an_adv_window_below_its_floor_is_refused(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"KO": make_bars([10.0] * 40, volumes=[100] * 40)})
    out = await pas.adv(db, "KO", window_days=10)
    assert_reasoned_refusal(db, out, parameter="ADV_MIN_OBS", needs=20, have=10)
    assert db.ops("price.adv") == []


async def test_sessions_without_volume_do_not_count_as_observations(monkeypatch):
    """30 bars, 10 with a recorded volume: the estimator has 10 observations,
    not 30, and says so rather than averaging what happens to be there."""
    db = FakeDb()
    volumes = [100] * 10 + [None] * 20
    install_bars(monkeypatch, {"KO": make_bars([10.0] * 30, volumes=volumes)})
    out = await pas.adv(db, "KO", window_days=20)
    assert_reasoned_refusal(db, out, parameter="window_days", needs=20, have=10)
    assert db.ops("price.adv") == []


# ── the generic primitive carries its caller's floor ──────────────────────────

async def test_regress_enforces_the_floor_its_caller_declares():
    db = FakeDb()

    async def mint(quantity, points):
        return await cs._record(
            db, None, "price.returns.series",
            {"result_type": {"unit_class": "ratio", "kind": "series", "quantity": quantity}},
            {"points": [{POINT_PERIOD_KEY: d.isoformat(), "value": v, "fact_ids": []}
                        for d, v in points]},
            [], {}, "test")

    days = weekdays(10)
    sx = await mint("X.returns", [(d, 0.01 * i) for i, d in enumerate(days)])
    sy = await mint("Y.returns", [(d, 0.02 * i) for i, d in enumerate(days)])
    out = await pas.regress(db, sx, sy, min_obs=pas.BETA_MIN_OBS,
                            min_obs_param="BETA_MIN_OBS")
    assert_reasoned_refusal(db, out, parameter="BETA_MIN_OBS", needs=60, have=10)
    assert db.ops("price.regress") == []


# ── no price history at all is an absence too ─────────────────────────────────

async def test_no_price_history_is_a_citable_absence_not_a_bare_error(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {})
    out = await pas.get_price(db, "ZZZZ")
    assert out["error"] == "no_price_history"
    assert out["absence_id"].startswith("calc_")
    row = next(r for r in db.rows if r.id == out["absence_id"])
    assert row.operation == "absence.no_price_history"
    assert qn.calc_kind(row) == qn.KIND_ABSENCE
    assert "ZZZZ" in out["statement"]
    assert "coverage" in out["statement"] or "price history" in out["statement"]
