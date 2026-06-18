"""Exposure accounting — market values, weights, sector and issuer concentration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


@dataclass
class PositionExposure:
    ticker: str
    sector: str
    asset_class: str
    quantity: float
    price: float
    market_value: float
    weight: float  # fraction of total portfolio MV


@dataclass
class ExposureResult:
    portfolio_market_value: float
    gross_exposure: float    # abs sum of all positions
    net_exposure: float      # algebraic sum (same as MV for long-only)
    positions: list[PositionExposure] = field(default_factory=list)
    sector_map: dict[str, dict] = field(default_factory=dict)
    # sector -> {"market_value": float, "weight": float}
    issuer_map: dict[str, dict] = field(default_factory=dict)
    # ticker -> {"market_value": float, "weight": float, "sector": str}


def calc_exposure(
    positions_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    as_of_date: date,
) -> ExposureResult:
    """
    Compute portfolio exposure for a given as_of_date.

    positions_df columns: ticker, quantity, sector, asset_class [, cost_basis]
    prices_df columns: ticker, price_date, close
    """
    as_of = pd.Timestamp(as_of_date)

    # Get the closest available price on or before as_of_date for each ticker
    prices_on_date = (
        prices_df[prices_df["price_date"] <= as_of]
        .sort_values("price_date")
        .groupby("ticker")
        .last()
        .reset_index()[["ticker", "close"]]
        .rename(columns={"close": "mkt_price"})
    )

    # Drop existing price column from positions to avoid merge suffix collision
    pos_clean = positions_df.drop(columns=["price", "market_value"], errors="ignore")
    merged = pos_clean.merge(prices_on_date, on="ticker", how="left")
    merged = merged.rename(columns={"mkt_price": "price"})
    merged["price"] = merged["price"].fillna(0.0)
    merged["market_value"] = merged["quantity"] * merged["price"]

    total_mv = merged["market_value"].sum()

    pos_list: list[PositionExposure] = []
    for _, row in merged.iterrows():
        mv = float(row["market_value"])
        weight = mv / total_mv if total_mv > 0 else 0.0
        pos_list.append(PositionExposure(
            ticker=str(row["ticker"]),
            sector=str(row.get("sector", "Unknown") or "Unknown"),
            asset_class=str(row.get("asset_class", "equity") or "equity"),
            quantity=float(row["quantity"]),
            price=float(row["price"]),
            market_value=mv,
            weight=weight,
        ))

    # Sector aggregation
    sector_map: dict[str, dict] = {}
    for pos in pos_list:
        s = pos.sector
        if s not in sector_map:
            sector_map[s] = {"market_value": 0.0, "weight": 0.0}
        sector_map[s]["market_value"] += pos.market_value
    for s, v in sector_map.items():
        v["weight"] = v["market_value"] / total_mv if total_mv > 0 else 0.0

    # Issuer aggregation (one row per ticker)
    issuer_map: dict[str, dict] = {
        pos.ticker: {
            "market_value": pos.market_value,
            "weight": pos.weight,
            "sector": pos.sector,
        }
        for pos in pos_list
    }

    gross_exp = float(merged["market_value"].abs().sum())
    net_exp = float(merged["market_value"].sum())

    return ExposureResult(
        portfolio_market_value=float(total_mv),
        gross_exposure=gross_exp,
        net_exposure=net_exp,
        positions=pos_list,
        sector_map=sector_map,
        issuer_map=issuer_map,
    )
