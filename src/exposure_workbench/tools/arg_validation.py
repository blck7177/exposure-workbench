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

import re
from typing import Any

from jsonschema import Draft202012Validator


_QUOTED = re.compile(r"'([^']+)'")


def _path(error) -> str:
    return ".".join(str(p) for p in error.absolute_path)


def _fields(error) -> list[str]:
    """The argument(s) a problem is about, fully qualified.

    Most errors carry the path to the offending value and one name is enough.
    Two do not, and both are reported against the CONTAINER:

      required            path is the enclosing object, the missing name is in
                          the message. Unqualified that reads 'financial_summary'
                          for a block that is missing its text.
      additionalProperties  path is the enclosing object too, and the unexpected
                          keys are in the message — so without this every
                          unknown argument would be filed under the empty
                          string, which is both useless and sorts first, ahead
                          of the real problems it is usually mixed with.
    """
    if error.validator in ("required", "additionalProperties", "unevaluatedProperties"):
        names = _QUOTED.findall(error.message)
        if names:
            prefix = _path(error)
            return [f"{prefix}.{n}" if prefix else n for n in names]
    return [_path(error)]


def validate_args(schema: dict, args: Any) -> list[dict]:
    """Every way `args` fails `schema`, as {field, problem}. Empty means valid."""
    if not isinstance(args, dict):
        return [{"field": "", "problem":
                 f"arguments must be an object, got {type(args).__name__}"}]

    validator = Draft202012Validator(schema)
    problems = [
        {"field": field, "problem": e.message}
        for e in validator.iter_errors(args)
        for field in _fields(e)
    ]
    # Stable across runs; ties broken by the message so two problems on one
    # field do not swap places either.
    return sorted(problems, key=lambda p: (p["field"], p["problem"]))
