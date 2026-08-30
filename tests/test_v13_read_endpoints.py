"""V13-S5 — the panels read what already happened (offline).

Eleven endpoints were added to serve charts. None of them computes anything new,
and these tests are about the two ways that claim could quietly stop being true.

FIRST: a panel that recomputes is a second opinion nobody asked for. The book's
value chart and the volatility tile above it must come from one series, or the
page disagrees with itself in the third decimal — which is where trust in a risk
page goes. The live check for that is in the acceptance run (the last point of
the rolling volatility equals exposure_metrics.rolling_vol_30d to six places);
what is pinned here is the structural half: the chart series is built by the same
function the return series is a percentage change of.

SECOND: a read that mints a ledger row turns "this desk performed 25,119
calculations" into "a browser was left open". The ledger's one-row-per-
calculation contract is what makes a number citable, and a page refreshing every
two seconds is the fastest way to destroy it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── one valuation convention, not two ────────────────────────────────────────

def test_the_value_chart_and_the_return_series_share_one_panel():
    """Read out of the source, because agreement on today's data is what a
    divergence looks like on the day it is introduced."""
    from exposure_workbench.services import market_data_service as mds

    values = inspect.getsource(mds.build_portfolio_values)
    returns = inspect.getsource(mds.build_portfolio_returns)
    assert "total_return_panel(prices_df, held)" in values
    assert "total_return_panel(prices_df, held)" in returns, (
        "the two series must be built on the same panel — adjusted closes, fixed "
        "quantities, no forward fill — or the chart and the tile describe "
        "different books"
    )


def test_the_values_are_the_series_the_returns_are_a_change_of():
    from exposure_workbench.services.market_data_service import (
        build_portfolio_returns, build_portfolio_values,
    )

    positions = pd.DataFrame([{"ticker": "AAA", "quantity": 10.0},
                              {"ticker": "BBB", "quantity": 5.0}])
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    prices = pd.DataFrame([
        {"ticker": t, "price_date": d, "close": p, "adj_close": p}
        for t, series in (("AAA", [100.0, 101.0, 99.0, 102.0]),
                          ("BBB", [50.0, 50.5, 51.0, 49.0]))
        for d, p in zip(dates, series)
    ])
    values = build_portfolio_values(positions, prices)
    returns = build_portfolio_returns(positions, prices)
    assert len(values) == 4
    derived = values.pct_change().dropna()
    for day, expected in returns.items():
        assert derived.loc[day] == pytest.approx(expected, abs=1e-12)


def test_a_holding_with_no_quantity_fails_loudly_in_both():
    """The same refusal, because a book valued with a hole in it is a wrong
    number rather than a partial one."""
    from exposure_workbench.services.market_data_service import build_portfolio_values

    positions = pd.DataFrame([{"ticker": "AAA", "quantity": None}])
    prices = pd.DataFrame([{"ticker": "AAA", "price_date": pd.Timestamp("2026-01-02"),
                            "close": 100.0, "adj_close": 100.0}])
    with pytest.raises(ValueError, match="no quantity"):
        build_portfolio_values(positions, prices)


# ── a read does not mint a ledger row ────────────────────────────────────────

def test_a_deriving_read_asks_for_the_existing_calculation_first():
    """The reconcile panel calls the same service the agent's tool calls, and
    that service records a row. Asking find_recorded first is what keeps the
    ledger a record of calculations rather than of page views."""
    src = (ROOT / "apps" / "api" / "routes" / "exposure_runs.py").read_text()
    reconcile = src[src.index("async def run_reconcile"):src.index("async def run_factor_correlation")]
    assert "calc_service.find_recorded(" in reconcile, (
        "the reconcile read must look for the existing calculation before "
        "handing back a new one"
    )


def test_the_lookup_key_is_a_subset_of_what_the_operation_records():
    """The bug this replaces, and the shape of it.

    `find_recorded` compared params for JSONB EQUALITY, on the argument that the
    params ARE the call. reconcile records `terms_positions` and `terms_factors`
    beside its run_id — facts about what the call turned out to involve, which no
    caller can know before making it — so equality never matched, every read fell
    through to the recording path, and /reconcile minted a ledger row per
    request. Live, for a week. The test that was here asserted the equality, so
    it passed the whole time; the test above asserted the lookup was CALLED, and
    it was.

    A source-read cannot see behaviour. What it can see is the relationship the
    two ends have to hold: the keys the lookup is made with must be a subset of
    the keys the record is written with, or containment can never match. That is
    checked here from both sources, and the live half is
    tests/test_reconcile_reuse_live.py, which calls the endpoint twice and counts
    the ledger.
    """
    import re
    from exposure_workbench.services import calc_service, reconcile_service

    lookup = set(reconcile_service.identifying_params("run_x"))
    assert lookup, "the operation must export the params that identify one of its calls"

    recorder = inspect.getsource(reconcile_service._record_reconcile)
    params_block = recorder[recorder.index("{**identifying_params"):]
    params_block = params_block[:params_block.index("}") + 1]
    recorded = set(re.findall(r'"(\w+)":', params_block)) | lookup
    assert lookup <= recorded, (
        f"the lookup is keyed on {sorted(lookup - recorded)}, which the record does "
        "not carry — containment can never match and every read will mint a row"
    )
    assert recorded - lookup, (
        "this guard is vacuous unless the record carries more than the lookup; if "
        "the two sets became equal, equality would do and containment's obligation "
        "on the caller should be reconsidered"
    )

    body = inspect.getsource(calc_service.find_recorded)
    assert "CalcLedger.operation == operation" in body
    assert "CalcLedger.params.contains(params)" in body, (
        "equality here is what shipped the bug; containment plus a caller that "
        "passes every distinguishing argument is the contract"
    )


def test_a_read_does_not_go_through_the_recording_entry_point():
    """get_db commits at the end of every request.

    The first fix called reconcile_move and then decided whether to commit, which
    could not work for that reason: the row was written before the route had an
    opinion. The read must call the computation that does not record at all.
    """
    src = (ROOT / "apps" / "api" / "routes" / "exposure_runs.py").read_text()
    body = src[src.index("async def run_reconcile"):src.index("async def run_factor_correlation")]
    hit = body[body.index("if existing is not None"):]
    assert "reconcile_service.reconcile(db, run_id)" in hit, (
        "when the calculation already exists the read must use the non-recording "
        "entry point"
    )
    assert "await db.commit()" not in body, (
        "the route must not reason about committing; get_db commits every request"
    )


# ── the honest absences ──────────────────────────────────────────────────────

def test_the_limit_book_says_when_a_run_recorded_no_levels():
    """Rows written before V13 were not backfilled, so most runs in the live
    database have checks with no numbers. The panel has to say that rather than
    draw an empty meter, which reads as "measured, and at zero"."""
    src = (ROOT / "apps" / "api" / "routes" / "exposure_runs.py").read_text()
    book = src[src.index("async def run_limit_book"):src.index("async def run_stress")]
    assert "unrecorded" in book and "detail" in book
    assert "r.current_value is None" in book, (
        "utilisation must be None where the run recorded no levels — computing "
        "it from today's thresholds would describe a check that never ran "
        "against them"
    )


def test_the_history_endpoint_states_its_valuation_assumption():
    """A line chart is the most persuasive way there is to imply that this is
    what the book was worth. It is what today's book would have been worth."""
    src = (ROOT / "apps" / "api" / "routes" / "portfolios.py").read_text()
    assert "valuation_assumption" in src
    assert "no holding history to replay" in src


