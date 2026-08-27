"""V10-S3 — the baseline recipe on the series primitives (offline).

The recipe is the one consumer of the old series path that was not a tool: the
issuer page's Financials tab reads what it writes. Migrating it is what makes
S4's deletion possible, and these pin the two things that must stay true.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from exposure_workbench.services import recipe

ROOT = Path(__file__).resolve().parents[1]


def test_the_recipe_no_longer_reaches_the_ladder():
    """The import graph, not a grep: a comment may say 'period_ladder'."""
    tree = ast.parse((ROOT / "src/exposure_workbench/services/recipe.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported |= {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert not any("period_ladder" in m for m in imported), imported
    src = inspect.getsource(recipe)
    for gone in ("cs.series(", "cs.change(", "cs.combine(", "cs.stat(", "SeriesSpec"):
        assert gone not in src, f"recipe still calls the v1 series path: {gone}"


def test_the_label_set_is_unchanged():
    """The one promise of S3: the Financials tab shows the same rows under the
    same names. Values may change where the ladder was wrong; the set may not."""
    src = inspect.getsource(recipe.run_standard_recipe)
    for label in ("_yoy", "gross_profit_derived", "free_cash_flow", "current_ratio",
                  "cash_to_long_term_debt_noncurrent", "return_", "_vs_"):
        assert label in src, label
    assert recipe._GROWTH_METRICS == ("revenue", "operating_income", "net_income", "operating_cash_flow")
    assert [m for m, _ in recipe._MARGIN_NUMERATORS] == ["gross_margin", "operating_margin", "net_margin"]


def test_an_unavailable_metric_is_an_entry_with_a_reason_not_a_gap():
    """Unchanged from v1, and now a shape check rather than an except clause:
    the primitives return their refusals, they do not raise."""
    out = recipe._unavailable("x", {"error": "not_reported", "detail": "why"})
    assert out == {"unavailable": True, "reason": "not_reported: why"}
    src = inspect.getsource(recipe.run_standard_recipe)
    assert "except" not in src


def test_the_recipe_ends_with_one_manifest_row():
    """The financials route reads this rather than scanning by operation name.
    A v2 yoy row's `series` param is the id of the series it was taken over —
    a different id every run — so 'latest row per metric' had nothing stable
    to key on. The manifest names each label's row."""
    src = inspect.getsource(recipe.run_standard_recipe)
    assert "OP_MANIFEST" in src and '"labels": labels' in src
    assert recipe.OP_MANIFEST == "recipe.manifest"
    assert recipe.RECIPE_VERSION == "v2"


def test_the_route_reads_the_manifest_and_nothing_else():
    tree = ast.parse((ROOT / "apps/api/routes/issuers.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "financials")
    attrs = {f"{a.value.id}.{a.attr}" for a in ast.walk(fn)
             if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name)}
    assert "CalcLedger.operation" in attrs and "CalcLedger.id" in attrs
    assert "CalcLedger.invoked_by" not in attrs, "the route must not scan the ledger by invoker"
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "OP_MANIFEST" in names
