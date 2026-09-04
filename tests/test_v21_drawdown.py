"""V21-S2 — the deepest fall in a window is computed where every estimate is (offline).

R20's `Peak-to-trough decline | $205.10` was the trough slotted under a label
the model wrote; V19 made the label the table's, and the cell then honestly
read as the peak — the subtraction was still the model's initiative, and it
did not take it (V19 §3). `get_drawdown` does the subtraction: peak, trough,
fall and depth as four typed rows, dated, with the window they were read over.
Constructed bars, so every number has an answer the test can derive by hand.
"""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.analytics import drawdown as dd
from exposure_workbench.analytics import units as u
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.tools import faces
from tests.test_price_quantities import FakeDb, install_bars, make_bars, weekdays


# ── the pure function ─────────────────────────────────────────────────────────

def _levels(values, start=date(2025, 1, 6)):
    return list(zip(weekdays(len(values), start), values))


def test_the_deepest_episode_is_found_on_levels_with_the_first_bar_eligible_as_peak():
    """find_episodes cannot make the first observation a peak; a price series
    asked about 'its high' may have set it on the first bar of the window."""
    ep = dd.deepest_from_levels(_levels([100.0, 90.0, 95.0, 80.0, 85.0, 101.0]))
    assert ep is not None
    assert (ep.peak, ep.trough) == (100.0, 80.0)
    assert ep.peak_date == date(2025, 1, 6) and ep.trough_date == date(2025, 1, 9)
    assert ep.fall == 20.0 and ep.depth == pytest.approx(0.2)
    assert ep.recovery_date == date(2025, 1, 13), "the first bar back at or above the peak"


def test_a_later_deeper_fall_wins_over_an_earlier_shallower_one():
    ep = dd.deepest_from_levels(_levels([10, 12, 9, 11, 8, 13, 7, 14]))
    assert (ep.peak, ep.trough) == (13, 7)
    assert ep.depth == pytest.approx(6 / 13)
    assert ep.recovery_date == date(2025, 1, 15), "the eighth weekday from 2025-01-06"


def test_an_unrecovered_episode_has_no_recovery_date():
    ep = dd.deepest_from_levels(_levels([50.0, 60.0, 30.0, 40.0]))
    assert (ep.peak, ep.trough, ep.recovery_date) == (60.0, 30.0, None)


def test_a_series_that_never_falls_has_no_episode():
    assert dd.deepest_from_levels(_levels([1.0, 2.0, 2.0, 3.0])) is None
    assert dd.deepest_from_levels(_levels([5.0])) is None
    assert dd.deepest_from_levels([]) is None


def test_the_level_episode_agrees_with_the_return_episode_on_an_interior_peak():
    """Two readings of one path: the book's episode finder on returns and this
    one on levels name the same peak, trough and depth when the peak is not
    the first bar (where find_episodes cannot look)."""
    import pandas as pd
    levels = [100.0, 104.0, 110.0, 99.0, 93.5, 100.0, 112.0]
    lv = _levels(levels)
    from_levels = dd.deepest_from_levels(lv)
    rets = pd.Series([levels[i] / levels[i - 1] - 1 for i in range(1, len(levels))],
                     index=pd.to_datetime([d for d, _ in lv[1:]]))
    from_returns = dd.deepest(rets)
    assert from_levels.peak_date == from_returns.peak_date
    assert from_levels.trough_date == from_returns.trough_date
    assert from_levels.depth == pytest.approx(from_returns.depth)


# ── the tool ──────────────────────────────────────────────────────────────────

def _bars_with_a_fall(n: int = 60):
    # 60 sessions: climbs to 200 at bar 20, falls to 150 at bar 30, back to 205 at bar 45.
    adj = []
    for i in range(n):
        if i <= 20:
            adj.append(100.0 + 5.0 * i)          # 100 → 200
        elif i <= 30:
            adj.append(200.0 - 5.0 * (i - 20))   # 200 → 150
        elif i <= 45:
            adj.append(150.0 + (55.0 / 15) * (i - 30))  # 150 → 205
        else:
            adj.append(205.0 - 0.5 * (i - 45))   # a shallow drift down
    return make_bars(adj)


