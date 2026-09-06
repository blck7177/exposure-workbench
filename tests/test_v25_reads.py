"""V25 — the new reads say what a run recorded, and record nothing (offline).

Eight endpoints were added or widened so two pages could draw what the database
already held. None of them computes a measure, and these tests are about the
ways that claim could quietly stop being true.

FIRST: the rules that turn thirty-three photographs into a series — one point
per dated update, a delta against the previous DATED update — are pure
functions here rather than a `DISTINCT ON` and a window function, precisely so
they can be stated in a test. Five runs on 2026-09-03 must be one point, and
the first update must have no delta rather than a zero.

SECOND: a read that mints a ledger row turns "this desk performed N
calculations" into "a browser was open". The balance series is the one new read
with a recorder behind it, and the lookup that keeps it honest has two ways to
be wrong — a key narrower than what the recorder writes (which never matches,
so every read mints) and a key that ignores whose row it is (which matches the
wrong issuer's). Both are pinned.

THIRD: what the desk withholds must not reach a reader through a series that is
refused on a panel, and the snapshot must never again answer "in this book"
with a row from somebody else's book.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest


def _code(obj) -> str:
    """The source with its docstrings removed.

    A guard that reads prose is a guard that fails the moment a docstring
    explains the very thing the code must not do — which is what happened here:
    `measures_service` names `get_balance_series` to say it deliberately does
    not call it, and a plain substring check read that as a call.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ── one point per dated update ───────────────────────────────────────────────

@dataclass
class _Run:
    id: str
    as_of_date: date
    completed_at: datetime | None
    created_at: datetime


def _run(rid: str, day: str, minute: int, *, completed: bool = True) -> _Run:
    at = datetime(2026, 9, 3, 12, minute, tzinfo=timezone.utc)
    return _Run(rid, date.fromisoformat(day), at if completed else None, at)


def test_five_runs_of_one_close_are_one_point_and_say_so():
    """The demo book has five completed runs dated 2026-09-03 — re-runs of the
    same close after a deploy. Five points stacked on one date would say the
    book moved five times that day."""
    from exposure_workbench.services.run_series_service import collapse_by_date

    runs = [_run("run_a", "2026-09-03", 1), _run("run_b", "2026-09-03", 9),
            _run("run_c", "2026-09-03", 5), _run("run_d", "2026-09-02", 3)]
    got = collapse_by_date(runs)

    assert [r.as_of_date.isoformat() for r, _ in got] == ["2026-09-02", "2026-09-03"], (
        "one point per as_of_date, oldest first")
    kept, stood_for = got[-1]
    assert kept.id == "run_b", "the LATEST completed run of the day is the one drawn"
    assert stood_for == 3, "how many it stood for is on the wire, not lost"


def test_a_run_with_no_completion_time_still_orders():
    """`completed_at` is NULL on rows written before it was set. Falling back to
    `created_at` keeps the ordering; crashing on the None would lose the day."""
    from exposure_workbench.services.run_series_service import collapse_by_date

    got = collapse_by_date([_run("run_x", "2026-09-03", 2, completed=False),
                            _run("run_y", "2026-09-03", 7, completed=False)])
    assert [r.id for r, _ in got] == ["run_y"]


# ── a delta is against the previous dated update ─────────────────────────────

def test_no_previous_update_is_not_a_zero():
    """On the first update, and on a name the book did not hold last time, there
    is no move to state. A zero would claim the weight held steady — a claim
    about a comparison that was never made."""
    from exposure_workbench.services.run_series_service import _delta

    assert _delta(0.16, None) is None
    assert _delta(None, 0.16) is None
    assert _delta(0.16, 0.15) == pytest.approx(0.01)


def test_the_delta_is_computed_on_the_server_beside_both_figures():
    """The rule apps/web/app/components/book/panels.tsx states: a page renders
    what a run stored, and a percentage it computes is a stored figure over a
    stored figure — not a measure the client decided to derive. So the
    subtraction lives in the service."""
    from exposure_workbench.services import run_series_service as rss

    src = inspect.getsource(rss.get_run_series)
    assert "_delta(_f(r.weight), prev_issuer.get(r.ticker))" in src
    assert "_delta(_f(r.weight), prev_sector.get(r.sector))" in src


def test_the_comparison_basis_is_replaced_wholesale_each_update():
    """A name sold between updates must not keep comparing against the weight it
    had while it was held; the previous update's map is replaced, not updated."""
    from exposure_workbench.services import run_series_service as rss

    assert ("prev_issuer = {r.ticker: _f(r.weight) for r in rows_i}"
            in inspect.getsource(rss.get_run_series))
    src = _code(rss.get_run_series)
    assert "prev_issuer.update" not in src and "prev_sector.update" not in src


# ── the withheld set cannot arrive through the series ────────────────────────

