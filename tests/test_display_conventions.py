"""V15-S6 — one rule for how a number looks, held on both sides of the wire.

Three surfaces show the same figure (the renderer, the stored prose, the table
the model reads) and each used to round on its own. The rule is data in
analytics/display_conventions.py; apps/web/lib/display.ts mirrors it; and one
fixture — tests/fixtures/display_cases.json — is what both suites read. A
change to either side the other does not mirror fails one of them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exposure_workbench.analytics import display_conventions as dc

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "display_cases.json"
TS_MIRROR = ROOT / "apps" / "web" / "lib" / "display.ts"
UNIT_CLASSES = ("RATIO", "PERCENT", "MONEY", "MONEY_PER_SHARE", "MULTIPLE", "COUNT")

CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[f"{c['unit_class']}:{c['value']}" for c in CASES])
def test_display_reads_as_the_fixture_says(case):
    assert dc.display(case["value"], case["unit_class"]) == case["display"]


@pytest.mark.parametrize("case", CASES, ids=[f"{c['unit_class']}:{c['value']}" for c in CASES])
def test_reader_value_is_the_fixture_value_with_the_fixture_type(case):
    """An int in the fixture is an int on the table: `27` positions, not `27.0`,
    because the model reads it back as a count."""
    got = dc.reader_value(case["value"], case["unit_class"])
    assert got == case["reader_value"]
    assert type(got) is type(case["reader_value"]), (got, case["reader_value"])


def test_the_fixture_covers_every_unit_class():
    covered = {c["unit_class"] for c in CASES}
    assert set(UNIT_CLASSES) <= covered, sorted(set(UNIT_CLASSES) - covered)
    assert covered <= set(UNIT_CLASSES), "a unit class the display rule does not know"


@pytest.mark.parametrize("value,unit", [
    (1.5e-7, "RATIO"), (8.4e10, "MONEY"), (2.3e12, "MONEY"), (1e-9, "PERCENT"),
    (123456789.123, "COUNT"), (1e-5, "MULTIPLE"), (1.5e-7, "MONEY_PER_SHARE"),
])
def test_no_surface_ever_shows_scientific_notation(value, unit):
    """"科学计数法零出口": the model reads the table as figures, the person
    reads the answer as figures, and neither is handed 1.5e-07."""
    assert "e" not in dc.display(value, unit).lower()
    assert "e" not in repr(dc.reader_value(value, unit)).lower()


@pytest.mark.xfail(not TS_MIRROR.exists(), strict=False,
                   reason="apps/web/lib/display.ts is created by the S6 web lane; absent at authoring time")
def test_the_web_mirror_exists_and_names_the_same_unit_classes():
    """The TypeScript side is the other half of the lock; its vitest suite reads
    the same fixture. Until it lands this is an expected failure, not a green."""
    assert TS_MIRROR.exists(), TS_MIRROR
    src = TS_MIRROR.read_text()
    for unit in UNIT_CLASSES:
        assert unit in src, f"display.ts does not handle {unit}"
