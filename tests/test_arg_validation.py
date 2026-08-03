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


# ── a problem has to name the field it is about ──────────────────────────────

NESTED = {
    "type": "object",
    "properties": {
        "financial_summary": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "citations": {"type": "array"}},
            "required": ["text", "citations"],
            "additionalProperties": False,
        },
    },
    "required": ["financial_summary"],
    "additionalProperties": False,
}


def test_an_unknown_argument_is_reported_under_its_own_name():
    """jsonschema reports additionalProperties against the CONTAINER, so the
    path is empty and the key is buried in prose. Blank fields also sort first,
    so every unknown key would outrank the missing ones it is usually mixed
    with — which is the failure _field exists to prevent."""
    problems = validate_args(SCHEMA, {"ticker": "NVDA", "mode": "yoy", "tickr": "NVDA"})
    assert [p["field"] for p in problems] == ["tickr"]


def test_several_unknown_arguments_are_reported_one_by_one():
    problems = validate_args(SCHEMA, {"ticker": "N", "mode": "yoy", "aa": 1, "bb": 2})
    assert [p["field"] for p in problems] == ["aa", "bb"]


def test_a_nested_problem_names_the_leaf_not_the_block():
    """'financial_summary' does not tell a brief-writing agent which of the two
    fields it left out."""
    problems = validate_args(NESTED, {"financial_summary": {"citations": []}})
    assert [p["field"] for p in problems] == ["financial_summary.text"]


def test_a_nested_unknown_argument_names_the_path_to_it():
    problems = validate_args(
        NESTED, {"financial_summary": {"text": "x", "citations": [], "confidence": "low"}})
    assert [p["field"] for p in problems] == ["financial_summary.confidence"]


def test_a_real_field_still_outranks_nothing():
    """Ordering stays by field name; what changed is that no problem is filed
    under the empty string any more."""
    problems = validate_args(SCHEMA, {"zz": 1})
    assert "" not in [p["field"] for p in problems]


def test_a_recorded_argument_is_bounded():
    """result_summary beside it is capped at 2000; args was not.

    A tool's arguments come from the model, and `think` takes free prose with no
    upper bound — its own 400-char truncation protects the RETURN value, not the
    row. Rejection makes it worse rather than better: an argument refused before
    the budget was spent is still written, so an unbounded payload costs nothing
    to store repeatedly. The cap is here rather than in twenty-two schemas
    because it is a property of the audit row, not of any one tool.
    """
    from exposure_workbench.services.trace_service import bound_args

    out = bound_args({"thought": "x" * 50_000, "ticker": "NVDA"})
    assert len(out["thought"]) <= 4096
    assert out["ticker"] == "NVDA"
    assert out["thought"].endswith("…[truncated]")


def test_bounding_leaves_ordinary_arguments_untouched():
    from exposure_workbench.services.trace_service import bound_args

    args = {"ticker": "NVDA", "last_n": 12, "citations": ["fact_a", "fact_b"], "flag": None}
    assert bound_args(args) == args