def test_the_series_passes_its_checks_through_the_one_withheld_filter():
    """VaR, expected shortfall and the stress checks are refused on the mandate
    panel (analytics/withheld). A series of the same rows would be the same
    numbers by another door."""
    from exposure_workbench.services import run_series_service as rss

    src = inspect.getsource(rss.get_run_series)
    assert "wh.published_checks(" in src, "checks must go through the one filter"
    assert "wh.published_alerts(" in src, "so must the alert count"


def test_run_series_records_nothing():
    """It reads rows a run wrote. A read that records is a page view counted as
    a calculation (the guard test_v13_read_endpoints.py earned)."""
    from exposure_workbench.services import run_series_service as rss

    src = _code(rss)
    for forbidden in ("calc_service", "cs._record", "_record(", "record_"):
        assert forbidden not in src, f"the run series must not reach {forbidden}"


def test_the_span_is_anchored_on_the_book_not_on_the_clock():
    """A book last updated in June still has a year of its own history. Bounding
    on today would empty its chart rather than scroll it."""
    from exposure_workbench.services import run_series_service as rss

    src = _code(rss.get_run_series)
    assert "date.today()" not in src and "datetime.now" not in src
    assert "newest - timedelta(days=window)" in inspect.getsource(rss.get_run_series)


# ── room to a tier ───────────────────────────────────────────────────────────

def test_room_is_signed_and_absent_rather_than_zero():
    """Over the tier reads negative; a check that recorded no level has no room
    to report, and 0.0 would read as "exactly at the tier"."""
    from apps.api.routes.exposure_runs import run_limit_book

    src = inspect.getsource(run_limit_book)
    assert '"room_warning": (None if r.current_value is None or r.warning_level is None' in src
    assert "float(r.warning_level) - float(r.current_value)" in src, (
        "room is tier minus measured, so over the tier is negative")
    assert "float(r.breach_level) - float(r.current_value)" in src


# ── the snapshot answers about the book it was asked about ───────────────────

def test_the_snapshot_reads_a_named_book_and_no_other():
    """It took the newest issuer_exposures row on ANY book, which is the wrong
    book the moment two hold the name — and the demo book is public, so a
    signed-in reader could be shown the demo's money as their own."""
    from apps.api.routes.issuers import snapshot

    src = inspect.getsource(snapshot)
    assert "portfolio: str | None = None" in src, "the book is a parameter"
    assert "get_latest_completed_run(db, portfolio)" in src
    assert "IssuerExposure.run_id == run.id" in src, (
        "the row must be bound to that book's own run")
    assert "order_by(IssuerExposure.created_at.desc())" not in _code(snapshot), (
        "the newest row on any book is the query this endpoint no longer makes")


def test_without_a_book_there_is_no_exposure_to_state():
    from apps.api.routes.issuers import snapshot

    src = inspect.getsource(snapshot)
    assert "exposure = None" in src and "if portfolio:" in src


# ── the balance series reuses the calculation it already performed ───────────

def test_the_balance_read_and_the_recorder_are_two_functions():
    """The reconcile lesson: a version that computed and then decided whether to
    commit could never work, because the session commits at the end of the
    request. The read must not go through the recorder at all."""
    from exposure_workbench.services import fundamentals_service as fs

    read = _code(fs.balance_points)
    assert "cs._record" not in read and "_metric_absence" not in read, (
        "the pure read writes nothing — not a ledger row, not an absence row")
    assert "cs._record" in _code(fs.get_balance_series)


def test_the_endpoint_asks_for_an_existing_row_before_performing_one():
    from apps.api.routes.issuers import balance_series

    src = _code(balance_series)
    assert src.index("find_recorded") < src.index("get_balance_series"), (
        "look the calculation up first; perform it only when there is none")


def test_the_lookup_key_is_a_subset_of_what_the_recorder_writes():
    """Containment can never match a key the record does not carry, so every
    read would mint. The failure is invisible except in the ledger's row count —
    which is how the /reconcile version of this bug was found, a week in."""
    import re

    from exposure_workbench.services import fundamentals_service as fs

    lookup = set(fs.identifying_params_balance_series("MSFT", "revenue", 12, "2026-03-31"))
    recorder = inspect.getsource(fs.get_balance_series)
    params_block = recorder[recorder.index("{**identifying_params_balance_series"):]
    recorded = set(re.findall(r'"(\w+)":', params_block)) | lookup
    assert lookup <= recorded, (
        f"the lookup is keyed on {sorted(lookup - recorded)}, which the record does not "
        "carry — containment can never match and every read will mint a row")
    assert recorded - lookup, (
        "this guard is vacuous unless the record carries more than the lookup")


