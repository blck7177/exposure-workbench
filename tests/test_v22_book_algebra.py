"""V22 — the book's figures enter the typed algebra; the panel is the algebra;
a sale is a primitive (offline).

WHY THIS FILE. The conversation battery (docs/spikes/V21_CONVERSATIONS.md)
measured a desk with two worlds of values and one algebra. An issuer's figures
had operators (calculate, rank), methods as data (formulas.py) and a refusal
that reached the trace when a method was missing. The book's figures — weights,
market values, limit levels, net betas — had none of the three: readable,
citable, terminal. "How much must I sell to get back under the limit" is
(weight − limit) × market value, two operations over four figures the run
already held, and no tool could perform either; "if I sell NVDA, where does
concentration land" is nine renormalisations and a limit pass, and there was
no object for a book that does not exist.

What V22 does NOT do is hand the model a bare calculator. typed_calculator's
own docstring is the reason: a bare calculator discards the operand's type,
and a type is the only thing that stops 82.7 + 8.31 being called total debt.
So the book's figures come in TYPED — unit, as-of, entity, and one new axis,
the BASE (the book a share is a share of) — and the base adds exactly the
refusals a bare calculator would let through.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from exposure_workbench.analytics import integration as ig
from exposure_workbench.analytics import resources
from exposure_workbench.analytics import scenario as sc
from exposure_workbench.analytics import units
from exposure_workbench.services import integration_service as isvc
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import scenario_service as ssvc
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.tools import definitions, faces
from exposure_workbench.tools.registries import build_meta_registry

RUN = "run_b791e7985dcd"          # the deployed desk's latest run, 2026-09-03
AS_OF = date(2026, 9, 3)
MV = 10_986_070.0                 # exposure_metrics.portfolio_market_value on that run

# issuer_exposures.<T>.weight on that run, to the ledger's precision
WEIGHTS = {"MSFT": 0.16251671, "AAPL": 0.14937553, "JPM": 0.14830326, "LLY": 0.12666222,
           "GOOGL": 0.12469609, "HYG": 0.07210040, "AMZN": 0.07069862, "TLT": 0.05976295,
           "XOM": 0.04429518, "NVDA": 0.04158903}
WARN_MSFT, BREACH_MSFT = 0.15, 0.20


def _q(value, unit, label, sid=RUN, not_alone=None):
    return qn.Quantity(value, unit, label, sid, not_alone=not_alone)


def _run_quantities():
    out = [_q(w, qn.RATIO, f"issuer_exposures.{t}.weight") for t, w in WEIGHTS.items()]
    out += [_q(w * MV, qn.MONEY, f"issuer_exposures.{t}.market_value") for t, w in WEIGHTS.items()]
    out.append(_q(MV, qn.MONEY, "exposure_metrics.portfolio_market_value"))
    out.append(_q(WEIGHTS["MSFT"], qn.RATIO, "limit_checks.issuer_concentration:MSFT.current_value"))
    out.append(_q(WARN_MSFT, qn.RATIO, "limit_checks.issuer_concentration:MSFT.warning_level"))
    out.append(_q(BREACH_MSFT, qn.RATIO, "limit_checks.issuer_concentration:MSFT.breach_level"))
    out.append(_q(1.1, qn.RATIO, "factor_attributions.rates.beta",
                  not_alone="these factors are collinear"))
    out.append(_q(10.0, qn.COUNT, "count.positions"))
    return out


class _Desk:
    """The calculator with its two collaborators held still: the namer answers
    from a fixture, the ledger records to a list, so what is under test is
    the typing and the rules, not the database."""

    def __init__(self, monkeypatch, rows: dict[str, list[qn.Quantity]],
                 contexts: dict[str, tuple[str, date]], facts: dict[str, tc.Typed] | None = None):
        self.rows: list[dict] = []
        self._facts = facts or {}
        n = [0]

        async def quantities(_db, rid):
            qs = rows.get(rid)
            return qn.Resolved(tuple(qs), frozenset(), "run") if qs is not None \
                else qn.Resolved((), frozenset(), None)

        async def context(_db, rid):
            if rid in contexts:
                return contexts[rid]
            return tc._err("unknown_operand", f"{rid} is unknown")

        async def record(_db, _ticker, operation, params, result, input_refs,
                         flags, invoked_by, unit_class=None):
            n[0] += 1
            cid = f"calc_v22_{n[0]}"
            self.rows.append({"id": cid, "operation": operation, "params": params,
                              "result": result, "input_refs": list(input_refs)})
            # Read-back: a row this desk wrote resolves the way the ledger would.
            rt = params.get("result_type") or {}
            basis = rt.get("basis") or {}
            self._facts[cid] = tc.Typed(
                value=result.get("value"), unit_class=rt["unit_class"],
                instant=date.fromisoformat(basis["instant"]) if basis.get("instant") else None,
                interval=(tuple(date.fromisoformat(x) for x in basis["interval"])
                          if basis.get("interval") else None),
                quantity=rt.get("quantity"), source_id=cid, recorded_basis=basis or None,
                issuers=tuple(rt.get("issuers") or ()), base=rt.get("base"))
            return cid

        real_resolve = tc._resolve

        async def resolve(db, ref):
            if ref in self._facts:
                return self._facts[ref]
            return await real_resolve(db, ref)

        monkeypatch.setattr(tc, "_named_quantities", quantities)
        monkeypatch.setattr(tc, "_named_context", context)
        monkeypatch.setattr(tc, "_resolve", resolve)
        monkeypatch.setattr(tc.cs, "_record", record)

    async def calc(self, op, a, b, **kw):
        return await tc.calculate(None, op, a, b, **kw)

    async def rank(self, refs, **kw):
        return await tc.rank(None, refs, **kw)


def _desk(monkeypatch, **extra):
    return _Desk(monkeypatch, {RUN: _run_quantities()}, {RUN: (RUN, AS_OF)}, **extra)


# ── a named figure is a typed operand ───────────────────────────────────────

def test_the_separator_is_the_first_colon_because_labels_hold_colons():
    """`limit_checks.issuer_concentration:MSFT.current_value` has a colon of
    its own; the boundary is the first one, after the row id."""
    assert tc.split_named(f"{RUN}:limit_checks.issuer_concentration:MSFT.current_value") == \
        (RUN, "limit_checks.issuer_concentration:MSFT.current_value")
    assert tc.split_named("fact_abc") is None
    assert tc.split_named("chunk_x:1") is None, "only run_ and calc_ rows hold named figures"
    assert tc.split_named("run_x:") is None


def test_a_book_name_parses_into_what_and_whose():
    assert tc._parse_book_name("issuer_exposures.MSFT.weight") == ("issuer_exposures.weight", "MSFT")
    assert tc._parse_book_name("limit_checks.issuer_concentration:MSFT.current_value") == \
        ("limit_checks.current_value", "issuer_concentration:MSFT")
    assert tc._parse_book_name("portfolio.integration.room_to_breach.sector_max") == \
        ("portfolio.integration.room_to_breach", "sector_max")
    assert tc._parse_book_name("exposure_metrics.portfolio_market_value") == \
        ("exposure_metrics.portfolio_market_value", None)
    assert tc._parse_book_name("count.positions") == ("count.positions", None)


async def test_a_run_weight_resolves_typed_with_its_base_and_date(monkeypatch):
    _desk(monkeypatch)
    t = await tc._resolve(None, f"{RUN}:issuer_exposures.MSFT.weight")
    assert isinstance(t, tc.Typed)
    assert t.value == WEIGHTS["MSFT"]
    assert t.unit_class == units.RATIO, "the gate's RATIO is the algebra's ratio"
    assert t.instant == AS_OF, "a run figure is a reading at the run's date"
    assert t.base == RUN, "and a figure OF that run's book"
    assert t.issuers == ("MSFT",), "the row label is the entity"
    assert t.quantity == "issuer_exposures.weight"


async def test_the_book_market_value_is_money_of_the_book_with_no_entity(monkeypatch):
    _desk(monkeypatch)
    t = await tc._resolve(None, f"{RUN}:exposure_metrics.portfolio_market_value")
    assert t.unit_class == units.MONEY and t.base == RUN and t.issuers == ()


async def test_an_unknown_name_is_refused_and_points_at_the_manifest(monkeypatch):
    _desk(monkeypatch)
    r = await tc._resolve(None, f"{RUN}:issuer_exposures.MSFT.rank")
    assert r["error"] == "unknown_name" and "describe_run" in r["detail"]


async def test_a_collinear_coefficient_may_not_be_an_operand(monkeypatch):
    """The projection the table applies (V11-F) holds at the calculator too:
    a figure the row says may not stand alone is not an operand either."""
    _desk(monkeypatch)
    r = await tc._resolve(None, f"{RUN}:factor_attributions.rates.beta")
    assert r["error"] == "not_alone"


async def test_a_row_this_desk_does_not_hold_is_refused(monkeypatch):
    _desk(monkeypatch)
    r = await tc._resolve(None, "run_nope:issuer_exposures.MSFT.weight")
    assert r["error"] == "unknown_operand"


# ── the rules the base adds ─────────────────────────────────────────────────

def _share(v, base, entity="MSFT", on=AS_OF, unit=units.RATIO):
    return tc.Typed(value=v, unit_class=unit, instant=on, quantity="issuer_exposures.weight",
                    source_id=f"{base}:x", issuers=(entity,), base=base)


def test_two_books_weights_cannot_be_summed_or_multiplied():
    a, b = _share(0.16, "run_a"), _share(0.12, "run_b", on=date(2026, 9, 2))
    assert tc._check("add", a, b)["error"] == "different_books"
    assert tc._check("multiply", a, b)["error"] == "different_books"


def test_two_books_weights_may_be_differenced_and_the_result_is_of_neither():
    """The change a sale makes, or the drift between two runs — R2's shape one
    axis over: the difference between two readings is allowed, the sum is not."""
    a, b = _share(0.18, "calc_scn"), _share(0.16, "run_a")
    assert tc._check("subtract", a, b) is None
    t = tc._result_type("subtract", a, b, 0.02)
    assert t.base is None, "a change between two books is a figure of neither"
    assert t.unit_class == units.RATIO


def test_two_books_may_be_divided():
    a = tc.Typed(value=1.1e7, unit_class=units.MONEY, instant=AS_OF, source_id="run_a:mv",
                 quantity="exposure_metrics.portfolio_market_value", base="run_a")
    b = tc.Typed(value=1.0e7, unit_class=units.MONEY, instant=date(2026, 8, 3), source_id="run_b:mv",
                 quantity="exposure_metrics.portfolio_market_value", base="run_b")
    assert tc._check("divide", a, b) is None
    assert tc._result_type("divide", a, b, 1.1).base is None


def test_a_book_figure_and_a_filed_figure_are_not_parts_of_one_whole():
    """A position's market value plus the issuer's cash: two worlds in one
    number. Refused for add and subtract alike."""
    position = tc.Typed(value=1.78e6, unit_class=units.MONEY, instant=AS_OF, issuers=("MSFT",),
                        quantity="issuer_exposures.market_value", source_id="run_a:mv", base="run_a")
    cash = tc.Typed(value=32.1e9, unit_class=units.MONEY, instant=AS_OF, issuers=("MSFT",),
                    quantity="cash_and_equivalents", source_id="fact_c")
    assert tc._check("add", position, cash)["error"] == "mixed_worlds"
    assert tc._check("subtract", position, cash)["error"] == "mixed_worlds"


def test_a_share_of_the_book_times_money_not_the_books_is_refused():
    weight = _share(0.16, "run_a")
    revenue = tc.Typed(value=245e9, unit_class=units.MONEY, issuers=("MSFT",),
                       interval=(date(2025, 7, 1), date(2026, 6, 30)),
                       quantity="total_revenues", source_id="fact_r")
    r = tc._check("multiply", weight, revenue)
    assert r["error"] == "mixed_worlds" and "portfolio_market_value" in r["detail"]


def test_a_share_of_the_book_times_an_issuers_ratio_is_an_analysts_arithmetic():
    """weight × net margin — the weighted margin — goes through, and stays a
    figure of the book."""
    weight = _share(0.16, "run_a")
    margin = tc.Typed(value=0.35, unit_class=units.RATIO, issuers=("MSFT",),
                      interval=(date(2025, 7, 1), date(2026, 6, 30)),
                      quantity="net_margin", source_id="calc_m")
    assert tc._check("multiply", weight, margin) is None
    assert tc._result_type("multiply", weight, margin, 0.056).base == "run_a"


def test_the_rules_are_silent_when_neither_operand_has_a_base():
    """Every pre-V22 combination is untouched: the base axis adds refusals
    only where a base is present."""
    a = tc.Typed(value=1.0, unit_class=units.MONEY, instant=AS_OF, source_id="fact_a", issuers=("A",))
    b = tc.Typed(value=2.0, unit_class=units.MONEY, instant=AS_OF, source_id="fact_b", issuers=("B",))
    assert tc._book_rule("add", a, b) is None


# ── the compositions the battery could not perform ──────────────────────────

async def test_trim_to_limit_is_two_calls_over_the_runs_own_figures(monkeypatch):
    """C12#t2, 'give me the levels': (current − warning) × market value is the
    dollars of MSFT that must go to clear the warning. Two calls, four figures
    the run holds, a typed money result of THIS book, about MSFT."""
    d = _desk(monkeypatch)
    excess = await d.calc("subtract",
                          f"{RUN}:limit_checks.issuer_concentration:MSFT.current_value",
                          f"{RUN}:limit_checks.issuer_concentration:MSFT.warning_level",
                          as_quantity="excess_over_warning")
    assert "error" not in excess, excess
    assert excess["value"] == pytest.approx(WEIGHTS["MSFT"] - WARN_MSFT)
    assert excess["type"]["unit_class"] == units.RATIO and excess["type"]["base"] == RUN
    assert excess["type"]["basis"] == {"instant": AS_OF.isoformat()}, "same run, same date: a reading"

    dollars = await d.calc("multiply", excess["calc_id"],
                           f"{RUN}:exposure_metrics.portfolio_market_value",
                           as_quantity="dollars_to_sell")
    assert "error" not in dollars, dollars
    assert dollars["value"] == pytest.approx((WEIGHTS["MSFT"] - WARN_MSFT) * MV)   # $137,509.45
    assert dollars["type"]["unit_class"] == units.MONEY
    assert dollars["type"]["base"] == RUN
    assert dollars["type"]["issuers"] == ["issuer_concentration:MSFT"], "about the MSFT check"
    assert dollars["type"]["quantity"] == "dollars_to_sell"


async def test_post_trade_weight_of_a_full_exit_is_one_division(monkeypatch):
    """C01#t3 without the scenario primitive: MSFT's weight after NVDA leaves is
    MSFT.mv / (book.mv − NVDA.mv). Three calls; the scenario tool does it for
    every name at once, but the algebra can do it for one."""
    d = _desk(monkeypatch)
    rest = await d.calc("subtract", f"{RUN}:exposure_metrics.portfolio_market_value",
                        f"{RUN}:issuer_exposures.NVDA.market_value", as_quantity="book_without_nvda")
    assert "error" not in rest, rest
    w = await d.calc("divide", f"{RUN}:issuer_exposures.MSFT.market_value", rest["calc_id"],
                     as_quantity="msft_weight_after")
    assert "error" not in w, w
    assert w["value"] == pytest.approx(WEIGHTS["MSFT"] / (1 - WEIGHTS["NVDA"]), rel=1e-6)
    assert w["type"]["unit_class"] == units.RATIO and w["type"]["base"] == RUN


async def test_a_weight_from_this_run_and_a_weight_from_another_run_cannot_be_summed(monkeypatch):
    other = "run_3c94a47d6547"
    d = _Desk(monkeypatch,
              {RUN: _run_quantities(),
               other: [_q(0.160, qn.RATIO, "issuer_exposures.MSFT.weight", sid=other)]},
              {RUN: (RUN, AS_OF), other: (other, date(2026, 9, 2))})
    r = await d.calc("add", f"{RUN}:issuer_exposures.MSFT.weight", f"{other}:issuer_exposures.MSFT.weight")
    assert r["error"] == "different_books"
    r = await d.calc("subtract", f"{RUN}:issuer_exposures.MSFT.weight", f"{other}:issuer_exposures.MSFT.weight")
    assert "error" not in r and r["value"] == pytest.approx(WEIGHTS["MSFT"] - 0.160)


# ── ordering over the book ──────────────────────────────────────────────────

async def test_the_holdings_rank_by_weight_and_each_place_is_a_name(monkeypatch):
    """C01#t1: `rank` over ten `run_…:issuer_exposures.<T>.weight` refs was
    refused as unknown_operand. Now the ordering is computed and every place
    is on the table — `issuer_exposures.weight.rank.MSFT` is 1."""
    d = _desk(monkeypatch)
    r = await d.rank([f"{RUN}:issuer_exposures.{t}.weight" for t in WEIGHTS], direction="highest")
    assert "error" not in r, r
    assert r["leader"] == "MSFT"
    assert [e["label"] for e in r["ordering"]][:3] == ["MSFT", "AAPL", "JPM"]
    assert r["ordering"][-1]["label"] == "NVDA" and r["ordering"][-1]["rank"] == 10
    assert r["quantity"] == "issuer_exposures.weight"
    assert r["type"]["issuers"] == sorted(WEIGHTS)


async def test_a_weight_and_a_market_value_are_not_one_measure(monkeypatch):
    d = _desk(monkeypatch)
    r = await d.rank([f"{RUN}:issuer_exposures.MSFT.weight", f"{RUN}:issuer_exposures.AAPL.market_value"])
    assert r["error"] == "incomparable_units"


# ── the panel is the algebra ────────────────────────────────────────────────

async def test_headroom_on_the_panel_is_subtract_in_the_algebra(monkeypatch):
    """PARITY. What get_portfolio_analysis calls `room_to_breach` and
    `room_to_warning` is exactly what calculate(subtract) produces from the
    same four figures of the same run. The panel exists to save calls; it is
    not a second arithmetic."""
    d = _desk(monkeypatch)
    room = ig.headroom([{"limit_type": "issuer_concentration:MSFT", "entity_id": None,
                         "current_value": WEIGHTS["MSFT"], "warning_level": WARN_MSFT,
                         "breach_level": BREACH_MSFT, "evaluated": True, "source_id": RUN}])
    assert len(room) == 1
    to_breach = await d.calc("subtract", f"{RUN}:limit_checks.issuer_concentration:MSFT.breach_level",
                             f"{RUN}:limit_checks.issuer_concentration:MSFT.current_value")
    to_warning = await d.calc("subtract", f"{RUN}:limit_checks.issuer_concentration:MSFT.warning_level",
                              f"{RUN}:limit_checks.issuer_concentration:MSFT.current_value")
    assert to_breach["value"] == pytest.approx(room[0].to_breach)
    assert to_warning["value"] == pytest.approx(room[0].to_warning)
    assert room[0].status == "warning" and to_warning["value"] < 0 < to_breach["value"]


async def test_the_net_beta_on_the_panel_is_scale_then_add_in_the_algebra(monkeypatch):
    """PARITY for the netting: net = Σ β_i × sense_i. The sense is data
    (_RISK_SENSE), applied by scale; the sum is add; the panel's net_beta is
    that number."""
    factors = [{"factor_name": "rates", "factor_ticker": "TLT", "beta": 1.1, "source_id": RUN},
               {"factor_name": "credit", "factor_ticker": "HYG", "beta": 0.4, "source_id": RUN}]
    net = ig.net_factor_exposure(factors, "rates_up", False)
    d = _Desk(monkeypatch,
              {RUN: [_q(1.1, qn.RATIO, "factor_attributions.rates.beta"),
                     _q(0.4, qn.RATIO, "factor_attributions.credit.beta")]},
              {RUN: (RUN, AS_OF)})
    legs = []
    for leg in net.legs:
        sense = ig._RISK_SENSE[next(f["factor_ticker"] for f in factors if f["factor_name"] == leg.name)][1]
        s = await tc.scale(None, f"{RUN}:factor_attributions.{leg.name}.beta", sense,
                           unit_class=units.RATIO, quantity=f"{leg.name}.signed")
        assert s["type"]["base"] == RUN, "scale carries the base"
        legs.append(s)
    total = legs[0]["value"] if len(legs) == 1 else None
    if len(legs) > 1:
        acc = legs[0]
        for nxt in legs[1:]:
            acc = await d.calc("add", acc["calc_id"], nxt["calc_id"])
        total = acc["value"]
    assert total == pytest.approx(net.net)


def test_the_analysis_row_states_its_own_type_and_base():
    """So `calc_…:portfolio.integration.room_to_breach.<check>` resolves through
    the row's own params — unit, date, book — and not through a rule about the
    operation's name. LEGACY_RATIO_OPS still lists the op for rows written
    before V22; a new row no longer needs it."""
    src = inspect.getsource(isvc._record)
    assert '"result_type"' in src and '"base": run_id' in src and '"as_of": out["as_of"]' in src
    # The identifying set is unchanged: find_recorded matches by containment.
    assert isvc.identifying_params("run_x") == {"run_id": "run_x"}


async def test_an_analysis_distance_is_an_operand_of_the_run_it_analysed(monkeypatch):
    calc = "calc_analysis"
    d = _Desk(monkeypatch,
              {RUN: _run_quantities(),
               calc: [_q(0.0374833, qn.RATIO, "portfolio.integration.room_to_breach.issuer_concentration:MSFT", sid=calc)]},
              {RUN: (RUN, AS_OF), calc: (RUN, AS_OF)})   # an analysis is ABOUT the run
    t = await tc._resolve(None, f"{calc}:portfolio.integration.room_to_breach.issuer_concentration:MSFT")
    assert t.base == RUN and t.issuers == ("issuer_concentration:MSFT",)
    dollars = await d.calc("multiply", f"{calc}:portfolio.integration.room_to_breach.issuer_concentration:MSFT",
                           f"{RUN}:exposure_metrics.portfolio_market_value", as_quantity="dollars_of_room")
    assert "error" not in dollars, dollars
    assert dollars["type"]["unit_class"] == units.MONEY and dollars["type"]["base"] == RUN


# ── the sale, as arithmetic ─────────────────────────────────────────────────

def _holdings():
    return [sc.Holding(t, "Technology" if t in ("MSFT", "AAPL", "GOOGL", "NVDA") else "Other", w * MV)
            for t, w in WEIGHTS.items()]


def test_selling_a_name_renormalises_every_other_weight():
    book = sc.without(_holdings(), [sc.Sale("NVDA")])
    assert isinstance(book, sc.ScenarioBook)
    assert sorted(book.weights) == sorted(t for t in WEIGHTS if t != "NVDA")
    assert sum(book.weights.values()) == pytest.approx(1.0)
    # The fixture's weights are the ledger's eight-decimal values and do not
    # sum to one exactly; the check is against the fixture's own market values.
    mv = {h.ticker: h.market_value for h in _holdings()}
    rest = sum(mv.values()) - mv["NVDA"]
    for t, w in book.weights.items():
        assert w == pytest.approx(mv[t] / rest, rel=1e-9), t
        assert w == pytest.approx(WEIGHTS[t] / (1 - WEIGHTS["NVDA"]), rel=1e-6), t
    assert book.market_value == pytest.approx(rest)
    assert book.proceeds == pytest.approx(MV * WEIGHTS["NVDA"])
    assert book.sold == [sc.SoldLeg("NVDA", 1.0, pytest.approx(MV * WEIGHTS["NVDA"]), True)]


def test_selling_a_name_moves_its_sector_and_every_sector_weight():
    before = sc.without(_holdings(), [sc.Sale("XOM", 1e-9)])   # an all-but-nothing sale: the book as is
    after = sc.without(_holdings(), [sc.Sale("NVDA")])
    assert after.sectors["Technology"]["market_value"] == pytest.approx(
        before.sectors["Technology"]["market_value"] - WEIGHTS["NVDA"] * MV, rel=1e-6)
    assert sum(s["weight"] for s in after.sectors.values()) == pytest.approx(1.0)
    assert after.sectors["Other"]["weight"] > before.sectors["Other"]["weight"], "the rest grew"


def test_a_partial_sale_keeps_the_name_at_its_smaller_size():
    book = sc.without(_holdings(), [sc.Sale("MSFT", 0.5)])
    msft_after = WEIGHTS["MSFT"] * MV * 0.5
    assert book.weights["MSFT"] == pytest.approx(msft_after / (MV - msft_after))
    assert book.sold[0].exited is False
    assert "MSFT" in book.weights


def test_a_trim_that_clears_the_warning_can_be_found():
    """The battery's C12#t2 in the scenario's terms: selling the excess over the
    warning line, then a little more for the renormalisation, puts MSFT under
    15% of the smaller book. The sale that does it exactly is
    f = 1 − warn(1−w)/(w(1−warn)); this checks the arithmetic agrees."""
    w, warn = WEIGHTS["MSFT"], WARN_MSFT
    f = 1 - warn * (1 - w) / (w * (1 - warn))
    book = sc.without(_holdings(), [sc.Sale("MSFT", f)])
    assert book.weights["MSFT"] == pytest.approx(warn, abs=1e-6)


@pytest.mark.parametrize("sales, code", [
    ([sc.Sale("TSLA")], "not_held"),
    ([sc.Sale("MSFT", 0.0)], "bad_fraction"),
    ([sc.Sale("MSFT", 1.5)], "bad_fraction"),
    ([sc.Sale("MSFT"), sc.Sale("MSFT", 0.5)], "duplicate_sale"),
    ([sc.Sale(t) for t in WEIGHTS], "empty_book"),
])
def test_the_sales_a_scenario_refuses(sales, code):
    assert sc.without(_holdings(), sales)["error"] == code


def test_an_unpriced_holding_refuses_the_whole_scenario():
    """V2-E5's rule one layer over: a holding with no market value cannot be a
    share of anything, and renormalising around it would fake the others."""
    hs = _holdings() + [sc.Holding("ZZZ", None, None)]
    assert sc.without(hs, [sc.Sale("NVDA")])["error"] == "unpriced_holding"


# ── the sale, as a row a run's readers can take ─────────────────────────────

class _Check:
    def __init__(self, key, cur, warn, brch, status):
        self.check_key, self.current_value, self.warning_level, self.breach_level, self.status = \
            key, cur, warn, brch, status


class _Alert:
    def __init__(self, key, entity, cur, lim, sev="warning"):
        self.check_key, self.alert_type, self.entity_id = key, key.split(":")[0], entity
        self.current_value, self.limit_value, self.severity = cur, lim, sev


def _scenario_row():
    book = sc.without(_holdings(), [sc.Sale("NVDA")])
    w = book.weights["MSFT"]
    checks = [_Check("issuer_concentration:MSFT", w, 0.15, 0.20, "warning"),
              _Check("issuer_concentration:AAPL", book.weights["AAPL"], 0.15, 0.20, "warning"),
              _Check("gross_exposure", 1.0, 1.05, 1.10, "ok")]
    alerts = [_Alert("issuer_concentration:MSFT", "MSFT", w, 0.15)]
    recorded = ssvc.recorded_shape(book, checks, alerts)
    row = type("Row", (), {"id": "calc_scn", "operation": tc.SCENARIO_OP,
                           "params": {"run_id": RUN, "as_of": AS_OF.isoformat()},
                           "result": recorded, "unit_class": None, "company_id": None})()
    return book, row


def test_the_scenario_row_publishes_a_runs_names_with_a_runs_units():
    book, row = _scenario_row()
    r = qn._from_scenario(row, "calc_scn")
    held = {q.label: q for q in r.quantities}
    assert held["issuer_exposures.MSFT.weight"].value == pytest.approx(book.weights["MSFT"])
    assert held["issuer_exposures.MSFT.weight"].unit_class == qn.RATIO
    assert held["issuer_exposures.MSFT.market_value"].unit_class == qn.MONEY
    assert "issuer_exposures.NVDA.weight" not in held, "the name sold is gone"
    assert held["sector_exposures.Technology.weight"].unit_class == qn.RATIO
    assert held["exposure_metrics.portfolio_market_value"].value == pytest.approx(book.market_value)
    assert held["limit_checks.issuer_concentration:MSFT.current_value"].unit_class == qn.RATIO
    assert held["limit_checks.issuer_concentration:MSFT.warning_level"].value == 0.15
    assert held["count.positions"].value == 9 and held["count.alerts"].value == 1
    assert held["count.limit_checks.fired=true"].value == 1
    assert held["count.limit_checks.fired=false"].value == 2
    # The groups are the run's groups, from the same patterns.
    assert held["issuer_exposures.MSFT.weight"].group == "concentration"
    assert held["limit_checks.issuer_concentration:MSFT.current_value"].group == "mandate"
    assert held["count.positions"].group == "counts"


def test_the_scenario_writer_writes_only_columns_the_declaration_names():
    """Writer ⊆ declaration, per table. A value key the resources do not
    declare is a number the tool produced that nothing can cite; a label key
    or a status is text, not a figure, and is listed here as such."""
    _, row = _scenario_row()
    declared = {r.table: {c.name for c in r.columns} for r in resources.RUN_CHILDREN}
    text_keys = {"label", "sector", "status", "fired"}
    for table in qn.SCENARIO_TABLES:
        held = row.result[table]
        rows = held if isinstance(held, list) else [held]
        for r in rows:
            assert set(r) - text_keys <= declared[table], (table, set(r) - text_keys - declared[table])


async def test_a_scenario_weight_is_an_operand_whose_base_is_the_scenario(monkeypatch):
    """The change the sale makes: scenario MSFT weight − run MSFT weight goes
    through (two books differenced), their sum is refused."""
    book, row = _scenario_row()
    scn = qn._from_scenario(row, "calc_scn")
    d = _Desk(monkeypatch, {RUN: _run_quantities(), "calc_scn": list(scn.quantities)},
              {RUN: (RUN, AS_OF), "calc_scn": ("calc_scn", AS_OF)})
    t = await tc._resolve(None, "calc_scn:issuer_exposures.MSFT.weight")
    assert t.base == "calc_scn" and t.instant == AS_OF and t.issuers == ("MSFT",)
    change = await d.calc("subtract", "calc_scn:issuer_exposures.MSFT.weight",
                          f"{RUN}:issuer_exposures.MSFT.weight", as_quantity="msft_weight_change")
    assert "error" not in change, change
    assert change["value"] == pytest.approx(book.weights["MSFT"] - WEIGHTS["MSFT"])
    assert change["type"]["base"] is None if "base" in change["type"] else True
    summed = await d.calc("add", "calc_scn:issuer_exposures.MSFT.weight", f"{RUN}:issuer_exposures.MSFT.weight")
    assert summed["error"] == "different_books"


def test_the_scenario_context_reads_base_and_date_from_the_rows_params():
    """A scenario's base is the row itself (the hypothetical book IS the row);
    an analysis row's base is the run it analysed. Both date from params."""
    src = inspect.getsource(tc._named_context)
    assert "SCENARIO_OP" in src and 'params.get("run_id")' in src and 'params.get("as_of")' in src


