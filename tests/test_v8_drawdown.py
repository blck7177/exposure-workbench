"""V8-D1 — episodes on constructed paths, and the decomposition that is absent.

Constructed rather than sampled: an episode detector is judged by whether it puts
the peak and trough on the right days, and a real series has no independently
known answer to compare against.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import pandas as pd
import pytest

from exposure_workbench.analytics import drawdown as dd
from exposure_workbench.services import quantities as qn
from exposure_workbench.analytics.risk_metrics import calc_risk_metrics


def _series(returns):
    start = date(2026, 1, 5)
    idx = [start + timedelta(days=i) for i in range(len(returns))]
    return pd.Series(returns, index=pd.to_datetime(idx))


def test_a_single_fall_and_recovery_has_the_right_three_dates():
    #        d0     d1     d2     d3      d4     d5
    # cum: 1.100  1.000  0.900  0.990  1.100  1.155
    #             peak at d0, trough at d2, back to the peak level at d4
    r = _series([0.10, -0.0909090909, -0.10, 0.10, 0.1111111111, 0.05])
    eps = dd.find_episodes(r, min_depth=0.01)
    assert len(eps) == 1
    e = eps[0]
    assert e.peak_date == date(2026, 1, 5)
    assert e.trough_date == date(2026, 1, 7)
    assert e.depth == pytest.approx(0.1818, abs=1e-3)
    assert e.recovery_date == date(2026, 1, 9)
    assert e.trough_days == 2 and e.recovery_days == 2


def test_an_unrecovered_fall_is_reported_with_no_recovery_date():
    """Not dropped. The episode a reader is most likely asking about is the one
    the book is still in."""
    r = _series([0.05, -0.10, -0.05])
    e = dd.find_episodes(r, min_depth=0.01)[0]
    assert e.recovery_date is None and e.recovery_days is None
    assert e.trough_date == date(2026, 1, 7)


def test_episodes_come_back_deepest_first():
    r = _series([0.02, -0.03, 0.04, 0.02, -0.15, 0.20, 0.01])
    eps = dd.find_episodes(r, min_depth=0.01)
    assert len(eps) == 2
    assert eps[0].depth > eps[1].depth


def test_the_floor_reports_and_does_not_judge():
    """A 0.4% dip is an episode; listing four hundred of them answers nothing.
    Raising the floor must remove episodes and change no surviving one."""
    r = _series([0.02, -0.004, 0.01, -0.12, 0.05])
    small = dd.find_episodes(r, min_depth=0.001)
    large = dd.find_episodes(r, min_depth=0.05)
    assert len(small) > len(large)
    assert large[0] == small[0]


def test_the_deepest_episode_reproduces_max_drawdown():
    """The metrics row and this module must not disagree about the same book.
    `deepest` uses no floor for exactly this reason."""
    r = _series([0.03, -0.05, -0.07, 0.02, -0.04, 0.09, 0.01] * 6)
    metrics = calc_risk_metrics(r, min_obs=10)
    assert dd.deepest(r).depth == pytest.approx(metrics.max_drawdown, abs=1e-9)


def test_a_series_that_only_rises_has_no_episodes():
    assert dd.find_episodes(_series([0.01] * 10)) == []


def test_a_short_series_returns_nothing_rather_than_guessing():
    assert dd.find_episodes(_series([0.01])) == []


# ── the absence ───────────────────────────────────────────────────────────────

def test_there_is_no_depth_decomposition_in_the_api():
    """The load-bearing test of this module. A drawdown's depth is a PATH
    statistic: it depends on the order of the returns and its endpoints are
    chosen by the data. Contributions are additive within a period; depth is not
    additive across periods. So no set of per-name numbers sums to it, and a
    function claiming to produce one would be returning a different quantity
    under this one's name.

    Asserted as an absence from the module's surface, not as a runtime refusal —
    a function that exists and declines is a function a model retries."""
    exported = [n for n in dir(dd) if not n.startswith("_")]
    for name in exported:
        low = name.lower()
        assert not ("attribut" in low or "decompos" in low or "contribut" in low), (
            f"{name} looks like a depth decomposition, which does not exist")


def test_the_reason_is_written_down_where_the_next_author_will_look():
    """The rule is only as durable as its argument. A later batch asked to 'break
    the drawdown down by holding' needs to find why not, in the module, not in a
    review comment."""
    doc = inspect.getdoc(dd) or ""
    assert "path statistic" in doc
    assert "not additive" in doc


# ── D2: the tools' shape ──────────────────────────────────────────────────────

def test_the_span_is_an_enum_not_a_day_count():
    """"The last 37 days" is a window chosen after seeing the answer. Named spans
    can still be shopped between, but each one is a period a reader recognises
    and the set is small enough to see in the schema."""
    from exposure_workbench.tools.registries import build_meta_registry
    schema = build_meta_registry().tools["get_drawdown_episodes"].json_schema
    assert set(schema["properties"]["span"]["enum"]) == {"3m", "6m", "1y", "3y", None}


def test_explain_episode_always_carries_the_caveat():
    """Not conditionally. A caveat that appears when someone remembers it is
    absent exactly when it matters."""
    from exposure_workbench.services import drawdown_service as dsvc
    src = inspect.getsource(dsvc.explain_episode)
    body = src.split("return {", 1)[1]
    assert '"fixed_window_caveat"' in body
    assert "if " not in body.split('"fixed_window_caveat"')[0].rsplit("\n", 1)[-1]


def test_explain_episode_returns_no_per_day_factor_series():
    """Betas are estimated on a rolling window, so a factor's daily contribution
    is measured against a different model each day and adding them across a
    window is arithmetic over incompatible fits. The shape is not offered rather
    than refused — there is no field to ask for."""
    from exposure_workbench.services import drawdown_service as dsvc
    src = inspect.getsource(dsvc.explain_episode)
    for word in ("factor_contribution", "daily_factor", "factor_series", "factors"):
        assert f'"{word}"' not in src


def test_an_unavailable_benchmark_says_why():
    from exposure_workbench.services import drawdown_service as dsvc
    src = inspect.getsource(dsvc.explain_episode)
    assert '"unavailable_reason"' in src


def test_episode_depths_are_citable():
    """A tool returning numbers no citation can reach is a tool whose output the
    gate will refuse. Declared as a list under one unit, so a list is not a
    licence to walk arbitrary structure."""
    from exposure_workbench.services import numeric_verification as nv
    keys = qn._CALC_RESULT_KEYS["portfolio.drawdown_episodes"]
    assert keys == {"deepest_depth": nv.RATIO, "episode_depths": nv.RATIO}
    assert "portfolio.drawdown_episodes" in qn._CALC_RATIO_OPS
