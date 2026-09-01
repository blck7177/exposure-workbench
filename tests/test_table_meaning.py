"""V16 (M2) — the table carries meaning, not only names.

Three closures of the same gap: the model was shown WHAT a figure is called and
its value, and nothing about what question it answers or why a name it expected
is missing. So (1) a payload entry is now `name: [value, group]` with one legend
of the groups' questions per payload; (2) the group vocabulary is the closed set
resources.GROUP_QUESTIONS, stamped where the quantity is named; (3) the reason a
collinear coefficient is projected off the table — written on the row since
V11-F — finally reaches the model, as the `detail` of the same `unknown_name`
refusal it always got. No new error class: the class stays, the sentence gets
true.
"""

from __future__ import annotations

from types import SimpleNamespace

from exposure_workbench.analytics import resources
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import resolver
from exposure_workbench.services import table as tb


def _q(value, unit, label, ref, table=None, not_alone=None, group="other"):
    return qn.Quantity(value, unit, label, ref, not_alone, table, group)


class _Db:
    """A db whose every execute() resolves to one row — enough for the
    single-select _from_* readers."""

    def __init__(self, row):
        self._row = row

    async def execute(self, _stmt):
        row = self._row
        return SimpleNamespace(scalar_one_or_none=lambda: row)


# ── the payload: [value, group] plus one legend ───────────────────────────────

def _table() -> tb.Table:
    t = tb.Table()
    t.refs = {"run_1"}
    t.rows = {"run_1": "run"}
    t.quantities = {"run_1": {
        "issuer_exposures.MSFT.weight": _q(0.1633512, qn.RATIO, "issuer_exposures.MSFT.weight",
                                           "run_1", "issuer_exposures", group="concentration"),
        "exposure_metrics.portfolio_market_value": _q(10869311, qn.MONEY,
                                                      "exposure_metrics.portfolio_market_value",
                                                      "run_1", "exposure_metrics", group="book"),
    }}
    return t


def test_a_payload_entry_is_value_and_group_with_the_legend_read_first():
    out = tb._payload(_table(), ["run_1"])
    assert out["quantities"]["run_1"] == {
        "issuer_exposures.MSFT.weight": [0.1634, "concentration"],
        "exposure_metrics.portfolio_market_value": [10869311, "book"],
    }
    assert list(out)[0] == "groups", "the legend comes before the names it explains"
    # The legend's text is the resources' own question, verbatim — one owner.
    assert out["groups"] == {"book": resources.GROUP_QUESTIONS["book"],
                             "concentration": resources.GROUP_QUESTIONS["concentration"]}


def test_the_legend_lists_only_used_groups_and_a_figureless_payload_has_none():
    out = tb._payload(_table(), ["run_1"])
    assert "counts" not in out["groups"], "the legend is the slice's, not the vocabulary's"
    t = tb.Table()
    t.refs, t.rows, t.passages = {"chunk_1"}, {"chunk_1": "passage"}, {"chunk_1": "text"}
    assert "groups" not in tb._payload(t, ["chunk_1"])


def test_run_names_fall_in_their_declared_groups():
    assert resources.group_of("issuer_exposures.MSFT.weight") == "concentration"
    assert resources.group_of("count.positions") == "counts"
    assert resources.group_of("factor_attributions.sum_of_contributions") == "factor_exposure"
    assert resources.group_of("portfolio.integration.room_to_warning.sector_max") == "mandate"
    assert resources.group_of("no.such.name") is None, "None: the caller decides from the row"


# ── the projection's reason reaches the model ─────────────────────────────────

async def test_a_projected_names_refusal_carries_the_rows_own_reason(monkeypatch):
    reason = ("these factors are collinear, so no single beta is determined; "
              "their sum, 0.00310000, is")

    async def fake_of_ref(db, ref):
        assert ref == "run_1"
        return qn.Resolved((
            _q(0.42, qn.RATIO, "factor_attributions.market.beta", "run_1",
               "factor_attributions", not_alone=reason),
            _q(0.0031, qn.RATIO, "factor_attributions.sum_of_contributions", "run_1",
               "factor_attributions", group="factor_exposure"),
        ), frozenset(), "run")
    monkeypatch.setattr(qn, "of_ref", fake_of_ref)

    t = tb.Table()
    await tb._place(None, t, {"type": "run", "id": "run_1", "scope": ["factor_attributions"]})
    # The builder still projects the coefficient — and now remembers why.
    assert t.names("run_1") == ["factor_attributions.sum_of_contributions"]
    assert t.projected_reason("run_1", "factor_attributions.market.beta") == reason
    # And the projected name's group travels into the payload like any other's.
    out = tb._payload(t, ["run_1"])
    assert out["quantities"]["run_1"]["factor_attributions.sum_of_contributions"] == [0.0031, "factor_exposure"]

    v = resolver.resolve_against(
        [{"type": "paragraph", "runs": ["beta ", {"ref": "run_1", "name": "factor_attributions.market.beta"}]}], t)
    assert v.error == "unknown_name", "no new error class — the detail changes, the class does not"
    [p] = v.problems
    assert p["reason"] == "unknown_name"
    assert p["detail"] == reason, "the row's sentence, not a bare 'use one of the names'"
    assert p["available"] == ["factor_attributions.sum_of_contributions"]


