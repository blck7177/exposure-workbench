"""Gold figures for the V24 conversation battery (tests/battery/conversations_v24.json).

One derivation per turn tag, each computed by the desk's own services on the
fixture database — never by the model, never through a tool wrapper. See
scripts/gold/__init__.py for the data model and the convention.

Book = port_001 (AAPL MSFT GOOGL NVDA JPM AMZN TLT HYG LLY XOM). "Latest run"
is what get_run_freshness reports (as_of desc, completed_at desc); "the run
before" is the latest completed run with an EARLIER as_of — the fixture holds
several runs per as_of and those share their figures, so a same-as_of prior
run would compare the book with itself.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from exposure_workbench.db.models import ExposureRun
from exposure_workbench.services import (
    compute_service as cps,
    drawdown_service as dd,
    formula_service as fsv,
    fundamentals_service as fu,
    price_analytics_service as pa,
    quantities,
    reconcile_service as rc,
    run_reads_service as rr,
    scenario_service as sc,
    series_service as ss,
    typed_calculator as tc,
)

from scripts.gold import Figure, Gold, skip

BOOK = "port_001"
HOLDINGS = ("AAPL", "MSFT", "GOOGL", "NVDA", "JPM", "AMZN", "TLT", "HYG", "LLY", "XOM")
GOLD = "gold"

RATIO, MONEY, COUNT, MULTIPLE = "RATIO", "MONEY", "COUNT", "MULTIPLE"
MONEY_PER_DAY, COUNT_PER_DAY = "MONEY_PER_DAY", "COUNT_PER_DAY"


# ── shared helpers ────────────────────────────────────────────────────────────

async def _latest_run(db) -> tuple[str, str]:
    fr = await rr.get_run_freshness(db, BOOK)
    rid = fr["latest_completed_run"]
    if rid is None:
        raise RuntimeError(f"no completed run on {BOOK}: {fr['detail']}")
    return rid, fr["run_as_of"]


async def _prior_run(db, latest_as_of: str) -> tuple[str, str] | None:
    """The latest completed run whose as_of is strictly before the latest's,
    ordered as get_run_freshness orders. None when the fixture has no such run."""
    row = (await db.execute(
        select(ExposureRun)
        .where(ExposureRun.portfolio_id == BOOK, ExposureRun.status == "completed",
               ExposureRun.as_of_date < date.fromisoformat(latest_as_of))
        .order_by(ExposureRun.as_of_date.desc(),
                  ExposureRun.completed_at.desc().nullslast(),
                  ExposureRun.created_at.desc()).limit(1))).scalar_one_or_none()
    return None if row is None else (row.id, row.as_of_date.isoformat())


async def _earliest_run(db) -> tuple[str, str] | None:
    row = (await db.execute(
        select(ExposureRun)
        .where(ExposureRun.portfolio_id == BOOK, ExposureRun.status == "completed")
        .order_by(ExposureRun.as_of_date.asc(), ExposureRun.completed_at.asc().nullslast())
        .limit(1))).scalar_one_or_none()
    return None if row is None else (row.id, row.as_of_date.isoformat())


async def _run_values(db, rid: str) -> dict[str, float]:
    res = await quantities.of_ref(db, rid)
    return {q.label: q.value for q in res.quantities}


def _ok(out: dict, what: str) -> dict:
    if out.get("error"):
        raise RuntimeError(f"{what}: {out.get('error')}: {out.get('statement') or out.get('detail')}")
    return out


async def _top_five_share(db, rid: str) -> tuple[float, list[tuple[str, float]]]:
    """Sum of the five largest issuer weights on a run, folded by the desk's
    own `sum` (compute_service._fold over typed_calculator.add)."""
    vals = await _run_values(db, rid)
    weights = sorted(((v, lbl.split(".")[1]) for lbl, v in vals.items()
                      if lbl.startswith("issuer_exposures.") and lbl.endswith(".weight")),
                     reverse=True)[:5]
    refs = [f"{rid}:issuer_exposures.{t}.weight" for _, t in weights]
    summed = _ok(await cps._fold(db, "add", refs, "top_five_share", GOLD), f"top five sum on {rid}")
    return float(summed["value"]), [(t, v) for v, t in weights]


def _flow_note(flow: dict) -> str:
    p = flow.get("period") or {}
    return f"read_fundamentals flow {p.get('start')}..{p.get('end')}: {flow.get('derivation')}"


# ── N01 earnings quality ──────────────────────────────────────────────────────

async def n01_t1(db) -> Gold:
    """Are NVDA's profits real: the accruals ratio (Sloan) over the latest TTM,
    with the two flows it is built from and their ratio."""
    ar = _ok(await fsv.evaluate_formula(db, "NVDA", "accruals_ratio", months=12, invoked_by=GOLD),
             "NVDA accruals_ratio")
    ac = _ok(await fsv.evaluate_formula(db, "NVDA", "accruals", months=12, invoked_by=GOLD),
             "NVDA accruals")
    ni = _ok(await fu.get_flow(db, "NVDA", "net_income", months=12, invoked_by=GOLD), "NVDA net_income")
    ocf = _ok(await fu.get_flow(db, "NVDA", "operating_cash_flow", months=12, invoked_by=GOLD),
              "NVDA operating_cash_flow")
    conv = _ok(await tc.calculate(db, "divide", ocf["calc_id"], ni["calc_id"], invoked_by=GOLD),
               "OCF ÷ net income")
    figs = [
        Figure("accruals_ratio_ttm", float(ar["value"]), RATIO, "NVDA", True,
               f"evaluate_formula('NVDA','accruals_ratio', months=12): {ar['definition']}; basis {ar['basis']}"),
        Figure("accruals_ttm", float(ac["value"]), MONEY, "NVDA", False,
               f"evaluate_formula('NVDA','accruals', months=12): {ac['definition']}; basis {ac['basis']}"),
        Figure("net_income_ttm", float(ni["value"]), MONEY, "NVDA", False, _flow_note(ni)),
        Figure("operating_cash_flow_ttm", float(ocf["value"]), MONEY, "NVDA", False, _flow_note(ocf)),
        Figure("ocf_to_net_income_ttm", float(conv["value"]), RATIO, "NVDA", False,
               "typed_calculator.divide(operating_cash_flow TTM, net_income TTM) — cash conversion, "
               "not a registry formula"),
    ]
    return Gold(figures=figs, identity=[ar["basis"], ni["period"]["start"], ni["period"]["end"]])


async def n01_t2(db) -> Gold:
    """Worsening or one odd quarter: the accruals ratio on NVDA's own quarterly
    grid. The latest quarter is what the question is about; the prior quarters
    are the comparison."""
    ser = _ok(await fsv.evaluate_formula_series(db, "NVDA", "accruals_ratio", months=3, last_n=8,
                                                invoked_by=GOLD), "NVDA accruals_ratio series")
    pts = [p for p in ser["points"] if p.get("value") is not None]
    if not pts:
        return skip("accruals_ratio has no derivable quarterly point for NVDA")
    figs = []
    for i, p in enumerate(reversed(pts[-4:])):
        figs.append(Figure(f"accruals_ratio_q_{p['period_end']}", float(p["value"]), RATIO, "NVDA",
                           i == 0,
                           f"evaluate_formula_series('NVDA','accruals_ratio', months=3, last_n=8) point "
                           f"{p.get('start')}..{p['period_end']}"
                           + (" — the latest quarter, the one the question is about" if i == 0 else "")))
    acs = _ok(await fsv.evaluate_formula_series(db, "NVDA", "accruals", months=3, last_n=8,
                                                invoked_by=GOLD), "NVDA accruals series")
    apts = [p for p in acs["points"] if p.get("value") is not None]
    if apts:
        p = apts[-1]
        figs.append(Figure(f"accruals_q_{p['period_end']}", float(p["value"]), MONEY, "NVDA", False,
                           f"evaluate_formula_series('NVDA','accruals', months=3) latest point "
                           f"{p.get('start')}..{p['period_end']}"))
    return Gold(figures=figs, identity=[p["period_end"] for p in pts[-4:]])


# ── N02 working capital ───────────────────────────────────────────────────────

async def n02_t1(db) -> Gold:
    """Receivables and inventory against the top line: year-over-year growth of
    each at the latest reported quarter, by the desk's own series `yoy`.
    NVDA's live top-line tag is total_revenues (revenue is superseded after
    2022-01-30 and yields no quarterly grid)."""
    rev = _ok(await fu.get_flow(db, "NVDA", "total_revenues", months=3, last_n=8, invoked_by=GOLD),
              "NVDA total_revenues quarterly")
    rev_yoy = _ok(await ss.series_stat(db, rev["calc_id"], "yoy", invoked_by=GOLD), "revenue yoy")
    ar = _ok(await fu.get_balance_series(db, "NVDA", "accounts_receivable", last_n=8, invoked_by=GOLD),
             "NVDA accounts_receivable series")
    ar_yoy = _ok(await ss.series_stat(db, ar["calc_id"], "yoy", invoked_by=GOLD), "AR yoy")
    inv = _ok(await fu.get_balance_series(db, "NVDA", "inventory", last_n=8, invoked_by=GOLD),
              "NVDA inventory series")
    inv_yoy = _ok(await ss.series_stat(db, inv["calc_id"], "yoy", invoked_by=GOLD), "inventory yoy")

    def last(series: dict) -> dict:
        pts = [p for p in series["points"] if p.get("value") is not None]
        return pts[-1]

    r, a, i = last(rev_yoy), last(ar_yoy), last(inv_yoy)
    figs = [
        Figure("total_revenues_yoy_latest_q", float(r["value"]), RATIO, "NVDA", True,
               f"series yoy over read_fundamentals('NVDA','total_revenues', months=3, last_n=8), "
               f"point {r['period_end']} against the same quarter a year earlier"),
        Figure("accounts_receivable_yoy_latest", float(a["value"]), RATIO, "NVDA", True,
               f"series yoy over the accounts_receivable balance series, point {a['period_end']}"),
        Figure("inventory_yoy_latest", float(i["value"]), RATIO, "NVDA", True,
               f"series yoy over the inventory balance series, point {i['period_end']}"),
        Figure("total_revenues_latest_q", float(last(rev)["value"]), MONEY, "NVDA", False,
               f"quarter {last(rev).get('start')}..{last(rev)['period_end']}"),
        Figure("accounts_receivable_latest", float(last(ar)["value"]), MONEY, "NVDA", False,
               f"balance at {last(ar)['period_end']}"),
        Figure("inventory_latest", float(last(inv)["value"]), MONEY, "NVDA", False,
               f"balance at {last(inv)['period_end']}"),
    ]
    # The TTM view of the same question, as a ratio of the two windows.
    now = _ok(await fu.get_flow(db, "NVDA", "total_revenues", months=12, invoked_by=GOLD), "TTM now")
    rpts = [p for p in rev["points"] if p.get("value") is not None]
    if len(rpts) >= 8:
        start_prev, end_prev = rpts[-8]["start"], rpts[-5]["period_end"]
        ago = await fu.get_flow(db, "NVDA", "total_revenues", start=start_prev, end=end_prev,
                                invoked_by=GOLD)
        if not ago.get("error"):
            g = _ok(await tc.calculate(db, "divide", now["calc_id"], ago["calc_id"], invoked_by=GOLD),
                    "TTM ratio")
            figs.append(Figure("total_revenues_ttm_over_prior_ttm", float(g["value"]), RATIO, "NVDA",
                               False, f"typed_calculator.divide: {g['basis']} (a ratio of levels, "
                                      f"not a growth rate — subtract 1 for growth)"))
    dso = _ok(await fsv.evaluate_formula(db, "NVDA", "days_sales_outstanding", months=12, invoked_by=GOLD),
              "NVDA DSO")
    figs.append(Figure("days_sales_outstanding_ttm", float(dso["value"]), COUNT, "NVDA", False,
                       f"evaluate_formula('NVDA','days_sales_outstanding', months=12): basis {dso['basis']}"))
    return Gold(figures=figs, identity=[r["period_end"], a["period_end"], i["period_end"]])


async def n02_t2(db) -> Gold:
    """Inventory in days, now against a year ago. `now` is the desk's default
    12-month evaluation. The year-ago figure pins the TTM window ending one
    year earlier (the same call evaluate_formula_series makes per slot);
    the fiscal-year grid points are the other way a reader may say 'a year ago'.
    QUIRK: the 3-month grid of days_inventory is inventory ÷ ONE QUARTER's
    cost of revenue × 365 (≈4× the annual figure) — not used here."""
    now = _ok(await fsv.evaluate_formula(db, "NVDA", "days_inventory", months=12, invoked_by=GOLD),
              "NVDA days_inventory now")
    iv = now["periods"]["intervals"][0]
    figs = [Figure("days_inventory_ttm_now", float(now["value"]), COUNT, "NVDA", True,
                   f"evaluate_formula('NVDA','days_inventory', months=12): {now['definition']}; basis {now['basis']}")]
    identity = [now["basis"]]
    # A year earlier: the TTM window that ends four quarters before `iv` ends.
    q = _ok(await fu.get_flow(db, "NVDA", "cost_of_revenue", months=3, last_n=8, invoked_by=GOLD),
            "NVDA cost_of_revenue quarterly")
    qpts = [p for p in q["points"] if p.get("value") is not None]
    if len(qpts) >= 8 and qpts[-1]["period_end"] == iv[1]:
        w = (qpts[-8]["start"], qpts[-5]["period_end"])
        ago = await fsv.evaluate_formula(db, "NVDA", "days_inventory", months=12, at=w[1],
                                         invoked_by=GOLD, _window=w)
        if not ago.get("error"):
            figs.append(Figure("days_inventory_ttm_year_ago", float(ago["value"]), COUNT, "NVDA", False,
                               f"evaluate_formula pinned to the TTM window {w[0]}..{w[1]} at {w[1]}: basis {ago['basis']}"))
            identity.append(ago["basis"])
    fy = await fsv.evaluate_formula_series(db, "NVDA", "days_inventory", months=12, last_n=3, invoked_by=GOLD)
    if not fy.get("error"):
        for p in fy["points"]:
            if p.get("value") is not None:
                figs.append(Figure(f"days_inventory_fy_{p['period_end']}", float(p["value"]), COUNT, "NVDA",
                                   False, f"evaluate_formula_series months=12 last_n=3, fiscal year "
                                          f"{p.get('start')}..{p['period_end']}"))
                identity.append(p["period_end"])
    return Gold(figures=figs, identity=identity)


# ── N03 liquidity ─────────────────────────────────────────────────────────────

async def _days_to_exit(db, rid: str) -> list[tuple[str, float, dict]]:
    """Position market value ÷ dollar ADV(20d) for every holding, by the typed
    calculator (money ÷ money_per_day → a count of days). Position share
    counts (pos_ ids) are not calculator operands, so the dollar basis is the
    desk's computable path."""
    out = []
    for t in HOLDINGS:
        a = _ok(await pa.adv(db, t, window_days=20, invoked_by=GOLD), f"{t} adv")
        d = _ok(await tc.calculate(db, "divide", f"{rid}:issuer_exposures.{t}.market_value",
                                   a["adv_dollars"]["calc_id"], invoked_by=GOLD), f"{t} days")
        out.append((t, float(d["value"]), a))
    out.sort(key=lambda x: -x[1])
    return out


