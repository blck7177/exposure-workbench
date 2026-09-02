"""V17 — an ordering is a computation, with operands and refusals (offline).

WHY THIS FILE. The gate resolves every figure to the row it came from and says
nothing about the sentence between two figures. Asked which of five holdings
carried the highest accruals ratio, the model laid out five true, correctly
cited values and wrote "3.40% on JPM was the highest, above 4.11%" — every slot
true, the ordering false (V16 battery, G6). It had no ordering primitive, so it
compared by eye.

`typed_calculator.rank` is that primitive. What it removes is not "the model can
write a false superlative" — prose is prose — but the state where the correct
order was never computed at all: it now costs one call, and it publishes a PLACE
per name that an answer can slot exactly like a figure.

The refusals below are the ways a league table is wrong before any arithmetic:
two measures compared as one, two units compared as one, one figure entered
twice, entries with nothing to tell them apart.
"""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.analytics import units
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import typed_calculator as tc

MONEY, RATIO, COUNT = units.MONEY, units.RATIO, units.COUNT


def q(value: float, *, sid: str, issuer: str | None = "AAPL",
      quantity: str | None = "accruals_ratio", unit: str = RATIO,
      on: str = "2026-03-28") -> tc.Typed:
    return tc.Typed(value=value, unit_class=unit, quantity=quantity, source_id=sid,
                    instant=date.fromisoformat(on),
                    issuers=(issuer,) if issuer else ())


class _Desk:
    """rank() with its two collaborators held still: what is under test is which
    orderings it refuses and what it writes, not the ledger."""

    def __init__(self, monkeypatch, operands: dict[str, tc.Typed | dict]):
        self.rows: list[dict] = []
        self._operands = operands

        async def resolve(_db, ref):
            return operands.get(ref, tc._err("unknown_operand", f"{ref} is unknown"))

        async def record(_db, _ticker, operation, params, result, input_refs,
                         flags, invoked_by, unit_class=None):
            self.rows.append({"operation": operation, "params": params, "result": result,
                              "input_refs": list(input_refs), "flags": flags,
                              "unit_class": unit_class})
            return "calc_rank_1"

        monkeypatch.setattr(tc, "_resolve", resolve)
        monkeypatch.setattr(tc.cs, "_record", record)

    async def rank(self, refs, **kw):
        return await tc.rank(None, refs, **kw)


def _five(monkeypatch, **kw):
    return _Desk(monkeypatch, {
        "a": q(0.0411, sid="a", issuer="MSFT"),
        "b": q(0.0340, sid="b", issuer="JPM"),
        "c": q(-0.0122, sid="c", issuer="XOM"),
        "d": q(0.0233, sid="d", issuer="LLY"),
        "e": q(-0.0050, sid="e", issuer="NVDA"),
    })


# ── the ordering itself ──────────────────────────────────────────────────────

async def test_the_highest_is_the_highest(monkeypatch):
    """The G6 case, computed: MSFT's 4.11% outranks JPM's 3.40%, which is the
    comparison the model got backwards while quoting both figures correctly."""
    out = await _five(monkeypatch).rank(["a", "b", "c", "d", "e"], direction="highest")
    assert out["leader"] == "MSFT"
    assert [e["label"] for e in out["ordering"]] == ["MSFT", "JPM", "LLY", "NVDA", "XOM"]
    assert [e["rank"] for e in out["ordering"]] == [1, 2, 3, 4, 5]


async def test_lowest_first_is_a_different_order_not_a_different_reading(monkeypatch):
    out = await _five(monkeypatch).rank(["a", "b", "c", "d", "e"], direction="lowest")
    assert out["leader"] == "XOM"
    assert [e["rank"] for e in out["ordering"]][:2] == [1, 2]


async def test_each_entry_keeps_the_row_it_came_from(monkeypatch):
    """An ordering is only as citable as its entries: the reader following
    "JPM, 2nd" has to land on JPM's own calculation, not on the ranking."""
    out = await _five(monkeypatch).rank(["a", "b", "c", "d", "e"], direction="highest")
    assert {e["label"]: e["ref"] for e in out["ordering"]}["JPM"] == "b"
    assert all(e["basis"] for e in out["ordering"])


async def test_the_spread_is_the_distance_between_the_ends(monkeypatch):
    out = await _five(monkeypatch).rank(["a", "c"], direction="highest")
    assert out["spread"] == pytest.approx(0.0411 - (-0.0122))


