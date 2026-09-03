"""V20 — what the desk computes and does not publish is decided once (offline).

The 9/2 quant audit sorted every measure on the book page by three questions —
a named standard method, a value pinned by a test, inputs free of a known
defect — and four measures failed one and were on the page anyway: VaR and
expected shortfall (no value test, no backtest), the stress losses (unsourced
shocks through collinear betas). Hiding them in the UI would have left them in
the agent's manifest, the daily report and the limit engine; so the decision
is analytics/withheld.py and every reader derives from it. The workflow still
computes and stores them, so release is an edit to that file.

Also here: the method statements the page shows behind an ⓘ come from the
server (analytics/methods.py) and quote the code's own constants; the
portfolio volatility the run reports is pinned to a hand computation, which
it never was.
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pandas as pd
import pytest

from exposure_workbench.analytics import methods as mt
from exposure_workbench.analytics import resources as R
from exposure_workbench.analytics import risk_metrics as rm
from exposure_workbench.analytics import withheld as wh
from exposure_workbench.services import quantities as qn
from exposure_workbench.tools.registries import build_meta_registry


# ── one decision, derived everywhere ─────────────────────────────────────────

def test_a_withheld_column_is_absent_from_the_published_resources_and_present_in_the_declaration():
    published = {f"{r.table}.{c.name}" for r in R.RUN_CHILDREN for c in r.columns}
    declared = {f"{r.table}.{c.name}" for r in R._DECLARED for c in r.columns}
    for col in wh.WITHHELD_METRICS:
        assert f"exposure_metrics.{col}" not in published, col
        assert f"exposure_metrics.{col}" in declared, "withheld is not deleted"
    assert all(r.table not in wh.WITHHELD_TABLES for r in R.RUN_CHILDREN)
    assert any(r.table == "stress_results" for r in R._DECLARED)


def test_the_manifest_groups_carry_no_withheld_name():
    keys = [k for k, _, _ in R.RUN_GROUPS]
    assert not (set(keys) & wh.WITHHELD_GROUPS)
    for _key, _q, names in R.RUN_GROUPS:
        for n in names:
            assert not wh.is_withheld_name(n), n
    assert "stress" in [k for k, _, _ in R._DECLARED_GROUPS]


def test_run_tables_the_gate_can_resolve_exclude_the_withheld_table():
    assert "stress_results" not in qn.RUN_TABLES
    assert "exposure_metrics" in qn.RUN_TABLES


def test_no_tool_declares_a_scope_over_a_withheld_table():
    reg = build_meta_registry()
    for name, tool in reg.tools.items():
        ev = tool.evidence
        if ev is None:
            continue
        assert not (set(ev.scope) & set(wh.WITHHELD_TABLES)), name


def test_the_api_models_carry_no_withheld_field():
    from apps.api.routes import exposure_runs as api
    fields = set(api.ExposureMetricsOut.model_fields)
    assert not (fields & set(wh.WITHHELD_METRICS)), fields & set(wh.WITHHELD_METRICS)
    assert {"methods", "withheld"} <= set(api.ExposureRunOut.model_fields)


def test_every_reader_that_used_to_serve_a_withheld_measure_now_asks_withheld_py():
    """Source pins over the nine readers the audit found. A tenth reader that
    reaches for the column directly is the failure this guards against; add
    it here when it is written."""
    from exposure_workbench.agents import direct_llm_agent
    from exposure_workbench.services import integration_service, portfolio_service, run_reads_service
    from exposure_workbench.tools import definitions
    from exposure_workbench.workflow import exposure_workflow
    from apps.api.routes import exposure_runs, portfolios
    for mod in (run_reads_service, integration_service, exposure_runs, portfolios,
                exposure_workflow, portfolio_service, definitions):
        assert "withheld" in inspect.getsource(mod), mod.__name__
    # Alerts and checks raised by a withheld check before V20 still exist as
    # rows; every reader of them goes through the two filters.
    assert "published_alerts" in inspect.getsource(qn._from_run) and "published_checks" in inspect.getsource(qn._from_run), \
        "the table itself is a reader: a run's alert and check rows"
    for mod, fn in ((portfolio_service, "published_alerts"), (run_reads_service, "published_alerts"),
                    (run_reads_service, "published_checks"), (integration_service, "published_checks"),
                    (exposure_runs, "published_checks"), (exposure_runs, "is_withheld_check"),
                    (portfolios, "published_alerts"), (definitions, "published_alerts")):
        assert fn in inspect.getsource(mod), (mod.__name__, fn)
    assert "var_95_1d is not None" in inspect.getsource(direct_llm_agent._build_user_message)


def test_the_entry_point_and_the_manifest_carry_the_withheld_sentence():
    from exposure_workbench.tools import definitions
    assert "withheld_note()" in inspect.getsource(definitions._get_portfolio_snapshot)
    assert "withheld_pending_validation" in inspect.getsource(definitions)
    assert any("withholds" in c for c in definitions._FACE_CAPABILITIES["cannot"])


def test_withheld_check_filters_read_the_type_before_the_colon():
    class Row:
        def __init__(self, t): self.alert_type = t; self.limit_type = t
    rows = [Row("stress_loss:market_downside"), Row("var_95"), Row("daily_loss"), Row("issuer_concentration:AAPL")]
    assert [r.alert_type for r in wh.published_alerts(rows)] == ["daily_loss", "issuer_concentration:AAPL"]
    assert [r.limit_type for r in wh.published_checks(rows)] == ["daily_loss", "issuer_concentration:AAPL"]


def test_the_withheld_sentence_names_every_withheld_measure():
    note = wh.withheld_note()
    for name in list(wh.WITHHELD_METRICS) + list(wh.WITHHELD_TABLES):
        assert name in note
    assert "do not estimate" in note


def test_every_reason_states_the_release_condition_in_the_module_docstring():
    doc = wh.__doc__
    for word in ("Release:", "var_95_1d", "stress_results", "backtest"):
        assert word in doc


# ── the ⓘ text comes from the code ───────────────────────────────────────────

def test_method_statements_quote_the_codes_own_constants():
    assert f"√{rm._TRADING_DAYS_PER_YEAR}" in mt.METHODS["volatility"]
    assert "ddof=1" in mt.METHODS["volatility"]
    assert "VIF above 5" in mt.METHODS["attribution"]
    from exposure_workbench.analytics import factor_model as fm
    assert fm._VIF_THRESHOLD == 5.0


def test_no_method_statement_describes_a_withheld_measure():
    text = " ".join(mt.METHODS.values()).lower()
    for word in ("var", "value at risk", "expected shortfall", "stress", "scenario"):
        assert word not in text, word


def test_the_page_no_longer_carries_its_own_method_strings():
    """The tiles used to hard-code a `basis` sentence each; now they read the
    server's. A string literal beside `basis=` is the regression."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "apps" / "web" / "app" / "components" / "book" / "sections.tsx"
    text = src.read_text()
    assert 'basis="' not in text
    assert "var_95" not in text and "expected_shortfall" not in text