async def n03_t1(db) -> Gold:
    rid, as_of = await _latest_run(db)
    rows = await _days_to_exit(db, rid)
    figs = []
    for rank, (t, days, a) in enumerate(rows, start=1):
        figs.append(Figure(f"days_to_exit_at_full_adv_{t}", days, COUNT, t, rank == 1,
                           f"rank {rank}: issuer_exposures.{t}.market_value on {rid} ÷ {t} dollar ADV "
                           f"({a['window']['from']}..{a['window']['to']}, n={a['n']}); the worst name is must"))
    worst = rows[0]
    figs.append(Figure(f"adv_dollars_20d_{worst[0]}", float(worst[2]["adv_dollars"]["value"]), MONEY_PER_DAY,
                       worst[0], False, "price_analytics_service.adv(window_days=20).adv_dollars"))
    figs.append(Figure(f"adv_shares_20d_{worst[0]}", float(worst[2]["adv_shares"]["value"]), COUNT_PER_DAY,
                       worst[0], False, "price_analytics_service.adv(window_days=20).adv_shares"))
    return Gold(figures=figs, identity=[as_of, rid])


async def n03_t2(db) -> Gold:
    rid, as_of = await _latest_run(db)
    rows = await _days_to_exit(db, rid)
    t, _, a = rows[0]
    q_dollars = _ok(await tc.scale(db, a["adv_dollars"]["calc_id"], 0.25, unit_class="money_per_day",
                                   quantity=f"{t}.adv_dollars.20d.quarter", invoked_by=GOLD), "quarter ADV $")
    days = _ok(await tc.calculate(db, "divide", f"{rid}:issuer_exposures.{t}.market_value",
                                  q_dollars["calc_id"], invoked_by=GOLD), "days at quarter ADV")
    q_shares = _ok(await tc.scale(db, a["adv_shares"]["calc_id"], 0.25, unit_class="count_per_day",
                                  quantity=f"{t}.adv_shares.20d.quarter", invoked_by=GOLD), "quarter ADV sh")
    figs = [
        Figure(f"days_to_exit_at_quarter_adv_{t}", float(days["value"]), COUNT, t, True,
               f"{t} is the worst name from t1; issuer_exposures.{t}.market_value on {rid} ÷ "
               f"(0.25 × dollar ADV 20d) via typed_calculator.scale then divide"),
        Figure(f"quarter_adv_dollars_{t}", float(q_dollars["value"]), MONEY_PER_DAY, t, False,
               "typed_calculator.scale(adv_dollars, 0.25)"),
        Figure(f"quarter_adv_shares_{t}", float(q_shares["value"]), COUNT_PER_DAY, t, False,
               "typed_calculator.scale(adv_shares, 0.25)"),
        Figure(f"days_to_exit_at_full_adv_{t}", rows[0][1], COUNT, t, False, "from t1"),
    ]
    return Gold(figures=figs, identity=[as_of, rid])


