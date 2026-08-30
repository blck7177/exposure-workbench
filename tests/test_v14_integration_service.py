"""V14-A — the read, the row it mints, and the gate's side of the bargain (offline).

The arithmetic itself is held by test_v14_integration. Here: that what this
service DERIVES can be quoted, that what it merely ORDERS is not recorded a
second time, and that the tool is on the face it says it is on.
"""

from __future__ import annotations

import inspect

from exposure_workbench.services import integration_service as isvc
from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


def test_the_ledger_operation_is_typed_as_a_ratio():
    """The V8-B failure, one op later: an operation missing from _CALC_RATIO_OPS
    is typed MONEY, and the gate refuses the figure the tool itself produced
    while the refusal reads as the model having invented it."""
    assert isvc.OP_INTEGRATION in nv._CALC_RATIO_OPS


def test_every_derived_quantity_is_declared_with_a_unit():
    """A quantity this read computes and does not declare is a number the tool
    produced that nothing can cite — V8-C ④'s episode depths, exactly."""
    declared = set(nv._CALC_RESULT_KEYS[isvc.OP_INTEGRATION])
    assert declared == {"net_beta", "gross_beta", "room_to_warning", "room_to_breach"}
    assert all(u == nv.RATIO for u in nv._CALC_RESULT_KEYS[isvc.OP_INTEGRATION].values())


def test_what_is_only_ordered_is_not_recorded_again():
    """The stress losses, the betas and the limit levels resolve through the run
    id already. Recording them here would build a second, weaker path to the
    same evidence — reconcile_service's rule, and the reason its docstring says
    so. A stress loss appearing in the ledger row is this test's failure."""
    declared = set(nv._CALC_RESULT_KEYS[isvc.OP_INTEGRATION])
    # Whole names, not substrings: net_beta IS derived and contains "beta".
    for forbidden in ("loss_pct", "beta", "weight", "contribution",
                      "warning_level", "breach_level", "current"):
        assert forbidden not in declared


def test_the_labelled_family_resolves_with_its_label():
    """Four net betas and eight distances must not read alike. The label is the
    risk or the check; a positional one would leave a refusal unable to say
    which of them the answer nearly matched (_RUN_CHILDREN's reason for its
    label column, one layer over)."""
    row = type("Row", (), {
        "operation": isvc.OP_INTEGRATION,
        "params": {},
        "result": {"net_beta": [{"label": "rates_up", "value": -1.1},
                                {"label": "equity_down", "value": -0.9}],
                   "quality_flags": {}},
    })()
    values: list = []
    for key, unit in nv._CALC_RESULT_KEYS[row.operation].items():
        kv = row.result.get(key)
        for item in (kv if isinstance(kv, list) else [kv]):
            if isinstance(item, dict) and isinstance(item.get("value"), (int, float)):
                values.append((f"{row.operation}.{key}.{item['label']}", item["value"], unit))
    labels = {v[0] for v in values}
    assert "portfolio.integration.net_beta.rates_up" in labels
    assert "portfolio.integration.net_beta.equity_down" in labels


def test_an_entry_without_a_number_contributes_nothing():
    """The declared shape is closed: a dict that is not {label, value} is not a
    licence to walk arbitrary structure, which is what the declaration table
    exists to prevent."""
    kept = [e for e in [{"label": "x"}, {"value": 1.0}, {"label": "y", "value": 2.0}]
            if isinstance(e.get("value"), (int, float)) and isinstance(e.get("label"), str)]
    assert kept == [{"label": "y", "value": 2.0}]


def test_the_tool_is_on_the_meta_face_and_not_the_research_face():
    """It answers a question about THIS DESK's book, which is the whole of the
    reason the meta-only block exists."""
    assert "get_portfolio_analysis" in faces.FACE_META_AGENT
    assert "get_portfolio_analysis" not in faces.FACE_RESEARCH


def test_the_meta_face_resolves_with_the_new_tool_on_it():
    """A face naming a tool its registry does not have is a build error, not a
    smaller face — the bug that shipped silently for two phases. Both faces are
    resolved because both are built from the same read registry: the narrowing
    is the face's job, and a tool added to the wrong list would still resolve
    while answering the wrong agent (which the test above holds)."""
    assert "get_portfolio_analysis" in faces.resolve(build_meta_registry(),
                                                     faces.FACE_META_AGENT)
    assert "get_portfolio_analysis" not in faces.resolve(build_research_registry(),
                                                         faces.FACE_RESEARCH)


def test_there_is_no_top_k():
    """A ranking that names the three worst scenarios leaves a reader unable to
    tell whether the fourth was 0.1% or 7%. The whole-set rule is why the answer
    can be ordered at all."""
    # The code, not the prose: the docstring says the word in order to forbid it.
    code = "\n".join(ln for ln in inspect.getsource(isvc).splitlines()
                     if not ln.strip().startswith("#"))
    assert "top_k=" not in code
    assert ".limit(" not in code


def test_an_unmeasured_risk_is_said_rather_than_omitted():
    """A payload that simply lacks the key reads as a book with no exposure to
    that risk. stress.py's rule for an unevaluated scenario, one layer up."""
    src = inspect.getsource(isvc)
    assert '"measured": False' in src
    assert "risks_unmeasured" in src


def test_a_run_still_going_is_refused_rather_than_ranked():
    """Half-written children produce a ranking that changes under the reader."""
    src = inspect.getsource(isvc)
    assert "run_not_completed" in src
