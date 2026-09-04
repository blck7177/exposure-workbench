#!/usr/bin/env python3
"""V21-S4 — re-fit every stored run's attribution on the current factor set.

V20 took `^VIX` out of factor_config.yaml (an index level, not a return; one
of the collinearity's sources). Runs computed since regress on seven ETF
factors; every run before that still holds an eight-factor fit, so the
attribution history has a seam: R², residual, VIF and each factor's
contribution are not comparable across it, and a question that reads an old
run reads a VIX row a new run does not have.

This script closes the seam the only honest way — by fitting the old runs on
the same seven factors from the prices the desk holds — and records that it
did, per run, on the run's own timeline (`workflow_events.reattribute`) with
the before/after numbers. Nothing else about a run is touched: market values,
weights, P&L, alerts, limit checks, the daily report's text (which may still
mention eight factors — it is a document written on its day, and stays one).

What it reads is what the workflow reads (positions_for_run, get_prices_df,
get_factor_prices_df, the carried share count of V21-S3) and how it fits is
the workflow's own calc_factor_attribution with the workflow's own config, so
a re-fit here and a fresh run there are the same computation.

    python scripts/reattribute_runs.py                 # dry run: report only
    python scripts/reattribute_runs.py --apply         # write
    python scripts/reattribute_runs.py --run-id run_…  # one run

Runs whose fit cannot be made (a factor without prices over the window, too
few aligned observations) are listed and left as they are. Back up first
(scripts/backup_db.sh); this UPDATEs and DELETEs.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=False)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.analytics import splits as sp                                  # noqa: E402
from exposure_workbench.analytics.factor_model import calc_factor_attribution          # noqa: E402
from exposure_workbench.db.models import (                                             # noqa: E402
    ExposureMetrics, ExposureRun, FactorAttribution, WorkflowEvent,
)
from exposure_workbench.services import market_data_service as mds                     # noqa: E402
from exposure_workbench.services import portfolio_service                              # noqa: E402
from exposure_workbench.workflow.exposure_workflow import _LOOKBACK_DAYS, ExposureWorkflow  # noqa: E402

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")

REASON = "V21: attribution re-fitted on the current factor set (^VIX left the set in V20)"


def _f(v):
    return None if v is None else float(v)


async def _refit(db, wf: ExposureWorkflow, run: ExposureRun) -> tuple[dict | None, str | None]:
    """The new fit for one run, or (None, why not)."""
    import pandas as pd

    as_of = run.as_of_date
    positions = await portfolio_service.positions_for_run(db, run.portfolio_id, as_of)
    if not positions:
        return None, "no positions resolve for this run"
    tickers = sorted({p.ticker for p in positions})
    stated_from = min(p.as_of_date for p in positions)
    splits_by = await mds.get_splits(db, tickers, min(stated_from, as_of), max(stated_from, as_of))
    positions_df = pd.DataFrame([
        {"ticker": p.ticker,
         "quantity": sp.carry(p.ticker, float(p.quantity), p.as_of_date, as_of,
                              splits_by.get(p.ticker, [])).valued}
        for p in positions
    ])
    start = as_of - timedelta(days=_LOOKBACK_DAYS)
    prices_df = await mds.get_prices_df(db, tickers, start, as_of)
    if prices_df.empty:
        return None, "no holding prices over the window"
    factor_tickers = wf._factor_tickers()
    factor_prices_df = await mds.get_factor_prices_df(db, factor_tickers, start, as_of)
    factor_returns_df = mds.build_factor_returns_df(factor_prices_df)
    missing = [t for t in factor_tickers if t not in factor_returns_df.columns]
    if missing:
        return None, f"no factor prices over the window for {', '.join(missing)}"
    portfolio_returns = mds.build_portfolio_returns(positions_df, prices_df)
    cfg = (wf._factor_config or {}).get("regression", {})
    result = calc_factor_attribution(
        portfolio_returns, factor_returns_df[factor_tickers], wf._factor_config or {},
        lookback=int(cfg.get("window_days", 60)),
        min_observations=int(cfg.get("min_observations", 30)),
        include_intercept=bool(cfg.get("include_intercept", True)),
    )
    if not result.factors:
        return None, f"the fit was refused (observations={result.observations})"
    return {"result": result, "factor_tickers": factor_tickers}, None


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; without it, report only")
    ap.add_argument("--run-id", action="append", default=[], help="only this run (repeatable)")
    ap.add_argument("--portfolio-id", default=None)
    ap.add_argument("--configs", default=str(ROOT / "configs"))
    args = ap.parse_args(argv)

    wf = ExposureWorkflow(configs_dir=args.configs)
    wf._load_configs()
    current = wf._factor_tickers()
    print(f"factor set: {', '.join(current)} ({len(current)})")

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    changed = skipped = same = 0
    async with mk() as db:
        q = select(ExposureRun).where(ExposureRun.status == "completed").order_by(ExposureRun.as_of_date)
        if args.run_id:
            q = q.where(ExposureRun.id.in_(args.run_id))
        if args.portfolio_id:
            q = q.where(ExposureRun.portfolio_id == args.portfolio_id)
        runs = (await db.execute(q)).scalars().all()
        print(f"{len(runs)} completed run(s)")

        for run in runs:
            old_rows = (await db.execute(
                select(FactorAttribution).where(FactorAttribution.run_id == run.id)
            )).scalars().all()
            old_set = sorted(r.factor_ticker or r.factor_name for r in old_rows)
            metrics = (await db.execute(
                select(ExposureMetrics).where(ExposureMetrics.run_id == run.id)
            )).scalar_one_or_none()
            if old_set == sorted(current):
                same += 1
                print(f"  = {run.id} {run.as_of_date} already on the current set")
                continue
            if not old_rows:
                # Nothing to RE-fit: a seed's "previous" run, or a run that
                # never reached the attribution step. A fit written here would
                # be a first fit under a re-fit's name.
                skipped += 1
                print(f"  ! {run.id} {run.as_of_date} left as is: no attribution was ever recorded for it")
                continue

            fit, why = await _refit(db, wf, run)
            if fit is None:
                skipped += 1
                print(f"  ! {run.id} {run.as_of_date} left as is: {why}")
                continue
            res = fit["result"]
            before = {"factors": old_set,
                      "r_squared": _f(metrics.model_r_squared) if metrics else None,
                      "max_vif": _f(metrics.max_vif) if metrics else None,
                      "collinear": metrics.collinear if metrics else None,
                      "observations": metrics.observations if metrics else None}
            after = {"factors": sorted(fit["factor_tickers"]), "r_squared": res.r_squared,
                     "max_vif": res.max_vif, "collinear": res.collinear,
                     "observations": res.observations}
            print(f"  ~ {run.id} {run.as_of_date}: factors {len(before['factors'])}→{len(after['factors'])}, "
                  f"R² {before['r_squared']}→{after['r_squared']:.4f}, "
                  f"VIF {before['max_vif']}→{after['max_vif']}, "
                  f"collinear {before['collinear']}→{after['collinear']}, n={after['observations']}")
            if not args.apply:
                changed += 1
                continue

            await db.execute(delete(FactorAttribution).where(FactorAttribution.run_id == run.id))
            for fr in res.factors:
                db.add(FactorAttribution(
                    run_id=run.id, factor_name=fr.factor_name, factor_ticker=fr.factor_ticker,
                    beta=fr.beta, factor_return=fr.factor_return, contribution=fr.contribution,
                    r_squared=fr.r_squared,
                ))
            if metrics is not None:
                metrics.attribution_portfolio_return = res.portfolio_return
                metrics.alpha = res.alpha
                metrics.residual = res.residual
                metrics.model_r_squared = res.r_squared
                metrics.observations = res.observations
                metrics.regression_window_days = res.window_days
                metrics.max_vif = res.max_vif
                metrics.collinear = res.collinear
                metrics.attribution_date = res.as_of
            db.add(WorkflowEvent(
                run_id=run.id, step_name="reattribute", status="completed",
                message=(f"Attribution re-fitted on {len(after['factors'])} factors "
                         f"(was {len(before['factors'])}); R² {before['r_squared']}→{after['r_squared']:.4f}"),
                payload_summary={"reason": REASON, "before": before, "after": after},
            ))
            await db.commit()
            changed += 1

    await engine.dispose()
    verb = "re-fitted" if args.apply else "would re-fit"
    print(f"\n{verb} {changed}; already current {same}; left as is {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