def test_sales_are_parsed_with_one_as_the_whole_position():
    assert ssvc._sales([{"ticker": "nvda"}]) == [sc.Sale("NVDA", 1.0)]
    assert ssvc._sales([{"ticker": "MSFT", "fraction": 0.25}]) == [sc.Sale("MSFT", 0.25)]
    assert ssvc._sales([])["error"] == "bad_sale"
    assert ssvc._sales([{"fraction": 1}])["error"] == "bad_sale"


# ── what the first live turns taught (2026-09-04, deployed stack) ──────────

async def test_a_named_figure_on_a_single_valued_row_is_the_row(monkeypatch):
    """Live turn 2 wrote `calc_…:issuer_concentration:MSFT.excess_weight` for a
    calculator row that holds one figure, and was refused `undated_operand`
    although the bare id carried the date and the base. A row of one figure IS
    that figure; the bare resolution (leaves, base and all) is the answer."""
    excess = tc.Typed(value=0.0125, unit_class=units.RATIO, instant=AS_OF, base=RUN,
                      quantity="issuer_concentration:MSFT.excess_weight", source_id="calc_x",
                      issuers=("issuer_concentration:MSFT",))
    d = _Desk(monkeypatch, {}, {}, facts={"calc_x": excess})

    async def quantities(_db, rid):
        return qn.Resolved((_q(0.0125, qn.RATIO, "issuer_concentration:MSFT.excess_weight", sid="calc_x"),
                            _q(1.0, qn.COUNT, "quality_flags.n", sid="calc_x")), frozenset(), "scalar")
    monkeypatch.setattr(tc, "_named_quantities", quantities)
    t = await tc._resolve(None, "calc_x:issuer_concentration:MSFT.excess_weight")
    assert t is excess, "resolved as the bare row, not re-derived from the name"


