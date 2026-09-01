"""V16 Lane E — the registry's failure conditions fire, and its shape is
checked at import, not at a user (offline).

Three families of guard:

  * FAILURE CONDITIONS AS DATA. A formula that does not apply — to a negative
    denominator, to a financial issuer — refuses with the sentence the
    REGISTRY carries for it, per formula and per reason. ROE is the case that
    forced this: banks report ROE, so the panel-wide "interest expense is an
    operating cost for a bank" refusal was wrong for it, and negative book
    equity makes ROE a number Damodaran says to suppress rather than display.

  * IMPORT-TIME VALIDATION. Every rule in fm.validate removes a silent-failure
    class the V16 audit found live in the evaluator: difference with signs=()
    returned its first operand as the answer, an unknown op fell through to
    divide, a three-input divide dropped its third input. Each rule has its
    counterexample here.

  * THE FINAL ROW CARRIES THE NAME. Whatever the operand count — one-component
    cover, two-term quotient, three-term difference — the last ledger row a
    formula writes is named for the formula (as_quantity), because that row is
    what the table calls the value. The one-component cover used to return a
    bare fact id and the name landed nowhere.

The arithmetic itself is stubbed: what these tests pin is which calls the
evaluator makes and what it names them, which is exactly the surface the audit
found silently wrong. The live half is the integration battery.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services import formula_service as fsvc

W0, W1 = "2025-07-01", "2026-06-30"
AS_OF = "2026-06-30"

# A sector value meaning "the gate must not even look": bank-applicable
# formulas skip the sector query entirely, and asking would be the bug.
_MUST_NOT_ASK = object()


def _bs(balances: dict[str, float]) -> dict:
    return {
        "ticker": "TEST", "as_of": AS_OF,
        "balances": {m: {"value": v, "fact_id": f"fact_{m}", "as_of": AS_OF}
                     for m, v in balances.items()},
        "not_reported_at_this_date": {},
        "basis": f"balance sheet as of {AS_OF}; one instant, no substitution",
    }


class Desk:
    """Every collaborator evaluate_formula reaches, held still and recorded."""

    def __init__(self, monkeypatch, *, balances: dict | None = None,
                 flows: dict | None = None, sector: object = None):
        self.calls: list[tuple] = []      # (op, a, b, as_quantity)
        self.scales: list[tuple] = []     # (ref, factor, unit_class, quantity)
        self.refusals: list[dict] = []
        self._n = 0
        flows = flows or {}
        bs = _bs(balances or {})

        async def get_balance_sheet(_db, _t, at=None, invoked_by="agent"):
            return bs

        async def get_flow(_db, _t, metric, months=None, start=None, end=None,
                           last_n=None, invoked_by="agent"):
            if metric not in flows:
                return {"error": "not_derivable", "metric": metric,
                        "detail": f"no {metric} on this desk"}
            return {"calc_id": f"calc_flow_{metric}", "value": flows[metric],
                    "basis": f"{start or W0}..{end or W1}",
                    "period": {"start": start or W0, "end": end or W1}}

        async def calculate(_db, op, a, b, invoked_by="agent", as_quantity=None):
            self._n += 1
            self.calls.append((op, a, b, as_quantity))
            return {"calc_id": f"calc_step_{self._n}", "op": op, "value": 1.0,
                    "basis": "stub"}

        async def scale(_db, ref, factor, *, unit_class, quantity=None,
                        invoked_by="agent"):
            self._n += 1
            self.scales.append((ref, factor, unit_class, quantity))
            return {"calc_id": f"calc_scale_{self._n}", "value": factor,
                    "basis": "stub"}

        async def sector_fn(_db, _t):
            assert sector is not _MUST_NOT_ASK, (
                "the sector was consulted for a formula whose "
                "not_for_financials is None; the gate must not run at all")
            return sector

        async def refuse(_db, error, *, kind, ticker, statement, tried=None,
                         stopped_at=None, neighbours=None, invoked_by="agent",
                         **extra):
            self._n += 1
            out = {"error": error, "absence_id": f"calc_absent_{self._n}",
                   "statement": statement, **extra}
            self.refusals.append(out)
            return out

        monkeypatch.setattr(fsvc.fs, "get_balance_sheet", get_balance_sheet)
        monkeypatch.setattr(fsvc.fs, "get_flow", get_flow)
        monkeypatch.setattr(fsvc.tc, "calculate", calculate)
        monkeypatch.setattr(fsvc.tc, "scale", scale)
        monkeypatch.setattr(fsvc, "_sector", sector_fn)
        monkeypatch.setattr(fsvc.ab, "refuse", refuse)

    @property
    def named(self) -> list[str | None]:
        return [q for *_ignored, q in self.calls]


# ── failure conditions: the denominator that flips the sign ──────────────────

async def test_roe_refuses_a_non_positive_equity_with_the_registrys_sentence(monkeypatch):
    Desk(monkeypatch, balances={"stockholders_equity": -5.0e9},
         flows={"net_income": 1.0e9}, sector=_MUST_NOT_ASK)
    out = await fsvc.evaluate_formula(None, "TEST", "roe")
    assert out["error"] == "not_meaningful"
    assert fm.FORMULAS["roe"].denominator_must_be_positive in out["statement"]
    assert "stockholders_equity is not positive" in out["statement"]


async def test_equity_multiplier_refuses_a_non_positive_equity(monkeypatch):
    Desk(monkeypatch, balances={"total_assets": 1.0e10, "stockholders_equity": 0.0},
         sector=_MUST_NOT_ASK)
    out = await fsvc.evaluate_formula(None, "TEST", "equity_multiplier")
    assert out["error"] == "not_meaningful"
    assert fm.FORMULAS["equity_multiplier"].denominator_must_be_positive in out["statement"]


async def test_roe_over_positive_equity_computes_and_names_its_row(monkeypatch):
    desk = Desk(monkeypatch, balances={"stockholders_equity": 5.0e9},
                flows={"net_income": 1.0e9}, sector=_MUST_NOT_ASK)
    out = await fsvc.evaluate_formula(None, "TEST", "roe")
    assert not out.get("error")
    assert desk.calls == [("divide", "calc_flow_net_income",
                           "fact_stockholders_equity", "roe")]
    assert out["calc_id"] == "calc_step_1"


# ── failure conditions: the financial issuer, per formula and per reason ─────

def test_the_bank_applicable_set_is_exactly_the_measures_banks_report():
    applies = {n for n, f in fm.FORMULAS.items() if f.not_for_financials is None}
    assert applies == {"roe", "roa", "tax_burden", "asset_turnover",
                       "equity_multiplier", "accruals", "accruals_ratio"}


def test_net_debt_to_ebitda_refuses_banks_exactly_as_debt_to_ebitda_does():
    """One mechanism, one sentence: the new leverage measure carries the same
    default reason its sibling has always been refused with."""
    assert (fm.FORMULAS["net_debt_to_ebitda"].not_for_financials
            == fm.FORMULAS["debt_to_ebitda"].not_for_financials
            == fm.NOT_FOR_FINANCIALS_DEFAULT)


@pytest.mark.parametrize("name", ["roic", "nopat", "invested_capital",
                                  "quick_ratio", "quick_assets", "fcf_margin",
                                  "capex_intensity", "net_debt_to_ebitda",
                                  "cash_conversion_cycle"])
async def test_a_bank_excluded_formula_refuses_with_its_own_reason(monkeypatch, name):
    Desk(monkeypatch, sector="Financials")
    out = await fsvc.evaluate_formula(None, "JPM", name)
    assert out["error"] == "not_applicable"
    assert fm.FORMULAS[name].not_for_financials in out["statement"]
    assert name in out["statement"]


async def test_roe_is_not_refused_for_a_bank(monkeypatch):
    """The case that forced per-formula refusals: ROE is the profitability
    measure banks themselves report, and the sector gate must not even run."""
    desk = Desk(monkeypatch, balances={"stockholders_equity": 3.0e11},
                flows={"net_income": 5.0e10}, sector=_MUST_NOT_ASK)
    out = await fsvc.evaluate_formula(None, "JPM", "roe")
    assert not out.get("error")
    assert desk.named == ["roe"]


async def test_bank_refusals_for_one_reason_share_one_absence_row(monkeypatch):
    """roic and nopat are refused for the same sentence; within one panel's
    cache that is ONE absence row, the way _unavailable shares a missing
    input's row. A different sentence (quick_ratio) is a different row."""
    desk = Desk(monkeypatch, sector="Financials")
    cache: dict = {}
    a = await fsvc.evaluate_formula(None, "JPM", "roic", _cache=cache)
    b = await fsvc.evaluate_formula(None, "JPM", "nopat", _cache=cache)
    c = await fsvc.evaluate_formula(None, "JPM", "quick_ratio", _cache=cache)
    assert a["absence_id"] == b["absence_id"]
    assert b["formula"] == "nopat", "the shared row still names each formula"
    assert c["absence_id"] != a["absence_id"]
    assert len(desk.refusals) == 2


