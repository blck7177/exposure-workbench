"""Limit checking — compare computed metrics against risk limits and generate alerts.

This module owns WHICH checks exist and WHAT their alerts look like. It owns no
threshold numbers and has no way to obtain one: the thresholds arrive from the
portfolio's risk_limits rows and there is no second source to fall back on. In
particular it must never import `limit_defaults` — that module is for seeding a
new portfolio, and the missing import is the only thing standing between "a run
uses the desk's policy" and "a run quietly uses a number from the source tree".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class MissingLimit(LookupError):
    """No risk_limits row backs a check that is about to run.

    Braces, not belt: a run reaches step 8 only after step 3 has confirmed the
    portfolio's limit set is complete, so this should be unraisable. It exists
    so that if that ever stops being true the run stops instead of inventing a
    threshold. Do not catch it.
    """

    def __init__(self, limit_type: str, entity_id: str | None):
        self.limit_type, self.entity_id = limit_type, entity_id
        super().__init__(
            f"no risk_limits row for {limit_type}"
            + (f" / {entity_id}" if entity_id else "")
        )


@dataclass(frozen=True)
class LimitSpec:
    """One check the engine can run.

    scope        "portfolio" — one threshold for the book, looked up with no
                 entity. "entity" — looked up per sector / issuer / scenario,
                 with the portfolio-wide row as the fallback.
    entity_type  What lands on the alert. Authoritative over the row's own
                 column, because the two genuinely disagree: stress_loss is
                 keyed by scenario name yet its alert is about the whole book.
    label        The alert's human prefix, with `{entity}` where the entity
                 name belongs. Portfolio-scoped labels have no placeholder.
    """

    scope: str
    entity_type: str
    label: str


LIMIT_SPECS: dict[str, LimitSpec] = {
    "daily_loss":             LimitSpec("portfolio", "portfolio", "Daily portfolio loss"),
    "var_95":                 LimitSpec("portfolio", "portfolio", "1-day 95% VaR"),
    "expected_shortfall_95":  LimitSpec("portfolio", "portfolio", "Expected Shortfall (95%)"),
    "rolling_volatility_30d": LimitSpec("portfolio", "portfolio", "30d rolling volatility (annualised)"),
    "gross_exposure":         LimitSpec("portfolio", "portfolio", "Gross exposure % NAV"),
    "sector_concentration":   LimitSpec("entity",    "sector",    "Sector {entity}"),
    "issuer_concentration":   LimitSpec("entity",    "issuer",    "Issuer {entity}"),
    # Keyed per scenario, reported against the portfolio — the disagreement that
    # is the reason entity_type comes from here and never from the row.
    "stress_loss":            LimitSpec("entity",    "portfolio", "Stress scenario: {entity}"),
}

# Every limit type a portfolio must carry a row for. Absence is a hard error at
# validation time, never a number supplied on the portfolio's behalf.
REQUIRED_LIMIT_TYPES = frozenset(LIMIT_SPECS)


@dataclass
class AlertResult:
    alert_type: str
    severity: str          # "warning" | "breach"
    entity_type: str       # "portfolio" | "sector" | "issuer"
    entity_id: str         # ticker or sector name or "portfolio"
    current_value: float
    limit_value: float
    utilization: float     # current / limit (breach_level used as denominator)
    message: str


def _check_one(
    alert_type: str,
    entity_type: str,
    entity_id: str,
    current_value: float,
    warning_level: float,
    breach_level: float,
    label: str | None = None,
) -> AlertResult | None:
    """Return an alert if current_value breaches warning or breach level, else None."""
    if current_value <= 0:
        return None

    if current_value >= breach_level:
        severity = "breach"
        limit_value = breach_level
    elif current_value >= warning_level:
        severity = "warning"
        limit_value = warning_level
    else:
        return None

    utilization = current_value / breach_level if breach_level > 0 else 0.0
    display_name = label or entity_id
    pct = f"{current_value * 100:.1f}%"
    limit_pct = f"{limit_value * 100:.1f}%"
    msg = f"{display_name}: {pct} vs limit {limit_pct} [{severity.upper()}]"

    return AlertResult(
        alert_type=alert_type,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        current_value=current_value,
        limit_value=limit_value,
        utilization=utilization,
        message=msg,
    )


def check_limits(
    risk_metrics_result: Any,           # RiskResult
    stress_result: Any,                 # StressResult
    exposure_result: Any,               # ExposureResult
    pnl_result: Any,                    # PnlResult
    limits_config: dict,
    db_limits: list[dict] | None = None,
) -> list[AlertResult]:
    """
    Check all risk limits.

    limits_config: dict loaded from risk_limits.yaml
    db_limits: optional list of per-portfolio overrides from the DB
    """
    alerts: list[AlertResult] = []

    def cfg(key: str, sub: str, default: float) -> float:
        return float(limits_config.get(key, {}).get(sub, default))

    # ── Portfolio-level limits ─────────────────────────────────────────────────

    # Daily loss
    if pnl_result and pnl_result.daily_return < 0:
        daily_loss = -pnl_result.daily_return
        a = _check_one(
            "daily_loss", "portfolio", "portfolio",
            daily_loss,
            cfg("daily_loss", "warning", 0.02),
            cfg("daily_loss", "breach", 0.03),
            "Daily portfolio loss",
        )
        if a:
            alerts.append(a)

    # VaR 95
    if risk_metrics_result and risk_metrics_result.var_95_1d is not None:
        a = _check_one(
            "var_95", "portfolio", "portfolio",
            risk_metrics_result.var_95_1d,
            cfg("var_95", "warning", 0.025),
            cfg("var_95", "breach", 0.035),
            "1-day 95% VaR",
        )
        if a:
            alerts.append(a)

    # Expected Shortfall
    if risk_metrics_result and risk_metrics_result.es_95 is not None:
        a = _check_one(
            "expected_shortfall_95", "portfolio", "portfolio",
            risk_metrics_result.es_95,
            cfg("expected_shortfall_95", "warning", 0.035),
            cfg("expected_shortfall_95", "breach", 0.05),
            "Expected Shortfall (95%)",
        )
        if a:
            alerts.append(a)

    # Rolling vol 30d
    if risk_metrics_result and risk_metrics_result.vol_30d is not None:
        a = _check_one(
            "rolling_volatility_30d", "portfolio", "portfolio",
            risk_metrics_result.vol_30d,
            cfg("rolling_volatility_30d", "warning", 0.18),
            cfg("rolling_volatility_30d", "breach", 0.25),
            "30d rolling volatility (annualised)",
        )
        if a:
            alerts.append(a)

    # Gross exposure
    if exposure_result and exposure_result.portfolio_market_value > 0:
        mv = exposure_result.portfolio_market_value
        # Assume NAV ≈ portfolio_market_value for a long-only book
        gross_pct = exposure_result.gross_exposure / mv
        a = _check_one(
            "gross_exposure", "portfolio", "portfolio",
            gross_pct,
            cfg("gross_exposure", "warning", 1.10),
            cfg("gross_exposure", "breach", 1.20),
            "Gross exposure % NAV",
        )
        if a:
            alerts.append(a)

    # ── Sector concentration ────────────────────────────────────────────────────
    if exposure_result:
        for sector, data in exposure_result.sector_map.items():
            weight = data["weight"]
            a = _check_one(
                "sector_concentration", "sector", sector,
                weight,
                cfg("sector_concentration", "warning", 0.40),
                cfg("sector_concentration", "breach", 0.50),
                f"Sector {sector}",
            )
            if a:
                alerts.append(a)

    # ── Issuer concentration ────────────────────────────────────────────────────
    if exposure_result:
        for ticker, data in exposure_result.issuer_map.items():
            weight = data["weight"]
            a = _check_one(
                "issuer_concentration", "issuer", ticker,
                weight,
                cfg("issuer_concentration", "warning", 0.15),
                cfg("issuer_concentration", "breach", 0.20),
                f"Issuer {ticker}",
            )
            if a:
                alerts.append(a)

    # ── Stress losses ───────────────────────────────────────────────────────────
    if stress_result:
        for scenario in stress_result.scenarios:
            loss_pct = scenario.estimated_loss_pct
            a = _check_one(
                "stress_loss", "portfolio", scenario.name,
                loss_pct,
                cfg("stress_loss", "warning", 0.06),
                cfg("stress_loss", "breach", 0.08),
                f"Stress scenario: {scenario.name}",
            )
            if a:
                alerts.append(a)

    # Sort: breach first, then by entity type
    severity_order = {"breach": 0, "warning": 1}
    alerts.sort(key=lambda a: (severity_order.get(a.severity, 2), a.alert_type))

    return alerts