def test_only_a_calculator_row_of_one_figure_takes_the_shortcut():
    one = qn.Resolved((_q(1.0, qn.RATIO, "a", sid="c"), _q(2.0, qn.COUNT, "quality_flags.n", sid="c")),
                      frozenset(), "scalar")
    two = qn.Resolved((_q(1.0, qn.RATIO, "a", sid="c"), _q(2.0, qn.RATIO, "b", sid="c")), frozenset(), "scalar")
    assert tc._is_single_valued(one) and not tc._is_single_valued(two)
    src = inspect.getsource(tc._resolve_named)
    assert 'resolved.kind == "scalar"' in src and 'name.startswith("portfolio.")' in src, (
        "an analysis row with one distance is still a row ABOUT a run")


def test_a_calculator_row_of_the_book_dates_and_bases_itself():
    """`_named_context` reads result_type.base and basis.instant when a ledger
    row has no run_id — the shape every V22 calculator row has."""
    src = inspect.getsource(tc._named_context)
    assert 'rt.get("base")' in src and 'rt["basis"]["instant"]' in src


def test_read_quantities_reads_a_scenario_row_and_refuses_other_ledger_rows():
    """Live turn 1 called read_quantities on the scenario's calc_id and got
    `unknown_run`, then wrote the whole id as a slot name. A scenario is a
    run-shaped row and reads like one; a calculator row is not."""
    src = inspect.getsource(definitions._read_quantities)
    assert "SCENARIO_OP" in src and '"not_a_book"' in src
    rq = build_meta_registry().get("read_quantities")
    assert "hypothetical_book" in rq.description
    assert "calc_" in rq.json_schema["properties"]["run_id"]["description"]