# ── import-time validation: one counterexample per silent-failure class ──────

def _formula(**kw) -> fm.Formula:
    base = dict(expression="a over b", inputs=("net_income", "revenue"),
                op="divide", basis="window", source_url="https://example.test",
                unit_class="ratio")
    base.update(kw)
    return fm.Formula(**base)


@pytest.mark.parametrize("bad,because", [
    (dict(op="ratio_of"), "unknown op used to fall through the else-branch into divide"),
    (dict(op="divide", inputs=("a", "b", "c")),
     "a three-input divide evaluated two and dropped the third"),
    (dict(op="product", inputs=("a",)), "product is binary"),
    (dict(op="sum", inputs=("a",)),
     "a one-term sum returns its input under another name, unrenamed"),
    (dict(op="difference", inputs=("a", "b"), signs=()),
     "signs=() looped zero times and returned the first operand as the answer"),
    (dict(op="difference", inputs=("a", "b", "c"), signs=(1, -1)),
     "too few signs silently drop trailing inputs"),
    (dict(op="difference", inputs=("a", "b"), signs=(-1, -1)),
     "signs[0] is never read, so -1 there would be silently ignored"),
    (dict(op="difference", inputs=("a", "b"), signs=(1, 2)),
     "a sign is +1 or -1, nothing else"),
    (dict(op="sum", inputs=("a", "b"), signs=(1, -1)),
     "signs on a sum would be silently ignored"),
    (dict(op="divide", unit_class="count", expression="a over b"),
     "a count from a divide is scaled by 365 and the expression must say so"),
    (dict(op="sum", inputs=("a", "b"),
          denominator_must_be_positive="no denominator to check"),
     "the denominator condition only means something on a divide"),
    (dict(unit_class="dollars"), "unit_class outside the vocabulary"),
])
def test_a_malformed_formula_is_refused_at_import(bad, because):
    with pytest.raises(ValueError):
        fm.validate({"bad": _formula(**bad)})


