"""
Seed the demo Postgres database.

Market/factor prices are REAL (yfinance) as of P1 — synthetic price CSVs are
retired. Company identity rows are seeded here (write path); the resolve_company
workflow step later validates/enriches them via EDGAR.

Usage:
    # Against host-mapped Postgres (default localhost:5433):
    python scripts/seed_demo_db.py

Requires network access (yfinance). Fails loud if a ticker returns no data.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2
import yaml
from psycopg2.extras import execute_values
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from exposure_workbench.analytics.limit_defaults import DEMO_OVERRIDES, SEED_DEFAULTS
from exposure_workbench.analytics.limits import LIMIT_SPECS
from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
from exposure_workbench.services.market_data_ingestion_service import (
    ingest_factor_prices,
    ingest_market_prices,
)
from exposure_workbench.utils.ids import new_id

DATA_DIR = ROOT / "data" / "demo"

# Sync DSN (psycopg2) for the non-price seed tables — host-mapped port.
DB_URL = os.getenv(
    "DATABASE_URL_LOCAL_SYNC",
    os.getenv("DATABASE_URL_SYNC", "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench"),
)
DB_DSN = DB_URL.replace("postgresql+psycopg2://", "postgresql://")

# Async URL (asyncpg) for the market-data ingestion service — host-mapped port.
ASYNC_DB_URL = os.getenv(
    "DATABASE_URL_LOCAL",
    "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench",
)

PRICE_LOOKBACK_DAYS = 400
BENCHMARK = "SPY"

# Company identity — CIKs manually verified against EDGAR (see IMPLEMENTATION_PLAN
# §P1 user checkpoint). ETFs are is_investigable=False (no 10-K/10-Q).
#   (ticker, name, cik, exchange, is_investigable)
COMPANIES = [
    ("AAPL",  "Apple Inc.",                                  "320193",  "NASDAQ",   True),
    ("MSFT",  "Microsoft Corporation",                       "789019",  "NASDAQ",   True),
    ("NVDA",  "NVIDIA Corporation",                          "1045810", "NASDAQ",   True),
    ("AMZN",  "Amazon.com, Inc.",                            "1018724", "NASDAQ",   True),
    ("GOOGL", "Alphabet Inc.",                               "1652044", "NASDAQ",   True),
    ("JPM",   "JPMorgan Chase & Co.",                        "19617",   "NYSE",     True),
    ("XOM",   "Exxon Mobil Corporation",                     "34088",   "NYSE",     True),
    ("LLY",   "Eli Lilly and Company",                       "59478",   "NYSE",     True),
    ("TLT",   "iShares 20+ Year Treasury Bond ETF",          None,      "NASDAQ",   False),
    ("HYG",   "iShares iBoxx $ High Yield Corporate Bond ETF", None,    "NYSE Arca", False),
]


def get_conn():
    return psycopg2.connect(DB_DSN)


def _read_holdings() -> list[dict]:
    """Holdings from positions_seed.csv (quantities/sectors/cost_basis kept;
    synthetic price/market_value/as_of_date dropped — priced from real data)."""
    out = []
    with open(DATA_DIR / "positions_seed.csv") as f:
        for row in csv.DictReader(f):
            out.append({
                "portfolio_id": row["portfolio_id"],
                "ticker": row["ticker"],
                "asset_class": row["asset_class"],
                "sector": row["sector"],
                "region": row["region"],
                "currency": row["currency"],
                "quantity": float(row["quantity"]),
                "cost_basis": float(row["cost_basis"]),
            })
    return out


def _factor_tickers() -> list[str]:
    cfg = yaml.safe_load((ROOT / "configs" / "factor_config.yaml").read_text())
    return [c["ticker"] for c in (cfg.get("factors") or {}).values() if isinstance(c, dict) and "ticker" in c]


def seed_portfolio(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO portfolios (id, name, description, currency, base_nav, benchmark, manager, is_active, is_public, owner_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_public = TRUE,
                owner_id = EXCLUDED.owner_id, updated_at = NOW()
        """, (
            "port_001", "US Growth & Income Portfolio",
            "Diversified US equity portfolio with growth tilt and fixed income allocation",
            "USD", 10_000_000.0, "SPY", "Demo PM", True, "user_demo_system",
        ))
    conn.commit()
    print("  portfolios: seeded port_001")


