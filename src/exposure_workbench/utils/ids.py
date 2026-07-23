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


# ─── Issuer Intelligence id prefixes (IMPLEMENTATION_PLAN §0.5) ─────────────────

def new_company_id() -> str:
    return new_id("co_")


def new_filing_id() -> str:
    return new_id("filing_")


def new_fact_id() -> str:
    return new_id("fact_")


def new_chunk_id() -> str:
    return new_id("chunk_")


def new_calc_id() -> str:
    return new_id("calc_")


def new_source_id() -> str:
    return new_id("src_")


def new_research_run_id() -> str:
    return new_id("rrun_")


def new_session_id() -> str:
    return new_id("sess_")


def new_step_id() -> str:
    return new_id("step_")


def new_brief_id() -> str:
    return new_id("brief_")