# ── N04 drawdown anatomy ──────────────────────────────────────────────────────

async def n04_t1(db) -> Gold:
    ep = _ok(await dd.get_drawdown_episodes(db, BOOK, span="1y"), "drawdown episodes")
    if not ep.get("episodes"):
        return skip(f"no drawdown episode at least {ep.get('reported_floor')} deep in the 1y span "
                    f"{ep['window']['from']}..{ep['window']['to']}")
    worst = ep["episodes"][0]
    src = (f"drawdown_service.get_drawdown_episodes('{BOOK}', span='1y'), window "
           f"{ep['window']['from']}..{ep['window']['to']}, episode peak {worst['peak_date']} "
           f"trough {worst['trough_date']}")
    figs = [
        Figure("worst_drawdown_depth", float(worst["depth"]), RATIO, BOOK, True, src + " — depth as a ratio of the peak"),
        Figure("worst_drawdown_trough_days", float(worst["trough_days"]), COUNT, BOOK, True,
               src + " — sessions from peak to trough (how fast)"),
    ]
    if worst.get("recovery_days") is not None:
        figs.append(Figure("worst_drawdown_recovery_days", float(worst["recovery_days"]), COUNT, BOOK, False,
                           src + f" — sessions from trough to recovery on {worst['recovery_date']} (recovered={worst['recovered']})"))
    for e in ep["episodes"][1:]:
        figs.append(Figure(f"drawdown_depth_{e['peak_date']}", float(e["depth"]), RATIO, BOOK, False,
                           f"the next episode, peak {e['peak_date']} trough {e['trough_date']}"))
    identity = [worst["peak_date"], worst["trough_date"]] + ([worst["recovery_date"]] if worst.get("recovery_date") else [])
    return Gold(figures=figs, identity=identity + [ep["window"]["from"], ep["window"]["to"]])


