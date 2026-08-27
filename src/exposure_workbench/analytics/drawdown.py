"""V8-D1 — drawdown episodes: when the book fell, how far, and whether it came back.

`calc_risk_metrics` computes a maximum drawdown and keeps one number. The series
it computed that number from — every peak, every trough, every recovery — is
discarded on the same line. So "the book is down 17.7% from its high" was
answerable and "when did that start, and has it recovered" was not.

An episode is a peak, a trough and possibly a recovery. Nothing more is inferred.

WHAT THIS MODULE DOES NOT PROVIDE, and will not:

    A decomposition of a drawdown's DEPTH into per-position or per-factor parts.

Not withheld out of caution — it does not exist. A drawdown is a path statistic:
its depth depends on the ORDER of the returns, and its endpoints are chosen by
the data (the peak is wherever the maximum happened to fall). Contributions are
additive within a period and drawdown depth is not additive across periods, so
there is no set of per-name numbers that sums to it. Anything presenting itself
as one is a different quantity wearing the name — usually the cumulative
contribution over the window between the two dates, which is a real number and a
DIFFERENT one, because it ignores the path that made those dates the endpoints.

That real number is what `explain_episode` returns, labelled as what it is. The
absent function is absent from the API, not refused at runtime: a tool that
exists and declines is a tool a model retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Episode:
    """One peak-to-trough fall in a cumulative return series.

    `depth` is positive: 0.1766 means the book was 17.66% below its high. It is
    a distance from a running maximum, not a return, and the two are different
    quantities even though both are written as percentages.
    """

    peak_date: date
    trough_date: date
    depth: float
    recovery_date: date | None
    trough_days: int          # sessions from peak to trough
    recovery_days: int | None  # sessions from trough back to the peak level


def find_episodes(returns: pd.Series, min_depth: float = 0.05) -> list[Episode]:
    """Every episode at least `min_depth` deep, deepest first.

    `min_depth` is a reporting floor, not a judgement: a 0.4% dip is an episode
    too, and listing four hundred of them answers nothing. It has a default so
    the caller need not pick one, and it is an argument so the caller may.

    An episode still in progress has `recovery_date=None`. That is the honest
    shape — the alternative, dropping unrecovered episodes, hides exactly the one
    a reader is most likely asking about.
    """
    r = returns.dropna()
    if len(r) < 2:
        return []

    cum = (1.0 + r).cumprod()
    running_max = cum.cummax()

    episodes: list[Episode] = []
    peak_idx: int | None = None
    trough_idx: int | None = None

    values = cum.to_numpy()
    peaks = running_max.to_numpy()
    index = list(cum.index)

    for i in range(len(values)):
        under_water = values[i] < peaks[i]
        if under_water:
            if peak_idx is None:
                # The peak is the last point that WAS at the running max, which
                # is the previous session by construction.
                peak_idx = i - 1 if i > 0 else 0
                trough_idx = i
            elif values[i] < values[trough_idx]:
                trough_idx = i
        elif peak_idx is not None:
            # Back to the high: the episode closed on this session.
            episodes.append(_episode(index, values, peak_idx, trough_idx, i))
            peak_idx = trough_idx = None

    if peak_idx is not None:
        episodes.append(_episode(index, values, peak_idx, trough_idx, None))

    deep = [e for e in episodes if e.depth >= min_depth]
    return sorted(deep, key=lambda e: e.depth, reverse=True)


def _as_date(v) -> date:
    return v.date() if hasattr(v, "date") else v


def _episode(index, values, peak_idx: int, trough_idx: int, recovery_idx: int | None) -> Episode:
    depth = (values[peak_idx] - values[trough_idx]) / values[peak_idx]
    return Episode(
        peak_date=_as_date(index[peak_idx]),
        trough_date=_as_date(index[trough_idx]),
        depth=float(depth),
        recovery_date=None if recovery_idx is None else _as_date(index[recovery_idx]),
        trough_days=trough_idx - peak_idx,
        recovery_days=None if recovery_idx is None else recovery_idx - trough_idx,
    )


def deepest(returns: pd.Series) -> Episode | None:
    """The episode behind `max_drawdown`, with its dates.

    Uses no floor: the deepest episode is the deepest whatever its size, and
    `calc_risk_metrics.max_drawdown` is its depth. A floor here could return None
    for a series whose max_drawdown the metrics row states, which is two parts of
    one system disagreeing about the same book.
    """
    found = find_episodes(returns, min_depth=0.0)
    return found[0] if found else None
