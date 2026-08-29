"""Response models more than one router answers with (V7).

A nested model that two routes return has to be one class. The alternative is
not two definitions of a shape — it is two shapes that agree until somebody
adds a field to one of them, and the consumer that reads both cannot tell which
route it is looking at any more.

Only genuinely shared models belong here. A model one router owns stays in that
router, where the reader of the endpoint can see it without a second file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, computed_field, model_validator


class RunErrorOut(BaseModel):
    """Why a step stopped — the KIND of failure, and only that (V13-S2).

    `code` is what the UI turns into a sentence: one of the codes in
    exposure_workbench.errors.workflow_codes, which is also the set
    apps/web/lib/errors.ts has wording for (guarded both ways).

    There is deliberately no `detail` here. The exception's own words — the
    provider's 429 JSON, "http://exposure-mcp:8000/mcp/research could not be
    reached" — are recorded in the database for the operator and are NOT served,
    because the demo book is public: anything on this payload is readable by any
    anonymous visitor with devtools open, which is the hole this batch exists to
    close. See the scrubber below, which is the other half of the same rule.
    """

    code: str


class WorkflowEventOut(BaseModel):
    """One step of a run's outer timeline, for whoever is watching it happen.

    Returned by the exposure run detail and — since V7-U1 — by the research run
    detail, which had no events endpoint at all: a cold issuer spends minutes in
    EDGAR ingest and embedding, and the page showed a spinner for all of it.
    The steps were already being recorded; nothing was reaching the person
    waiting.

    payload_summary carries what a step decided rather than only that it
    finished — `evaluated` for the limit checks, `scenarios_unevaluated` and
    `factors_held_flat` for stress. It is on the wire (V7-U4) because a check
    that never ran looked exactly like a check that passed, which in a risk
    product is the one place a UI must not be quiet.
    """

    id: int
    step_name: str
    status: str
    message: str | None
    duration_ms: int | None
    payload_summary: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _scrub_operator_detail(self):
        """Take the exception's own words back out of payload_summary.

        `step` writes {"error": {"code": …, "detail": …}} into the payload so the
        operator has the failure's own words in the database. payload_summary is
        served whole (V7-U4 put it on the wire so a check that never ran could
        stop looking like one that passed), so without this the detail rides out
        with it — and on the public demo book that means an anonymous visitor,
        which is exactly the leak this batch closes. Stripped here rather than
        never stored: the operator needs it, the reader must not have it, and one
        scrubber at the boundary is easier to keep true than a rule about what
        every step may put in its payload.
        """
        err = (self.payload_summary or {}).get("error")
        if isinstance(err, dict) and "detail" in err:
            self.payload_summary = {
                **self.payload_summary,
                "error": {k: v for k, v in err.items() if k != "detail"},
            }
        return self

    @computed_field
    @property
    def error(self) -> RunErrorOut | None:
        """The failure this step recorded, lifted out of its payload.

        Derived rather than stored a second time: `step` already writes the
        classified failure into payload_summary (V13-S2), and a column beside it
        would be the same fact in two places, free to disagree. Steps that
        succeeded, and every event written before V13, answer None — which the
        UI renders as the generic sentence rather than as a claim about a cause.
        """
        e = (self.payload_summary or {}).get("error")
        if isinstance(e, dict) and isinstance(e.get("code"), str):
            return RunErrorOut(code=e["code"])
        return None