async def n04_t2(db) -> Gold:
    ep = _ok(await dd.get_drawdown_episodes(db, BOOK, span="1y"), "drawdown episodes")
    if not ep.get("episodes"):
        return skip("no drawdown episode to explain (see t1)")
    worst = ep["episodes"][0]
    ex = _ok(await dd.explain_episode(db, BOOK, worst["peak_date"], worst["trough_date"]), "explain_episode")
    b = ex["benchmark"]
    src = f"drawdown_service.explain_episode('{BOOK}', {worst['peak_date']}, {worst['trough_date']}), window {ex['window']['from']}..{ex['window']['to']}"
    figs = []
    if b.get("window_return") is not None:
        figs.append(Figure("benchmark_window_return", float(b["window_return"]), RATIO, b["ticker"], True,
                           src + f" — {b['ticker']} cumulative return over the fixed window (the market half)"))
    figs.append(Figure("book_window_return", float(ex["portfolio_window_return"]), RATIO, BOOK, False,
                       src + " — the book's cumulative return over the same window"
                       + ("" if b.get("window_return") is not None
                          else f"; benchmark UNAVAILABLE: {b.get('unavailable_reason')}")))
    hold = sorted([h for h in ex["holdings"] if h.get("window_return") is not None],
                  key=lambda h: h["window_return"])
    for rank, h in enumerate(hold, start=1):
        figs.append(Figure(f"holding_window_return_{h['ticker']}", float(h["window_return"]), RATIO, h["ticker"],
                           rank == 1, src + f" — rank {rank} of {len(hold)} by window return (most negative first)"
                           + ("; the holding that fell most is must" if rank == 1 else "")))
    return Gold(figures=figs, identity=[ex["window"]["from"], ex["window"]["to"], b["ticker"]])


