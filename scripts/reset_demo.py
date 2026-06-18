"""
Reset the demo database — drop all run data, re-seed portfolio/positions/limits.
Preserves market prices (no need to re-fetch).

Usage:
    python scripts/reset_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2

DB_URL = os.getenv(
    "DATABASE_URL_LOCAL_SYNC",
    os.getenv("DATABASE_URL_SYNC", "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench")
)
DB_DSN = DB_URL.replace("postgresql+psycopg2://", "postgresql://")

TRUNCATE_TABLES = [
    "workflow_events",
    "daily_reports",
    "risk_alerts",
    "factor_attributions",
    "factor_residuals",
    "issuer_exposures",
    "sector_exposures",
    "exposure_metrics",
    "exposure_runs",
    "tasks",
    "schedules",
]


def main() -> None:
    print(f"Resetting demo data at: {DB_DSN[:50]}...")
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        for table in TRUNCATE_TABLES:
            cur.execute(f"TRUNCATE TABLE {table} CASCADE")
            print(f"  truncated: {table}")
    conn.commit()
    conn.close()
    print("\nDone. Run `python scripts/seed_demo_db.py` to re-seed.")


if __name__ == "__main__":
    main()
