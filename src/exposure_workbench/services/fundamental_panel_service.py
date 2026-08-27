"""The credit panel, assembled from stored facts. One tool call, one object.

Why a method tool rather than a procedure the model follows: the steps that must
not be skipped — take every component at ONE date, compose a total from a
non-overlapping set, name the four quarters behind a TTM, refuse a financial
issuer outright — are all steps a prompt can only recommend. Here a test fails
when one is removed.

It states no judgement. There is no threshold, no flag, no healthy/risky, and
that is a product decision (2026-08-24): the panel lays out evidence and the
reading belongs to the user. What it does carry is every formula and every
period convention, so the reading can be checked.

EBIT and EBITDA start from net income (SEC C&DI 103.01), and operating income is
returned beside them — not as an alternative but because they answer different
questions and the gap between them is information. Measured on GOOGL's June
2026 quarter: operating income 40.770bn against pretax income 138.753bn, so a
correctly-computed EBIT is almost entirely non-operating and says nothing about
operations on its own.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import fundamental_panel as fp
from exposure_workbench.db.models import Company, FinancialFact, Position
from exposure_workbench.services import calc_service as cs

# Balance-sheet lines the panel may read. All INSTANT (V9-M3 asserts it).
_BALANCES = (
    "long_term_debt_total", "long_term_debt_noncurrent", "current_portion_long_term_debt",
    "debt_current_total", "short_term_borrowings", "commercial_paper",
    "cash_and_equivalents", "current_assets", "current_liabilities",
    "total_assets", "total_liabilities", "stockholders_equity",
    "accounts_receivable", "inventory", "accounts_payable",
)
# Flow lines, summed to TTM.
_FLOWS = (
    "revenue", "total_revenues", "gross_profit", "cost_of_revenue", "operating_income",
    "net_income", "interest_expense", "income_tax_expense", "depreciation_amortization",
    "operating_cash_flow", "capex",
)

# A financial issuer's interest expense is a cost of goods sold, not a financing
# charge: JPM's quarterly interest expense of 24.356bn exceeds its net income of
# 16.494bn. Adding it back produces a number that is not EBIT and not anything
# else. The refusal is total rather than per-line, because every leverage and
# coverage line on this panel rests on the same mistake.
_FINANCIAL_SECTORS = {"Financials", "Financial Services"}


async def _sector(db: AsyncSession, ticker: str) -> str | None:
    """From positions, which is the only place a usable sector lives here:
    companies.sector holds SIC codes for one issuer and NULL for the rest, and
    security_master has no sector column at all."""
    return (await db.execute(
        select(Position.sector).where(Position.ticker == ticker,
                                      Position.sector.is_not(None)).limit(1)
    )).scalar_one_or_none()


async def _balance_dates(db: AsyncSession, company_id: str) -> dict[str, dict[date, tuple[float, str]]]:
    rows = (await db.execute(
        select(FinancialFact.normalized_metric, FinancialFact.period_end,
               FinancialFact.value, FinancialFact.id)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric.in_(_BALANCES),
               FinancialFact.dimensions_hash == "",
               FinancialFact.value.is_not(None))
    )).all()
    out: dict[str, dict[date, tuple[float, str]]] = {}
    for metric, pe, value, fid in rows:
        # Latest filing wins within a period; period_ladder does the same for
        # restatements and this mirrors it for a single-date read.
        out.setdefault(metric, {})[pe] = (float(value), fid)
    return out


def _pick_as_of(balances: dict[str, dict[date, tuple[float, str]]]) -> date | None:
    """The most recent date at which a debt composition can actually be formed.

    Not "the latest date any balance exists": GOOGL has a noncurrent balance at
    2026-06-30 and its last long_term_debt_total at 2025-12-31, and mixing them
    reports a total smaller than its own component.
    """
    dates = sorted({d for per_date in balances.values() for d in per_date}, reverse=True)
    for d in dates:
        present = {m for m, per_date in balances.items() if d in per_date}
        if any(all(k in present for k in recipe) for recipe in fp.DEBT_RECIPES):
            return d
    return dates[0] if dates else None


async def build_panel(db: AsyncSession, ticker: str, invoked_by: str = "agent") -> dict:
    ticker = ticker.upper()
    company_id = (await db.execute(
        select(Company.id).where(Company.ticker == ticker)
    )).scalar_one_or_none()
    if company_id is None:
        return {"error": "unknown_company", "ticker": ticker}

    sector = await _sector(db, ticker)
    if sector in _FINANCIAL_SECTORS:
        return {
            "ticker": ticker, "sector": sector,
            "error": "not_applicable",
            "detail": ("this is a standard non-financial credit panel and it does not "
                       "apply to a financial issuer: interest expense is an operating "
                       "cost for a bank, so leverage and coverage built on adding it "
                       "back describe nothing"),
        }

    balances = await _balance_dates(db, company_id)
    as_of = _pick_as_of(balances)
    if as_of is None:
        return {"ticker": ticker, "error": "no_balance_sheet_data"}

    at_date = {m: v for m, (v, _f) in
               ((m, per[as_of]) for m, per in balances.items() if as_of in per)}
    bal_ids = {m: f for m, (_v, f) in
               ((m, per[as_of]) for m, per in balances.items() if as_of in per)}

    def bal(metric: str) -> fp.Line:
        if metric not in at_date:
            return fp.Missing(missing=(metric,),
                              reason=f"{metric} not reported at {as_of.isoformat()}")
        return fp.Amount(value=at_date[metric], formula=metric,
                         basis=f"as of {as_of.isoformat()}",
                         fact_ids=(bal_ids[metric],))

    # Flows, as TTM.
    flows: dict[str, fp.Line] = {}
    for metric in _FLOWS:
        try:
            points, _flags = await cs.load_fact_series(
                db, cs.SeriesSpec(ticker, metric, period_type="quarterly", last_n=8))
        except Exception:
            flows[metric] = fp.Missing(missing=(metric,),
                                       reason=f"{metric} is not reported by this issuer")
            continue
        flows[metric] = fp.ttm([fp.Q(period_end=p.period_end, value=p.value,
                                     fact_ids=tuple(p.input_fact_ids))
                                for p in points if p.value is not None])

    # Whichever top line this issuer reports — named, never guessed. NVDA changed
    # tagging in 2022 and LLY only ever reports the total, so this is the normal
    # case rather than an edge one.
    revenue = flows["revenue"] if isinstance(flows["revenue"], fp.Amount) else flows["total_revenues"]
    revenue_name = ("revenue (from contracts with customers)"
                    if isinstance(flows["revenue"], fp.Amount) else "total revenues")

    debt = fp.total_debt(at_date)
    if isinstance(debt, fp.Amount):
        debt = fp.Amount(value=debt.value, formula=debt.formula,
                         basis=f"as of {as_of.isoformat()}",
                         fact_ids=tuple(bal_ids[k] for k in debt.formula.split(" + ")
                                        if k in bal_ids))

    ebit = fp.add({"net_income": flows["net_income"],
                   "interest_expense": flows["interest_expense"],
                   "income_tax_expense": flows["income_tax_expense"]},
                  formula="net income + interest expense + income tax expense (SEC C&DI 103.01)")
    ebitda = fp.add({"ebit": ebit, "depreciation_amortization": flows["depreciation_amortization"]},
                    formula="EBIT + D&A (SEC C&DI 103.01)")
    fcf = (fp.Amount(value=flows["operating_cash_flow"].value - flows["capex"].value,
                     formula="operating cash flow − capital expenditures (SEC C&DI 102.07)",
                     basis=flows["operating_cash_flow"].basis,
                     fact_ids=flows["operating_cash_flow"].fact_ids + flows["capex"].fact_ids,
                     quarters=flows["operating_cash_flow"].quarters)
           if isinstance(flows["operating_cash_flow"], fp.Amount)
           and isinstance(flows["capex"], fp.Amount)
           else fp.Missing(missing=("operating_cash_flow", "capex"),
                           reason="free cash flow needs both operating cash flow and capex"))

    lines: dict[str, fp.Line] = {
        # what the book owes
        "total_debt": debt,
        "cash_and_equivalents": bal("cash_and_equivalents"),
        "net_debt": fp.add({"total_debt": debt,
                            "cash": _negate(bal("cash_and_equivalents"))},
                           formula="total debt − cash and equivalents (not an agency-adjusted net debt)"),
        # what it earns, on three bases that answer different questions
        "operating_income_ttm": flows["operating_income"],
        "ebit_ttm": ebit,
        "ebitda_ttm": ebitda,
        # can it carry the debt
        "ebit_interest_coverage": fp.ratio(ebit, flows["interest_expense"],
                                           name="ebit_interest_coverage",
                                           formula="TTM EBIT ÷ TTM interest expense"),
        "debt_to_ebitda": fp.ratio(debt, ebitda, name="debt_to_ebitda",
                                   formula="total debt ÷ TTM EBITDA"),
        "debt_to_ocf": fp.ratio(debt, flows["operating_cash_flow"], name="debt_to_ocf",
                                formula="total debt ÷ TTM operating cash flow"),
        # can it pay this year
        "current_ratio": fp.ratio(bal("current_assets"), bal("current_liabilities"),
                                  name="current_ratio",
                                  formula="current assets ÷ current liabilities"),
        # what it generates
        "operating_cash_flow_ttm": flows["operating_cash_flow"],
        "free_cash_flow_ttm": fcf,
        "fcf_to_debt": fp.ratio(fcf, debt, name="fcf_to_debt",
                                formula="TTM free cash flow ÷ total debt"),
        # margins, against whichever top line this issuer reports
        "gross_margin": fp.ratio(flows["gross_profit"], revenue, name="gross_margin",
                                 formula=f"TTM gross profit ÷ TTM {revenue_name}"),
        "operating_margin": fp.ratio(flows["operating_income"], revenue, name="operating_margin",
                                     formula=f"TTM operating income ÷ TTM {revenue_name}"),
        "net_margin": fp.ratio(flows["net_income"], revenue, name="net_margin",
                               formula=f"TTM net income ÷ TTM {revenue_name}"),
        # working capital, on ending balances (an average needs two dates and
        # doubles the surface a missing quarter can remove)
        "days_sales_outstanding": _days(bal("accounts_receivable"), revenue,
                                        "accounts receivable", f"TTM {revenue_name}"),
        "days_inventory": _days(bal("inventory"), flows["cost_of_revenue"],
                                "inventory", "TTM cost of revenue"),
        "days_payable": _days(bal("accounts_payable"), flows["cost_of_revenue"],
                              "accounts payable", "TTM cost of revenue"),
    }

    return {
        "ticker": ticker,
        "sector": sector,
        "sector_unknown": sector is None,
        "as_of": as_of.isoformat(),
        "revenue_basis": revenue_name,
        "judgement": ("none: this panel reports measured values and their definitions. "
                      "Thresholds and conclusions are the reader's."),
        "lines": {name: _render(name, line) for name, line in lines.items()},
    }


def _negate(line: fp.Line) -> fp.Line:
    if isinstance(line, fp.Missing):
        return line
    return fp.Amount(value=-line.value, formula=f"−{line.formula}", basis=line.basis,
                     fact_ids=line.fact_ids, quarters=line.quarters)


def _days(balance: fp.Line, flow: fp.Line, bal_name: str, flow_name: str) -> fp.Line:
    r = fp.ratio(balance, flow, name=f"days of {bal_name}",
                 formula=f"ending {bal_name} ÷ {flow_name} × 365")
    if isinstance(r, fp.Missing):
        return r
    return fp.Amount(value=r.value * 365, formula=r.formula, basis=r.basis,
                     fact_ids=r.fact_ids, quarters=r.quarters)


def _render(name: str, line: fp.Line) -> dict:
    if isinstance(line, fp.Missing):
        return {"name": name, "status": "unavailable",
                "missing": list(line.missing), "reason": line.reason,
                "also_reported": list(line.alternatives)}
    return {"name": name, "value": line.value, "formula": line.formula,
            "basis": line.basis, "fact_ids": list(dict.fromkeys(line.fact_ids)),
            "quarters": list(line.quarters)}