# ── the volatility the run reports, pinned by hand ───────────────────────────

def test_portfolio_rolling_volatility_matches_the_hand_computation():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 0.01, 80), index=pd.bdate_range("2026-01-05", periods=80))
    out = rm.calc_risk_metrics(r)
    arr = r.to_numpy()
    by_hand_30 = float(np.std(arr[-30:], ddof=1) * math.sqrt(252))
    by_hand_60 = float(np.std(arr[-60:], ddof=1) * math.sqrt(252))
    assert out.vol_30d == pytest.approx(by_hand_30, rel=1e-12)
    assert out.vol_60d == pytest.approx(by_hand_60, rel=1e-12)
    # And the drawdown, from the running maximum of the compounded path.
    cum = (1 + r).cumprod()
    assert out.max_drawdown == pytest.approx(float(abs((cum / cum.cummax() - 1).min())), rel=1e-12)


def test_a_count_of_observations_is_a_count_not_a_ratio():
    """"75000.0% observations over a 75000.0%-day window" — the default
    question's answer on the V20 stack. Declared COUNT now, and a COUNT column
    reaches the table like the other two kinds."""
    from exposure_workbench.analytics import display_conventions as dc
    assert R.column_unit("exposure_metrics", "observations") == R.COUNT
    assert R.column_unit("exposure_metrics", "regression_window_days") == R.COUNT
    assert any(cols for _m, _a, _r, cols, _l, _q in qn._RUN_CHILDREN), "count columns reach the table"
    assert dc.display(750.0, "COUNT") == "750"