def seed_companies(conn) -> None:
    rows = [
        (f"co_{tk.lower()}", tk, name, cik, exch, inv, "seed")
        for (tk, name, cik, exch, inv) in COMPANIES
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO companies (id, ticker, name, cik, exchange, is_investigable, resolved_by)
            VALUES %s
            ON CONFLICT (ticker) DO UPDATE SET
                name = EXCLUDED.name, cik = EXCLUDED.cik, exchange = EXCLUDED.exchange,
                is_investigable = EXCLUDED.is_investigable
        """, rows)
    conn.commit()
    print(f"  companies: {len(rows)} rows ({sum(1 for c in COMPANIES if c[4])} investigable)")


async def _pull_prices(market_tickers: list[str], factor_tickers: list[str]) -> None:
    end = date.today()
    start = end - timedelta(days=PRICE_LOOKBACK_DAYS)
    engine = create_async_engine(ASYNC_DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = YFinanceMarketDataProvider()
    try:
        async with factory() as db:
            mkt = await ingest_market_prices(db, market_tickers, start, end, provider)
            print(f"  market_prices: {sum(mkt.values())} real rows across {len(mkt)} tickers")
        async with factory() as db:
            fac = await ingest_factor_prices(db, factor_tickers, start, end, provider)
            print(f"  factor_prices: {sum(fac.values())} real rows across {len(fac)} tickers")
    finally:
        await engine.dispose()


def seed_prices(conn, holdings: list[dict]) -> None:
    """Retire synthetic prices, pull real ones (market: holdings+SPY; factors: config)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_prices")
        cur.execute("DELETE FROM factor_prices")
    conn.commit()

    holding_tickers = [h["ticker"] for h in holdings]
    market_tickers = list(dict.fromkeys([*holding_tickers, BENCHMARK]))
    factor_tickers = _factor_tickers()
    asyncio.run(_pull_prices(market_tickers, factor_tickers))


def _snapshot_date(conn, holding_tickers: list[str]) -> date:
    """Latest date on which ALL holdings have a real price (a clean snapshot day)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT price_date FROM market_prices
            WHERE ticker = ANY(%s)
            GROUP BY price_date
            HAVING count(DISTINCT ticker) = %s
            ORDER BY price_date DESC
            LIMIT 1
        """, (holding_tickers, len(holding_tickers)))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("No date has prices for all holdings — cannot snapshot positions")
    return row[0]


def seed_positions(conn, holdings: list[dict]) -> date:
    holding_tickers = [h["ticker"] for h in holdings]
    snap = _snapshot_date(conn, holding_tickers)

    with conn.cursor() as cur:
        cur.execute("SELECT ticker, close FROM market_prices WHERE price_date = %s AND ticker = ANY(%s)",
                    (snap, holding_tickers))
        close_by_ticker = {t: float(c) for t, c in cur.fetchall()}

    rows = []
    for h in holdings:
        price = close_by_ticker[h["ticker"]]
        mv = price * h["quantity"]
        rows.append((
            # pos_ + 12 hex, the same shape new_id("pos_") mints. A bare uuid4
            # here is what left the demo book's holdings uncitable: the id is the
            # evidence handle, and a holding without one is a number the agent
            # can read and cannot support.
            f"pos_{uuid.uuid4().hex[:12]}", h["portfolio_id"], snap, h["ticker"], h["asset_class"],
            h["sector"], h["region"], h["currency"], h["quantity"], h["cost_basis"], price, mv,
        ))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM positions WHERE portfolio_id = 'port_001'")
        execute_values(cur, """
            INSERT INTO positions
                (id, portfolio_id, as_of_date, ticker, asset_class, sector, region,
                 currency, quantity, cost_basis, price, market_value)
            VALUES %s
            ON CONFLICT (portfolio_id, as_of_date, ticker) DO NOTHING
        """, rows)
    conn.commit()
    print(f"  positions: {len(rows)} rows priced at snapshot {snap}")
    return snap


DEMO_PORTFOLIO_ID = "port_001"

# The risk_limits column order, written down once. build_demo_limit_rows() returns
# dicts so a test can compare them by field name; this tuple is what turns a dict
# back into the positional row execute_values wants, AND it generates the INSERT's
# own column list below — so the two orders cannot drift apart and silently swap
# warning_level with breach_level.
RISK_LIMIT_COLUMNS = (
    "id", "portfolio_id", "limit_type", "entity_type", "entity_id",
    "warning_level", "breach_level", "unit", "is_active",
)


def build_demo_limit_rows() -> list[dict]:
    """port_001's whole limit set as plain dicts. No database, no file, no clock.

    Split out of seed_risk_limits so a test can RUN it. The guarantee that matters
    is not "the source text mentions LIMIT_SPECS" — a substring check for that is
    satisfied by any one use of the name, including one in a branch that does not
    build the row you care about. It is "every row carries the entity_type the
    engine will report on the alert, and the numbers limit_defaults holds". Only
    calling the function shows that, so tests/test_risk_limits_parity.py calls it
    and compares every field.

    entity_type comes from LIMIT_SPECS and never from a literal: stress_loss is
    keyed per scenario but reported against the whole book, and that disagreement
    is settled in exactly one place.

    `id` is the one impure field — new_id() is random per call — so a caller
    comparing rows must compare the other eight.
    """
    specced = [
        {"limit_type": lt, "entity_id": None, "warning_level": w, "breach_level": b}
        for lt, (w, b) in SEED_DEFAULTS.items()
    ] + [
        {"limit_type": lt, "entity_id": entity_id, "warning_level": w, "breach_level": b}
        for (lt, entity_id), (w, b) in DEMO_OVERRIDES.items()
    ]
    return [
        {
            "id": new_id("rl_"),
            "portfolio_id": DEMO_PORTFOLIO_ID,
            "entity_type": LIMIT_SPECS[row["limit_type"]].entity_type,
            # The only value ck_risk_limits_unit admits. _check_one compares raw
            # floats, so a row on any other scale is a limit that cannot fire.
            "unit": "fraction",
            "is_active": True,
            **row,
        }
        for row in specced
    ]


