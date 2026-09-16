#!/usr/bin/env python3
"""V38 fixture checks (live, read-only: every program is rolled back).

Runs programs through the CURRENT program executor, adapter and digest against
a fixture database restored from backups/battery/battery-2026-09-13.sql.gz with
the v36 migrations and `remap_concepts.py --apply` (mapping v5).

    python live_checks.py [--db exposure_battery_v38]
"""
import argparse, asyncio, json, os, sys

from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src")
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.services import digest as dg, fact_adapters as fa, facts as F
from exposure_workbench.services import program_service as ps, run_reads_service

USER = "user_3IDBMeAxLTbecvGorzwV7FCeroR"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


async def run(mk, program: dict) -> dict:
    async with mk() as db:
        try:
            return await ps.run(db, program, invoked_by="v38_live_checks")
        finally:
            await db.rollback()


def facts_of(out: dict, node: str) -> list[dict]:
    return [f for f in out.get("_facts") or [] if (f.get("params") or {}).get("node") == node]


def point(fact: dict, period: str):
    return next((v for p, v in fact.get("points") or [] if p == period), None)


async def main(db_name: str) -> int:
    url = os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", f"/{db_name}")
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(USER)
    try:
        async with mk() as db:
            fresh = await run_reads_service.get_run_freshness(db, "port_001")
        run_id = fresh["latest_completed_run"]

        # ── S1: a quarter's days are a quarter's ────────────────────────────
        out = await run(mk, {"let": [["q", {"fn": "method", "name": "days_sales_outstanding", "subject": "AAPL",
                                            "params": {"months": 3, "last_n": 12}}],
                                     ["y", {"fn": "method", "name": "days_sales_outstanding", "subject": "AAPL",
                                            "params": {"last_n": 5}}]]})
        (q,), (y,) = facts_of(out, "q"), facts_of(out, "y")
        qv, yv = point(q, "2023-09-30"), point(y, "2023-09-30")
        check("S1 quarterly DSO AAPL 2023-09-30", qv is not None and abs(qv - 120.34 * 91 / 365) < 0.05,
              f"quarterly {qv:.2f} (round C printed 120.34; ×91/365 = {120.34 * 91 / 365:.2f}), annual {yv:.2f}")

        # ── S2: `at` reads the flow window ending there ─────────────────────
        annual = await run(mk, {"let": [["cov", {"fn": "method", "name": "ebit_interest_coverage", "subject": "MSFT",
                                                 "params": {"last_n": 5}}]]})
        (series,) = facts_of(annual, "cov")
        lets = [[f"c{d[:4]}", {"fn": "method", "name": "ebit_interest_coverage", "subject": "MSFT", "params": {"at": d}}]
                for d in ("2021-06-30", "2022-06-30", "2023-06-30", "2024-06-30", "2025-06-30")]
        out = await run(mk, {"let": lets})
        rows = []
        ok = True
        for name, expr in lets:
            (f,) = facts_of(out, name) or [{}]
            want = point(series, expr["params"]["at"])
            got = f.get("value")
            rows.append(f"{expr['params']['at']}: {got if got is None else round(got, 2)} vs {round(want, 2)} as_of {f.get('as_of')}")
            ok = ok and got is not None and abs(got - want) < 1e-6 and f.get("as_of") == expr["params"]["at"]
        check("S2 MSFT coverage at each fiscal year end = the annual series point", ok, "; ".join(rows))
        out = await run(mk, {"let": [["r23", {"fn": "method", "name": "roe", "subject": "JPM", "params": {"at": "2023-12-31"}}],
                                     ["r24", {"fn": "method", "name": "roe", "subject": "JPM", "params": {"at": "2024-12-31"}}],
                                     ["ry", {"fn": "method", "name": "roe", "subject": "JPM", "params": {"last_n": 3}}]]})
        (r23,), (r24,), (ry,) = facts_of(out, "r23"), facts_of(out, "r24"), facts_of(out, "ry")
        check("S2 JPM ROE at year ends = the annual series points",
              abs(r23["value"] - point(ry, "2023-12-31")) < 1e-9 and abs(r24["value"] - point(ry, "2024-12-31")) < 1e-9
              and r23["as_of"] == "2023-12-31",
              f"at 2023-12-31 {r23['value']:.4f} (series {point(ry, '2023-12-31'):.4f}; round C printed 0.1796 as of 2026-03-31)")
        out = await run(mk, {"let": [["odd", {"fn": "method", "name": "ebit_interest_coverage", "subject": "MSFT",
                                              "params": {"at": "2021-08-15"}}]]})
        (odd,) = facts_of(out, "odd")
        check("S2 a date no period ends near is refused", odd["kind"] == "absence", odd.get("text", "")[:160])

        # ── S3: XOM's total debt reads its term debt ───────────────────────
        out = await run(mk, {"let": [["td", {"fn": "method", "name": "total_debt", "subject": "XOM",
                                             "params": {"at": "2025-12-31"}}],
                                     ["fd", {"fn": "method", "name": "fcf_to_debt", "subject": "XOM", "params": {"last_n": 5}}],
                                     ["de", {"fn": "method", "name": "debt_to_ebitda", "subject": "XOM", "params": {"last_n": 5}}]]})
        (td,), (fd,), (de,) = facts_of(out, "td"), facts_of(out, "fd"), facts_of(out, "de")
        made = (td.get("params") or {}).get("made_of") or {}
        check("S3 XOM total debt 2025-12-31", abs(td["value"] - 43.537e9) < 0.01e9,
              f"{td['value'] / 1e9:.3f}bn made_of {json.dumps(made)[:220]}")
        check("S3 XOM fcf_to_debt / debt_to_ebitda FY2025", point(fd, "2025-12-31") < 1.0,
              f"fcf_to_debt {point(fd, '2025-12-31'):.1%} (round C 254.0%); points "
              f"{[round(v, 3) for _p, v in fd['points']]}; debt_to_ebitda {[round(v, 2) for _p, v in de['points']]}; "
              f"series made_of {json.dumps((fd.get('params') or {}).get('made_of'))[:160]}")

        # ── S4 / S5 / T3f: one identity; both sums offered ─────────────────
        out = await run(mk, {"let": [["book", {"fn": "run", "portfolio": "port_001"}],
                                     ["analysis", {"fn": "method", "name": "book.analysis", "subject": "$book"}],
                                     ["net", {"fn": "pick", "of": "$analysis", "key": "portfolio.integration.net_beta.equity_down"}],
                                     ["fsum", {"fn": "method", "name": "book.reconcile", "subject": "$book",
                                               "key": "portfolio.reconcile.sum_of_factor_contributions"}],
                                     ["apr", {"fn": "method", "name": "book.reconcile", "subject": "$book",
                                              "key": "portfolio.reconcile.alpha_plus_residual"}],
                                     ["fsum_run", {"fn": "pick", "of": "$book", "key": "factor_attributions.sum_of_contributions"}],
                                     ["legs", {"fn": "column", "run": "$book", "table": "factor_attributions", "col": "contribution"}]]})
        (net,) = facts_of(out, "net")
        table_net = next(f for f in facts_of(out, "analysis") if f["measure"] == "portfolio.integration.net_beta.equity_down")
        check("S4 pick and table give one identity",
              (net["measure"], net["subject"]) == (table_net["measure"], table_net["subject"]) == (
                  "portfolio.integration.net_beta.equity_down", run_id),
              f"pick ({net['measure']}, {net['subject']}) table ({table_net['measure']}, {table_net['subject']}) value {net['value']:.4f}")
        (fsum,), (apr,), (fsum_run,) = facts_of(out, "fsum"), facts_of(out, "apr"), facts_of(out, "fsum_run")
        check("S5 the factor sum and alpha+residual are on the page and resolve",
              abs(fsum["value"] - (-0.00471605)) < 1e-8 and abs(fsum_run["value"] - fsum["value"]) < 1e-12,
              f"factor sum {fsum['value']:.8f}, alpha+residual {apr['value']:.6f}, sum of both "
              f"{fsum['value'] + apr['value']:.6f}; measure {fsum['measure']} subject {fsum['subject']}")
        (legs,) = facts_of(out, "legs")
        check("T3f the collinear refusal says where the sum is", "pick(of=$<the run>, key='factor_attributions.sum_of_contributions')" in legs.get("text", ""),
              legs.get("text", "")[:220])

        # ── L2 + T2: sol Q13 seq13's buy runs; the refusal it meets is the real one ──
        out = await run(mk, {"let": [["book", {"fn": "run", "portfolio": "port_001"}],
                                     ["w", {"fn": "pick", "of": "$book", "key": "issuer_exposures.NVDA.weight"}],
                                     ["freed_w", {"fn": "mul", "a": "$w", "b": 0.5}],
                                     ["sold", {"fn": "sell", "run": "$book", "sales": [{"ticker": "NVDA", "fraction": 0.5}]}],
                                     ["after", {"fn": "method", "name": "book.buy", "subject": "$sold",
                                                "key": "issuer_exposures.TLT.weight",
                                                "params": {"buys": [{"ticker": "TLT", "weight": "$freed_w"}]}}]],
                             "return": ["freed_w", "after"]})
        (after,) = facts_of(out, "after")
        check("L2 the bound weight passes the type check; the buy meets the data refusal",
              out.get("error") is None and "no_sector" in (after.get("text") or ""), (after.get("text") or "")[:160])
        kept, note, held, made = fa.adapt_all("run", {}, out)
        res = {**note, "facts": F.block_for_model(kept)}
        shown = dg.render(res, mint=dg.Minter(), seen={}, cap=16000)
        check("T1+T2 the rendered result shows the returned weight and the refusal, and counts the rest",
              any(f.get("node") == "freed_w" for f in shown["figures"]) and any("no_sector" in b["text"] for b in shown["boundaries"])
              and any(e.get("shown") is False for e in shown["nodes"]),
              f"figures {[f.get('node') for f in shown['figures']]}, boundaries {[b.get('code') for b in shown['boundaries']]}, "
              f"nodes {[(e['name'], e['kind'], e.get('figures')) for e in shown['nodes']]}")

        # ── T1 on round C's mini Q08 seq24 program ─────────────────────────
        prog = {"let": [{"expr": {"fn": "run", "which": "latest", "portfolio": "port_001"}, "name": "book_latest"},
                        {"expr": {"fn": "run", "which": "prev", "portfolio": "port_001"}, "name": "book_prev"},
                        {"expr": {"fn": "method", "name": "book.analysis", "subject": "$book_latest"}, "name": "analysis_latest"},
                        {"expr": {"fn": "method", "name": "book.analysis", "subject": "$book_prev"}, "name": "analysis_prev"},
                        {"expr": {"fn": "pick", "of": "$analysis_latest", "key": "portfolio.integration.net_beta.equity_down"}, "name": "latest_exposure"},
                        {"expr": {"fn": "pick", "of": "$analysis_prev", "key": "portfolio.integration.net_beta.equity_down"}, "name": "prev_exposure"}],
                "return": ["latest_exposure", "prev_exposure"]}
        out = await run(mk, prog)
        kept, note, held, made = fa.adapt_all("run", {"program": prog}, out)
        shown = dg.render({**note, "facts": F.block_for_model(kept)}, mint=dg.Minter(), seen={}, cap=16000)
        figs = {f["node"]: f for f in shown["figures"]}
        check("T1 mini Q08 seq24: both returned net betas are shown, with their runs",
              set(figs) == {"latest_exposure", "prev_exposure"} and figs["latest_exposure"]["subject"] != figs["prev_exposure"]["subject"],
              "; ".join(f"{n} {f['value']} subject {f['subject']}" for n, f in figs.items())
              + f"; not returned {note.get('not_returned')}; run nodes "
                f"{[(e['name'], e.get('run')) for e in shown['nodes'] if e['kind'] == 'run']}")
    finally:
        await engine.dispose()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks pass" + (f"; failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="exposure_battery_v38")
    sys.exit(asyncio.run(main(ap.parse_args().db)))