def test_the_period_the_series_runs_through_is_part_of_its_identity():
    """The same (issuer, metric, last_n) after the next 10-Q is a different
    series. A lookup without it hands the page the id of a calculation that
    stops a quarter short of what it draws."""
    from exposure_workbench.services import fundamentals_service as fs

    after_the_filing = fs.identifying_params_balance_series("MSFT", "revenue", 12, "2026-03-31")
    before_it = fs.identifying_params_balance_series("MSFT", "revenue", 12, "2025-12-31")
    assert after_the_filing != before_it
    assert "through" in after_the_filing
    assert "ticker" not in after_the_filing, (
        "the ticker is the row's own company column, and the lookup passes it "
        "to find_recorded rather than burying it in the params")


def test_the_lookup_is_scoped_to_the_issuer_whose_row_it_wants():
    """The balance series records the ticker in the row's company column and not
    in its params, so containment over params alone matched another issuer's
    row of the same metric."""
    from apps.api.routes.issuers import balance_series
    from exposure_workbench.services import calc_service as cs

    assert "company_ticker" in inspect.signature(cs.find_recorded).parameters
    assert "company_ticker=c.ticker" in inspect.getsource(balance_series)
    assert "CalcLedger.company_id == company_ticker" in inspect.getsource(cs.find_recorded)


# ── the picker decides nothing the desk has not already decided ──────────────

def test_the_views_a_measure_supports_are_derived_from_what_exists():
    """A client that decided for itself whether a measure has a year-on-year
    series would be guessing about the recipe's contents."""
    from exposure_workbench.services import measures_service as ms

    src = inspect.getsource(ms.list_measures)
    assert 'f"{metric}_yoy" in manifest' in src, "yoy exists iff the recipe computed it"
    assert "SHARE_OF_REVENUE.get(metric)" in src, "share exists iff the metric has a margin"
    assert "if share_metric not in manifest" in src, (
        "and iff that margin's row is actually in this issuer's manifest")


def test_the_margin_table_is_read_from_the_recipe_not_restated():
    """A margin added to recipe._MARGIN_NUMERATORS must appear here without an
    edit; a copy of the table is the copy that goes stale."""
    from exposure_workbench.services import measures_service as ms
    from exposure_workbench.services.recipe import _MARGIN_NUMERATORS

    assert ms.SHARE_OF_REVENUE == {num: label for label, num in _MARGIN_NUMERATORS}
    assert ms.SHARE_OF_REVENUE["net_income"] == "net_margin"


def test_a_measure_that_cannot_be_drawn_is_listed_as_unavailable_with_a_reason():
    """NVDA holds two annual revenue facts and no quarterly boundary near them.
    A row that draws an empty chart when clicked is worse than a row that says
    why it cannot be drawn."""
    from exposure_workbench.services import measures_service as ms

    src = _code(ms.list_measures)
    assert "if not available:" in src and "unavailable.append(" in src


def test_the_missing_window_carries_the_engines_own_sentence():
    """"No held filing can reach this window" is a finding (V10 DP2), not an
    absence of data, and it must never be replaced by the twelve-month figure."""
    from exposure_workbench.services import measures_service as ms

    src = inspect.getsource(ms._latest_window)
    assert 'getattr(window, "reason", None)' in src, "the engine's own reason, when it has one"
    assert "months} months apart" in src, "and a sentence about what IS held when it has none"


def test_the_picker_records_nothing():
    from exposure_workbench.services import measures_service as ms

    src = _code(ms)
    assert "_record(" not in src, "the picker reads; it does not perform calculations"
    assert "get_balance_series" not in src, (
        "the recorder is not the way to learn a balance's latest reading")


# ── the windows a client may ask for come from the endpoint ──────────────────

@pytest.mark.parametrize("module_name, endpoint", [
    ("apps.api.routes.portfolios", "get_portfolio_history"),
    ("apps.api.routes.issuers", "price_index"),
])
def test_the_span_list_is_served_rather_than_copied_into_the_client(module_name, endpoint):
    """The client hard-coded `3y` and `1y` — copies of a list that lived in the
    handler, and that outlived the day anyone remembered the other windows."""
    import importlib

    module = importlib.import_module(module_name)
    src = inspect.getsource(getattr(module, endpoint))
    assert '"spans": sorted(_SPANS)' in src


def test_the_run_series_serves_its_own_span_list_too():
    from apps.api.routes.portfolios import get_portfolio_run_series

    assert '"spans": sorted(run_series_service.SPANS)' in inspect.getsource(get_portfolio_run_series)


# ── contribution reaches the wire, and is never called by its bare name ──────

def test_contribution_is_on_the_wire():
    """calc_pnl has computed it and the row has held it since V8; it was the one
    figure a "top contributors" sentence is made of that nothing could check."""
    from apps.api.routes.exposure_runs import IssuerExposureOut

    assert "contribution" in IssuerExposureOut.model_fields