# ── N05 market or us ──────────────────────────────────────────────────────────

async def n05_t1(db) -> Gold:
    rid, as_of = await _latest_run(db)
    rec = _ok(await rc.reconcile(db, rid), "reconcile")
    if "factor_share" not in rec:
        return skip(f"reconcile on {rid} reports no shares: {rec.get('shares_note')}")
    f = rec["identity_factors"]
    src = f"reconcile_service.reconcile('{rid}') — one-day attribution as of {as_of}"
    figs = [
        Figure("factor_share", float(rec["factor_share"]), RATIO, BOOK, True,
               src + ": sum of factor contributions ÷ attribution_portfolio_return (the market/factor half)"),
        Figure("unexplained_share", float(rec["unexplained_share"]), RATIO, BOOK, True,
               src + ": (alpha + residual) ÷ attribution_portfolio_return (the 'us' half)"),
        Figure("sum_of_factor_contributions", float(f["sum_of_factor_contributions"]), RATIO, BOOK, False, src),
        Figure("alpha_plus_residual", float(f["alpha_plus_residual"]), RATIO, BOOK, False, src),
        Figure("attribution_portfolio_return", float(f["attribution_portfolio_return"]), RATIO, BOOK, False, src),
        Figure("daily_return", float(rec["identity_positions"]["daily_return"]), RATIO, BOOK, False, src),
    ]
    lf = rec.get("largest_factor_contribution")
    if lf:
        figs.append(Figure(f"largest_factor_contribution_{lf['factor_name']}", float(lf["contribution"]), RATIO,
                           BOOK, False, src + (" — collinear: not quotable individually, the sum is"
                                               if not lf.get("quotable_individually") else "")))
    return Gold(figures=figs, identity=[as_of, rid])


# ── N06 top five ──────────────────────────────────────────────────────────────