def test_the_live_registry_passes_its_own_validation():
    fm.validate(fm.FORMULAS)          # raises on failure; importing already ran it


def test_a_count_divide_that_states_its_365_is_valid():
    fm.validate({"ok": _formula(op="divide", unit_class="count",
                                expression="a ÷ b × 365")})


# ── the final row carries the name, at every operand count ───────────────────

async def test_a_single_component_cover_still_writes_a_row_named_total_debt(monkeypatch):
    """The audit's finding: one component meant a bare fact id came back and
    the name landed nowhere. Now an identity scale row carries it."""
    desk = Desk(monkeypatch, balances={"long_term_debt_total": 8.4e9})
    got = await fsvc._total_debt(None, "TEST", None, "test")
    assert desk.scales == [("fact_long_term_debt_total", 1.0, "money", "total_debt")]
    assert got["id"].startswith("calc_scale"), "a ledger row, not the bare fact"
    assert desk.calls == [], "no addition was invented to get a row"


async def test_a_three_component_cover_names_only_its_final_step(monkeypatch):
    desk = Desk(monkeypatch, balances={"long_term_debt_noncurrent": 5.0e9,
                                       "current_portion_long_term_debt": 1.0e9,
                                       "commercial_paper": 2.0e9})
    got = await fsvc._total_debt(None, "TEST", None, "test")
    assert desk.named == [None, "total_debt"]
    assert got["id"] == "calc_step_2"


async def test_a_three_term_sum_names_only_its_final_step(monkeypatch):
    # ebit is bank-excluded, so its gate legitimately asks for the sector.
    desk = Desk(monkeypatch, sector="Technology",
                flows={"net_income": 9.0e9, "interest_expense": 1.0e9,
                       "income_tax_expense": 2.0e9})
    out = await fsvc.evaluate_formula(None, "TEST", "ebit")
    assert not out.get("error")
    assert [(op, q) for op, _a, _b, q in desk.calls] == [("add", None), ("add", "ebit")]
    assert out["calc_id"] == "calc_step_2"


