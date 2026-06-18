"""Stress scenario analysis — hypothetical 1-day shock P&L."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScenarioResult:
    name: str
    description: str
    estimated_loss_pct: float    # fraction of portfolio MV (positive = loss)
    estimated_loss_usd: float    # USD amount (positive = loss)


@dataclass
class StressResult:
    scenarios: list[ScenarioResult] = field(default_factory=list)
    worst_case_loss_pct: float = 0.0
    worst_case_loss_usd: float = 0.0


def calc_stress(
    sector_weights: dict[str, float],
    issuer_weights: dict[str, float],
    portfolio_market_value: float,
    stress_config: dict,
) -> StressResult:
    """
    Estimate stress P&L for each scenario.

    sector_weights:  {sector_name: weight_fraction}
    issuer_weights:  {ticker: weight_fraction}  (for ETF tickers like TLT, HYG)
    portfolio_market_value: total portfolio MV in USD
    stress_config: dict loaded from stress_scenarios.yaml
    """
    results: list[ScenarioResult] = []

    for scenario_name, cfg in stress_config.items():
        if not isinstance(cfg, dict):
            continue

        description = cfg.get("description", scenario_name)
        shocks: dict[str, float] = cfg.get("shocks", {})

        estimated_loss_pct = 0.0

        for entity, shock in shocks.items():
            # Match sector names
            sector_weight = sector_weights.get(entity, 0.0)
            if sector_weight > 0:
                # Sector shock: portfolio_loss += sector_weight * shock
                estimated_loss_pct += sector_weight * shock

            # Match issuer/ETF tickers (for TLT, HYG, etc. that might be held directly)
            issuer_weight = issuer_weights.get(entity, 0.0)
            if issuer_weight > 0:
                estimated_loss_pct += issuer_weight * shock

        # Flip sign: positive loss_pct means portfolio loses money
        estimated_loss_pct = -estimated_loss_pct
        estimated_loss_usd = estimated_loss_pct * portfolio_market_value

        results.append(ScenarioResult(
            name=scenario_name,
            description=description,
            estimated_loss_pct=estimated_loss_pct,
            estimated_loss_usd=estimated_loss_usd,
        ))

    # Sort by loss descending (worst first)
    results.sort(key=lambda r: r.estimated_loss_pct, reverse=True)

    worst_pct = results[0].estimated_loss_pct if results else 0.0
    worst_usd = results[0].estimated_loss_usd if results else 0.0

    return StressResult(
        scenarios=results,
        worst_case_loss_pct=worst_pct,
        worst_case_loss_usd=worst_usd,
    )
