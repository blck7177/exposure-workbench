"""One threshold, one place — asserted structurally (offline).

The bug this whole change repairs was not an arithmetic mistake. It was three
copies of the same eight numbers (a YAML, a seed CSV, and 16 literals inside
check_limits' cfg() closure) with no mechanism keeping them equal, plus a
fourth set — the user's own risk_limits rows — that the engine never read.

These tests do not check that the numbers are right. They check that there is
only one of each, and that the engine has no way to reach a number that did not
come from the database.
"""

from __future__ import annotations

import ast
from pathlib import Path

from exposure_workbench.analytics import limits
from exposure_workbench.analytics.limit_defaults import DEMO_OVERRIDES, SEED_DEFAULTS
from exposure_workbench.analytics.limits import LIMIT_SPECS, REQUIRED_LIMIT_TYPES


def test_the_seed_covers_exactly_the_checks_that_exist():
    # Both directions. A check with no seeded row fails every run of a new
    # portfolio; a seeded row for a check that does not exist is how
    # `stress_loss_tech` was served to users as policy in force while nothing
    # ever looked it up.
    assert set(SEED_DEFAULTS) == set(REQUIRED_LIMIT_TYPES)


def test_the_engine_cannot_import_the_seed_numbers():
    """The import direction IS the guarantee — there is nothing else.

    If analytics/limits.py could reach SEED_DEFAULTS, a plausible-looking edit
    would restore exactly the fallback this change deletes, and every test here
    would stay green because the numbers agree.

    Read as an import graph, not as text: the module's own docstring names
    limit_defaults in order to forbid it, and a substring check would call that
    sentence a violation while missing `importlib.import_module` entirely.
    """
    tree = ast.parse(Path(limits.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module or ''}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Call):
            # importlib.import_module("...") / __import__("...")
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in {"import_module", "__import__"}:
                imported.update(a.value for a in node.args
                                if isinstance(a, ast.Constant) and isinstance(a.value, str))

    offenders = sorted(m for m in imported if "limit_defaults" in m)
    assert not offenders, f"the engine must not be able to read a seed number: {offenders}"


def test_every_override_names_a_check_that_is_looked_up_per_entity():
    for limit_type, entity_id in DEMO_OVERRIDES:
        assert limit_type in LIMIT_SPECS, limit_type
        assert LIMIT_SPECS[limit_type].scope == "entity", limit_type
        assert entity_id, f"an override needs an entity: {limit_type}"


def test_a_portfolio_scoped_label_takes_no_entity_and_an_entity_one_requires_it():
    # The alert text is built by formatting the label, so a placeholder in the
    # wrong spec would either print a stray "{entity}" or drop the name.
    for limit_type, spec in LIMIT_SPECS.items():
        has_placeholder = "{entity}" in spec.label
        assert has_placeholder == (spec.scope == "entity"), limit_type
