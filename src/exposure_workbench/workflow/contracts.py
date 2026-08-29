"""Workflow contracts — typed input/output for each pipeline step."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class WorkflowInput:
    run_id: str
    portfolio_id: str
    as_of_date: date
    configs_dir: str = "/app/configs"


@dataclass
class WorkflowOutput:
    run_id: str
    status: str
    steps_completed: list[str] = field(default_factory=list)
    error: str | None = None
    # V13-S2. Which KIND of failure, from the closed set in
    # exposure_workbench.errors. `error` above is prose — sometimes this desk's
    # own sentence (a refused input names the stale holdings and the way out),
    # sometimes a provider's JSON. The code is what the UI keys a sentence on,
    # so a reader is never shown either one raw.
    error_code: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    report_id: str | None = None