async def n06_t1(db) -> Gold:
    rid, as_of = await _latest_run(db)
    share, five = await _top_five_share(db, rid)
    figs = [Figure("top_five_share", share, RATIO, BOOK, True,
                   f"sum of the five largest issuer_exposures.weight on {rid} (as_of {as_of}): "
                   + ", ".join(f"{t} {v:.8f}" for t, v in five))]
    for t, v in five:
        figs.append(Figure(f"weight_{t}", v, RATIO, t, False, f"issuer_exposures.{t}.weight on {rid}"))
    prior = await _prior_run(db, as_of)
    identity = [as_of, rid]
    if prior is None:
        figs[0].note += "; the fixture has no completed run with an earlier as_of, so no comparison figure"
    else:
        prid, pas_of = prior
        pshare, pfive = await _top_five_share(db, prid)
        figs.append(Figure("top_five_share_prior_run", pshare, RATIO, BOOK, False,
                           f"the same sum on {prid} (as_of {pas_of}), the latest completed run with an earlier "
                           f"as_of: " + ", ".join(f"{t} {v:.8f}" for t, v in pfive)
                           + ". must=False because 'the run before this one' is ambiguous: the fixture also holds "
                             "earlier-completed runs with the SAME as_of and identical weights, against which the "
                             "share is unchanged"))
        identity += [pas_of, prid]
    return Gold(figures=figs, identity=identity)


# ── N07 capex cycle ───────────────────────────────────────────────────────────

async def n07_t1(db) -> Gold:
    figs, identity = [], []
    for t in ("MSFT", "AMZN"):
        capex = _ok(await fu.get_flow(db, t, "capex", months=12, invoked_by=GOLD), f"{t} capex")
        figs.append(Figure(f"capex_ttm_{t}", float(capex["value"]), MONEY, t, False, _flow_note(capex)))
        identity += [capex["period"]["start"], capex["period"]["end"]]
        da = await fu.get_flow(db, t, "depreciation_amortization", months=12, invoked_by=GOLD)
        if da.get("error"):
            # Honest absence on this side: the desk holds no D&A line for the issuer.
            figs[-1].note += (f"; depreciation_amortization for {t} is NOT held ({da['error']}: "
                              f"{da.get('statement')})")
            dep = await fu.get_flow(db, t, "depreciation", months=12, invoked_by=GOLD)
            if not dep.get("error"):
                figs.append(Figure(f"depreciation_ttm_{t}", float(dep["value"]), MONEY, t, False,
                                   _flow_note(dep) + " — depreciation alone, not D&A"))
                r = _ok(await tc.calculate(db, "divide", capex["calc_id"], dep["calc_id"], invoked_by=GOLD),
                        f"{t} capex/depreciation")
                figs.append(Figure(f"capex_over_depreciation_{t}", float(r["value"]), RATIO, t, False,
                                   "typed_calculator.divide(capex TTM, depreciation TTM) — over depreciation ALONE, "
                                   "since the issuer's D&A is not held"))
            am = await fu.get_flow(db, t, "amortization_of_intangibles", months=12, invoked_by=GOLD)
            if not am.get("error"):
                figs.append(Figure(f"amortization_of_intangibles_ttm_{t}", float(am["value"]), MONEY, t, False,
                                   _flow_note(am)))
        else:
            figs.append(Figure(f"depreciation_amortization_ttm_{t}", float(da["value"]), MONEY, t, False, _flow_note(da)))
            r = _ok(await tc.calculate(db, "divide", capex["calc_id"], da["calc_id"], invoked_by=GOLD),
                    f"{t} capex/D&A")
            figs.append(Figure(f"capex_over_depreciation_amortization_{t}", float(r["value"]), RATIO, t, True,
                               "typed_calculator.divide(capex TTM, depreciation_amortization TTM) — the "
                               "over-investment ratio the question asks for; must for the issuer whose D&A is held"))
        ci = await fsv.evaluate_formula(db, t, "capex_intensity", months=12, invoked_by=GOLD)
        if not ci.get("error"):
            figs.append(Figure(f"capex_intensity_ttm_{t}", float(ci["value"]), RATIO, t, False,
                               f"evaluate_formula('{t}','capex_intensity', months=12): basis {ci['basis']}"))
    return Gold(figures=figs, identity=sorted(set(identity)))