def test_a_scenario_row_names_which_book_it_is_so_a_before_after_table_can_say_so():
    """Live turn 1's table read `issuer exposures weight | issuer exposures
    weight`: the scenario's names are the run's on purpose, so the SUBJECT has
    to tell them apart, and the renderer prefixes it into the derived name."""
    from exposure_workbench.services import answer_blocks as ab
    _, row = _scenario_row()
    row.params["sales"] = [{"ticker": "NVDA", "fraction": 1.0}]
    r = qn._from_scenario(row, "calc_scn")
    assert r.subject == "after_sale_of_NVDA"
    before = ["issuer_exposures.MSFT.weight", "issuer_exposures.AAPL.weight"]
    after = [ab._derivation_name(n, r.subject) for n in before]
    t = ab.derive_table([[b, a] for b, a in zip(before, after)])
    assert t["header"] == ["issuer exposures weight", "after sale of NVDA issuer exposures weight"]
    assert t["labels"] == ["MSFT", "AAPL"]
    assert t["explicit"] == [False, False]


# ── what a book-derived row is called on the legend ────────────────────────

def test_a_figure_made_from_the_books_figures_is_grouped_as_such():
    """`dollars_to_sell` is not a filed figure and not a formula's measure; the
    legend used to call it `fundamentals`. A row whose result_type carries a
    base is a figure of the book."""
    row = type("Row", (), {"id": "calc_d", "operation": "calc.scalar.multiply",
                           "params": {"result_type": {"unit_class": "money", "quantity": "dollars_to_sell",
                                                      "base": RUN, "basis": {"instant": AS_OF.isoformat()}}},
                           "result": {"value": 137509.45}, "unit_class": "MONEY", "company_id": None})()
    assert qn._of_the_book(row)
    assert "book_derived" in resources.GROUP_QUESTIONS
    plain = type("Row", (), {"params": {"result_type": {"unit_class": "ratio", "quantity": "net_margin"}}})()
    assert not qn._of_the_book(plain)