def seed_risk_limits(conn) -> None:
    """Write port_001's limit set from limit_defaults — the same numbers a new
    portfolio is created with, plus the demo book's four tighter overrides.

    This used to read data/demo/risk_limits_seed.csv, which is now deleted. The
    CSV was a third copy of thresholds that also lived in a YAML and in
    check_limits' literals, and it had drifted: it carried a `stress_loss_tech`
    row no code has ever looked up and no `gross_exposure` row at all. Once
    risk_limits is the only source a run reads — the engine has not been switched
    over yet — a seed missing a required default will be a portfolio that cannot
    complete a run, so the eight defaults come from SEED_DEFAULTS itself rather
    than from a file beside it.

    The rows themselves are built by build_demo_limit_rows(); this function is
    only the write.

    DELETE-then-INSERT, not upsert, is deliberate and stays: this is a seed
    script and port_001 is demo data that must land in a known state. Note that
    running it does NOT reset any other portfolio.
    """
    rows = [tuple(row[column] for column in RISK_LIMIT_COLUMNS)
            for row in build_demo_limit_rows()]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM risk_limits WHERE portfolio_id = %s", (DEMO_PORTFOLIO_ID,))
        execute_values(cur, f"""
            INSERT INTO risk_limits ({", ".join(RISK_LIMIT_COLUMNS)})
            VALUES %s
        """, rows)
    conn.commit()
    print(f"  risk_limits: {len(SEED_DEFAULTS)} defaults + {len(DEMO_OVERRIDES)} overrides "
          f"= {len(rows)} rows")


def seed_previous_runs(conn, snapshot: date) -> None:
    """Seed two prior completed runs (for compare_previous_run), dated just before
    the snapshot so the current run has a clean predecessor."""
    path = DATA_DIR / "previous_runs_seed.json"
    if not path.exists():
        print("  previous_runs: file not found, skipping")
        return
    runs = json.load(open(path))
    # Re-date the seeded runs relative to the real snapshot (they carry stale dates).
    for offset, run in enumerate(sorted(runs, key=lambda r: r["as_of_date"])):
        as_of = snapshot - timedelta(days=len(runs) - offset)
        run_id = run["run_id"]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM exposure_runs WHERE id = %s", (run_id,))
            cur.execute("""
                INSERT INTO exposure_runs (id, portfolio_id, status, as_of_date, triggered_by, completed_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (run_id, run["portfolio_id"], "completed", as_of, "seed"))
            cur.execute("""
                INSERT INTO exposure_metrics
                    (run_id, portfolio_market_value, daily_pnl, daily_return, gross_exposure, net_exposure)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (run_id, run.get("portfolio_market_value"), run.get("daily_pnl"),
                  run.get("daily_return"), run.get("gross_exposure"), run.get("gross_exposure")))
            for sector, d in run.get("sector_exposures", {}).items():
                cur.execute("INSERT INTO sector_exposures (run_id, sector, market_value, weight) VALUES (%s,%s,%s,%s)",
                            (run_id, sector, d["market_value"], d["weight"]))
            for ticker, d in run.get("issuer_exposures", {}).items():
                cur.execute("INSERT INTO issuer_exposures (run_id, ticker, market_value, weight) VALUES (%s,%s,%s,%s)",
                            (run_id, ticker, d["market_value"], d["weight"]))
        conn.commit()
    print(f"  previous_runs: {len(runs)} runs seeded")


def main() -> None:
    print(f"Connecting to: {DB_DSN[:50]}...")
    try:
        conn = get_conn()
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        print("Make sure Postgres is running: docker compose up postgres")
        sys.exit(1)

    print("Seeding demo data (real market data via yfinance)...")
    holdings = _read_holdings()
    seed_portfolio(conn)
    seed_companies(conn)
    seed_prices(conn, holdings)          # real prices; retires synthetic
    snapshot = seed_positions(conn, holdings)
    seed_risk_limits(conn)
    seed_previous_runs(conn, snapshot)

    conn.close()

    # V2-D: refresh the investable universe (best-effort — needs network).
    try:
        asyncio.run(_refresh_universe())
    except Exception as e:  # noqa: BLE001
        print(f"  security_master refresh skipped: {e}")

    print(f"\nDone. Demo database seeded (snapshot {snapshot}).")


async def _refresh_universe() -> None:
    from exposure_workbench.services import security_master_service as sm
    engine = create_async_engine(ASYNC_DB_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            r = await sm.refresh(db)
        print(f"  security_master: {r['active']} securities")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()
