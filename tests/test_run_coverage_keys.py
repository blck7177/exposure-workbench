"""V7-U4 — the keys the page reads are the keys the steps write (offline).

The middle panel now reports what a run actually evaluated, and it gets it from
workflow_events.payload_summary — a JSONB column, so the two ends agree by
convention and by nothing else. Rename a key on the workflow side and nothing
fails: the column still validates, the API still serves it, TypeScript still
compiles, and the panel renders "0 limit checks evaluated" under a run that
evaluated twelve. That is not a blank space where a feature used to be, it is a
false alarm on the one signal whose entire purpose is to stop a check that never
ran from looking like a check that passed.

So the contract is written down here, once, and both ends are held to it. This
file does not care what the values mean; the analytics tests do that. It cares
that the name survives.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "src" / "exposure_workbench" / "workflow" / "exposure_workflow.py"
VERIFICATION = ROOT / "src" / "exposure_workbench" / "services" / "report_verification.py"
PAGE = ROOT / "apps" / "web" / "app" / "page.tsx"

# step name -> the payload keys the page reads out of that step. Nested keys are
# listed flat because that is how they break: the web reaches
# scenarios_evaluated[name].factors_held_flat, and a rename of the inner name is
# as silent as a rename of the outer one.
CONTRACT = {
    "calculate_risk": {"scenarios_evaluated", "factors_held_flat", "scenarios_unevaluated",
                       "name", "reason"},
    "check_limits": {"evaluated", "inert_overrides"},
}

# generate_report's payload is not written inline — the step assigns whatever
# the verification verdict hands back — so its key is pinned against the verdict
# instead. Only the size of the check reaches the page; `unverified` cannot,
# because the gate refuses to persist a report that has any.
VERDICT_KEYS = {"numbers_checked"}


def _step_block(step_name: str) -> str:
    """The source of one workflow step, from its _StepContext to the next one."""
    src = WORKFLOW.read_text()
    start = src.index(f'_StepContext(db, run_id, "{step_name}"')
    nxt = src.find("_StepContext(db, run_id, ", start + 1)
    return src[start:nxt if nxt != -1 else len(src)]


@pytest.mark.parametrize("step_name,keys", sorted((s, tuple(sorted(k))) for s, k in CONTRACT.items()))
def test_the_step_still_writes_the_keys_the_page_reads(step_name, keys):
    written = set(re.findall(r'"(\w+)":', _step_block(step_name)))
    assert set(keys) <= written, (
        f'{step_name} no longer writes {sorted(set(keys) - written)} — '
        "the panel will report it as absent rather than as renamed"
    )


def test_the_report_gate_still_reports_how_many_numbers_it_checked():
    body = VERIFICATION.read_text()
    written = set(re.findall(r'"(\w+)":', body[body.index("def as_payload"):]))
    assert VERDICT_KEYS <= written


# `name` and `reason` are held against the producer only. A test that they
# appear somewhere in a 900-line TSX file asserts nothing — both words occur in
# it a dozen times over — and a check that cannot fail is worse than no check,
# because it reads in the summary like one that can.
_TOO_COMMON_TO_GREP = {"name", "reason"}


@pytest.mark.parametrize(
    "key",
    sorted((set().union(*CONTRACT.values()) | VERDICT_KEYS) - _TOO_COMMON_TO_GREP),
)
def test_the_page_still_reads_every_key_the_contract_names(key):
    """The other direction, and the one a Python-only change cannot notice.

    A key dropped from the page is a step that has gone back to being recorded
    and unread, which is the state this whole item existed to leave — and it
    leaves no trace in this repository's test suite anywhere else, because the
    web has none.
    """
    assert key in PAGE.read_text(), f"page.tsx no longer reads `{key}`"
