"""V25 — the arithmetic is closed over what an analyst asks of it (offline).

WHY THIS FILE. The 2026-09-06 battery returned 22 compute refusals in 20
turns, and 12 of them were the operator set being smaller than the question:
`add` and `divide` took exactly two operands (the top-five share was seven
calls and lost the turn); `sum`, `avg`, `abs` were defined on a ledgered
series only and refused a set of figures with `unknown_series`; a position
divided by its daily volume came out a RATIO because the algebra had no flow
dimension, and "0.0001 days" reached the reader as "0.01%". The procedures in
the skill registry had been writing those call chains out for the model —
arithmetic outsourced to prose. This file pins the closure: N-ary add and
multiply, a list against one figure, set statistics, and stock ÷ flow = time.

Held still: `_resolve` returns the typed operands below; `_record` keeps the
rows. What is under test is which combinations go through, what they are
named, and what a refusal says — not the ledger.
"""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.analytics import units
from exposure_workbench.services import compute_service as cmp
from exposure_workbench.services import typed_calculator as tc

MONEY, RATIO, COUNT = units.MONEY, units.RATIO, units.COUNT
MPD, CPD = units.MONEY_PER_DAY, units.COUNT_PER_DAY


def q(value: float, *, sid: str, unit: str = RATIO, issuer: str | None = "AAPL",
      quantity: str | None = "weight", on: str | None = "2026-09-03",
      interval: tuple[str, str] | None = None, base: str | None = None) -> tc.Typed:
    return tc.Typed(value=value, unit_class=unit, quantity=quantity, source_id=sid,
                    instant=date.fromisoformat(on) if on and not interval else None,
                    interval=(tuple(date.fromisoformat(d) for d in interval) if interval else None),
                    issuers=(issuer,) if issuer else (), base=base)


class _Desk:
    def __init__(self, monkeypatch, operands: dict[str, tc.Typed | tc.TypedSeries | dict]):
        self.rows: list[dict] = []
        self.n = 0

        async def resolve(_db, ref):
            return operands.get(ref, tc._err("unknown_operand", f"{ref} is unknown"))

        async def record(_db, _ticker, operation, params, result, input_refs, flags, invoked_by,
                         unit_class=None):
            self.n += 1
            cid = f"calc_{self.n}"
            self.rows.append({"id": cid, "operation": operation, "params": params,
                              "result": result, "input_refs": list(input_refs)})
            # a recorded row is resolvable as an operand of the next step
            rt = params.get("result_type") or {}
            if "value" in result:
                basis = rt.get("basis") or {}
                operands[cid] = tc.Typed(
                    value=float(result["value"]), unit_class=rt["unit_class"],
                    instant=date.fromisoformat(basis["instant"]) if basis.get("instant") else None,
                    interval=(tuple(date.fromisoformat(d) for d in basis["interval"])
                              if basis.get("interval") else None),
                    quantity=rt.get("quantity"), source_id=cid, recorded_basis=basis or None,
                    issuers=tuple(rt.get("issuers") or ()), base=rt.get("base"))
            return cid

        monkeypatch.setattr(tc, "_resolve", resolve)
        monkeypatch.setattr(tc.cs, "_record", record)
        monkeypatch.setattr(cmp, "current_session_id", lambda: "sess_test")

    async def op(self, op, operands, **kw):
        return await cmp._op(None, op, operands, kw.get("as_quantity"), kw.get("direction"),
                             kw.get("params") or {})


def _five_weights(monkeypatch) -> _Desk:
    return _Desk(monkeypatch, {
        f"w{i}": q(v, sid=f"w{i}", issuer=t, base="run_1")
        for i, (t, v) in enumerate([("MSFT", 0.163), ("AAPL", 0.149), ("JPM", 0.148),
                                    ("LLY", 0.127), ("GOOGL", 0.125)], start=1)})


# ── (1) add and multiply take N operands, folded through the pair rules ──────

