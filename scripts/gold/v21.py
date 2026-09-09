"""Gold figures for the V21 conversation battery (tests/battery/conversations_v21.json).

One derivation per turn tag. Each computes, with the desk's own services and
never a model or a tool wrapper, the figure(s) a correct answer must contain
(`must=True`) and the supporting figures the desk would produce beside them
(`must=False`). A turn whose answer is not a computable figure is `skip`ped
with the reason.

Book = port_001 (AAPL MSFT GOOGL NVDA JPM AMZN TLT HYG LLY XOM); every run
figure is read off the latest completed run at derivation time, so the gold
follows the fixture rather than pinning a run id.

    python scripts/gold_derive.py v21
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import ExposureRun
from exposure_workbench.services import (
    fundamentals_service as fs,
    formula_service as fo,
    integration_service as ig,
    price_analytics_service as pa,
    run_reads_service as rr,
    scenario_service as sc,
    series_service as ss,
    typed_calculator as tc,
)
from scripts.gold import Figure, Gold, skip

PORTFOLIO = "port_001"
HOLDINGS = ("AAPL", "MSFT", "GOOGL", "NVDA", "JPM", "AMZN", "TLT", "HYG", "LLY", "XOM")
ISSUERS = ("AAPL", "MSFT", "GOOGL", "NVDA", "JPM", "AMZN", "LLY", "XOM")   # names with filings
MEGACAPS = ("MSFT", "AAPL", "GOOGL", "AMZN", "NVDA")
INVOKED = "gold"

RATIO, MONEY, MULTIPLE, COUNT = "RATIO", "MONEY", "MULTIPLE", "COUNT"


# ── shared readers ────────────────────────────────────────────────────────────

async def _latest_run(db: AsyncSession) -> str:
    fr = await rr.get_run_freshness(db, PORTFOLIO)
    rid = fr.get("latest_completed_run")
    if not rid:
        raise RuntimeError(f"no completed run on {PORTFOLIO}: {fr}")
    return rid


async def _weights(db: AsyncSession, rid: str) -> dict[str, float]:
    """issuer_exposures.<T>.weight for every position on the run, read through
    the attribution payload (the run's own rows)."""
    at = await rr.get_attribution(db, rid)
    if at.get("error"):
        raise RuntimeError(f"get_attribution: {at}")
    return {p["ticker"]: p["weight"] for p in at["positions"] if p.get("weight") is not None}


async def _headroom(db: AsyncSession, rid: str) -> tuple[dict, dict[str, dict]]:
    """integration_service.get_portfolio_analysis: the analysis and its headroom
    rows keyed by check name (issuer_concentration:MSFT, ...)."""
    an = await ig.get_portfolio_analysis(db, rid)
    if an.get("error"):
        raise RuntimeError(f"get_portfolio_analysis: {an}")
    return an, {h["check"]: h for h in an["headroom"]}


async def _formula(db: AsyncSession, ticker: str, name: str, months: int = 12) -> dict:
    return await fo.evaluate_formula(db, ticker, name, months=months, invoked_by=INVOKED)


def _refusal(res: dict) -> str:
    return res.get("statement") or res.get("detail") or res.get("error") or "refused"


async def _flow(db: AsyncSession, ticker: str, metric: str, months: int = 12) -> dict:
    return await fs.get_flow(db, ticker, metric, months=months, invoked_by=INVOKED)


async def _yoy_latest(db: AsyncSession, ticker: str, metric: str, months: int,
                      last_n: int) -> tuple[float | None, str]:
    """The latest year-over-year change of a filed metric on the issuer's own
    reporting grid: get_flow(last_n=...) then the yoy series operator, which
    matches each point to its prior by date. Returns (value, basis) or
    (None, refusal)."""
    series = await fs.get_flow(db, ticker, metric, months=months, last_n=last_n,
                               invoked_by=INVOKED)
    if series.get("error"):
        return None, _refusal(series)
    ch = await ss.series_stat(db, series["calc_id"], "yoy", invoked_by=INVOKED)
    if ch.get("error"):
        return None, _refusal(ch)
    valued = [p for p in ch["points"] if p.get("value") is not None]
    if not valued:
        return None, f"yoy over {series['calc_id']} produced no valued point"
    last = valued[-1]
    period = last.get("period_end") or last.get("end")
    return float(last["value"]), (f"yoy of {ticker} {metric} over {months}-month windows on the "
                                  f"issuer's own reporting grid (get_flow last_n={last_n}, then "
                                  f"series yoy), latest point {period}")


# ── C01 trim one ──────────────────────────────────────────────────────────────

async def c01_t1(db: AsyncSession) -> Gold:
    return skip("which name to cut is a portfolio judgement over several lenses; the desk "
                "has no single figure that answers it (weights, headroom and per-name "
                "measures are supporting evidence, not the answer)")


async def c01_t2(db: AsyncSession) -> Gold:
    return skip("whether the fundamentals agree depends on which name t1 landed on (the "
                "model's judgement), and 'just expensive' needs a valuation measure the "
                "desk does not hold (no price multiple in the formula registry)")


async def c01_t3(db: AsyncSession) -> Gold:
    """The book after selling the name the desk's own ordering would pick: the
    issuer check with the least room to its breach level (integration headroom,
    sorted by room_to_breach). Which name t1 actually landed on is the model's
    judgement, so nothing here is must."""
    rid = await _latest_run(db)
    _an, room = await _headroom(db, rid)
    issuer_checks = sorted((h for k, h in room.items() if k.startswith("issuer_concentration:")),
                           key=lambda h: h["room_to_breach"])
    pick = issuer_checks[0]["check"].split(":", 1)[1]
    before = await _weights(db, rid)
    after = await sc.hypothetical_book(db, rid, [{"ticker": pick, "fraction": 1.0}])
    if after.get("error"):
        raise RuntimeError(f"hypothetical_book: {after}")
    positions = after["positions"]                     # sorted by weight desc
    largest = positions[0]
    note = (f"scenario_service.hypothetical_book on {rid} selling all of {pick} — the desk's "
            f"own pick: the issuer check with the least room to breach on the run "
            f"({issuer_checks[0]['room_to_breach']:.6g}). t1's pick is the model's judgement, "
            f"so these are supporting figures only.")
    figs = [
        Figure("largest_weight_after_sale", float(largest["weight"]), RATIO, largest["label"],
               must=False, note=note + f" Largest name after the sale is {largest['label']}."),
        Figure("alerts_after_sale", float(len(after["alerts"])), COUNT, None, must=False,
               note="count of concentration/exposure alerts on the scenario row "
                    "(daily_loss and rolling_volatility_30d checks do not run on a scenario)"),
    ]
    for p in positions:
        t = p["label"]
        figs.append(Figure("weight_after_sale", float(p["weight"]), RATIO, t, must=False,
                           note=f"{t} weight after the sale; before it was {before.get(t)}"))
    for a in after["alerts"]:
        figs.append(Figure(f"alert_{a['severity']}_current", float(a["current_value"]), RATIO,
                           a["entity_id"], must=False,
                           note=f"{a['alert_type']} {a['severity']} at level {a['limit_value']}"))
    return Gold(figures=figs, identity=[after["as_of"], pick])


# ── C02 NVDA bear ─────────────────────────────────────────────────────────────

async def c02_t1(db: AsyncSession) -> Gold:
    return skip("a bear case built from filing text is an argument, not a figure")


async def c02_t2(db: AsyncSession) -> Gold:
    return skip("which risk shows up first and what to watch follows from the risks t1 chose "
                "(the model's judgement); no desk figure answers it on its own")


# ── C03 smoke ─────────────────────────────────────────────────────────────────

async def c03_t1(db: AsyncSession) -> Gold:
    return skip("an open-ended diligence sweep with no metric named; where the smoke is "
                "is a judgement across the whole registry, not a figure")


async def c03_t2(db: AsyncSession) -> Gold:
    return skip("the figures behind 'the one that worries you most' depend on what t1 picked "
                "(the model's judgement)")


async def c03_t3(db: AsyncSession) -> Gold:
    return skip("one-off or building is a trend over whichever figure t2 showed; the "
                "series depends on the model's pick")


# ── C04 rates +100bp ──────────────────────────────────────────────────────────

async def _tlt_betas(db: AsyncSession, tickers) -> tuple[list[Figure], list[str]]:
    figs, absent = [], []
    for t in tickers:
        b = await pa.beta(db, t, benchmark="TLT", invoked_by=INVOKED)
        if b.get("error"):
            absent.append(f"{t} beta to TLT: {_refusal(b)}")
            continue
        figs.append(Figure("beta_to_tlt", float(b["beta"]["value"]), RATIO, t, must=False,
                           note=f"price_analytics.beta({t}, benchmark=TLT, window=1y): OLS of daily "
                                f"returns, n={b.get('n')} — the per-name rates sensitivity the desk "
                                f"has (skill.py: 'TLT for rates'); a beta to TLT's return, not a duration"))
    return figs, absent


async def c04_t1(db: AsyncSession) -> Gold:
    """Stress results are withheld on this desk, so what the desk can say about
    rates is the regression: the book's net beta to the rates factor (TLT)
    from integration_service, and each name's own beta to TLT from
    price_analytics.beta. Neither is a 100bp loss."""
    rid = await _latest_run(db)
    an, _room = await _headroom(db, rid)
    rates = an["net_exposures"]["rates_up"]
    figs: list[Figure] = []
    ident = [an["as_of"]]
    if rates.get("measured"):
        figs.append(Figure(
            "book_net_beta_rates_up", float(rates["net_beta"]), RATIO, PORTFOLIO, must=True,
            note=(f"integration_service.get_portfolio_analysis({rid}).net_exposures.rates_up."
                  f"net_beta — the sum over the rates legs (TLT), signed so that positive "
                  f"means the book {rates['direction']} if rates rise; the run is collinear "
                  f"(max VIF>5) so the net, not the single coefficient, is the quotable figure. "
                  f"Stress results are withheld, so no loss figure exists for +100bp.")))
    else:
        ident.append(f"rates_up not measured on {rid}: {rates.get('reason')}")
    betas, absent = await _tlt_betas(db, HOLDINGS)
    return Gold(figures=figs + betas, identity=ident + absent)


async def c04_t2(db: AsyncSession) -> Gold:
    """How much is TLT itself: its weight on the run. The equities' 'duration
    in disguise' is their beta to TLT (t1's figures); TLT against itself is
    1.0 by construction and price_analytics refuses the self-regression. The
    desk has no duration measure — that half is an honest absence."""
    rid = await _latest_run(db)
    w = await _weights(db, rid)
    figs = [Figure("tlt_weight", float(w["TLT"]), RATIO, "TLT", must=True,
                   note=f"issuer_exposures.TLT.weight on {rid} — the explicit rates leg")]
    if "HYG" in w:
        figs.append(Figure("hyg_weight", float(w["HYG"]), RATIO, "HYG", must=False,
                           note=f"issuer_exposures.HYG.weight on {rid} — the credit leg, not rates"))
    betas, absent = await _tlt_betas(db, [t for t in HOLDINGS if t != "TLT"])
    self_reg = await pa.beta(db, "TLT", benchmark="TLT", invoked_by=INVOKED)
    if self_reg.get("error"):
        absent.append(f"TLT against TLT refused by the desk: {_refusal(self_reg)}")
    absent.append("no duration measure exists on this desk for an equity or for TLT")
    return Gold(figures=figs + betas, identity=absent)


# ── C05 AMZN capital ──────────────────────────────────────────────────────────

async def _cash_shape(db: AsyncSession, ticker: str) -> tuple[list[Figure], list[str]]:
    figs, absent = [], []
    for metric, must in (("capex", True), ("buybacks", True), ("dividends_paid", False),
                         ("operating_cash_flow", False)):
        r = await _flow(db, ticker, metric)
        if r.get("error"):
            absent.append(f"{metric}: {_refusal(r)}")
            continue
        zero = float(r["value"]) == 0.0
        figs.append(Figure(metric, float(r["value"]), MONEY, ticker, must=must and not zero,
                           note=f"fundamentals_service.get_flow({ticker}, {metric}, months=12): "
                                f"{r['basis']}" + ("; filed as zero — an answer says 'none', "
                                                   "so not must" if zero else "")))
    fcf = await _formula(db, ticker, "free_cash_flow")
    if fcf.get("error"):
        absent.append(f"free_cash_flow: {_refusal(fcf)}")
    else:
        figs.append(Figure("free_cash_flow", float(fcf["value"]), MONEY, ticker, must=False,
                           note=f"formula_service.evaluate_formula({ticker}, free_cash_flow, "
                                f"months=12): {fcf['basis']}"))
    absent.append("debt repayment: no filed metric on this desk (SUPPORTED_METRICS has no "
                  "repayments line); the balance-sheet debt at two dates is the nearest evidence")
    return figs, absent


async def c05_t1(db: AsyncSession) -> Gold:
    figs, absent = await _cash_shape(db, "AMZN")
    return Gold(figures=figs, identity=absent)


async def _growth(db: AsyncSession, ticker: str) -> tuple[list[Figure], list[str]]:
    """Capex growth against revenue growth. The desk's series route is
    get_flow(last_n=...) on the issuer's own 12-month reporting grid then the
    yoy operator (matched by date) — must; the quarterly grid is the other
    legitimate reading and is recorded beside it, not must."""
    figs, ident = [], []
    for metric in ("capex", "revenue"):
        v, basis = await _yoy_latest(db, ticker, metric, 12, 3)
        if v is None:
            ident.append(f"{metric} annual yoy: {basis}")
        else:
            figs.append(Figure(f"{metric}_yoy_annual", v, RATIO, ticker, must=True, note=basis))
        q, qbasis = await _yoy_latest(db, ticker, metric, 3, 6)
        if q is None:
            ident.append(f"{metric} quarterly yoy: {qbasis}")
        else:
            figs.append(Figure(f"{metric}_yoy_latest_quarter", q, RATIO, ticker, must=False,
                               note=qbasis + " (the quarterly reading of the same question)"))
    ci = await _formula(db, ticker, "capex_intensity")
    if ci.get("error"):
        ident.append(f"capex_intensity: {_refusal(ci)}")
    else:
        figs.append(Figure("capex_intensity", float(ci["value"]), RATIO, ticker, must=False,
                           note=f"evaluate_formula({ticker}, capex_intensity, months=12): {ci['basis']}"))
    return figs, ident


async def c05_t2(db: AsyncSession) -> Gold:
    figs, ident = await _growth(db, "AMZN")
    return Gold(figures=figs, identity=ident)


async def c05_t3(db: AsyncSession) -> Gold:
    shape, absent = await _cash_shape(db, "MSFT")
    for f in shape:
        f.must = False       # the comparison is on growth; the shape is support
    growth, ident = await _growth(db, "MSFT")
    amzn_ci = await _formula(db, "AMZN", "capex_intensity")
    extra = []
    if not amzn_ci.get("error"):
        extra.append(Figure("capex_intensity", float(amzn_ci["value"]), RATIO, "AMZN", must=False,
                            note=f"evaluate_formula(AMZN, capex_intensity, months=12) for the comparison"))
    return Gold(figures=shape + growth + extra, identity=absent + ident)


# ── C06 KO ────────────────────────────────────────────────────────────────────

async def c06_t1(db: AsyncSession) -> Gold:
    from exposure_workbench.services import company_service as co
    try:
        c = await co.require_investigable(db, "KO")
    except Exception as exc:     # noqa: BLE001 — recorded as the reason
        return skip(f"KO is not investigable on this desk: {type(exc).__name__}: {exc}")
    return skip(f"a capability question, not a figure: KO ({c.name}) is prepared and "
                f"investigable on this desk; t2/t3 hold the figures")


async def c06_t2(db: AsyncSession) -> Gold:
    """KO's leverage against the book's names on the registry's leverage
    family: debt_to_ebitda first, and equity_multiplier (total_assets ÷
    equity, the leverage measure that needs no debt total) beside it. A
    measure the desk refuses for KO (its total_debt does not cover at the
    latest date) is recorded as the refusal, not skipped around: this turn is
    partly an honest-absence test. The book average is typed_calculator.
    aggregate(avg) over the held names that resolve; JPM is refused as a bank
    on debt_to_ebitda, ETFs have no filings."""
    figs, absent = [], []
    for name, unit, ko_must in (("debt_to_ebitda", MULTIPLE, True),
                                ("equity_multiplier", MULTIPLE, False),
                                ("net_debt_to_ebitda", MULTIPLE, False),
                                ("debt_to_operating_cash_flow", MULTIPLE, False)):
        ko = await _formula(db, "KO", name)
        if ko.get("error"):
            absent.append(f"KO {name}: {_refusal(ko)}")
            ko_ok = False
        else:
            ko_ok = True
            figs.append(Figure(name, float(ko["value"]), unit, "KO", must=ko_must,
                               note=f"evaluate_formula(KO, {name}, months=12): {ko['basis']}"))
        if name in ("net_debt_to_ebitda", "debt_to_operating_cash_flow"):
            continue              # KO-only alternates; the book comparison is on the first two
        refs = []
        for t in ISSUERS:
            r = await _formula(db, t, name)
            if r.get("error"):
                absent.append(f"{t} {name}: {_refusal(r)}")
                continue
            refs.append((t, r["calc_id"]))
            figs.append(Figure(name, float(r["value"]), unit, t, must=False,
                               note=f"evaluate_formula({t}, {name}, months=12): {r['basis']}"))
        if len(refs) >= 2:
            avg = await tc.aggregate(db, "avg", [c for _t, c in refs], invoked_by=INVOKED)
            if avg.get("error"):
                absent.append(f"{name} average refused: {_refusal(avg)}")
            else:
                figs.append(Figure(f"book_average_{name}", float(avg["value"]), unit, None,
                                   must=False,
                                   note=f"typed_calculator.aggregate(avg) over {name} of "
                                        f"{', '.join(t for t, _c in refs)} — the held names that "
                                        f"resolve; a different set gives a different average"
                                        + ("" if ko_ok else f"; KO's own {name} is refused, so "
                                           f"the comparison on this measure cannot be made")))
    if not figs:
        return skip("no leverage measure resolves for KO or the book: " + "; ".join(absent))
    return Gold(figures=figs, identity=absent)


async def c06_t3(db: AsyncSession) -> Gold:
    rid = await _latest_run(db)
    before = await _weights(db, rid)
    after = await sc.hypothetical_buy(db, rid, [{"ticker": "KO", "weight": 0.05}])
    if after.get("error"):
        return skip(f"hypothetical_buy(KO, 0.05) refused: {_refusal(after)}")
    post = {p["label"]: float(p["weight"]) for p in after["positions"]}
    alerted = {a["entity_id"]: a for a in after["alerts"]}
    figs = []
    for t in ("MSFT", "LLY"):
        a = alerted.get(t)
        figs.append(Figure("weight_after_buy", post[t], RATIO, t, must=True,
                           note=(f"scenario_service.hypothetical_buy({rid}, KO at 0.05): {t} weight "
                                 f"after every existing weight scales by 0.95 (before {before[t]}); "
                                 + (f"{a['severity']} against {a['limit_value']}" if a
                                    else "no alert"))))
    for t in post:
        if t in ("MSFT", "LLY"):
            continue
        figs.append(Figure("weight_after_buy", post[t], RATIO, t, must=False,
                           note=f"weight after the buy (before {before.get(t)})"))
    figs.append(Figure("alerts_after_buy", float(len(after["alerts"])), COUNT, None, must=False,
                       note="alerts on the scenario row: " +
                            ", ".join(f"{a['entity_id']} {a['severity']}" for a in after["alerts"])))
    for s in after["sectors"]:
        figs.append(Figure("sector_weight_after_buy", float(s["weight"]), RATIO, s["label"],
                           must=False, note="sector weight after the buy"))
    return Gold(figures=figs, identity=[after["as_of"]])


# ── C07 vol ───────────────────────────────────────────────────────────────────

async def c07_t1(db: AsyncSession) -> Gold:
    """The run's own volatility measures: 30d against 60d is the desk's
    comparison of 'the last month' with the baseline. Also the same measure
    on the newest completed run at least four weeks older, when there is one."""
    rid = await _latest_run(db)
    rs = await rr.get_risk_state(db, rid)
    m = rs["metrics"]
    figs = [
        Figure("rolling_vol_30d", float(m["rolling_vol_30d"]), RATIO, PORTFOLIO, must=True,
               note=f"exposure_metrics.rolling_vol_30d on {rid} (as of {rs['as_of']})"),
        Figure("rolling_vol_60d", float(m["rolling_vol_60d"]), RATIO, PORTFOLIO, must=True,
               note=f"exposure_metrics.rolling_vol_60d on {rid} — the baseline the 30d is against"),
    ]
    cutoff = date.fromisoformat(rs["as_of"]) - timedelta(days=28)
    older = (await db.execute(
        select(ExposureRun).where(ExposureRun.portfolio_id == PORTFOLIO,
                                  ExposureRun.status == "completed",
                                  ExposureRun.as_of_date <= cutoff)
        .order_by(ExposureRun.as_of_date.desc(), ExposureRun.completed_at.desc().nullslast())
        .limit(1))).scalar_one_or_none()
    if older is not None:
        old = await rr.get_risk_state(db, older.id)
        om = old.get("metrics") or {}
        if om.get("rolling_vol_30d") is not None:
            figs.append(Figure("rolling_vol_30d_a_month_ago", float(om["rolling_vol_30d"]), RATIO,
                               PORTFOLIO, must=False,
                               note=f"exposure_metrics.rolling_vol_30d on {older.id} "
                                    f"(as of {old['as_of']}), the newest run at least 4 weeks older"))
    return Gold(figures=figs, identity=[rs["as_of"]])


async def c07_t2(db: AsyncSession) -> Gold:
    """Market or something we hold: SPY's 30d vol against its longer window,
    and each holding's 30d vol, ordered by the desk's rank."""
    figs, refs, absent = [], [], []
    for w in (30, 63):
        r = await pa.rolling_volatility(db, "SPY", window_days=w, invoked_by=INVOKED)
        if r.get("error"):
            absent.append(f"SPY vol {w}d: {_refusal(r)}")
            continue
        figs.append(Figure(f"spy_vol_{w}d", float(r["value"]), RATIO, "SPY", must=False,
                           note=f"price_analytics.rolling_volatility(SPY, {w}): {r['basis']}, "
                                f"{r['window']['from']}..{r['window']['to']}"))
    for t in HOLDINGS:
        r = await pa.rolling_volatility(db, t, window_days=30, invoked_by=INVOKED)
        if r.get("error"):
            absent.append(f"{t} vol 30d: {_refusal(r)}")
            continue
        refs.append(r["calc_id"])
        figs.append(Figure("vol_30d", float(r["value"]), RATIO, t, must=False,
                           note=f"price_analytics.rolling_volatility({t}, 30): {r['window']['from']}"
                                f"..{r['window']['to']}"))
    if len(refs) >= 2:
        rk = await tc.rank(db, refs, direction="highest", invoked_by=INVOKED)
        if rk.get("error"):
            absent.append(f"rank of 30d vols refused: {_refusal(rk)}")
        else:
            top = rk["ordering"][0]
            figs.append(Figure("highest_vol_30d", float(top["value"]), RATIO, top["label"],
                               must=False, note=f"typed_calculator.rank over the holdings' 30d vols: "
                                                f"{' > '.join(e['label'] for e in rk['ordering'])}"))
    return Gold(figures=figs, identity=absent)


# ── C08 wrong premise ─────────────────────────────────────────────────────────

async def c08_t1(db: AsyncSession) -> Gold:
    rid = await _latest_run(db)
    w = await _weights(db, rid)
    big = max(w, key=w.get)
    return Gold(figures=[
        Figure("nvda_weight", float(w["NVDA"]), RATIO, "NVDA", must=True,
               note=f"issuer_exposures.NVDA.weight on {rid} — the premise's 18% is not this"),
        Figure("largest_weight", float(w[big]), RATIO, big, must=True,
               note=f"the largest issuer_exposures weight on {rid} is {big}"),
    ], identity=[big])


async def c08_t2(db: AsyncSession) -> Gold:
    rid = await _latest_run(db)
    w = await _weights(db, rid)
    big = max(w, key=w.get)
    _an, room = await _headroom(db, rid)
    h = room.get(f"issuer_concentration:{big}")
    figs = [Figure("largest_weight", float(w[big]), RATIO, big, must=True,
                   note=f"issuer_exposures.{big}.weight on {rid}")]
    if h is not None:
        figs += [
            Figure("room_to_breach", float(h["room_to_breach"]), RATIO, big, must=True,
                   note=f"get_portfolio_analysis({rid}).headroom[issuer_concentration:{big}]"
                        f".room_to_breach = breach {h['breach_level']} − current; status {h['status']}"),
            Figure("room_to_warning", float(h["room_to_warning"]), RATIO, big, must=False,
                   note="warning − current; negative means the warning is already crossed"),
            Figure("warning_level", float(h["warning_level"]), RATIO, big, must=False,
                   note="issuer_concentration warning tier for this name (risk_limits)"),
            Figure("breach_level", float(h["breach_level"]), RATIO, big, must=False,
                   note="issuer_concentration breach tier for this name (risk_limits)"),
        ]
    return Gold(figures=figs, identity=[big])


# ── C09 LLY concentration ─────────────────────────────────────────────────────

async def c09_t1(db: AsyncSession) -> Gold:
    return skip("what the filings say is passage evidence, not a figure")


async def c09_t2(db: AsyncSession) -> Gold:
    return skip("product-level revenue is dimensional (segment) data; the desk's fundamentals "
                "read undimensioned facts only (dimensions_hash = '') and hold no LLY revenue "
                "by product, so no service can put a number on it — an honest-absence turn")


# ── C10 news ──────────────────────────────────────────────────────────────────

async def c10_t1(db: AsyncSession) -> Gold:
    return skip("what happened last week is web research, not a desk figure")


async def c10_t2(db: AsyncSession) -> Gold:
    return skip("which position the news touches is the model's judgement over t1; the "
                "position's size would be issuer_exposures.<T>.weight on the latest run, "
                "but which T is not derivable")


# ── C11 ellipsis ──────────────────────────────────────────────────────────────

async def _measure(db: AsyncSession, tickers, name: str, must: bool) -> tuple[list[Figure], list[str], list[str]]:
    figs, absent, refs = [], [], []
    for t in tickers:
        r = await _formula(db, t, name)
        if r.get("error"):
            absent.append(f"{t} {name}: {_refusal(r)}")
            continue
        refs.append(r["calc_id"])
        figs.append(Figure(name, float(r["value"]), RATIO, t, must=must,
                           note=f"evaluate_formula({t}, {name}, months=12): {r['basis']}"))
    return figs, absent, refs


async def c11_t1(db: AsyncSession) -> Gold:
    figs, absent, _ = await _measure(db, ("MSFT", "AAPL"), "operating_margin", True)
    return Gold(figures=figs, identity=absent)


async def c11_t2(db: AsyncSession) -> Gold:
    """'The other two megacaps' is ambiguous among GOOGL, AMZN and NVDA; all
    three are recorded, none must."""
    figs, absent, _ = await _measure(db, ("GOOGL", "AMZN", "NVDA"), "operating_margin", False)
    for f in figs:
        f.note += " — which two of GOOGL/AMZN/NVDA the turn means is not derivable"
    return Gold(figures=figs, identity=absent)


async def c11_t3(db: AsyncSession) -> Gold:
    """Best business by operating margin, and whether the order holds on
    roic — both ordered by typed_calculator.rank over the five megacaps. The
    leader depends on which names t2 admitted, so the leaders are support."""
    om, absent, om_refs = await _measure(db, MEGACAPS, "operating_margin", False)
    roic, absent2, roic_refs = await _measure(db, MEGACAPS, "roic", False)
    figs = om + roic
    ident = absent + absent2
    for label, refs in (("operating_margin", om_refs), ("roic", roic_refs)):
        if len(refs) < 2:
            continue
        rk = await tc.rank(db, refs, direction="highest", invoked_by=INVOKED)
        if rk.get("error"):
            ident.append(f"rank on {label}: {_refusal(rk)}")
            continue
        order = [e["label"] for e in rk["ordering"]]
        top = rk["ordering"][0]
        figs.append(Figure(f"best_{label}", float(top["value"]), RATIO, top["label"], must=False,
                           note=f"typed_calculator.rank(highest) over {label} of "
                                f"{', '.join(MEGACAPS)}: {' > '.join(order)}"))
        ident.append(f"{label} order: {' > '.join(order)}")
    return Gold(figures=figs, identity=ident)


# ── C12 trigger levels ────────────────────────────────────────────────────────

async def c12_t1(db: AsyncSession) -> Gold:
    rid = await _latest_run(db)
    al = await rr.list_run_alerts(db, rid)
    conc = [a for a in al["alerts"]
            if a["alert_type"] in ("issuer_concentration", "sector_concentration")]
    figs = []
    for a in conc:
        figs.append(Figure(f"{a['alert_type']}_{a['severity']}", float(a["current_value"]), RATIO,
                           a["entity_id"], must=True,
                           note=f"alert {a['id']} on {rid}: {a['entity_id']} at {a['current_value']} "
                                f"against the {a['severity']} level {a['limit_value']}"))
    figs.append(Figure("concentration_alerts", float(len(conc)), COUNT, None, must=False,
                       note="concentration alerts on the run (issuer + sector)"))
    figs.append(Figure("concentration_breaches",
                       float(sum(1 for a in conc if a["severity"] == "breach")),
                       COUNT, None, must=False, note="of which breach severity"))
    figs.append(Figure("checks_clear", float(al["checks_clear"]), COUNT, None, must=False,
                       note=f"limit checks clear of {al['checks_run']} run"))
    return Gold(figures=figs, identity=[al["as_of"]] + [a["entity_id"] for a in conc])


async def c12_t2(db: AsyncSession) -> Gold:
    """The levels: for every concentration check on warning, its room to
    breach (what makes it worse) and its room to warning (negative: what it
    takes to clear); for the clear checks, the three nearest their warning."""
    rid = await _latest_run(db)
    _an, room = await _headroom(db, rid)
    figs, ident = [], []
    conc = {k: h for k, h in room.items()
            if k.startswith(("issuer_concentration:", "sector_concentration:"))}
    for k, h in sorted(conc.items(), key=lambda kv: kv[1]["room_to_breach"]):
        kind, entity = k.split(":", 1)
        if h["status"] != "clear":
            figs.append(Figure("room_to_breach", float(h["room_to_breach"]), RATIO, entity, must=True,
                               note=f"{kind}: breach {h['breach_level']} − current {h['current']} "
                                    f"(status {h['status']}) on {rid}"))
            figs.append(Figure("room_to_warning", float(h["room_to_warning"]), RATIO, entity, must=False,
                               note=f"{kind}: warning {h['warning_level']} − current; the negative of "
                                    f"this is what the weight must fall by to clear the warning"))
            ident.append(entity)
    clear = sorted((h for h in conc.values() if h["status"] == "clear"),
                   key=lambda h: h["room_to_warning"])
    for h in clear[:3]:
        kind, entity = h["check"].split(":", 1)
        figs.append(Figure("room_to_warning", float(h["room_to_warning"]), RATIO, entity, must=False,
                           note=f"{kind}: among the nearest clear checks to its warning "
                                f"{h['warning_level']}; current {h['current']}"))
        figs.append(Figure("room_to_breach", float(h["room_to_breach"]), RATIO, entity, must=False,
                           note=f"{kind}: breach {h['breach_level']} − current"))
    return Gold(figures=figs, identity=ident)


# ── C13 XOM ───────────────────────────────────────────────────────────────────

async def c13_t1(db: AsyncSession) -> Gold:
    return skip("whether XOM is still an oil bet is a thesis question from filing text")


async def c13_t2(db: AsyncSession) -> Gold:
    return skip("seeing it in the numbers would need segment revenue (dimensional facts the desk "
                "does not read) or a sensitivity to an oil price series the desk holds no "
                "prices for (USO is a run factor, not a price history) — an honest-absence turn")


DERIVATIONS = {
    "C01-trim-one#t1": c01_t1, "C01-trim-one#t2": c01_t2, "C01-trim-one#t3": c01_t3,
    "C02-nvda-bear#t1": c02_t1, "C02-nvda-bear#t2": c02_t2,
    "C03-smoke#t1": c03_t1, "C03-smoke#t2": c03_t2, "C03-smoke#t3": c03_t3,
    "C04-rates-100bp#t1": c04_t1, "C04-rates-100bp#t2": c04_t2,
    "C05-amzn-capital#t1": c05_t1, "C05-amzn-capital#t2": c05_t2, "C05-amzn-capital#t3": c05_t3,
    "C06-new-name-ko#t1": c06_t1, "C06-new-name-ko#t2": c06_t2, "C06-new-name-ko#t3": c06_t3,
    "C07-vol-rising#t1": c07_t1, "C07-vol-rising#t2": c07_t2,
    "C08-wrong-premise#t1": c08_t1, "C08-wrong-premise#t2": c08_t2,
    "C09-lly-concentration#t1": c09_t1, "C09-lly-concentration#t2": c09_t2,
    "C10-news-to-position#t1": c10_t1, "C10-news-to-position#t2": c10_t2,
    "C11-ellipsis#t1": c11_t1, "C11-ellipsis#t2": c11_t2, "C11-ellipsis#t3": c11_t3,
    "C12-trigger-levels#t1": c12_t1, "C12-trigger-levels#t2": c12_t2,
    "C13-xom-still-oil#t1": c13_t1, "C13-xom-still-oil#t2": c13_t2,
}
