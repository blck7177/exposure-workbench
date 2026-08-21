"""Report gate (V6) — the exposure report's numbers, checked against its own run.

This is the last LLM output surface in the system that reached a user without
passing a gate. The chat answer goes through `respond`, the issuer brief through
`submit_brief`; the daily report went through nothing at all, and a JSON parse
failure still persisted the raw text while any other exception persisted a
fabricated template. Measured on the live database before this existed: 9 of 19
stored reports were mock text, served as reports, and the mock's own disclaimer
said the API key was not configured when it was.

WHY THIS GATE HAS NO CITATIONS, WHEN THE OTHER TWO DO.

`respond` and `submit_brief` verify against evidence the agent chose, so the
agent must say what it chose, and the citation is that statement. A report has
no choice to state: it describes exactly one run, and the complete set of things
it may legitimately quote is that run's own deterministic rows. So the evidence
set is assembled HERE, from the run id, and the model is never asked for it.

That is not a shortcut, it is the reason this gate can be stricter than the other
two. The brief gate can only ask "does this number appear in something you
cited" — an existence check against a corpus. This one asks "is this number a
value of a row of this run", which is the whole truth about what the report is
allowed to say. Measured on a real stored report: 45 substantive numbers, all 45
resolvable this way once `contribution` is persisted and the run's alerts are
part of the run (V6 does both).

WHY IT DOES NOT RETRY.

`daily_reports` keeps its own cost books — `llm_model`, `prompt_tokens`,
`completion_tokens` — and that is the stated premise of this module's exemption
from the V4 rule that every completion goes through `llm_session`: one report IS
one completion (tests/test_v2_audit.py). Those three columns are scalar. A
second attempt would have nowhere to be recorded and would silently overwrite
the first, so a retry does not merely cost a completion, it breaks the accounting
that buys the exemption. A report that fails the gate is not written, and the
step records which numbers failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import RiskAlert
from exposure_workbench.services import numeric_verification as nv


@dataclass(frozen=True)
class ReportVerdict:
    accepted: bool
    checked: int = 0                       # substantive numbers extracted
    problems: list[dict] = field(default_factory=list)

    def as_payload(self) -> dict:
        """What the run's timeline records, verdict either way."""
        return {
            "numbers_checked": self.checked,
            "numbers_unverified": len(self.problems),
            # Bounded: a wholly hallucinated report would otherwise write its
            # entire number set into a step payload.
            "unverified": [
                {"number": p.get("number"), "nearest": p.get("nearest")}
                for p in self.problems[:10]
            ],
        }


# The fields whose text a reader sees. `markdown_report` is included even though
# no UI renders it today: it is served by the API and is the field the other five
# summarise, so a number that is wrong only there is still a wrong number the
# system published.
_CHECKED_FIELDS = (
    "executive_summary",
    "key_movements",
    "factor_explanation",
    "risk_alert_explanation",
    "recommended_actions",
    "markdown_report",
)


async def evidence_ids_for_run(db: AsyncSession, run_id: str) -> list[str]:
    """Everything this run is allowed to have said, as citable ids.

    The run itself fans out over its metrics, sector, issuer and factor rows
    (numeric_verification._RUN_CHILDREN). Its alerts are children of the run too
    and are resolved through the same id, so they need no separate listing —
    they are read here only to fail loudly if an alert id is malformed, which is
    a minting bug this system has had before and cannot detect from the run side.
    """
    ids = [run_id]
    alert_ids = (
        await db.execute(select(RiskAlert.id).where(RiskAlert.run_id == run_id))
    ).scalars().all()
    ids.extend(a for a in alert_ids if a)
    return ids


async def verify_report(db: AsyncSession, run_id: str, report) -> ReportVerdict:
    """Check every number the report states against this run's own rows.

    `report` is an agents.schemas.ReportOutput. Returns a verdict; persisting is
    the caller's decision and its only honest options are "all of it" or "none".
    """
    text = "\n\n".join(
        str(getattr(report, field_name, "") or "") for field_name in _CHECKED_FIELDS
    )
    numbers = nv.extract_numbers(text)
    if not numbers:
        # A report with no numbers in it is not thereby trustworthy, but there is
        # nothing here to check and this gate does not judge prose. Recorded as
        # zero checked so a run that produced one is distinguishable from a run
        # whose forty-five numbers all passed.
        return ReportVerdict(accepted=True, checked=0)

    ids = await evidence_ids_for_run(db, run_id)
    values, quoted = await nv.resolve_cited_values(db, ids)
    problems = nv.verify(numbers, values, quoted)
    return ReportVerdict(
        accepted=not problems, checked=len(numbers), problems=problems,
    )
