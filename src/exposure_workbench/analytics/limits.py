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


class LimitBook:
    """Every threshold a run may use, and no way to obtain one that is not here.

    Built from the portfolio's risk_limits rows. There is no config argument, no
    default parameter and no fallback: an absent row raises. That absence is the
    repair. The previous engine took a `db_limits` list, never read it, and
    supplied every threshold from 16 literals in its own source — so a desk that
    tightened a limit in the product saw no change in its alerts, and the demo
    book's twelve per-entity rows were displayed as policy in force while
    affecting nothing.

    A row with entity_id NULL is the portfolio-wide threshold for that check; a
    row with an entity_id overrides it for that one sector, issuer or scenario.
    Both live in the same table, and ux_risk_limits_default makes "exactly one
    default" a database fact, so nothing here arbitrates between sources.
    """

    def __init__(self, rows: list[dict]):
        """rows: ALL of the portfolio's risk_limits rows, active AND inactive.

        Inactive rows are excluded from thresholds but still scanned for a
        limit_type the engine cannot evaluate. If this only ever saw active
        rows, `UPDATE risk_limits SET is_active = false` would become the
        sanctioned way to hide a typo'd limit_type from the completeness check —
        the same silent path one level down.
        """
        self._defaults: dict[str, tuple[float, float]] = {}
        self._overrides: dict[tuple[str, str], tuple[float, float]] = {}
        self.unknown_types = sorted(
            {r["limit_type"] for r in rows if r["limit_type"] not in LIMIT_SPECS}
        )
        for r in rows:
            if not r["is_active"] or r["limit_type"] not in LIMIT_SPECS:
                continue
            # Belt to the database's braces (ck_risk_limits_unit,
            # ck_risk_limits_levels). A volume older than those constraints must
            # not quietly load a row that can never fire; `breach <= warning` and
            # not `<` because equal tiers are as dead as inverted ones, the
            # breach test coming first.
            if r["unit"] != "fraction":
                raise ValueError(f"risk_limits row {r['id']} has unit={r['unit']!r}")
            warning, breach = float(r["warning_level"]), float(r["breach_level"])
            if warning <= 0 or breach <= warning:
                raise ValueError(
                    f"risk_limits row {r['id']} can never fire: "
                    f"warning={warning} breach={breach}"
                )
            if r["entity_id"] is None:
                if r["limit_type"] in self._defaults:
                    raise ValueError(f"two default rows for {r['limit_type']}")
                self._defaults[r["limit_type"]] = (warning, breach)
            else:
                self._overrides[(r["limit_type"], r["entity_id"])] = (warning, breach)

        # Every (limit_type, entity_id) a run actually asked about. Recorded at
        # lookup, which happens when a check RUNS — not when it alerts — so this
        # separates "checked and fine" from "never checked at all".
        self.looked_up: set[tuple[str, str | None]] = set()

    def missing_required(self) -> list[str]:
        """Required checks with no active portfolio-wide row. Absence is an
        error the run reports, never a number supplied on its behalf."""
        return sorted(REQUIRED_LIMIT_TYPES - set(self._defaults))

    def get_portfolio(self, limit_type: str) -> tuple[float, float]:
        if LIMIT_SPECS[limit_type].scope != "portfolio":
            raise ValueError(f"{limit_type} is looked up per entity, not per book")
        self.looked_up.add((limit_type, None))
        try:
            return self._defaults[limit_type]
        except KeyError:
            raise MissingLimit(limit_type, None) from None

    def get_entity(self, limit_type: str, entity_id: str) -> tuple[float, float]:
        if LIMIT_SPECS[limit_type].scope != "entity":
            raise ValueError(f"{limit_type} is looked up per book, not per entity")
        self.looked_up.add((limit_type, entity_id))
        pair = self._overrides.get((limit_type, entity_id))
        if pair is not None:
            return pair
        try:
            return self._defaults[limit_type]
        except KeyError:
            raise MissingLimit(limit_type, entity_id) from None

    def inert_overrides(self) -> list[str]:
        """Overrides this run never consulted — a threshold set on a sector or
        issuer the book does not hold. Not an error; the desk may be holding it
        for a position it plans to take. Reported so it is visible rather than
        silently doing nothing, which is the state this whole change is about."""
        return sorted(f"{lt}:{eid}" for (lt, eid) in self._overrides
                      if (lt, eid) not in self.looked_up)


