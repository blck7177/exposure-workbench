"""V13-S2 — a failure has a code, the code has a sentence, and the sentence is
the only thing a reader gets (offline).

Three defects live in the gaps between those clauses, and each test below sits
in one of them:

  A code the UI has wording for that nothing raises is a branch that can never
  fire — the reader gets the generic sentence for a failure we thought we had
  explained, and neither half looks wrong on its own. This is the same defect
  test_error_vocabulary.py was written for after a mistyped ticker was explained
  as an expired conversation; workflow codes take a different path out of the
  system and needed their own guard.

  A code nothing has wording for is the mirror image: the API classifies a
  failure precisely and the page still says "the run stopped".

  A table naming a class that does not exist is the one that actually happened
  while this batch was being written. _BY_TYPE briefly held
  `providers.edgar_provider.EdgarUnavailable` and `price_provider
  .PriceProviderError`, neither of which is a real class. Nothing would have
  failed: those entries simply never match, every EDGAR failure quietly becomes
  `run_failed`, and the table reads as though it handles them.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from exposure_workbench.errors import BriefNotSubmitted, CODES, RunRefused, classify, detail_of
from exposure_workbench.errors.workflow_codes import _BY_TYPE, DEFAULT_CODE

ROOT = Path(__file__).resolve().parents[1]
ERRORS_TS = ROOT / "apps" / "web" / "lib" / "errors.ts"


def _wording_in_ts() -> set[str]:
    """The codes apps/web/lib/errors.ts holds a sentence for."""
    src = ERRORS_TS.read_text()
    block = re.search(r"const RUN_ERROR_WORDING: Record<string, string> = \{(.*?)\n\};",
                      src, re.S)
    assert block, "RUN_ERROR_WORDING is not where this guard expects it"
    return set(re.findall(r"^\s{2}([a-z_]+):", block.group(1), re.M))


# ── the table describes reality ──────────────────────────────────────────────

def test_every_type_in_the_table_is_a_class_that_exists():
    """The one that fired for real while this batch was written.

    An entry naming a class nobody defines is indistinguishable from a working
    one until the failure it claims to handle happens and comes out as
    `run_failed`. Only this repo's own modules are resolved: `openai` is an
    optional dependency by design, so its entries are checked for shape, not
    imported — a module that fails to import here would take the whole failure
    path down with it, which is the opposite of what an error module is for.
    """
    missing = []
    for dotted in _BY_TYPE:
        module, _, cls = dotted.rpartition(".")
        if not module.startswith("exposure_workbench."):
            assert module.isidentifier(), f"{dotted}: not a plausible module path"
            continue
        try:
            mod = importlib.import_module(module)
        except ImportError:
            missing.append(f"{dotted} (no module {module})")
            continue
        if not isinstance(getattr(mod, cls, None), type):
            missing.append(f"{dotted} (no class {cls})")
    assert missing == [], (
        "exception types named in _BY_TYPE that do not exist: " + "; ".join(missing)
        + ". Each one silently never matches, so the failure it claims to handle "
        "comes out as the catch-all while the table reads as if it were covered."
    )


def test_every_code_the_table_produces_is_a_code_that_is_defined():
    unknown = sorted(set(_BY_TYPE.values()) - set(CODES))
    assert unknown == [], f"_BY_TYPE maps to codes CODES does not define: {unknown}"


def test_the_catch_all_is_defined():
    assert DEFAULT_CODE in CODES


# ── the two languages agree, in both directions ──────────────────────────────

def test_the_ui_has_wording_for_every_code_the_api_can_produce():
    unworded = sorted(set(CODES) - _wording_in_ts())
    assert unworded == [], (
        f"apps/web/lib/errors.ts has no sentence for {unworded}. The API can "
        "classify these precisely and the page would still say 'the run stopped'."
    )


def test_the_ui_explains_no_code_the_api_cannot_produce():
    orphans = sorted(_wording_in_ts() - set(CODES))
    assert orphans == [], (
        f"apps/web/lib/errors.ts explains run codes nothing produces: {orphans}. "
        "Either they were renamed, or the branch was written for a code that "
        "never existed — a sentence nobody will ever be shown."
    )


# ── classification ───────────────────────────────────────────────────────────

def test_a_refusal_written_for_the_reader_is_classified_as_one():
    assert classify(RunRefused("Cannot value this portfolio as of …")) == "inputs_unusable"
    assert CODES["inputs_unusable"].speaks_for_itself


def test_an_agent_that_ran_out_of_room_is_not_a_defect():
    """`brief_not_submitted` exists so the reader can tell the two apart.

    Nothing is broken when the research agent spends its budget without
    converging, and "the run stopped before finishing" — the sentence for a
    defect — would be true and useless.
    """
    assert classify(BriefNotSubmitted("turns=30")) == "brief_not_submitted"
    assert classify(RuntimeError("turns=30")) == DEFAULT_CODE


def test_an_unrecognised_failure_is_the_catch_all_rather_than_a_guess():
    assert classify(ValueError("something nobody anticipated")) == DEFAULT_CODE
    assert classify(None) == DEFAULT_CODE


def test_the_informative_type_is_found_through_a_wrapper():
    """The wrapping really happens: direct_llm_agent raises ReportUnavailable
    from whatever the provider raised, and answering `run_failed` for a quota
    refusal would tell the reader to try again when trying again is exactly what
    will not work.
    """
    try:
        try:
            raise RunRefused("stale prices")
        except RunRefused as inner:
            raise RuntimeError("the LLM call failed") from inner
    except RuntimeError as outer:
        assert classify(outer) == "inputs_unusable"


def test_the_cause_walk_is_bounded_and_survives_a_cycle():
    """A chain that loops must not hang the failure path.

    An error module that can itself fail is worse than no error module: this is
    the code that runs when something has already gone wrong.
    """
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert classify(a) == DEFAULT_CODE


# ── what the operator keeps, and what the reader never sees ──────────────────

def test_the_detail_keeps_the_type_and_is_capped():
    d = detail_of(ValueError("Error code: 429 - " + "x" * 5000))
    assert d.startswith("ValueError: Error code: 429")
    assert len(d) <= 2000


def test_the_event_payload_reaches_the_wire_without_the_operators_words():
    """The scrubber at the API boundary, pinned where it can be read.

    `step` writes the exception's own words into payload_summary so the operator
    has them, and payload_summary is served whole (V7-U4). The demo book is
    public, so without the scrubber an anonymous visitor reads the internal
    hostname out of the JSON — the same leak this batch closes on the page,
    reappearing one layer down.
    """
    import datetime as dt
    import json

    from apps.api.schemas import WorkflowEventOut

    ev = WorkflowEventOut(
        id=1, step_name="agent_session", status="failed",
        message="Research agent analysing AAPL — stopped", duration_ms=1,
        payload_summary={
            "filings": 4,
            "error": {"code": "tool_face_unavailable",
                      "detail": "ToolFaceUnavailable: the research tool face at "
                                "http://exposure-mcp:8000/mcp/research could not be reached"},
        },
        created_at=dt.datetime(2026, 8, 29),
    )
    blob = json.dumps(ev.model_dump(), default=str)
    assert "exposure-mcp" not in blob and "detail" not in blob
    # and the rest of the payload is untouched — the scrubber is a scalpel
    assert '"filings": 4' in blob
    assert ev.error is not None and ev.error.code == "tool_face_unavailable"


@pytest.mark.parametrize("model_name,module", [
    ("ResearchRunOut", "apps.api.routes.research"),
    ("ExposureRunOut", "apps.api.routes.exposure_runs"),
])
def test_no_run_payload_carries_the_operators_words(model_name, module):
    """error_detail is written for the operator and is not served.

    The plan for this batch said it could ride along because RLS decides row
    visibility. True, and beside the point: the demo book is PUBLIC, so its runs
    are readable by every anonymous visitor, and a detail column would put the
    provider's 429 body back on the wire. Not a permission branch on the field —
    it is simply not on the payload.
    """
    model = getattr(importlib.import_module(module), model_name)
    assert "error_code" in model.model_fields
    assert "error_detail" not in model.model_fields


# ── the reader's sentence never comes from an unvouched string ───────────────

def test_the_ui_ignores_a_message_that_has_no_code_beside_it():
    """Rows written before this batch carry raw provider text and no code.

    They were not backfilled — guessing a code from prose is the string-matching
    this batch replaced — so the rule has to be fail-closed: no code, no trust in
    the message. This reads the rule out of the TypeScript, which is where it is
    implemented, because the two halves of it are one sentence apart.
    """
    src = ERRORS_TS.read_text()
    fn = re.search(r"export function explainRunError\((.*?)\n\}", src, re.S)
    assert fn, "explainRunError is not where this guard expects it"
    body = fn.group(1)
    assert "if (!code) return GENERIC_RUN_ERROR;" in body, (
        "explainRunError must refuse a message that has no code beside it: a "
        "legacy row's raw provider text would otherwise render verbatim."
    )
