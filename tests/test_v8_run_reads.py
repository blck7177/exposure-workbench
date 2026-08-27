"""V8-A — the run's findings, readable, and the two absences (offline).

The positive shape is checked live against real rows. What is checked HERE is
what must not be there, because an absence has no row to inspect and drifts back
in silently.
"""

from __future__ import annotations

import inspect

import pytest

from exposure_workbench.services import run_reads_service as rr
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry

_A_TOOLS = ["get_attribution", "get_risk_state", "list_run_alerts",
            "list_risk_limits", "get_run_freshness"]


# ── the face ──────────────────────────────────────────────────────────────────

def test_the_new_reads_are_on_the_meta_face_only():
    meta = set(faces.resolve(build_meta_registry(), faces.FACE_META_AGENT))
    research = set(faces.resolve(build_research_registry(), faces.FACE_RESEARCH))
    for name in _A_TOOLS:
        assert name in meta, f"{name} must be reachable by the agent that answers about the book"
        assert name not in research, (
            f"{name} is on the research face; a brief-writing agent reading the holder's "
            "attribution is writing about the wrong company")


# ── absence 1: no size argument ───────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", ["top_k", "limit", "n", "max_rows", "head"])
def test_attribution_has_no_size_argument(forbidden):
    """A size argument is the mechanism by which an answer names the two largest
    contributors and leaves the reader believing the other eight were flat. The
    set is small and comes back whole; if it ever stops being small the answer is
    pagination with a stated total, not a cut whose size the model chooses."""
    reg = build_meta_registry()
    props = reg.tools["get_attribution"].json_schema["properties"]
    assert forbidden not in props
    assert set(props) == {"run_id"}


# ── absence 2: no judgement ───────────────────────────────────────────────────

_JUDGEMENT_WORDS = (
    "healthy", "unhealthy", "risky", "safe", "concerning", "acceptable",
    "good", "bad", "strong", "weak", "excessive", "comfortable",
)


def test_the_reads_attach_no_verdict():
    """V9 spent a batch establishing that this desk lays out evidence and keeps
    its opinions. These tools are the quantitative half of the same surface and
    the rule does not change at the boundary.

    `quotable_individually` is not an exception: it states that a coefficient's
    ESTIMATE is indeterminate under collinearity — something the regression
    computed — and says nothing about whether the number is good news."""
    src = inspect.getsource(rr)
    # Only the payload keys and literal strings the model sees, not the prose.
    emitted = [line for line in src.splitlines()
               if '"' in line and not line.strip().startswith("#")]
    body = " ".join(emitted).lower()
    for word in _JUDGEMENT_WORDS:
        assert f'"{word}' not in body, f"a field or literal named {word!r} attaches a verdict"


def test_no_threshold_field_is_returned_beside_a_measurement():
    """The same rule V9's panel is pinned by. A limit LEVEL is legitimate — it is
    what the desk set — but it travels in list_risk_limits and on an alert, both
    of which say what they are. It must not appear as a bare companion field on
    a metric, where it reads as the number's own verdict."""
    src = inspect.getsource(rr.get_risk_state)
    for word in ("threshold", "limit_pct", "is_breach", "breached"):
        assert word not in src


# ── the alert sentence ────────────────────────────────────────────────────────

def _alert(severity, current, limit, util):
    class _A:
        id, alert_type = "alert_x", "issuer_concentration"
        entity_type, entity_id = "issuer", "AAPL"
        message = "AAPL over limit"
    _A.severity, _A.current_value, _A.limit_value, _A.utilization = severity, current, limit, util
    return _A()


def test_a_warning_alert_does_not_claim_utilisation_is_against_the_level_it_names():
    """The V3 corpus row — 0.158, 0.15, 0.792 — with the arithmetic followed
    through. 0.158/0.15 is 1.053, so a row holding 0.792 is a WARNING alert whose
    utilisation is measured against a breach level of about 0.20 that the row
    does not carry.

    The V8 plan proposed the sentence "15.8% vs limit 15.0% — utilisation is
    current/limit", and that is false here by the whole gap between the two
    tiers. `_check_one` is the authority: limit_value is the level crossed,
    utilisation is always current/breach_level. A sentence composed from the
    plan's assumption would have written the misattribution into the mitigation.
    """
    row = rr._alert_row(_alert("warning", 0.158, 0.15, 0.792))
    assert "0.158" in row["reads_as"]
    assert "79.2%" in row["reads_as"]
    assert "BREACH" in row["reads_as"], "the denominator must be named"
    assert "NOT against 0.15" in row["reads_as"], (
        "the one thing a reader would otherwise assume must be denied explicitly")
    assert "never a level in itself" in row["reads_as"]


def test_a_breach_alert_may_say_the_two_coincide():
    """At breach severity limit_value IS breach_level, so utilisation is against
    the level named and the sentence can say so plainly. Same numbers, different
    tier, different true sentence — which is why this is composed from severity
    rather than from a template."""
    row = rr._alert_row(_alert("breach", 0.158, 0.15, 1.0533))
    assert "breach level of 0.15" in row["reads_as"]
    assert "of that level is used" in row["reads_as"]
    assert "NOT against" not in row["reads_as"], "nothing to deny when the two agree"


def test_the_alert_sentence_never_presents_utilisation_as_a_level():
    """The single property both branches must have."""
    for sev, util in (("warning", 0.792), ("breach", 1.0533)):
        assert "never a level in itself" in rr._alert_row(_alert(sev, 0.158, 0.15, util))["reads_as"]


def test_an_alert_with_no_levels_composes_no_sentence():
    """Absent numbers produce no sentence rather than a sentence with holes."""

    class _A:
        id, alert_type, severity = "alert_y", "daily_loss", "warning"
        entity_type = entity_id = None
        current_value = limit_value = utilization = None
        message = "x"

    assert rr._alert_row(_A())["reads_as"] is None


# ── metadata honesty ──────────────────────────────────────────────────────────

def test_missing_regression_metadata_is_named_not_faked():
    """DP3. A run written before V8-P1 has no window and no observation count,
    and neither can be asserted afterwards from anything that survives. The read
    returns None plus a sentence saying why — the alternative, back-filling from
    today's config, would record a window the regression never ran over."""
    src = inspect.getsource(rr.get_attribution)
    assert "metadata_note" in src
    assert "cannot be reconstructed" in src
