"""Measures this desk computes and does not publish — declared once (V20).

WHY THIS EXISTS. The 9/2 quant audit sorted every measure on the book page by
three questions: is the method a named, industry-standard one; is its value
pinned by a test; are its inputs free of a known defect. Four measures failed
at least one and were still on the page, in the agent's manifest, in the daily
report and in the limit engine — each surface reading the column directly, so
withholding them meant remembering nine places.

So the decision is written here and every reader derives from it. The
workflow keeps COMPUTING and STORING them (the columns stay, the rows stay,
nothing is dropped from the database) so that validating them later is a
change to this file and not a re-run of history. What changes is that nothing
downstream can see a withheld measure without asking this module, and the
answer it gets is the reason, which is what a reader is owed instead of a
number.

WHAT IS WITHHELD, AND WHY (each reason is the condition for release):

    var_95_1d, expected_shortfall_95
        Historical simulation over the run's own return window. The method is
        standard; the value is pinned by no test, the quantile convention is
        undocumented, and no backtest (Kupiec or otherwise) has been run.
        Release: a hand-computed value test, the quantile convention stated in
        methods.py, one backtest on the demo book recorded in a coverage doc.

    stress_loss_* and the stress_results table
        Scenario shocks propagated linearly through the regression's partial
        betas. The shock sizes in configs/stress_scenarios.yaml are hand-written
        with no source; three of the five scenarios shock SPY/QQQ/IWM by
        DIFFERENT amounts, so their losses depend on individual betas the same
        run flags as collinear (max VIF 17.9 on the live book); factors a
        scenario does not name are held at zero. Release: sourced shocks
        (historical-date replays are the standard alternative) and a factor set
        whose individual betas are determinate.

Not withheld, and why: market value, weights, day P&L, the value path and its
drawdown (accounting identities and a running maximum, tested); rolling
volatility (sample std × √252, tested); the one-regression attribution's
TOTAL, residual and per-holding split (tested for additivity). Individual
factor betas are not withheld here because their condition is data-dependent:
the table already projects them off when the run is collinear (V11-F), and the
API nulls them under the same flag so the page and the agent agree.
"""

from __future__ import annotations

# exposure_metrics columns that are computed, stored, and not published.
WITHHELD_METRICS: dict[str, str] = {
    "var_95_1d": ("withheld pending validation: historical-simulation VaR with no value test, "
                  "an undocumented quantile convention and no backtest"),
    "expected_shortfall_95": ("withheld pending validation: expected shortfall shares VaR's "
                              "unvalidated tail"),
    "stress_loss_tech": "withheld pending validation: see stress_results",
    "stress_loss_rates": "withheld pending validation: see stress_results",
    "stress_loss_credit": "withheld pending validation: see stress_results",
    "stress_loss_market": "withheld pending validation: see stress_results",
}

# Run child tables withheld whole.
WITHHELD_TABLES: dict[str, str] = {
    "stress_results": ("withheld pending validation: scenario shocks are unsourced and "
                       "propagate through individually collinear betas"),
}

# Limit checks that are not evaluated while their input is withheld. The
# limit ROWS stay (a portfolio's policy is its own); the check does not run,
# so no alert and no limit_checks record is written for it.
WITHHELD_CHECKS: dict[str, str] = {
    "var_95": WITHHELD_METRICS["var_95_1d"],
    "expected_shortfall_95": WITHHELD_METRICS["expected_shortfall_95"],
    "stress_loss": WITHHELD_TABLES["stress_results"],
}

# Run groups (resources.RUN_GROUPS) withheld whole from the manifest.
WITHHELD_GROUPS: frozenset[str] = frozenset({"stress"})

# The one sentence a reader or the model sees where a withheld measure used
# to be. It names the state, not a number.
WITHHELD_NOTE = ("Some measures this run computed are withheld pending validation and are "
                 "not published anywhere on this desk: {names}. Say so if asked; do not "
                 "estimate them from other figures.")


def is_withheld_metric(column: str) -> bool:
    return column in WITHHELD_METRICS


def is_withheld_name(name: str) -> bool:
    """A quantity name: `exposure_metrics.var_95_1d`, `stress_results.*.loss_pct`,
    and the count over a withheld table (`count.stress_scenarios`)."""
    table, _, rest = name.partition(".")
    if table in WITHHELD_TABLES:
        return True
    if table == "count" and rest in _WITHHELD_COUNTS:
        return True
    return table == "exposure_metrics" and rest in WITHHELD_METRICS


# The count labels of withheld tables (resources.count_label), spelled here
# rather than imported: resources imports this module.
_WITHHELD_COUNTS: frozenset[str] = frozenset({"stress_scenarios"})


def withheld_note() -> str:
    names = sorted(WITHHELD_METRICS) + sorted(WITHHELD_TABLES)
    return WITHHELD_NOTE.format(names=", ".join(names))


def is_withheld_check(limit_type: str) -> bool:
    """`stress_loss:market_downside` and `var_95` alike: the type before the colon."""
    return limit_type.partition(":")[0] in WITHHELD_CHECKS


def published_alerts(rows):
    """Alert rows minus those a withheld check raised. New runs raise none
    (check_limits skips the check); rows from runs before V20 still exist and
    reach every reader through this one filter."""
    return [a for a in rows if not is_withheld_check(a.alert_type)]


def published_checks(rows):
    """limit_checks rows minus those of withheld checks — same reason."""
    return [c for c in rows if not is_withheld_check(c.limit_type)]
