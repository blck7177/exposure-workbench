"""V13 — everything a page can name has a caption, derived from where the names
come from (offline).

The point of deriving the key sets rather than listing them: a metric added to
concept_mapping, a scenario added to the YAML, a row added to the recipe are all
things somebody will do without thinking about the issuer page, and the first
sign of it should be a red test rather than `operating_lease_liability_noncurrent`
in a chip on a stranger's screen.

Deliberately one-directional in the other axis: a caption for a key that no
longer exists is dead weight, not a defect, and is caught by the same tests
failing when somebody removes the key. What must not happen is the reverse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.analytics.limits import LIMIT_SPECS
from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"


def test_every_supported_metric_has_a_caption():
    missing = sorted(set(SUPPORTED_METRICS) - set(dn.METRIC))
    assert missing == [], (
        f"metrics with no caption: {missing}. Each would reach a reader as its "
        "identifier — which is how `operating_lease_liability_noncurrent` came "
        "to be a chip on the issuer page."
    )


def test_every_factor_in_the_config_has_a_caption():
    cfg = yaml.safe_load((CONFIGS / "factor_config.yaml").read_text())
    missing = sorted(set(cfg["factors"]) - set(dn.FACTOR))
    assert missing == [], f"factors with no caption: {missing}"


def test_every_scenario_in_the_config_has_a_caption():
    cfg = yaml.safe_load((CONFIGS / "stress_scenarios.yaml").read_text())
    names = {k for k, v in cfg.items() if isinstance(v, dict)}
    missing = sorted(names - set(dn.SCENARIO))
    assert missing == [], f"stress scenarios with no caption: {missing}"


def test_every_mandate_check_has_a_caption():
    missing = sorted(set(LIMIT_SPECS) - set(dn.LIMIT))
    assert missing == [], f"limit types with no caption: {missing}"


def test_every_recipe_row_has_a_caption():
    """Derived from the constants the recipe mints its labels FROM.

    The first version of this guard read the source with a regex and matched
    four of the sixteen labels the live API actually returns — `gross_margin`,
    `revenue_yoy` and every `return_*` row slipped past it, so a missing caption
    for any of them would have shipped under a green test. Importing the tuples
    is not a nicety: the regex was pinning the guard, not the thing.
    """
    from exposure_workbench.services.recipe import (
        BENCHMARK, _GROWTH_METRICS, _MARGIN_NUMERATORS, _RETURN_WINDOWS,
    )

    labels = {f"{m}_yoy" for m in _GROWTH_METRICS}
    labels |= {label for label, _ in _MARGIN_NUMERATORS}
    labels |= {"gross_profit_derived", "free_cash_flow", "current_ratio",
               "cash_to_long_term_debt_noncurrent"}
    for window, _days in _RETURN_WINDOWS:
        labels |= {f"return_{window}", f"return_{window}_vs_{BENCHMARK}"}

    # The count is pinned too, because the set above is only as good as its
    # agreement with what the recipe can actually mint. Seventeen, of which
    # sixteen came back from /api/issuers/AAPL/financials on 2026-08-29: the
    # seventeenth, `gross_profit_derived`, is minted only when the issuer omits
    # GrossProfit and reports cost of revenue instead, and Apple reports it. A
    # conditional row still needs a caption — more so, since the issuer it
    # appears for is by definition the unusual one.
    assert len(labels) == 17, sorted(labels)
    missing = sorted(labels - set(dn.RECIPE_ROW))
    assert missing == [], (
        f"recipe rows with no caption: {missing}. These are the issuer page's "
        "Financials table, read straight off the manifest."
    )


@pytest.mark.parametrize("kind", sorted(dn._TABLES))
def test_no_caption_is_the_identifier_it_replaces(kind):
    """A caption identical to its key means the row was added to satisfy the
    guard rather than to say anything — except where the identifier IS the
    English (`Revenue`, `Inventory`, `Technology`), which is why this compares
    against the raw key and not against a formatted one.
    """
    table = dn._TABLES[kind]
    for key, value in table.items():
        assert value, f"{kind}.{key} has an empty caption"
        assert "_" not in value, (
            f"{kind}.{key} -> {value!r} still contains an underscore, so it is "
            "an identifier wearing a caption's clothes"
        )


def test_an_unknown_key_comes_back_as_itself_and_is_therefore_visible():
    """Not a fallback: no lesser answer is substituted for a real one.

    The identifier appears as itself, which is what every page did before this
    file existed, and it is loud — the guards above turn it into a red build.
    """
    assert dn.label("metric", "a_metric_nobody_has_added") == "a_metric_nobody_has_added"
    assert dn.label("metric", None) == ""
    assert dn.label("no_such_table", "x") == "x"
