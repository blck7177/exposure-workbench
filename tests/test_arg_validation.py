"""P1.2 — tool arguments are checked before anything is spent (offline).

invoke() handed args straight to `tool.fn(db, **args)`. A missing required
field, a string where a number belongs, an op the algebra does not have — all
of it arrived at the function body, and what came back was `tool_error` with a
Python exception in the detail: a message that tells the model something went
wrong, not what to send instead.

The check is a pure function so this file can be exhaustive about the problem
shapes without a database, and so the wrapper is left orchestrating rather than
validating (the same split V3 used for numeric verification).
"""

from __future__ import annotations

from exposure_workbench.tools.arg_validation import validate_args

SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "mode": {"type": "string", "enum": ["yoy", "qoq", "pct", "abs"]},
        "last_n": {"type": "integer", "minimum": 1, "maximum": 40},
    },
    "required": ["ticker", "mode"],
    "additionalProperties": False,
}


def test_valid_args_have_no_problems():
    assert validate_args(SCHEMA, {"ticker": "NVDA", "mode": "yoy"}) == []
    assert validate_args(SCHEMA, {"ticker": "NVDA", "mode": "yoy", "last_n": 8}) == []


def test_a_missing_required_field_names_the_field():
    problems = validate_args(SCHEMA, {"ticker": "NVDA"})
    assert len(problems) == 1
    assert problems[0]["field"] == "mode"
    assert "required" in problems[0]["problem"].lower()


def test_a_value_outside_the_enum_lists_what_is_allowed():
    """The model can only correct itself if the reply says what to send."""
    problems = validate_args(SCHEMA, {"ticker": "NVDA", "mode": "sideways"})
    assert problems[0]["field"] == "mode"
    assert "yoy" in problems[0]["problem"] and "qoq" in problems[0]["problem"]


def test_a_wrong_type_says_which_type():
    problems = validate_args(SCHEMA, {"ticker": "NVDA", "mode": "yoy", "last_n": "eight"})
    assert problems[0]["field"] == "last_n"
    assert "integer" in problems[0]["problem"]


def test_a_bound_is_reported_as_a_bound():
    problems = validate_args(SCHEMA, {"ticker": "NVDA", "mode": "yoy", "last_n": 999})
    assert problems[0]["field"] == "last_n"
    assert "40" in problems[0]["problem"]


def test_an_unknown_argument_is_a_problem_not_a_crash():
    """fn is called as fn(db, **args), so an extra key was a TypeError deep in
    the call — reported to the model as tool_error with a traceback string."""
    problems = validate_args(SCHEMA, {"ticker": "NVDA", "mode": "yoy", "tickr": "NVDA"})
    assert any("tickr" in p["problem"] or p["field"] == "tickr" for p in problems)


def test_every_problem_is_reported_not_just_the_first():
    problems = validate_args(SCHEMA, {"mode": "sideways", "last_n": 0})
    fields = {p["field"] for p in problems}
    assert {"ticker", "mode", "last_n"} <= fields, problems


def test_problems_are_ordered_deterministically():
    """jsonschema yields errors in an order that depends on dict iteration and
    validator registration. Two identical calls that disagree would make the
    trace unreproducible and the reply unstable for no reason."""
    bad = {"mode": "sideways", "last_n": 0, "extra": 1}
    assert validate_args(SCHEMA, bad) == validate_args(SCHEMA, bad)
    fields = [p["field"] for p in validate_args(SCHEMA, bad)]
    assert fields == sorted(fields)


def test_a_non_object_argument_payload_is_refused():
    """The protocol says arguments is an object; a list or a bare string coming
    through would otherwise reach **args and raise."""
    assert validate_args(SCHEMA, [])
    assert validate_args(SCHEMA, "NVDA")


def test_a_schema_with_no_constraints_accepts_anything():
    """think's argument is prose. An empty schema must not be turned into a
    refusal by the mere presence of a validator."""
    assert validate_args({"type": "object"}, {"thought": "anything at all"}) == []


# ── the trace of a refusal must not be the thing that crashes the call ────────

def test_redacting_a_non_dict_payload_does_not_raise():
    """invoke() promises never to raise to its caller, and the rejection path it
    gained in P1.2 hands record_step whatever the model sent — which, for
    `json.loads('"NVDA"')`, is a str. redact_args did `(args or {}).items()`.

    The payload is kept rather than dropped: what the model actually sent is the
    one thing an auditor reading that rejection wants to see.
    """
    from exposure_workbench.services.trace_service import redact_args

    assert redact_args("NVDA") == {"_raw": "NVDA"}
    assert redact_args([1, 2]) == {"_raw": "[1, 2]"}
    assert redact_args(5) == {"_raw": "5"}
    assert redact_args(None) == {}
    assert redact_args({"api_key": "sk-x", "ticker": "NVDA"}) == {
        "api_key": "[REDACTED]", "ticker": "NVDA"}


def test_a_huge_non_dict_payload_is_bounded():
    from exposure_workbench.services.trace_service import redact_args

    assert len(redact_args("x" * 50_000)["_raw"]) == 2000