async def test_the_top_five_share_is_one_add_over_five_weights(monkeypatch):
    desk = _five_weights(monkeypatch)
    out = await desk.op("add", ["w1", "w2", "w3", "w4", "w5"], as_quantity="top_five_share")
    assert not out.get("error"), out
    assert out["value"] == pytest.approx(0.163 + 0.149 + 0.148 + 0.127 + 0.125)
    assert out["type"]["quantity"] == "top_five_share" and out["type"]["unit_class"] == RATIO
    assert out["operands"] == ["w1", "w2", "w3", "w4", "w5"]
    # four rows: three intermediates and the named last one
    assert [r["operation"] for r in desk.rows] == ["calc.scalar.add"] * 4
    assert desk.rows[-1]["params"]["result_type"]["quantity"] == "top_five_share"
    assert all("quantity" in r["params"]["result_type"] for r in desk.rows[:-1])
    assert out["folded"] == ["calc_1", "calc_2", "calc_3"]


async def test_sum_over_a_set_is_the_same_fold(monkeypatch):
    desk = _five_weights(monkeypatch)
    out = await desk.op("sum", ["w1", "w2", "w3"], as_quantity="top_three")
    assert not out.get("error") and out["value"] == pytest.approx(0.163 + 0.149 + 0.148)
    assert out["type"]["quantity"] == "top_three"


async def test_a_fold_refuses_on_the_pair_that_fails_and_says_which(monkeypatch):
    """The pair rules are not weakened by the fold: a weight of another book
    stops the sum at that operand, with the same refusal one add would give."""
    ops = {f"w{i}": q(0.1, sid=f"w{i}", issuer=t, base="run_1") for i, t in enumerate(["A", "B"], 1)}
    ops["w6"] = q(0.2, sid="w6", issuer="XOM", base="run_2")
    desk = _Desk(monkeypatch, ops)
    out = await desk.op("add", ["w1", "w2", "w6"])
    assert out["error"] == "different_books"
    assert out["at"] == "w6" and "operand 3 of 3" in out["detail"]
    assert out["folded_so_far"] == ["calc_1"]


async def test_multiply_folds_like_add(monkeypatch):
    desk = _Desk(monkeypatch, {
        "a": q(2.0, sid="a", unit=MONEY, quantity="revenue", on=None, interval=("2025-01-01", "2025-12-31")),
        "m": q(0.5, sid="m", quantity="net_margin", on=None, interval=("2025-01-01", "2025-12-31")),
        "s": q(0.1, sid="s", quantity="payout", on=None, interval=("2025-01-01", "2025-12-31")),
    })
    out = await desk.op("multiply", ["a", "m", "s"], as_quantity="dividends_implied")
    assert not out.get("error"), out
    assert out["value"] == pytest.approx(0.1) and out["type"]["unit_class"] == MONEY


async def test_subtract_and_divide_stay_binary_and_point_at_by(monkeypatch):
    desk = _five_weights(monkeypatch)
    out = await desk.op("divide", ["w1", "w2", "w3"])
    assert out["error"] == "operands" and "params.by" in out["detail"]


# ── (2) a list against one figure ────────────────────────────────────────────

async def test_each_use_of_cash_over_operating_cash_flow_is_one_call(monkeypatch):
    win = ("2025-01-01", "2025-12-31")
    desk = _Desk(monkeypatch, {
        "ocf": q(100.0, sid="ocf", unit=MONEY, quantity="operating_cash_flow", on=None, interval=win),
        "capex": q(40.0, sid="capex", unit=MONEY, quantity="capex", on=None, interval=win),
        "buyb": q(30.0, sid="buyb", unit=MONEY, quantity="buybacks", on=None, interval=win),
        "div": q(10.0, sid="div", unit=MONEY, quantity="dividends_paid", on=None, interval=win),
    })
    out = await desk.op("divide", ["capex", "buyb", "div"], params={"by": "ocf"},
                        as_quantity="share_of_ocf")
    assert out["count"] == 3 and out["by"] == "ocf"
    shares = [r["value"] for r in out["results"]]
    assert shares == pytest.approx([0.4, 0.3, 0.1])
    assert all(r["type"]["unit_class"] == RATIO and r["type"]["quantity"] == "share_of_ocf"
               for r in out["results"])
    assert [r["operand"] for r in out["results"]] == ["capex", "buyb", "div"]