async def test_get_drawdown_mints_peak_trough_fall_and_depth_as_four_typed_rows(monkeypatch):
    db = FakeDb()
    bars = _bars_with_a_fall()
    install_bars(monkeypatch, {"NVDA": bars})

    out = await pas.drawdown(db, "NVDA", window="3m")

    assert out["peak"]["value"] == 200.0 and out["trough"]["value"] == 150.0
    assert out["fall"]["value"] == 50.0
    assert out["depth"]["value"] == pytest.approx(0.25)
    assert out["peak_date"] == bars[20].date.isoformat()
    assert out["trough_date"] == bars[30].date.isoformat()
    first_back = next(b for b in bars[31:] if b.adj_close >= 200.0)
    assert out["recovery_date"] == first_back.date.isoformat()
    assert [out[k]["quantity"] for k in ("peak", "trough", "fall", "depth")] == [
        "NVDA.drawdown.peak", "NVDA.drawdown.trough", "NVDA.drawdown.fall", "NVDA.drawdown.depth"]
    assert out["peak"]["unit_class"] == u.MONEY_PER_SHARE
    assert out["fall"]["unit_class"] == u.MONEY_PER_SHARE
    assert out["depth"]["unit_class"] == u.RATIO
    rows = db.ops(pas.OP_DRAWDOWN)
    assert len(rows) == 4 and len({r.id for r in rows}) == 4, "four rows, four calc_ids"
    assert all(r.params["result_type"]["quantity"].startswith("NVDA.drawdown.") for r in rows)
    assert {r.unit_class for r in rows} == {"MONEY_PER_SHARE", "RATIO"}


async def test_the_window_is_the_one_asked_for_and_is_stated(monkeypatch):
    """A fall outside the window is not the window's fall."""
    db = FakeDb()
    bars = _bars_with_a_fall(120)          # the 200→150 fall sits ~100 sessions back
    install_bars(monkeypatch, {"NVDA": bars})

    out = await pas.drawdown(db, "NVDA", window="1m")
    assert out["window"] == "1m"
    assert out["peak"]["value"] < 200.0, "the 3-month-old peak is outside a 1m window"
    assert out["interval"][1] == bars[-1].date.isoformat()
    assert out["basis"].startswith("adj_close over the last 1m")


async def test_too_short_a_history_is_refused_with_the_producer_parameter(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"NEW": make_bars([10.0, 9.0, 11.0, 8.0] * 3)})   # 12 bars

    async def _refuse(_db, error, **kw):
        return {"error": error, "absence_id": "absence_x", **kw}
    monkeypatch.setattr(pas.ab, "refuse", _refuse)

    out = await pas.drawdown(db, "NEW")
    assert out["error"] == "insufficient_observations"
    assert out["parameter"] == "DRAWDOWN_MIN_OBS" and out["needs"] == pas.DRAWDOWN_MIN_OBS
    assert out["have"] == 12
    assert db.ops(pas.OP_DRAWDOWN) == [], "nothing minted for a refused window"


async def test_a_name_that_never_fell_in_the_window_is_a_statement_not_a_zero(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"UP": make_bars([100.0 + i for i in range(40)])})

    async def _refuse(_db, error, **kw):
        return {"error": error, "absence_id": "absence_y", **kw}
    monkeypatch.setattr(pas.ab, "refuse", _refuse)

    out = await pas.drawdown(db, "UP", window="3m")
    assert out["error"] == "no_drawdown"
    assert "never sat below its running maximum" in out["statement"]
    assert db.ops(pas.OP_DRAWDOWN) == []


async def test_an_unknown_window_is_named_with_the_known_set(monkeypatch):
    db = FakeDb()
    install_bars(monkeypatch, {"NVDA": _bars_with_a_fall()})
    out = await pas.drawdown(db, "NVDA", window="2w")
    assert out["error"] == "unknown_window" and "1y" in out["known"]


# ── on the face, by the spec ──────────────────────────────────────────────────

def test_get_drawdown_is_on_both_faces_from_the_service_spec():
    spec = next(s for s in pas._TOOL_SPECS if s["name"] == "get_drawdown")
    assert spec["service_fn"] == "drawdown"
    assert "get_drawdown" in faces.READ_CORE
    assert "get_drawdown" in faces.FACE_META_AGENT and "get_drawdown" in faces.FACE_RESEARCH
    assert "peak − trough" in spec["description"], "the description says the subtraction is the tool's"
