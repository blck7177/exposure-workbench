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

from pydantic import BaseModel


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