async def test_a_name_never_projected_keeps_the_standing_unknown_name_detail(monkeypatch):
    async def fake_of_ref(db, ref):
        return qn.Resolved((_q(0.16, qn.RATIO, "issuer_exposures.MSFT.weight", "run_1",
                               "issuer_exposures", group="concentration"),), frozenset(), "run")
    monkeypatch.setattr(qn, "of_ref", fake_of_ref)
    t = tb.Table()
    await tb._place(None, t, {"type": "run", "id": "run_1", "scope": ["issuer_exposures"]})
    v = resolver.resolve_against(
        [{"type": "paragraph", "runs": ["w ", {"ref": "run_1", "name": "weight"}]}], t)
    assert v.error == "unknown_name"
    assert v.problems[0]["detail"] == "use one of the names this id holds on the table"


# ── facts: one unit judgement, and garbage units leave a citable trace ────────

def _fact_row(value, unit):
    return SimpleNamespace(value=value, unit=unit, normalized_metric="eps_diluted",
                           raw_concept=None, period_end="2026-03-31")


async def test_an_eps_fact_is_money_per_share_grouped_as_price():
    r = await qn._from_fact(_Db(_fact_row(2.176, "USD per Share")), "fact_1")
    [q] = r.quantities
    assert q.unit_class == qn.MONEY_PER_SHARE
    assert q.group == "price"
    assert q.label == "eps_diluted@2026-03-31"


async def test_a_fact_with_no_algebra_unit_is_citable_but_holds_no_figure():
    """units.fact_unit says None for a segment count / MWh / jobs: no algebra,
    no figure. The row stays on the table — citable — and a slot naming it gets
    the standing 'cited, not slotted' answer rather than a silent absence."""
    r = await qn._from_fact(_Db(_fact_row(7.0, "segment")), "fact_2")
    assert r.kind == "fact" and r.quantities == ()
    t = tb.Table()
    t.refs, t.rows = {"fact_2"}, {"fact_2": "fact"}
    v = resolver.resolve_against(
        [{"type": "paragraph", "runs": ["segments ", {"ref": "fact_2", "name": "segments@2026-03-31"}]}], t)
    assert v.error == "unknown_name"
    assert v.problems[0]["detail"] == "this id holds no figures; it can be cited, not slotted"


# ── calc rows: formula measures are derived, reads are fundamentals ───────────

def _calc_row(op, result, params=None, unit_class=None):
    return SimpleNamespace(operation=op, result=result, params=params or {}, unit_class=unit_class)


async def test_a_formula_measure_is_derived_and_a_flow_read_is_fundamentals():
    r = await qn._from_calc(_Db(_calc_row(
        "calc.scalar.divide", {"value": 0.3512},
        {"result_type": {"unit_class": "ratio", "quantity": "net_margin"}})), "calc_1")
    [q] = r.quantities
    assert (q.label, q.group) == ("net_margin", "derived"), "net_margin is a registry formula"

    r = await qn._from_calc(_Db(_calc_row(
        "flow.series", {"points": [{"value": 1.0, "period_end": "2026-03-31"}]},
        {"result_type": {"unit_class": "money", "quantity": "revenue"}})), "calc_2")
    assert r.quantities and all(q.group == "fundamentals" for q in r.quantities), (
        "a series of a filed metric is a read over fundamentals, not a derived measure")


async def test_an_integration_rows_quantities_keep_their_run_family():
    """portfolio.integration's labels are run-family names (RUN_GROUPS patterns
    cover them), so its net betas read factor_exposure and its rooms mandate —
    the same group describe_run files them under."""
    row = _calc_row("portfolio.integration",
                    {"net_beta": [{"value": 0.5, "label": "equity"}],
                     "room_to_warning": [{"value": 0.1, "label": "sector_max"}]},
                    {"result_type": {"unit_class": "ratio"}})
    r = await qn._from_calc(_Db(row), "calc_3")
    groups = {q.label: q.group for q in r.quantities}
    assert groups["portfolio.integration.net_beta.equity"] == "factor_exposure"
    assert groups["portfolio.integration.room_to_warning.sector_max"] == "mandate"


async def test_an_alerts_figures_come_grouped_as_mandate():
    row = SimpleNamespace(current_value=0.3, limit_value=0.25, utilization=1.2)
    r = await qn._from_alert(_Db(row), "alert_1")
    assert [(q.label, q.unit_class, q.group) for q in r.quantities] == [
        ("current_value", qn.RATIO, "mandate"),
        ("limit_value", qn.RATIO, "mandate"),
        ("utilization", qn.RATIO, "mandate"),
    ]


def test_every_group_a_quantity_carries_is_in_the_legend_vocabulary():
    """The stamps quantities.py can write are keys the legend can explain —
    the closed set is closed on both ends."""
    for key in ("fundamentals", "derived", "price", "mandate", "other"):
        assert key in resources.GROUP_QUESTIONS, key
