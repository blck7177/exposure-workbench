"""Tool-argument validation (MCP_PLAN P1.2) — a pure function, deliberately.

The wrapper used to pass whatever the model produced to `tool.fn(db, **args)`.
Three things arrived there as a result: a missing required field, a value of the
wrong type, and an operation the closed algebra does not have — each surfacing
as a Python exception the wrapper caught and returned as `tool_error` with the
traceback text in `detail`. That tells the model something failed. It does not
tell it what to send instead, which is the only part it can act on.

Kept out of registry.py so the wrapper orchestrates rather than validates, and
so the problem shapes can be tested without a database — the same split V3 used
for numeric verification.

Two decisions worth stating:

Problems are ALL reported, not just the first. A model that fixes one field per
turn spends the turn budget on a form it could have filled in once.

Problems are sorted by field. jsonschema's iteration order follows dict order
and validator registration, so two identical calls could produce two different
orders — an unreproducible trace and an unstable reply, for nothing.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


def _field(error) -> str:
    """The argument a problem is about.

    For most errors that is the path into the payload. For `required` the path
    is empty and the field name is in the validator's own value, which is the
    difference between "mode" and "" in a reply the model has to act on.
    """
    if error.validator == "required" and not error.absolute_path:
        missing = error.message.split("'")
        return missing[1] if len(missing) > 1 else ""
    return ".".join(str(p) for p in error.absolute_path)


def validate_args(schema: dict, args: Any) -> list[dict]:
    """Every way `args` fails `schema`, as {field, problem}. Empty means valid."""
    if not isinstance(args, dict):
        return [{"field": "", "problem":
                 f"arguments must be an object, got {type(args).__name__}"}]

    validator = Draft202012Validator(schema)
    problems = [
        {"field": _field(e), "problem": e.message}
        for e in validator.iter_errors(args)
    ]
    # Stable across runs; ties broken by the message so two problems on one
    # field do not swap places either.
    return sorted(problems, key=lambda p: (p["field"], p["problem"]))