async def test_equal_values_share_a_place(monkeypatch):
    """Numbering two identical figures 1 and 2 asserts a difference they do not
    have — and it is the ordinal, not the value, that the answer slots."""
    desk = _Desk(monkeypatch, {"a": q(0.05, sid="a", issuer="MSFT"),
                               "b": q(0.05, sid="b", issuer="JPM"),
                               "c": q(0.01, sid="c", issuer="XOM")})
    out = await desk.rank(["a", "b", "c"], direction="highest")
    assert [e["rank"] for e in out["ordering"]] == [1, 1, 3]
    assert out["quality_flags"]["tied_places"] == 1


# ── the refusals ─────────────────────────────────────────────────────────────

async def test_one_quantity_is_not_an_order(monkeypatch):
    out = await _five(monkeypatch).rank(["a"], direction="highest")
    assert out["error"] == "too_few_operands"


async def test_the_same_figure_cannot_hold_two_places(monkeypatch):
    out = await _five(monkeypatch).rank(["a", "a", "b"], direction="highest")
    assert out["error"] == "duplicate_operand"
    assert "a" in out["detail"]


async def test_a_direction_this_desk_does_not_have_is_refused(monkeypatch):
    out = await _five(monkeypatch).rank(["a", "b"], direction="biggest")
    assert out["error"] == "unsupported_direction"
    assert "highest" in out["detail"] and "lowest" in out["detail"]


async def test_two_units_are_not_one_league_table(monkeypatch):
    """Ranking a dollar amount against a percentage orders two different things
    by the size of their digits."""
    desk = _Desk(monkeypatch, {"a": q(0.04, sid="a", issuer="MSFT"),
                               "b": q(3.0e9, sid="b", issuer="JPM", unit=MONEY)})
    out = await desk.rank(["a", "b"], direction="highest")
    assert out["error"] == "incomparable_units"
    assert "money" in out["detail"] and "ratio" in out["detail"]


async def test_two_measures_are_not_one_league_table(monkeypatch):
    """The subtler half of the same error: both are ratios, and one is a margin
    while the other is a return. The order would be a real number about nothing."""
    desk = _Desk(monkeypatch, {"a": q(0.04, sid="a", issuer="MSFT", quantity="net_margin"),
                               "b": q(0.31, sid="b", issuer="JPM", quantity="roe")})
    out = await desk.rank(["a", "b"], direction="highest")
    assert out["error"] == "incomparable_quantities"
    assert "net_margin" in out["detail"] and "roe" in out["detail"]


async def test_an_operand_with_no_measure_name_is_refused(monkeypatch):
    """A row that never recorded what it is a quantity OF cannot be shown to be
    the same measure as anything else, and "probably the same" is the assumption
    this whole module exists to refuse."""
    desk = _Desk(monkeypatch, {"a": q(0.04, sid="a", issuer="MSFT", quantity=None),
                               "b": q(0.31, sid="b", issuer="JPM", quantity=None)})
    out = await desk.rank(["a", "b"], direction="highest")
    assert out["error"] == "incomparable_quantities"


async def test_a_series_has_no_single_place_to_take(monkeypatch):
    series = tc.TypedSeries(points=(), unit_class=RATIO, kind="series",
                            quantity="accruals_ratio", source_id="s")
    desk = _Desk(monkeypatch, {"a": q(0.04, sid="a", issuer="MSFT"), "s": series})
    out = await desk.rank(["a", "s"], direction="highest")
    assert out["error"] == "unrankable_operand"


async def test_an_unresolvable_operand_refuses_as_it_always_did(monkeypatch):
    out = await _five(monkeypatch).rank(["a", "nope"], direction="highest")
    assert out["error"] == "unknown_operand"


@pytest.mark.parametrize("issuers", [
    ("MSFT", "MSFT"),      # one issuer twice: two rows called the same thing
    (None, "JPM"),         # a quantity belonging to nobody in particular
])
async def test_entries_that_cannot_be_told_apart_are_refused_not_numbered(monkeypatch, issuers):
    """Every place on the table is named `<measure>.rank.<label>`. Two entries
    with one label would collide there, and the name would resolve to whichever
    was written last — a wrong answer with the gate's blessing."""
    desk = _Desk(monkeypatch, {"a": q(0.04, sid="a", issuer=issuers[0]),
                               "b": q(0.02, sid="b", issuer=issuers[1])})
    out = await desk.rank(["a", "b"], direction="highest")
    assert out["error"] == "indistinguishable_operands"


# ── what reaches the ledger ──────────────────────────────────────────────────

