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
WEB = ROOT / "apps" / "web" / "app"
STRESS_ROUTE = ROOT / "apps" / "api" / "routes" / "exposure_runs.py"


def _web_source() -> str:
    """Every .tsx the book is built from.

    It was one file. V13-S6c split page.tsx into the page, a rail, chart panels
    and the sections between them, and a guard pinned to one filename would have
    passed the day the reads moved out of it — which is the failure this guard
    exists to be the opposite of.
    """
    return "\n".join(p.read_text() for p in sorted(WEB.rglob("*.tsx")))

# step name -> the payload keys the page reads out of that step. Nested keys are
# listed flat because that is how they break: the web reaches
# scenarios_evaluated[name].factors_held_flat, and a rename of the inner name is
# as silent as a rename of the outer one.
CONTRACT = {
    "calculate_risk": {"scenarios_evaluated", "factors_held_flat", "scenarios_unevaluated",
                       "name", "reason"},
    "check_limits": {"evaluated", "inert_overrides"},
}

# Which keys the WEB reads out of payload_summary, and which ones it stopped
# needing to.
#
# V13-S5 gave the scenarios a typed endpoint that reads StressResult columns —
# `factors_held_flat` is a column on that table, not only a key in a JSONB blob
# — so the page no longer reaches into calculate_risk's payload for them. That
# is this guard's own worry resolved rather than evaded: the two ends now agree
# by a column type instead of by convention, which is a stronger guarantee than
# any string match here. So those keys are held against the ENDPOINT below, and
# the page is held to the ones it still reads as JSON.
VIA_TYPED_ENDPOINT = {"scenarios_evaluated", "factors_held_flat", "scenarios_unevaluated"}

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
    sorted((set().union(*CONTRACT.values()) | VERDICT_KEYS)
           - _TOO_COMMON_TO_GREP - VIA_TYPED_ENDPOINT),
)
def test_the_web_still_reads_every_key_the_contract_names(key):
    """The other direction, and the one a Python-only change cannot notice.

    A key dropped from the web is a step that has gone back to being recorded
    and unread, which is the state this whole item existed to leave — and it
    leaves no trace in this repository's test suite anywhere else, because the
    web has none.
    """
    assert key in _web_source(), f"nothing under apps/web/app reads `{key}` any more"


@pytest.mark.parametrize("key", sorted(VIA_TYPED_ENDPOINT))
def test_the_typed_endpoint_still_serves_what_the_page_stopped_digging_for(key):
    """The keys the page handed to a typed read.

    `scenarios_evaluated` and `scenarios_unevaluated` are the two halves of what
    calculate_risk decided, and the stress endpoint answers both from
    StressResult rows: a scenario with a loss is evaluated, one with a reason and
    no loss is not. `factors_held_flat` is a column it serves by name. If that
    endpoint stops carrying them the page goes quiet in exactly the way this file
    was written to prevent, and no TypeScript change would say so.
    """
    src = STRESS_ROUTE.read_text()
    block = src[src.index("async def run_stress("):]
    block = block[:block.index("\n@router") if "\n@router" in block else len(block)]
    if key == "factors_held_flat":
        assert "factors_held_flat" in block, "the stress endpoint no longer serves held-flat factors"
    else:
        # evaluated vs unevaluated is the presence of a loss against a reason.
        assert '"reason": r.reason' in block and '"loss_pct"' in block, (
            "the stress endpoint must serve both a loss and a reason, or the page "
            "cannot tell a scenario that ran from one that did not"
        )
