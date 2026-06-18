"""ID generation utilities."""

from __future__ import annotations

import uuid


def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}{uid}" if prefix else uid


def new_run_id() -> str:
    return new_id("run_")


def new_task_id() -> str:
    return new_id("task_")


def new_report_id() -> str:
    return new_id("rpt_")


def new_alert_id() -> str:
    return new_id("alert_")