def evaluated_key(limit_type: str, entity_id: str | None) -> str:
    """One string for a (check, entity) pair, for the run's payload_summary."""
    return limit_type if entity_id is None else f"{limit_type}:{entity_id}"


def _check_one(
    alert_type: str,
    entity_id: str,
    current_value: float,
    warning_level: float,
    breach_level: float,
) -> AlertResult | None:
    """Return an alert if current_value breaches warning or breach level, else None.

    entity_type and the human label come from LIMIT_SPECS, never from the row
    that supplied the numbers: stress_loss is keyed per scenario yet reported
    against the whole book, and a data model cannot reconcile that — the spec
    states it instead.
    """
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

    spec = LIMIT_SPECS[alert_type]
    entity_type = spec.entity_type
    utilization = current_value / breach_level if breach_level > 0 else 0.0
    display_name = spec.label.format(entity=entity_id)
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
    limits: LimitBook,
) -> tuple[list[AlertResult], list[str]]:
    """Compare this run's metrics against the portfolio's own thresholds.

    Returns the alerts and the list of (check, entity) pairs that were actually
    EVALUATED. The second half exists because row presence is not check
    execution: every check below sits behind a guard on its input, and a book
    with too little price history gets var_95, es_95 and vol_30d as None, so
    three of the eight silently do not run while the timeline says the step
    completed. Now that the run also certifies "eight limit rows present", a
    reader would take that for "eight checks enforced". This is the difference,
    written down.

    Every threshold comes from `limits` and there is nowhere else to get one.
    """
    alerts: list[AlertResult] = []

    def emit(alert_type: str, entity_id: str, value: float,
             levels: tuple[float, float]) -> None:
        a = _check_one(alert_type, entity_id, value, *levels)
        if a:
            alerts.append(a)

    # ── Portfolio-level limits ─────────────────────────────────────────────────
    # Each guard is on whether the INPUT exists, not on whether it is
    # interesting: a profitable day still ran the daily-loss check, and saying so
    # is the point of `evaluated`. _check_one's `current_value <= 0` return is
    # what keeps the alert list identical to before.

    if pnl_result is not None:
        emit("daily_loss", "portfolio", -pnl_result.daily_return,
             limits.get_portfolio("daily_loss"))

    if risk_metrics_result is not None:
        if risk_metrics_result.var_95_1d is not None:
            emit("var_95", "portfolio", risk_metrics_result.var_95_1d,
                 limits.get_portfolio("var_95"))
        if risk_metrics_result.es_95 is not None:
            emit("expected_shortfall_95", "portfolio", risk_metrics_result.es_95,
                 limits.get_portfolio("expected_shortfall_95"))
        if risk_metrics_result.vol_30d is not None:
            emit("rolling_volatility_30d", "portfolio", risk_metrics_result.vol_30d,
                 limits.get_portfolio("rolling_volatility_30d"))

    if exposure_result is not None:
        mv = exposure_result.portfolio_market_value
        # NAV is taken to be market value for a long-only book. A zero-valued
        # book has no ratio to compute, so the check genuinely cannot run and is
        # not recorded as having run.
        if mv > 0:
            emit("gross_exposure", "portfolio", exposure_result.gross_exposure / mv,
                 limits.get_portfolio("gross_exposure"))

        # ── Per-entity limits ──────────────────────────────────────────────────
        # Iterating the exposure maps and not the limit rows is what makes at
        # most one alert per (check, entity) possible, and it is also why an
        # override for a name the book does not hold is inert rather than an
        # error.
        for sector, data in exposure_result.sector_map.items():
            emit("sector_concentration", sector, data["weight"],
                 limits.get_entity("sector_concentration", sector))

        for ticker, data in exposure_result.issuer_map.items():
            emit("issuer_concentration", ticker, data["weight"],
                 limits.get_entity("issuer_concentration", ticker))

    if stress_result is not None:
        for scenario in stress_result.scenarios:
            emit("stress_loss", scenario.name, scenario.estimated_loss_pct,
                 limits.get_entity("stress_loss", scenario.name))

    # Sort: breach first, then by alert type
    severity_order = {"breach": 0, "warning": 1}
    alerts.sort(key=lambda a: (severity_order.get(a.severity, 2), a.alert_type))

    evaluated = sorted(evaluated_key(lt, eid) for lt, eid in limits.looked_up)
    return alerts, evaluated
