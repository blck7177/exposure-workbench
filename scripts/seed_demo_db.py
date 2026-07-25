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

from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
from exposure_workbench.services.market_data_ingestion_service import (
    ingest_factor_prices,
    ingest_market_prices,
)

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
            str(uuid.uuid4()), h["portfolio_id"], snap, h["ticker"], h["asset_class"],
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


def seed_risk_limits(conn) -> None:
    rows = []
    with open(DATA_DIR / "risk_limits_seed.csv") as f:
        for row in csv.DictReader(f):
            rows.append((
                str(uuid.uuid4()), row["portfolio_id"], row["limit_type"],
                row.get("entity_type", "portfolio"),
                row["entity_id"] if row.get("entity_id") else None,
                float(row["warning_level"]), float(row["breach_level"]),
                row.get("unit", "fraction"), True,
            ))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM risk_limits WHERE portfolio_id = 'port_001'")
        execute_values(cur, """
            INSERT INTO risk_limits
                (id, portfolio_id, limit_type, entity_type, entity_id,
                 warning_level, breach_level, unit, is_active)
            VALUES %s
        """, rows)
    conn.commit()
    print(f"  risk_limits: {len(rows)} rows")


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
