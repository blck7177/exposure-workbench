"""V8-P2/P3 — the run's own findings become rows (offline).

Two computations in this pipeline produce their most load-bearing output into a
place nothing can cite:

  * `calc_stress` records `factors_held_flat` per scenario — the factors the
    model HAS a beta for and the scenario says nothing about. Holding them at
    zero is an assertion ("credit does not move in an equity crash"), not an
    absence of one, and on the live book market_downside holds HYG flat while
    HYG carries the second-largest beta the book has. It reached
    workflow_events.payload_summary and stopped there.
  * `check_limits` returns `(alerts, evaluated)`. The alerts become rows. The
    evaluated list — the checks that RAN AND DID NOT FIRE — became nothing, so
    "we checked all eight and six were clear" was a claim the agent could make
    and could not support.

`workflow_events` is not a run child in the evidence resolver and has no id
prefix, so neither could ever be cited. Rows fix that; the payload_summary
writes stay, because the run panel in the web app reads them and two consumers
with different needs are allowed two carriers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from exposure_workbench.db.models import LimitCheck, StressResult as StressResultRow
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import numeric_verification as nv

ROOT = Path(__file__).resolve().parents[1]
INIT_SQL = (ROOT / "infra" / "init.sql").read_text()
MIGRATION = (ROOT / "infra" / "migrations" / "v8_skill_reads.sql").read_text()


# ── P2: stress ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("column", [
    "run_id", "scenario", "description", "shocks", "loss_pct", "loss_usd",
    "factors_held_flat", "status", "reason",
])
def test_a_scenario_is_a_row(column):
    assert column in StressResultRow.__table__.columns


def test_an_unevaluated_scenario_cannot_carry_a_loss():
    """The whole reason this table exists rather than a nullable column on the
    metrics row. `calc_stress` refuses to evaluate a scenario when any factor it
    shocks has no beta, because dropping the unknown legs and summing the rest
    understates the loss silently — and understating a stress loss is the one
    direction that matters. Storing that scenario with loss 0.0 would undo the
    refusal at the last step: 'no beta for TLT' would read as 'this book is safe
    in a rates shock'.

    A CHECK constraint rather than a convention, in all three schemas, because a
    convention is what the writer remembers and a constraint is what the
    database enforces.
    """
    ddl = str(StressResultRow.__table__.constraints)
    assert "unevaluated" in ddl and "loss_pct" in ddl, (
        "no CHECK tying status='unevaluated' to a NULL loss"
    )
    for name, body in (("init.sql", INIT_SQL), ("migration", MIGRATION)):
        assert re.search(r"CHECK[^)]*unevaluated", body, re.S), f"{name}: CHECK missing"


def test_the_scenario_carries_the_shocks_it_applied():
    """Same lesson as V8-P1's window: the persister must not re-read the config
    to find out what was shocked. A config reloaded between compute and write —
    or a lookup keyed on the wrong scenario — records shocks that were never
    applied, and the row would look perfectly well-formed."""
    from exposure_workbench.analytics.stress import ScenarioResult
    assert "shocks" in ScenarioResult.__dataclass_fields__


def test_a_scenarios_loss_is_citable_under_the_run():
    entry = next((m, money, ratio, label) for m, money, ratio, label, _qual in qn._RUN_CHILDREN
                 if m is StressResultRow)
    _model, money, ratio, label = entry
    assert "loss_usd" in money and "loss_pct" in ratio
    assert label == "scenario", "the label has to name the scenario or ten losses look alike"


# ── P3: limit checks ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("column", ["run_id", "limit_type", "fired", "alert_id"])
def test_a_limit_check_is_a_row(column):
    assert column in LimitCheck.__table__.columns


def test_the_checks_that_did_not_fire_are_recorded_too():
    """An affirmative negative is the point. `check_limits` already returns the
    evaluated list; without rows, "we checked eight limits and six were clear"
    is unsupportable, while "three alerts" is supportable — so the reassuring
    half of the answer was the unciteable half."""
    assert "fired" in LimitCheck.__table__.columns
    col = LimitCheck.__table__.columns["fired"]
    assert not col.nullable, "a check either fired or did not; there is no third state"


# ── all three schemas ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["stress_results", "limit_checks"])
def test_all_three_schemas_carry_the_table(table):
    assert f"CREATE TABLE IF NOT EXISTS {table}" in INIT_SQL
    assert f"CREATE TABLE IF NOT EXISTS {table}" in MIGRATION


@pytest.mark.parametrize("table", ["stress_results", "limit_checks"])
def test_the_new_tables_are_tenant_scoped_like_their_siblings(table):
    """A run child with no policy is readable by every tenant. issuer_exposures
    and sector_exposures are scoped through the run to the portfolio; these two
    hold the same class of information and get the same policy in both files."""
    for name, body in (("init.sql", INIT_SQL), ("migration", MIGRATION)):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in body, f"{name}: RLS not enabled"
        assert re.search(rf"CREATE POLICY tenant ON {table}", body), f"{name}: no tenant policy"