async def n07_t2(db) -> Gold:
    """Room on the balance sheet. total_debt (and every leverage measure over
    it) is refused for MSFT — incomplete cover — so that side is an honest
    absence; free cash flow after the capex is the figure both sides hold."""
    figs, identity, refusals = [], [], []
    for t in ("MSFT", "AMZN"):
        fcf = _ok(await fsv.evaluate_formula(db, t, "free_cash_flow", months=12, invoked_by=GOLD), f"{t} fcf")
        figs.append(Figure(f"free_cash_flow_ttm_{t}", float(fcf["value"]), MONEY, t, True,
                           f"evaluate_formula('{t}','free_cash_flow', months=12): {fcf['definition']}; basis {fcf['basis']}"))
        identity.append(fcf["basis"])
        for name, unit in (("total_debt", MONEY), ("net_debt", MONEY), ("debt_to_ebitda", MULTIPLE),
                           ("net_debt_to_ebitda", MULTIPLE), ("fcf_to_debt", RATIO),
                           ("debt_to_operating_cash_flow", MULTIPLE), ("current_ratio", MULTIPLE),
                           ("ebit_interest_coverage", MULTIPLE)):
            r = await fsv.evaluate_formula(db, t, name, months=12, invoked_by=GOLD)
            if r.get("error"):
                refusals.append(f"{t} {name}: {r['error']} — {r.get('statement') or r.get('detail')}")
                continue
            figs.append(Figure(f"{name}_{t}", float(r["value"]), unit, t, False,
                               f"evaluate_formula('{t}','{name}', months=12): basis {r['basis']}"))
        bs = _ok(await fu.get_balance_sheet(db, t, invoked_by=GOLD), f"{t} balance sheet")
        for line in ("cash_and_equivalents", "long_term_debt_total"):
            v = bs["balances"].get(line)
            if v is not None:
                figs.append(Figure(f"{line}_{t}", float(v["value"]), MONEY, t, False,
                                   f"get_balance_sheet('{t}') at {bs['as_of']}"))
        identity.append(bs["as_of"])
    g = Gold(figures=figs, identity=sorted(set(identity)))
    if refusals:
        g.figures[0].note += ". REFUSED by the desk (honest absence): " + " | ".join(refusals)
    return g


# ── N08 what's in the price ───────────────────────────────────────────────────

async def n08_t1(db) -> Gold:
    d = _ok(await pa.distance_from_52w_high(db, "XOM", invoked_by=GOLD), "XOM distance_from_52w_high")
    return Gold(figures=[Figure("distance_from_52w_high", float(d["value"]), RATIO, "XOM", True,
                                f"price_analytics_service.distance_from_52w_high('XOM'): {d['basis']}")],
                identity=[d["high_date"], d["as_of"]])


async def n08_t2(db) -> Gold:
    m = _ok(await pa.momentum_12_1(db, "XOM", invoked_by=GOLD), "XOM momentum_12_1")
    return Gold(figures=[Figure("momentum_12_1", float(m["value"]), RATIO, "XOM", True,
                                f"price_analytics_service.momentum_12_1('XOM'): {m['basis']}")],
                identity=[m["formation"]["from"], m["formation"]["to"]])


# ── N09 no forecast ───────────────────────────────────────────────────────────

async def n09_t1(db) -> Gold:
    return skip("a forward estimate of next year's revenue growth is not a figure this desk holds or "
                "computes; the turn tests honest abstention")


async def n09_t2(db) -> Gold:
    return skip("what LLY's filings say would move revenue is passage evidence (filing text), not a "
                "computable figure")


# ── N10 margin debate ─────────────────────────────────────────────────────────

async def n10_t1(db) -> Gold:
    figs, identity = [], []
    for t in ("AAPL", "MSFT"):
        gm = _ok(await fsv.evaluate_formula(db, t, "gross_margin", months=12, invoked_by=GOLD), f"{t} gross_margin")
        figs.append(Figure(f"gross_margin_ttm_{t}", float(gm["value"]), RATIO, t, True,
                           f"evaluate_formula('{t}','gross_margin', months=12): {gm['definition']}; basis {gm['basis']}"))
        identity.append(gm["basis"])
        ser = await fsv.evaluate_formula_series(db, t, "gross_margin", months=3, last_n=8, invoked_by=GOLD)
        if not ser.get("error"):
            pts = [p for p in ser["points"] if p.get("value") is not None]
            if pts:
                p = pts[-1]
                figs.append(Figure(f"gross_margin_latest_q_{t}", float(p["value"]), RATIO, t, False,
                                   f"evaluate_formula_series months=3 last_n=8, quarter {p.get('start')}..{p['period_end']}"))
                identity.append(p["period_end"])
            yoy = await ss.series_stat(db, ser["calc_id"], "yoy", invoked_by=GOLD)
            ypts = [p for p in yoy.get("points", []) if p.get("value") is not None]
            if ypts:
                p = ypts[-1]
                figs.append(Figure(f"gross_margin_yoy_latest_q_{t}", float(p["value"]), RATIO, t, False,
                                   f"series yoy over the quarterly gross_margin series, point {p['period_end']} — "
                                   f"relative change in the margin against the same quarter a year earlier"))
    g = Gold(figures=figs, identity=identity)
    g.figures[0].note += ("; the mix-versus-price split is NOT held as figures on this desk — the honest "
                          "answer says so")
    return g


# ── N11 one question ──────────────────────────────────────────────────────────

async def n11_t1(db) -> Gold:
    return skip("a synthesis turn: which line of XOM's numbers deserves the one question is the analyst's "
                "judgement, not a computable figure")


# ── N12 sector drift ──────────────────────────────────────────────────────────

