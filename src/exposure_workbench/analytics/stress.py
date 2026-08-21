"""Stress scenario analysis — hypothetical 1-day shock P&L, propagated by beta.

A scenario says what the FACTORS do. What the book does about it is not in the
scenario, it is in the betas, and this module is the join between the two.

What it replaces, and why: shocks used to be matched by name against the book's
sector labels and its ticker list, and a name that matched nothing contributed
exactly zero. The demo portfolio is eight single stocks plus TLT and HYG, so the
"broad market correction −10%" scenario — whose shocks are SPY, QQQ, IWM, TLT and
GLD — matched one holding, TLT, whose shock is +3%. A −10% equity crash was
therefore reported as a GAIN on a book that is 80% equities, that number was
persisted as exposure_metrics.stress_loss_market, and the stress limit never
fired because the limit engine skips non-positive losses. The scenario named the
right things; nothing connected them to the portfolio.

Propagation through the estimated betas is that connection, and it also makes
the double-count structurally impossible: a shock is applied once, to a
coefficient, rather than once per naming convention it happens to match. TLT
being both a factor and a holding used to add its weight AND its sector's; now
its influence reaches the answer exactly once, through β_TLT, which already
knows the book holds it.

On collinearity: SPY, QQQ and IWM are nearly collinear, so their individual
betas are poorly determined. Their SUM is not, and a broad-equity scenario moves
all three by about the same amount — so the propagated loss is stable even when
the betas it is built from individually are not. A scenario that shocked only one
of the three would not have that protection, and none does.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScenarioResult:
    name: str
    description: str
    estimated_loss_pct: float    # fraction of portfolio MV (positive = loss)
    estimated_loss_usd: float    # USD amount (positive = loss)
    # Factors the model estimates a beta for and this scenario says nothing
    # about. They are held at zero, which is an ASSERTION — "credit does not
    # move in a 10% equity crash" — not an absence of one. Recorded because it
    # is the same shape as the failure this module was rewritten to remove: a
    # factor contributing nothing because nobody named it. Measured on the live
    # book, market_downside leaves HYG flat while the book's beta to HYG is the
    # second largest it has.
    factors_held_flat: list[str] = field(default_factory=list)


@dataclass
class UnevaluatedScenario:
    name: str
    reason: str


@dataclass
class StressResult:
    scenarios: list[ScenarioResult] = field(default_factory=list)
    worst_case_loss_pct: float = 0.0
    worst_case_loss_usd: float = 0.0
    # Scenarios that could not be computed, and why. A scenario absent from
    # `scenarios` is absent from the limit checks too, which is the point:
    # reporting an uncomputable scenario as 0.0 loss is how "no beta for TLT"
    # became "this book is safe in a rates shock".
    unevaluated: list[UnevaluatedScenario] = field(default_factory=list)


def calc_stress(
    portfolio_market_value: float,
    stress_config: dict,
    betas: dict[str, float],
) -> StressResult:
    """
    Estimate stress P&L for each scenario.

    portfolio_market_value: total portfolio MV in USD
    stress_config: dict loaded from stress_scenarios.yaml
    betas: factor_ticker -> partial beta, from the factor regression

    A scenario is evaluated only when EVERY factor it shocks has a beta. Dropping
    the unknown legs and summing the rest would understate the loss silently, and
    understating a stress loss is the one direction that matters.
    """
    results: list[ScenarioResult] = []
    unevaluated: list[UnevaluatedScenario] = []

    for scenario_name, cfg in stress_config.items():
        if not isinstance(cfg, dict):
            continue

        description = cfg.get("description", scenario_name)
        shocks: dict[str, float] = cfg.get("factor_shocks", {})

        if not shocks:
            unevaluated.append(UnevaluatedScenario(
                scenario_name, "scenario declares no factor_shocks"
            ))
            continue

        unknown = sorted(set(shocks) - set(betas))
        if unknown:
            unevaluated.append(UnevaluatedScenario(
                scenario_name,
                f"no beta estimated for {', '.join(unknown)}",
            ))
            continue

        portfolio_move = sum(betas[factor] * shock for factor, shock in shocks.items())
        estimated_loss_pct = -portfolio_move
        results.append(ScenarioResult(
            name=scenario_name,
            description=description,
            estimated_loss_pct=estimated_loss_pct,
            estimated_loss_usd=estimated_loss_pct * portfolio_market_value,
            factors_held_flat=sorted(set(betas) - set(shocks)),
        ))

    # Sort by loss descending (worst first)
    results.sort(key=lambda r: r.estimated_loss_pct, reverse=True)

    worst_pct = results[0].estimated_loss_pct if results else 0.0
    worst_usd = results[0].estimated_loss_usd if results else 0.0

    return StressResult(
        scenarios=results,
        worst_case_loss_pct=worst_pct,
        worst_case_loss_usd=worst_usd,
        unevaluated=unevaluated,
    )