def test_the_window_panel_uses_the_engines_own_notion_of_a_hole():
    """The first version stepped 91 days at a time with a tolerance and called
    anything unmatched a gap — inventing structure, and wrong: it did not know
    that Apple's year ends in late September, nor that a year filed as H1 + FY
    yields H1 and FY − H1. consecutive_windows knows both, because it was built
    for exactly this, and it keeps an underivable slot in place (V10 DP2)."""
    src = (ROOT / "apps" / "api" / "routes" / "issuers.py").read_text()
    windows = src[src.index("async def reported_windows"):src.index("async def coverage")]
    assert "ia.consecutive_windows(" in windows
    assert "timedelta(days=91)" not in windows, "the hand-rolled stepping is back"


# ── the charts are not a second implementation ───────────────────────────────

@pytest.mark.parametrize("route_file,marker", [
    ("exposure_runs.py", "reconcile_service.reconcile_move("),
    ("exposure_runs.py", "factor_model.factor_correlation("),
    ("portfolios.py", "market_data_service.build_portfolio_values("),
    ("portfolios.py", "dd.find_episodes("),
    ("issuers.py", "market_data_service.price_points("),
    ("issuers.py", "fundamentals_service._flow_facts("),
    ("issuers.py", "calc_service.list_available_metrics("),
])
def test_each_panel_calls_the_service_rather_than_reimplementing_it(route_file, marker):
    src = (ROOT / "apps" / "api" / "routes" / route_file).read_text()
    assert marker in src, f"{route_file} should reach the analytics through {marker}"


def test_the_benchmark_is_indexed_rather_than_given_a_second_axis():
    """A dual-axis chart invents a correlation by choosing where the scales line
    up. Indexing both series to a common base is the honest way to put a
    $250 stock and a $600 index on one plot."""
    for f in ("portfolios.py", "issuers.py"):
        src = (ROOT / "apps" / "api" / "routes" / f).read_text()
        assert "base_bench" in src, f"{f} does not index its benchmark"
