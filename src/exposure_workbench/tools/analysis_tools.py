"""The `analyze` verb: one request, one aligned table (services/analysis_execution).

Registered on every agent face. What a face may analyse is what it may measure:
the issuer analyst the formulas, the filed lines and the name's place in the
book; the risk manager the book's columns; the market analyst the price
statistics; the lead all of them. The server checks the measure against the face
at the door, so the aggregate cannot widen a face.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import analysis_execution as ax
from exposure_workbench.services import method_index as mi
from exposure_workbench.tools.registry import READ, Tool, current_session_id

SCOPE_SCHEMA = {
    "type": ["object", "null"],
    "description": ("which subjects: {subjects: [tickers]}, or {book: port_…, sector: 'Technology'}, or "
                    "{book: port_…, holdings: 'all'}; expected_count says how many the question said there were "
                    "(a mismatch is reported, never resolved for you); basis says why these, in your words"),
    "properties": {
        "subjects": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 32},
        "book": {"type": ["string", "null"]},
        "sector": {"type": ["string", "null"]},
        "holdings": {"type": ["string", "null"], "enum": ["all", None]},
        "expected_count": {"type": ["integer", "null"], "minimum": 1},
        "basis": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


def _requests_schema(measures: list[str]) -> dict:
    return {
        "type": "array", "minItems": 1, "maxItems": ax.MAX_REQUESTS,
        "items": {"type": "object", "properties": {
            "measure": {"type": "string", "enum": measures},
            "compare": {"type": ["string", "null"], "enum": [*ax.ALL_COMPARES, None],
                        "description": "the period to set the latest against; issuer measures take previous_ttm | "
                                       "previous_fy | previous_quarter, book columns previous_run"},
            "change": {"type": ["string", "null"], "enum": ["absolute", "relative", None],
                       "description": "with compare: absolute (percentage points for a ratio) or relative; default absolute"},
            "rank": {"type": ["boolean", "null"], "description": "order the subjects on the measure (and on its change)"},
            "direction": {"type": ["string", "null"], "enum": [*ax.DIRECTIONS, None], "description": "default highest first"},
            "params": {"type": ["object", "null"], "description": "a price statistic's own params (window, benchmark)"},
        }, "required": ["measure"], "additionalProperties": False},
    }


def analyze_tool(face: str | None) -> Tool:
    measures = mi.measures_for(face)
    allowed = set(measures)

    async def _analyze(db: AsyncSession, requests: list, scope: dict | None = None, why: str | None = None) -> dict:
        return await ax.analyze(db, scope=scope, requests=requests, allowed_measures=allowed,
                                invoked_by=current_session_id())

    return Tool(
        name="analyze", display="Analysing {requests}", rows=False, view=True, tool_class=READ, fn=_analyze,
        description=(
            "One analysis as a table: measures over a scope of subjects, each at its latest period and, with "
            "`compare`, against the comparable period before — on each issuer's OWN calendar — with the change "
            "stated in percentage points, and ranked when asked. The desk binds dates, pairs numerators with "
            "denominators, computes and records every cell; you read the aligned table. Each cell carries its "
            "display, period and id; what could not be read says why; a scope that resolves to fewer subjects "
            "than expected is reported as a mismatch. The measures, by name, are listed in your MEASURES block."),
        json_schema={"type": "object", "properties": {
            "requests": _requests_schema(measures), "scope": SCOPE_SCHEMA,
            "why": {"type": ["string", "null"], "description": "optional: what this analysis is for"}},
            "required": ["requests"], "additionalProperties": False},
    )
