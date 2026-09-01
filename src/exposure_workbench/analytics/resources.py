"""What this desk holds that can be cited, declared once (V15-S1).

WHY THIS EXISTS. "Which numbers may an answer point at" had four descriptions
that had to agree and no mechanism making them: numeric_verification's
_RUN_CHILDREN (which columns of a run's children carry values, and in what
unit), its _RUN_COUNTS (which children are countable), its _CALC_RESULT_KEYS
(which result keys of which ledger operations are values), and its
_CALC_RATIO_OPS (which operations produce a ratio — a rule mirroring
typed_calculator._result_type, which the comment there admits). A column added
to a table was citable only if someone remembered the first list; a new ledger
operation was typed correctly only if someone remembered the fourth.

They are one fact — a RESOURCE has citable columns, each with a unit and a
reader-facing name — so it is written once here and the rest is derived.

WHAT THIS IS NOT. display_names is a different thing and stays where it is.
This file describes COLUMNS ("factor_attributions.contribution is a ratio called
'contribution'"); display_names describes VALUES ("the factor key `small_cap`
reads 'Small cap'"). A label like `factor_attributions.small_cap.contribution`
is built from both, and collapsing them would put a factor's name and a column's
unit in one table that means two things. The plan's phrasing said four lists
become one; measured against the code it is four becoming two, and this is the
honest split.

THE UNIT IS THE POINT. A citable value without a unit class is a number the gate
must guess about, and guessing is what _COMPATIBLE was widened to survive. Every
column here declares its unit, so the guess has no occasion to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

from exposure_workbench.db.models import (
    ExposureMetrics, FactorAttribution, IssuerExposure, LimitCheck, RiskAlert,
    SectorExposure, StressResult,
)

# The unit classes, named here so this module does not import the gate it feeds.
# numeric_verification asserts they are the same strings (test_resources).
MONEY = "MONEY"
RATIO = "RATIO"
COUNT = "COUNT"


@dataclass(frozen=True)
class Column:
    """One citable column: its name on the row, its unit, and what to call it."""
    name: str
    unit: str
    display: str


@dataclass(frozen=True)
class Resource:
    """A table whose rows a run fans out to.

    `label_column` names the row within the run — a ticker, a scenario, a factor
    — so ten issuer weights do not arrive as ten indistinguishable ratios.
    `count_split` is the ONE column whose distinct values partition the rows,
    which is the whole vocabulary for counting (V8-P4's restraint kept: no
    predicate, no caller-chosen grouping).
    """
    model: type
    label_column: str | None
    columns: tuple[Column, ...]
    count_label: str | None = None
    count_split: str | None = None

    @property
    def table(self) -> str:
        return self.model.__tablename__


def _money(*names: tuple[str, str]) -> tuple[Column, ...]:
    return tuple(Column(n, MONEY, d) for n, d in names)


def _ratio(*names: tuple[str, str]) -> tuple[Column, ...]:
    return tuple(Column(n, RATIO, d) for n, d in names)


# ── a run's children ─────────────────────────────────────────────────────────
#
# Order is table order and stays stable: it decides which label a figure held by
# two rows of one id resolves to (answer_blocks takes the first).
RUN_CHILDREN: tuple[Resource, ...] = (
    Resource(
        ExposureMetrics, None,
        _money(("portfolio_market_value", "market value"), ("daily_pnl", "day P&L"),
               ("gross_exposure", "gross exposure"), ("net_exposure", "net exposure"))
        # V8-P1's ratio group, which includes the regression's own numbers. None
        # is an amount of money; a bare figure is written as COUNT and meets a
        # stored RATIO, so "58 observations" verifies while "58%" does not.
        + _ratio(("daily_return", "day return"), ("gross_exposure_pct", "gross exposure"),
                 ("net_exposure_pct", "net exposure"), ("rolling_vol_30d", "30-day volatility"),
                 ("rolling_vol_60d", "60-day volatility"), ("var_95_1d", "VaR 95% 1-day"),
                 ("expected_shortfall_95", "expected shortfall 95%"),
                 ("max_drawdown", "max drawdown"), ("stress_loss_tech", "stress loss, technology"),
                 ("stress_loss_rates", "stress loss, rates"),
                 ("stress_loss_credit", "stress loss, credit"),
                 ("stress_loss_market", "stress loss, market"),
                 ("attribution_portfolio_return", "attribution return"), ("alpha", "alpha"),
                 ("residual", "residual"), ("model_r_squared", "model R²"),
                 ("observations", "observations"),
                 ("regression_window_days", "regression window, days"),
                 ("max_vif", "max VIF")),
    ),
    Resource(
        IssuerExposure, "ticker",
        _money(("market_value", "market value"), ("daily_pnl", "day P&L"))
        + _ratio(("weight", "weight"), ("weight_change", "weight change"),
                 ("daily_return", "day return"), ("contribution", "contribution")),
        count_label="positions",
    ),
    Resource(
        SectorExposure, "sector",
        _money(("market_value", "market value"))
        + _ratio(("weight", "weight"), ("weight_change", "weight change")),
    ),
    # An unevaluated scenario holds NULLs and contributes no value, which is
    # correct: there is no number to quote.
    Resource(
        StressResult, "scenario",
        _money(("loss_usd", "estimated loss")) + _ratio(("loss_pct", "estimated loss")),
        count_label="stress_scenarios", count_split="status",
    ),
    Resource(
        FactorAttribution, "factor_name",
        _ratio(("beta", "beta"), ("factor_return", "factor return"),
               ("contribution", "contribution"), ("r_squared", "R²")),
        count_label="factors",
    ),
    # A run's own alerts. Requiring them to be cited separately made a citation
    # set assembled by hand out of two kinds of id to describe one run.
    Resource(
        RiskAlert, "alert_type",
        _ratio(("current_value", "measured"), ("limit_value", "limit"),
               ("utilization", "limit used")),
        count_label="alerts",
    ),
    # V13-S5 added the three numbers a check actually saw; V8-P3 had listed this
    # with no value columns and the line was not revisited, so the columns were
    # written and stayed unciteable.
    Resource(
        LimitCheck, "limit_type",
        _ratio(("current_value", "measured"), ("warning_level", "warning tier"),
               ("breach_level", "breach tier")),
        count_label="limit_checks", count_split="fired",
    ),
)


# ── the ledger ───────────────────────────────────────────────────────────────
#
# What an OPERATION computed, at the top level where the resolver reads it. A
# quantity a service records and does not declare here is a number the tool
# produced and the gate will refuse — which is the intended direction: the
# declaration is the promise, not the write.
CALC_RESULTS: dict[str, dict[str, str]] = {
    "portfolio.drawdown_episodes": {"deepest_depth": RATIO, "episode_depths": RATIO},
    "portfolio.reconcile": {
        "sum_of_position_contributions": RATIO, "sum_of_factor_contributions": RATIO,
        "alpha_plus_residual": RATIO, "factor_share": RATIO, "unexplained_share": RATIO,
    },
    # V14-A. The quantities that read DERIVED and only those: a net beta is a sum
    # it performed, a distance to a threshold a subtraction. The stress losses and
    # limit levels it ORDERS are columns above and resolve through the run id.
    "portfolio.integration": {
        "net_beta": RATIO, "gross_beta": RATIO,
        "room_to_warning": RATIO, "room_to_breach": RATIO,
    },
}

# Operations whose single `value` is a ratio rather than the money underneath.
#
# TRANSITIONAL. calc_ledger.unit_class (v15_calc_unit.sql) is the real home: a
# row's unit is a property of the row, not of a list someone must extend when
# they add an operation. This backfills history and types rows written before
# the column existed; test_resources pins that nothing NEW may be added here.
LEGACY_RATIO_OPS: frozenset[str] = frozenset({
    "change.yoy", "change.qoq", "change.pct", "combine.divide",
    "stat.cagr", "window_return", "window_return.relative",
    "calc.scalar.divide", "calc.series.divide", "stat.mean", "stat.stdev",
    "portfolio.reconcile", "portfolio.drawdown_episodes", "portfolio.integration",
})


def column_unit(table: str, column: str) -> str | None:
    for r in RUN_CHILDREN:
        if r.table == table:
            for c in r.columns:
                if c.name == column:
                    return c.unit
    return None


def countable() -> tuple[tuple[type, str, str | None], ...]:
    """The counting vocabulary, derived — (model, label, split)."""
    return tuple((r.model, r.count_label, r.count_split)
                 for r in RUN_CHILDREN if r.count_label)