async def test_a_refused_entry_in_a_broadcast_is_its_own_refusal(monkeypatch):
    desk = _Desk(monkeypatch, {
        "ocf": q(100.0, sid="ocf", unit=MONEY, quantity="operating_cash_flow", on=None,
                 interval=("2025-01-01", "2025-12-31")),
        "capex": q(40.0, sid="capex", unit=MONEY, quantity="capex", on=None,
                   interval=("2025-01-01", "2025-12-31")),
    })
    out = await desk.op("divide", ["capex", "nope"], params={"by": "ocf"})
    assert out["count"] == 2
    assert not out["results"][0].get("error")
    assert out["results"][1]["error"] == "unknown_operand" and out["results"][1]["operand"] == "nope"


async def test_by_must_name_one_figure(monkeypatch):
    desk = _five_weights(monkeypatch)
    out = await desk.op("divide", ["w1"], params={"by": ["w2", "w3"]})
    assert out["error"] == "params"


# ── (3) statistics over a set of figures ─────────────────────────────────────

async def test_avg_min_max_std_over_a_set_of_like_figures(monkeypatch):
    desk = _five_weights(monkeypatch)
    avg = await desk.op("avg", ["w1", "w2", "w3", "w4", "w5"])
    assert avg["value"] == pytest.approx((0.163 + 0.149 + 0.148 + 0.127 + 0.125) / 5)
    assert avg["type"]["quantity"] == "weight.avg" and avg["type"]["unit_class"] == RATIO
    assert avg["type"]["base"] == "run_1" and avg["type"]["entries"] == 5
    # all five are as of the same run date, so the average is too
    assert avg["type"]["basis"] == {"instant": "2026-09-03"}
    mx = await desk.op("max", ["w1", "w2", "w3", "w4", "w5"])
    assert mx["value"] == 0.163 and "w1" in mx["basis"]
    mn = await desk.op("min", ["w1", "w2", "w3", "w4", "w5"])
    assert mn["value"] == 0.125
    sd = await desk.op("std", ["w1", "w2"])
    assert sd["value"] == pytest.approx(abs(0.163 - 0.149) / 2)
    assert desk.rows[0]["operation"] == "calc.set.avg"


async def test_abs_of_one_figure(monkeypatch):
    desk = _Desk(monkeypatch, {"d": q(-0.083, sid="d", issuer="XOM", quantity="distance_from_52w_high")})
    out = await desk.op("abs", ["d"])
    assert out["value"] == pytest.approx(0.083) and out["type"]["quantity"] == "distance_from_52w_high.abs"


async def test_a_set_statistic_refuses_mixed_measures_like_rank_does(monkeypatch):
    desk = _Desk(monkeypatch, {
        "a": q(0.1, sid="a", quantity="weight"),
        "b": q(0.2, sid="b", quantity="net_margin", issuer="MSFT"),
    })
    out = await desk.op("avg", ["a", "b"])
    assert out["error"] == "incomparable_quantities"
    desk = _Desk(monkeypatch, {
        "a": q(0.1, sid="a", quantity="x"),
        "b": q(2.0, sid="b", unit=MONEY, quantity="x", issuer="MSFT"),
    })
    assert (await desk.op("avg", ["a", "b"]))["error"] == "incomparable_units"
    desk = _five_weights(monkeypatch)
    assert (await desk.op("avg", ["w1", "w1"]))["error"] == "duplicate_operand"


async def test_a_change_op_over_a_set_says_what_it_needs(monkeypatch):
    """yoy over two separate figures is the class of refusal the battery hit
    six times; the refusal now says how the change between two figures IS
    computed, and where a series comes from."""
    desk = _five_weights(monkeypatch)
    out = await desk.op("yoy", ["w1", "w2"])
    assert out["error"] == "series_only"
    assert "subtract" in out["detail"] and "last_n" in out["detail"]
    one = await desk.op("avg", ["w1"])
    assert one["error"] == "not_a_series" and "two or more figures" in one["detail"]