# ── a quotient's reading is declared, never inferred ────────────────────────

def test_the_recipe_declares_how_each_quotient_reads():
    """money ÷ money is a RATIO to the algebra and can be nothing else — net
    margin and current ratio are the same operation on the same units. Which of
    the two readings a named measure has is the registry's to declare
    (analytics/units.REFINEMENTS, V17), and this recipe never asked: every
    current ratio it computed was recorded as a ratio and printed as `128.3%`,
    on the page and to the model alike, because display_conventions is one rule
    shared by both."""
    from exposure_workbench.services import recipe

    src = _code(recipe.run_standard_recipe)
    assert "as_unit_class=as_unit or _reading_of(label)" in src, (
        "the recipe must declare the reading of what it computes")


def test_the_reading_comes_from_the_registry_and_only_when_dimensionless():
    """Declaring `money` on a quotient is not a reading of it: `units.refine`
    would refuse and the row would not be written at all. A producer must not be
    able to turn a correct calculation into a refusal by consulting a table."""
    from exposure_workbench.analytics import units
    from exposure_workbench.services.recipe import _reading_of

    assert _reading_of("current_ratio") == units.MULTIPLE
    assert _reading_of("net_margin") == units.RATIO
    assert _reading_of("free_cash_flow") is None, "money is not a reading of a quotient"
    assert _reading_of("no_such_measure") is None


def test_every_liquidity_and_leverage_quotient_the_recipe_computes_reads_as_a_multiple():
    """The guard that would have caught this one. A current ratio is 1.28×; a
    coverage or leverage quotient served as a percent is the defect V17 named
    and this batch found two more of."""
    import re

    from exposure_workbench.analytics import formulas as fm
    from exposure_workbench.analytics import units
    from exposure_workbench.services import recipe

    src = _code(recipe.run_standard_recipe)
    # ast.unparse normalises string quotes, so the pattern accepts either: the
    # guard reads CODE, and code has no opinion about which quote it was written
    # with.
    called = set(re.findall(r"ratio\(\s*['\"]([a-z_]+)['\"]", src))
    assert {"current_ratio", "cash_to_long_term_debt_noncurrent"} <= called, (
        "this guard is vacuous unless it sees the recipe's own liquidity rows")
    for label in sorted(called):
        formula = fm.FORMULAS.get(label)
        family = formula.family if formula else None
        if family in ("liquidity", "leverage", "coverage", "turnover"):
            assert _declared_unit(src, label) == units.MULTIPLE, (
                f"{label} is a {family} quotient and must read as a multiple")
    # The one the registry does not hold: stated at the call site, and checked
    # here rather than trusted.
    assert _declared_unit(src, "cash_to_long_term_debt_noncurrent") == units.MULTIPLE


def _declared_unit(src: str, label: str) -> str | None:
    """What the recipe will record for `label` — an explicit `as_unit` at the
    call site, or the registry's declaration."""
    import re

    from exposure_workbench.services.recipe import _reading_of

    call = re.search(rf"ratio\(\s*['\"]{label}['\"].*?\)\n", src, re.S)
    if call and "as_unit=" in call.group(0):
        stated = re.search(r"as_unit=units\.([A-Z_]+)", call.group(0))
        if stated:
            from exposure_workbench.analytics import units
            return getattr(units, stated.group(1))
    return _reading_of(label)


# ── a wire type is a claim about the wire ───────────────────────────────────

def test_the_ladders_slot_type_names_the_key_the_server_sends():
    """`WindowSlot` was typed with `end` and the server has always written
    `period_end` (analytics/units.POINT_PERIOD_KEY), so `s.end` was undefined on
    every slot the API had ever returned: the ladder's bars were positioned at
    NaN and its year axis threw on a `.slice` of undefined. TypeScript cannot
    catch this — the JSON arrives as `any` — so the guard is here, where the key
    is defined.

    The check is the shape rather than the file: whichever way the two sides are
    spelled, they must be spelled the same.
    """
    from pathlib import Path

    from exposure_workbench.analytics import units

    charts = (Path(__file__).resolve().parents[1] / "apps/web/lib/charts.ts").read_text()
    slot = charts[charts.index("export type WindowSlot = {"):]
    slot = slot[:slot.index("};")]
    assert f"{units.POINT_PERIOD_KEY}: string" in slot, (
        f"WindowSlot must carry `{units.POINT_PERIOD_KEY}`, which is what "
        f"fundamentals_service._slot writes; it declared: {slot.strip()[:200]}")


def test_the_briefs_endpoint_reports_no_total_it_cannot_see():
    """RLS decides which briefs come back. A count of what the caller cannot see
    would need an unscoped query."""
    from apps.api.routes.issuers import briefs

    src = _code(briefs)
    assert "func.count" not in src and "select(func" not in src
