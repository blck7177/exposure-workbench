"""
Seed the demo Postgres database.

Usage:
    # Inside Docker network (default):
    python scripts/seed_demo_db.py

    # Against local port-forwarded Postgres:
    DATABASE_URL_SYNC=postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench \
    python scripts/seed_demo_db.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2
from psycopg2.extras import execute_values

DATA_DIR = ROOT / "data" / "demo"

# Use local URL if available (for running outside Docker)
DB_URL = os.getenv(
    "DATABASE_URL_LOCAL_SYNC",
    os.getenv(
        "DATABASE_URL_SYNC",
        "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench",
    )
)
# Strip sqlalchemy driver prefix for psycopg2
DB_DSN = DB_URL.replace("postgresql+psycopg2://", "postgresql://")


def get_conn():
    return psycopg2.connect(DB_DSN)


def seed_portfolio(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM portfolios WHERE id = 'port_001'")
        cur.execute("""
            INSERT INTO portfolios (id, name, description, currency, base_nav, benchmark, manager, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                updated_at = NOW()
        """, (
            "port_001",
            "US Growth & Income Portfolio",
            "Diversified US equity portfolio with growth tilt and fixed income allocation",
            "USD",
            10_000_000.0,
            "SPY",
            "Demo PM",
            True,
        ))
    conn.commit()
    print("  portfolios: seeded port_001")


def seed_positions(conn) -> None:
    path = DATA_DIR / "positions_seed.csv"
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append((
                str(uuid.uuid4()),
                row["portfolio_id"],
                row["as_of_date"],
                row["ticker"],
                row["asset_class"],
                row["sector"],
                row["region"],
                row["currency"],
                float(row["quantity"]),
                float(row["cost_basis"]),
                float(row["price"]),
                float(row["market_value"]),
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
    print(f"  positions: {len(rows)} rows")


def seed_market_prices(conn) -> None:
    path = DATA_DIR / "market_prices_seed.csv"
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append((
                row["ticker"],
                row["price_date"],
                float(row["close"]),
                float(row["adj_close"]) if row.get("adj_close") else float(row["close"]),
                row.get("source", "seed"),
            ))
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO market_prices (ticker, price_date, close, adj_close, source)
            VALUES %s
            ON CONFLICT (ticker, price_date) DO NOTHING
        """, rows)
    conn.commit()
    print(f"  market_prices: {len(rows)} rows")


def seed_factor_prices(conn) -> None:
    path = DATA_DIR / "factor_prices_seed.csv"
    if not path.exists():
        print("  factor_prices: file not found, skipping")
        return
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            daily_ret = float(row["daily_return"]) if row.get("daily_return") and row["daily_return"] not in ("", "nan") else None
            rows.append((
                row["ticker"],
                row["price_date"],
                float(row["close"]),
                daily_ret,
                row.get("source", "seed"),
            ))
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO factor_prices (ticker, price_date, close, daily_return, source)
            VALUES %s
            ON CONFLICT (ticker, price_date) DO NOTHING
        """, rows)
    conn.commit()
    print(f"  factor_prices: {len(rows)} rows")


def seed_risk_limits(conn) -> None:
    path = DATA_DIR / "risk_limits_seed.csv"
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            entity_id = row["entity_id"] if row.get("entity_id") else None
            rows.append((
                str(uuid.uuid4()),
                row["portfolio_id"],
                row["limit_type"],
                row.get("entity_type", "portfolio"),
                entity_id,
                float(row["warning_level"]),
                float(row["breach_level"]),
                row.get("unit", "fraction"),
                True,
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


def seed_previous_runs(conn) -> None:
    path = DATA_DIR / "previous_runs_seed.json"
    if not path.exists():
        print("  previous_runs: file not found, skipping")
        return

    with open(path) as f:
        runs = json.load(f)

    for run in runs:
        run_id = run["run_id"]
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO exposure_runs
                    (id, portfolio_id, status, as_of_date, triggered_by, completed_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO NOTHING
            """, (run_id, run["portfolio_id"], "completed", run["as_of_date"], "seed"))

            cur.execute("""
                INSERT INTO exposure_metrics
                    (run_id, portfolio_market_value, daily_pnl, daily_return,
                     gross_exposure, net_exposure)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO NOTHING
            """, (
                run_id,
                run.get("portfolio_market_value"),
                run.get("daily_pnl"),
                run.get("daily_return"),
                run.get("gross_exposure"),
                run.get("gross_exposure"),
            ))

            for sector, data in run.get("sector_exposures", {}).items():
                cur.execute("""
                    INSERT INTO sector_exposures (run_id, sector, market_value, weight)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (run_id, sector) DO NOTHING
                """, (run_id, sector, data["market_value"], data["weight"]))

            for ticker, data in run.get("issuer_exposures", {}).items():
                cur.execute("""
                    INSERT INTO issuer_exposures (run_id, ticker, market_value, weight)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (run_id, ticker) DO NOTHING
                """, (run_id, ticker, data["market_value"], data["weight"]))

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

    print("Seeding demo data...")
    seed_portfolio(conn)
    seed_positions(conn)
    seed_market_prices(conn)
    seed_factor_prices(conn)
    seed_risk_limits(conn)
    seed_previous_runs(conn)

    conn.close()
    print("\nDone. Demo database seeded.")


if __name__ == "__main__":
    main()