async def test_an_ordering_of_one_books_figures_carries_that_base(monkeypatch):
    d = _desk(monkeypatch)
    r = await d.rank([f"{RUN}:issuer_exposures.{t}.weight" for t in ("MSFT", "AAPL", "NVDA")])
    assert r["type"]["base"] == RUN
    assert d.rows[-1]["params"]["result_type"]["base"] == RUN


# ── the tool, its face, and what the model is told ──────────────────────────

def test_the_scenario_tool_is_meta_only_and_registered():
    assert "hypothetical_book" in faces.FACE_META_AGENT
    assert "hypothetical_book" not in faces.FACE_RESEARCH
    assert build_meta_registry().get("hypothetical_book").name == "hypothetical_book"


def test_the_operators_say_the_grammar_where_the_model_reads_it():
    """The battery's C01#t1 handed rank ten run refs and was refused; the
    description is where the model learns a figure may be named."""
    meta = build_meta_registry()
    calc, rank, analysis, scn = (meta.get(n) for n in
                                 ("calculate", "rank", "get_portfolio_analysis", "hypothetical_book"))
    for tool in (calc, rank):
        assert "run_…:issuer_exposures" in tool.description, tool.name
    assert "ref:name" in calc.json_schema["properties"]["a"]["description"]
    assert "ref:name" in rank.json_schema["properties"]["refs"]["description"]
    assert "calc_id:portfolio.integration.room_to_breach" in analysis.description
    assert "unmeasured" in scn.description and "proceeds leave" in scn.description
    assert any("hypothetical_book" in line for line in definitions._FACE_CAPABILITIES["can"])
    assert any("run_id:issuer_exposures" in line for line in definitions._FACE_CAPABILITIES["can"])


def test_the_scenario_schema_bounds_the_fraction_and_requires_a_ticker():
    scn = build_meta_registry().get("hypothetical_book")
    item = scn.json_schema["properties"]["sales"]["items"]
    assert item["required"] == ["ticker"] and item["additionalProperties"] is False
    assert item["properties"]["fraction"]["exclusiveMinimum"] == 0
    assert item["properties"]["fraction"]["maximum"] == 1