async def n12_t1(db) -> Gold:
    rid, as_of = await _latest_run(db)
    vals = await _run_values(db, rid)
    sectors = sorted(((v, lbl.split(".")[1]) for lbl, v in vals.items()
                      if lbl.startswith("sector_exposures.") and lbl.endswith(".weight")), reverse=True)
    top_w, top = sectors[0]
    figs = [Figure(f"sector_weight_{top}", top_w, RATIO, BOOK, True,
                   f"sector_exposures.{top}.weight on {rid} (as_of {as_of}) — the largest sector, "
                   f"the 'one trade' the question is about")]
    for w, s in sectors[1:]:
        figs.append(Figure(f"sector_weight_{s}", w, RATIO, BOOK, False, f"sector_exposures.{s}.weight on {rid}"))
    warn = vals.get(f"limit_checks.sector_concentration:{top}.warning_level")
    if warn is not None:
        figs.append(Figure(f"sector_warning_level_{top}", warn, RATIO, BOOK, False,
                           f"limit_checks.sector_concentration:{top}.warning_level on {rid} — the mandate's line"))
    identity = [as_of, rid]
    prior = await _prior_run(db, as_of)
    if prior:
        prid, pas_of = prior
        pv = await _run_values(db, prid)
        w = pv.get(f"sector_exposures.{top}.weight")
        if w is not None:
            figs.append(Figure(f"sector_weight_{top}_prior_run", w, RATIO, BOOK, False,
                               f"sector_exposures.{top}.weight on {prid} (as_of {pas_of}), the latest run with an earlier as_of"))
            identity += [pas_of, prid]
    earliest = await _earliest_run(db)
    if earliest and earliest[0] != rid:
        erid, eas_of = earliest
        ev = await _run_values(db, erid)
        w = ev.get(f"sector_exposures.{top}.weight")
        if w is not None:
            figs.append(Figure(f"sector_weight_{top}_earliest_run", w, RATIO, BOOK, False,
                               f"sector_exposures.{top}.weight on {erid} (as_of {eas_of}), the earliest completed "
                               f"run the fixture holds — the drift over the whole run history"))
            identity += [eas_of, erid]
    return Gold(figures=figs, identity=identity)


async def n12_t2(db) -> Gold:
    """Options short of selling the biggest position: the largest sector's
    weight after selling each of that sector's OTHER names, by the desk's own
    scenario engine. No must: which option the answer picks is open."""
    rid, as_of = await _latest_run(db)
    vals = await _run_values(db, rid)
    sectors = sorted(((v, lbl.split(".")[1]) for lbl, v in vals.items()
                      if lbl.startswith("sector_exposures.") and lbl.endswith(".weight")), reverse=True)
    top = sectors[0][1]
    att = _ok(await rr.get_attribution(db, rid), "attribution")
    in_sector = sorted((p for p in att["positions"] if p["sector"] == top), key=lambda p: -p["weight"])
    biggest = max(att["positions"], key=lambda p: p["weight"])["ticker"]
    figs = [Figure(f"weight_{biggest}", float(vals[f"issuer_exposures.{biggest}.weight"]), RATIO, biggest, False,
                   f"the biggest position on {rid}, which the question keeps")]
    for p in in_sector:
        if p["ticker"] == biggest:
            continue
        for frac in (1.0, 0.5):
            s = await sc.hypothetical_book(db, rid, [{"ticker": p["ticker"], "fraction": frac}])
            if s.get("error"):
                continue
            w = next((x["weight"] for x in s["sectors"] if x["label"] == top), None)
            if w is not None:
                figs.append(Figure(f"sector_weight_{top}_after_selling_{int(frac * 100)}pct_{p['ticker']}", float(w),
                                   RATIO, BOOK, False,
                                   f"scenario_service.hypothetical_book('{rid}', sell {frac:g} of {p['ticker']}): "
                                   f"{top} weight of the resulting book"))
    return Gold(figures=figs, identity=[as_of, rid, top, biggest])


DERIVATIONS = {
    "N01-earnings-quality#t1": n01_t1,
    "N01-earnings-quality#t2": n01_t2,
    "N02-working-capital#t1": n02_t1,
    "N02-working-capital#t2": n02_t2,
    "N03-liquidity#t1": n03_t1,
    "N03-liquidity#t2": n03_t2,
    "N04-drawdown-anatomy#t1": n04_t1,
    "N04-drawdown-anatomy#t2": n04_t2,
    "N05-market-or-us#t1": n05_t1,
    "N06-top-five#t1": n06_t1,
    "N07-capex-cycle#t1": n07_t1,
    "N07-capex-cycle#t2": n07_t2,
    "N08-whats-in-the-price#t1": n08_t1,
    "N08-whats-in-the-price#t2": n08_t2,
    "N09-no-forecast#t1": n09_t1,
    "N09-no-forecast#t2": n09_t2,
    "N10-margin-debate#t1": n10_t1,
    "N11-one-question#t1": n11_t1,
    "N12-sector-drift#t1": n12_t1,
    "N12-sector-drift#t2": n12_t2,
}
