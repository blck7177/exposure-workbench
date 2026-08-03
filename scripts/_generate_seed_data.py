"""
Generate demo seed data files using yfinance.
Run this once to create data/demo/*.csv and data/demo/previous_runs_seed.json

Market observations only. Risk thresholds used to be emitted here as
risk_limits_seed.csv, which put policy numbers in a file whose whole reason for
existing is that its contents come from a price feed — and the copy promptly
drifted, carrying a `stress_loss_tech` row no code has ever looked up. They now
live in analytics/limit_defaults.SEED_DEFAULTS, which seed_demo_db.py reads
directly. Do not add them back.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "demo"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOLDINGS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM", "XOM", "LLY", "TLT", "HYG"]
FACTORS = ["SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "USO"]

SECTOR_MAP = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMZN": "Consumer_Discretionary", "GOOGL": "Communication_Services",
    "JPM": "Financials", "XOM": "Energy", "LLY": "Healthcare",
    "TLT": "Fixed_Income", "HYG": "Fixed_Income",
}
ASSET_CLASS_MAP = {
    "AAPL": "equity", "MSFT": "equity", "NVDA": "equity", "AMZN": "equity",
    "GOOGL": "equity", "JPM": "equity", "XOM": "equity", "LLY": "equity",
    "TLT": "etf", "HYG": "etf",
}
QUANTITY_MAP = {
    "AAPL": 5000, "MSFT": 3500, "NVDA": 2000, "AMZN": 3000,
    "GOOGL": 4000, "JPM": 4500, "XOM": 3000, "LLY": 1200,
    "TLT": 8000, "HYG": 10000,
}
COST_BASIS_MAP = {
    "AAPL": 165.00, "MSFT": 310.00, "NVDA": 480.00, "AMZN": 155.00,
    "GOOGL": 130.00, "JPM": 175.00, "XOM": 105.00, "LLY": 720.00,
    "TLT": 92.00, "HYG": 76.00,
}

end_date = date.today()
start_date = end_date - timedelta(days=120)


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    print(f"Fetching prices for {tickers}...")
    data = yf.download(
        tickers,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=True,
        progress=False,
    )
    if len(tickers) == 1:
        close = data[["Close"]].rename(columns={"Close": tickers[0]})
    else:
        close = data["Close"]
    close.index = pd.to_datetime(close.index).date
    return close


def generate_positions_seed(prices: pd.DataFrame) -> None:
    """positions_seed.csv — snapshot on latest available date."""
    latest_date = max(prices.index)
    rows = []
    for ticker in HOLDINGS:
        price = float(prices.loc[latest_date, ticker]) if ticker in prices.columns else 100.0
        qty = QUANTITY_MAP[ticker]
        mv = round(qty * price, 2)
        rows.append({
            "portfolio_id": "port_001",
            "as_of_date": latest_date.isoformat(),
            "ticker": ticker,
            "asset_class": ASSET_CLASS_MAP[ticker],
            "sector": SECTOR_MAP[ticker],
            "region": "US",
            "currency": "USD",
            "quantity": qty,
            "cost_basis": COST_BASIS_MAP[ticker],
            "price": round(price, 4),
            "market_value": mv,
        })
    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "positions_seed.csv", index=False)
    print(f"  positions_seed.csv — {len(df)} rows, date={latest_date}")


def generate_market_prices_seed(prices: pd.DataFrame) -> None:
    """market_prices_seed.csv — 90 days of daily prices for holdings."""
    rows = []
    recent = sorted(prices.index)[-90:]
    for d in recent:
        for ticker in HOLDINGS:
            if ticker in prices.columns:
                close = prices.loc[d, ticker]
                if pd.notna(close):
                    rows.append({
                        "ticker": ticker,
                        "price_date": d.isoformat(),
                        "close": round(float(close), 4),
                        "adj_close": round(float(close), 4),
                        "source": "yfinance",
                    })
    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "market_prices_seed.csv", index=False)
    print(f"  market_prices_seed.csv — {len(df)} rows")


def generate_factor_prices_seed(factor_prices: pd.DataFrame) -> None:
    """factor_prices_seed.csv — 90 days for factor tickers."""
    rows = []
    recent = sorted(factor_prices.index)[-90:]
    for ticker in FACTORS:
        if ticker not in factor_prices.columns:
            continue
        series = factor_prices[ticker].dropna()
        for d in recent:
            if d in series.index:
                close = float(series.loc[d])
                rows.append({
                    "ticker": ticker,
                    "price_date": d.isoformat(),
                    "close": round(close, 4),
                    "source": "yfinance",
                })
    df = pd.DataFrame(rows)
    # compute daily returns
    df = df.sort_values(["ticker", "price_date"])
    df["daily_return"] = df.groupby("ticker")["close"].pct_change().round(8)
    df.to_csv(DATA_DIR / "factor_prices_seed.csv", index=False)
    print(f"  factor_prices_seed.csv — {len(df)} rows")


def generate_previous_runs_seed(prices: pd.DataFrame) -> None:
    """previous_runs_seed.json — 2 previous run snapshots."""
    sorted_dates = sorted(prices.index)
    if len(sorted_dates) < 3:
        print("  Not enough price data for previous runs, skipping")
        return

    runs = []
    for i, run_date in enumerate([sorted_dates[-3], sorted_dates[-2]]):
        total_mv = 0.0
        holdings_data = []
        for ticker in HOLDINGS:
            if ticker not in prices.columns:
                continue
            price = float(prices.loc[run_date, ticker])
            qty = QUANTITY_MAP[ticker]
            mv = qty * price
            total_mv += mv
            holdings_data.append({"ticker": ticker, "price": round(price, 4), "market_value": round(mv, 2)})

        sector_exp = {}
        for h in holdings_data:
            sector = SECTOR_MAP[h["ticker"]]
            sector_exp[sector] = sector_exp.get(sector, 0) + h["market_value"]

        runs.append({
            "run_id": f"run_seed_prev_{i+1:02d}",
            "portfolio_id": "port_001",
            "as_of_date": run_date.isoformat(),
            "status": "completed",
            "portfolio_market_value": round(total_mv, 2),
            "daily_return": round(float(np.random.normal(0.001, 0.008)), 6),
            "daily_pnl": round(total_mv * float(np.random.normal(0.001, 0.008)), 2),
            "gross_exposure": round(total_mv, 2),
            "sector_exposures": {k: {"market_value": round(v, 2), "weight": round(v / total_mv, 6)}
                                  for k, v in sector_exp.items()},
            "issuer_exposures": {h["ticker"]: {"market_value": round(h["market_value"], 2),
                                                "weight": round(h["market_value"] / total_mv, 6)}
                                  for h in holdings_data},
        })

    with open(DATA_DIR / "previous_runs_seed.json", "w") as f:
        json.dump(runs, f, indent=2)
    print(f"  previous_runs_seed.json — {len(runs)} runs")


def main() -> None:
    print("Generating seed data...")
    np.random.seed(42)

    all_tickers = list(set(HOLDINGS + FACTORS))
    prices_raw = fetch_prices(all_tickers)

    holding_prices = prices_raw[[t for t in HOLDINGS if t in prices_raw.columns]]
    factor_prices = prices_raw[[t for t in FACTORS if t in prices_raw.columns]]

    generate_positions_seed(holding_prices)
    generate_market_prices_seed(holding_prices)
    generate_factor_prices_seed(factor_prices)
    generate_previous_runs_seed(holding_prices)

    print(f"\nSeed data written to {DATA_DIR}")


if __name__ == "__main__":
    main()