async def test_a_single_series_still_routes_to_the_series_service(monkeypatch):
    series = tc.TypedSeries(points=((date(2025, 12, 31), q(1.0, sid="s")),), unit_class=RATIO,
                            kind="flow", quantity="gross_margin", source_id="calc_s")
    desk = _Desk(monkeypatch, {"calc_s": series})
    seen = {}

    async def stat(_db, sid, op, invoked_by="agent"):
        seen.update(sid=sid, op=op)
        return {"calc_id": "calc_x", "op": op, "value": 1.0}

    monkeypatch.setattr(cmp.series_service, "series_stat", stat)
    out = await desk.op("yoy", ["calc_s"])
    assert seen == {"sid": "calc_s", "op": "yoy"} and out["calc_id"] == "calc_x"
    both = await desk.op("avg", ["calc_s", "calc_s"])
    assert both["error"] == "duplicate_operand"


# ── (4) stock ÷ flow is a time: days to liquidate from the algebra ───────────

async def test_a_position_over_its_daily_dollar_volume_is_days(monkeypatch):
    """The N03 case: $1.64M held ÷ $16B traded a session. The quotient is a
    COUNT of days, from the table — no caller declares it."""
    desk = _Desk(monkeypatch, {
        "mv": q(1_641_050.0, sid="mv", unit=MONEY, quantity="market_value", base="run_1"),
        "adv": q(16_000_000_000.0, sid="adv", unit=MPD, quantity="AAPL.adv_dollars.20d", on=None,
                 interval=("2026-08-06", "2026-09-05")),
    })
    out = await desk.op("divide", ["mv", "adv"], as_quantity="days_to_sell")
    assert not out.get("error"), out
    assert out["type"]["unit_class"] == COUNT
    assert out["value"] == pytest.approx(1_641_050 / 16_000_000_000)


async def test_a_participation_rate_scales_a_flow_and_the_days_follow(monkeypatch):
    desk = _Desk(monkeypatch, {
        "mv": q(1_641_050.0, sid="mv", unit=MONEY, quantity="market_value", base="run_1"),
        "adv": q(16_000_000_000.0, sid="adv", unit=MPD, quantity="AAPL.adv_dollars.20d", on=None,
                 interval=("2026-08-06", "2026-09-05")),
        "part": q(0.2, sid="part", quantity="participation", on=None),
    })
    sellable = await desk.op("multiply", ["adv", "part"], as_quantity="sellable_per_day")
    assert sellable["type"]["unit_class"] == MPD
    days = await desk.op("divide", ["mv", sellable["calc_id"]], as_quantity="days_to_sell")
    assert days["type"]["unit_class"] == COUNT
    assert days["value"] == pytest.approx(1_641_050 / (16_000_000_000 * 0.2))


async def test_money_over_money_is_still_a_ratio_so_a_false_days_cannot_be_typed(monkeypatch):
    """The second N03 turn divided AAPL's market value by TLT's and called it
    days. The algebra still says RATIO, and nothing lets a caller say COUNT."""
    desk = _Desk(monkeypatch, {
        "a": q(1_641_050.0, sid="a", unit=MONEY, quantity="market_value", base="run_1"),
        "t": q(656_560.0, sid="t", unit=MONEY, quantity="market_value", issuer="TLT", base="run_1"),
    })
    out = await desk.op("divide", ["a", "t"], as_quantity="days_to_sell")
    assert out["type"]["unit_class"] == RATIO
    assert units.refine(RATIO, COUNT) is None


def test_the_flow_rows_of_the_algebra():
    assert units.quotient_unit(MONEY, MPD) == COUNT
    assert units.quotient_unit(COUNT, CPD) == COUNT
    assert units.quotient_unit(MPD, CPD) == units.MONEY_PER_SHARE
    assert units.quotient_unit(MPD, units.MONEY_PER_SHARE) == CPD
    assert units.product_unit(units.MONEY_PER_SHARE, CPD) == MPD
    assert units.product_unit(MPD, RATIO) == MPD
    # a flow over a stock is not a thing this desk computes
    assert units.quotient_unit(MPD, MONEY) is None
    assert units.product_unit(MPD, MONEY) is None
    assert units.product_unit(MPD, COUNT) is None