async def test_the_row_records_every_operand_and_its_own_kind(monkeypatch):
    desk = _five(monkeypatch)
    await desk.rank(["a", "b", "c", "d", "e"], direction="highest")
    row = desk.rows[0]
    assert row["operation"] == tc.RANK_OP
    assert row["input_refs"] == ["a", "b", "c", "d", "e"]
    assert row["params"]["result_type"]["kind"] == "ranking"
    assert row["params"]["result_type"]["quantity"] == "accruals_ratio"
    assert row["params"]["result_type"]["unit_class"] == RATIO
    assert len(row["params"]["operand_types"]) == 5, "each operand's type, for the audit"


async def test_a_refused_ordering_writes_nothing(monkeypatch):
    desk = _Desk(monkeypatch, {"a": q(0.04, sid="a", issuer="MSFT", quantity="net_margin"),
                               "b": q(0.31, sid="b", issuer="JPM", quantity="roe")})
    await desk.rank(["a", "b"], direction="highest")
    assert desk.rows == []


async def test_the_caller_may_name_the_ordered_measure(monkeypatch):
    desk = _five(monkeypatch)
    out = await desk.rank(["a", "b"], direction="highest", as_quantity="accrual_quality")
    assert out["quantity"] == "accrual_quality"
    assert desk.rows[0]["params"]["result_type"]["quantity"] == "accrual_quality"


# ── what reaches the table ───────────────────────────────────────────────────

class _Row:
    """A stored ranking row, as quantities reads it back."""

    def __init__(self, result, operation=tc.RANK_OP):
        self.operation = operation
        self.result = result
        self.params = {"result_type": {"quantity": "accruals_ratio", "unit_class": "ratio"}}
        self.unit_class = "RATIO"
        self.company_id = None


def _named(result) -> dict[str, qn.Quantity]:
    resolved = qn._from_ranking(_Row(result), "accruals_ratio", qn.RATIO, "calc_rank_1")
    return {v.label: v for v in resolved.quantities}


ORDERING = {
    "ordering": [{"rank": 1, "label": "MSFT", "ref": "a", "value": 0.0411},
                 {"rank": 2, "label": "JPM", "ref": "b", "value": 0.0340}],
    "leader": "MSFT", "direction": "highest", "ranked": 2, "spread": 0.0071,
}


def test_a_place_is_on_the_table_under_its_own_name():
    """This is the whole point: "JPM is the highest" stops being prose and
    becomes `accruals_ratio.rank.JPM`, which is 2, and a slot that says 1 is
    refused by the same lookup that refuses any other unknown name."""
    names = _named(ORDERING)
    assert names["accruals_ratio.rank.MSFT"].value == 1.0
    assert names["accruals_ratio.rank.JPM"].value == 2.0
    assert names["accruals_ratio.rank.JPM"].unit_class == qn.COUNT


def test_each_value_is_on_the_table_beside_its_place():
    names = _named(ORDERING)
    assert names["accruals_ratio.MSFT"].value == pytest.approx(0.0411)
    assert names["accruals_ratio.MSFT"].unit_class == qn.RATIO


def test_the_spread_and_the_count_are_figures_too():
    names = _named(ORDERING)
    assert names["accruals_ratio.spread"].value == pytest.approx(0.0071)
    assert names["accruals_ratio.ranked"].value == 2.0
    assert names["accruals_ratio.ranked"].unit_class == qn.COUNT


def test_the_leader_is_a_label_and_not_a_quantity():
    """A ticker has no digits, so the model may write it as text. Putting it on
    the table as a figure would mean inventing a number for a name."""
    assert not any(n.endswith(".leader") for n in _named(ORDERING))


def test_a_ranking_row_is_scalar_kind_so_no_trend_may_point_at_it():
    """`trend` and `chart` assert a claim about a sequence and must land on a
    series row. An ordering is not one, however many entries it has."""
    assert qn.calc_kind(_Row(ORDERING)) == qn.KIND_SCALAR


# ── an ordering is not an operand ────────────────────────────────────────────

async def test_an_ordering_cannot_be_fed_back_into_the_calculator(monkeypatch):
    """Without its own branch this fell through to `untyped_operand`, whose
    sentence is about a legacy row and sends the caller to recompute something
    that is not wrong."""
    class _DB:
        async def execute(self, *a, **kw):
            class R:
                @staticmethod
                def scalar_one_or_none():
                    return _Row(ORDERING)
            return R()

    out = await tc._resolve(_DB(), "calc_rank_1")
    assert out["error"] == "not_a_quantity"
    assert "ordering" in out["detail"]