async def test_a_three_term_difference_follows_its_signs_and_names_the_last_row(monkeypatch):
    """invested_capital = total_debt + equity − cash: signs (1, 1, -1), the
    subtract is the final, named step, and the nested total_debt keeps its own
    named row on the way."""
    desk = Desk(monkeypatch, sector="Technology",
                balances={"long_term_debt_total": 8.0e9,
                          "stockholders_equity": 6.0e10,
                          "cash_and_equivalents": 3.0e10})
    out = await fsvc.evaluate_formula(None, "TEST", "invested_capital")
    assert not out.get("error")
    assert desk.scales[0][3] == "total_debt"
    assert [(op, q) for op, _a, _b, q in desk.calls] == [
        ("add", None), ("subtract", "invested_capital")]
    assert out["calc_id"] == "calc_step_3"      # scale row was step 1


async def test_a_product_formula_names_its_one_multiply(monkeypatch):
    desk = Desk(monkeypatch, sector="Technology",
                flows={"operating_income": 1.0e10, "net_income": 8.0e9,
                       "pretax_income": 1.0e10})
    out = await fsvc.evaluate_formula(None, "TEST", "nopat")
    assert not out.get("error")
    assert [(op, q) for op, _a, _b, q in desk.calls] == [
        ("divide", "tax_burden"), ("multiply", "nopat")]
    assert out["calc_id"] == "calc_step_2"


# ── the days path is derived from unit_class, not a second list ──────────────

def test_the_days_list_is_gone_the_unit_class_is_the_rule():
    """DAYS_FORMULAS was a second list that had to agree with unit_class; the
    unit_class is now the rule, so there is nothing to drift."""
    assert not hasattr(fm, "DAYS_FORMULAS")
    for name, f in fm.FORMULAS.items():
        if f.op == "divide" and f.unit_class == "count":
            assert "365" in f.expression, name


async def test_a_count_divide_scales_by_365_and_the_scale_row_carries_the_name(monkeypatch):
    desk = Desk(monkeypatch, sector="Technology",
                balances={"accounts_receivable": 4.0e9}, flows={"revenue": 2.0e10})
    out = await fsvc.evaluate_formula(None, "TEST", "days_sales_outstanding")
    assert not out.get("error")
    assert desk.named == [None], "the quotient row is anonymous"
    (ref, factor, unit_class, quantity) = desk.scales[0]
    assert (factor, unit_class, quantity) == (365, "count", "days_sales_outstanding")
    assert out["calc_id"].startswith("calc_scale"), (
        "the value printed is the scaled row the ledger holds")


async def test_the_cash_conversion_cycle_is_a_named_difference_of_the_three_days(monkeypatch):
    desk = Desk(monkeypatch, sector="Technology",
                balances={"accounts_receivable": 4.0e9, "inventory": 3.0e9,
                          "accounts_payable": 5.0e9},
                flows={"revenue": 2.0e10, "cost_of_revenue": 1.4e10})
    out = await fsvc.evaluate_formula(None, "TEST", "cash_conversion_cycle")
    assert not out.get("error")
    # Three quotient-and-scale pairs, then + days_inventory − days_payable.
    assert [q for *_x, q in desk.scales] == [
        "days_sales_outstanding", "days_inventory", "days_payable"]
    assert [(op, q) for op, _a, _b, q in desk.calls] == [
        ("divide", None), ("divide", None), ("divide", None),
        ("add", None), ("subtract", "cash_conversion_cycle")]


# ── method knowledge travels as data ─────────────────────────────────────────

def test_roe_carries_the_dupont_decomposition_in_its_note():
    """The decomposition is method knowledge an agent may quote, and it names
    the registry's own measures so each leg is one evaluate_formula away."""
    note = fm.FORMULAS["roe"].note
    assert "net_margin × asset_turnover × equity_multiplier" in note
    for leg in ("net_margin", "asset_turnover", "equity_multiplier"):
        assert leg in fm.FORMULAS, f"the DuPont note names {leg}, which must exist"


def test_every_new_formula_names_its_authority():
    for name in ("roe", "roa", "roic", "nopat", "tax_burden", "invested_capital",
                 "asset_turnover", "equity_multiplier", "quick_assets",
                 "quick_ratio", "fcf_margin", "capex_intensity",
                 "net_debt_to_ebitda", "cash_conversion_cycle", "accruals",
                 "accruals_ratio"):
        auth = fm.authority(fm.FORMULAS[name])
        assert auth["url"].startswith("https://"), name
        assert auth["cite_as"], name


def test_accruals_ratio_cites_sloan():
    assert "Sloan" in fm.FORMULAS["accruals_ratio"].citation
