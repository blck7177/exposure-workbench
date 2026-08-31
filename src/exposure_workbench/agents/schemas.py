"""Agent input/output schemas for structured LLM communication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReportInput:
    portfolio_id: str
    as_of_date: str
    portfolio_market_value: float = 0.0
    daily_pnl: float = 0.0
    daily_return: float = 0.0
    top_contributors: list[dict[str, Any]] = field(default_factory=list)
    top_detractors: list[dict[str, Any]] = field(default_factory=list)
    sector_exposures: dict[str, float] = field(default_factory=dict)
    var_95_1d: float | None = None
    vol_30d: float | None = None
    max_drawdown: float | None = None
    factor_attributions: list[dict[str, Any]] = field(default_factory=list)
    stress_scenarios: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    audience: str = "portfolio_manager"


@dataclass
class ReportOutput:
    executive_summary: str = ""
    key_movements: str = ""
    factor_explanation: str = ""
    risk_alert_explanation: str = ""
    recommended_actions: str | None = None   # V13-S7: no longer requested; None = not produced
    markdown_report: str = ""
    confidence_flags: dict[str, Any] = field(default_factory=dict)
    llm_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
