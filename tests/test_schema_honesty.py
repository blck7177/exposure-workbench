"""P1.2b — the schemas say what the functions actually accept (offline).

Turning on validation made every schema load-bearing at once, and seven of them
were not true to their functions. They all failed the same way: a parameter the
function declares `str | None = None` was typed `{"type": "string"}`, which
Draft 2020-12 rejects an explicit `null` for. Omitting an optional argument and
sending `null` for it are the same intent, and a model that has not been given
`strict` function calling emits either — so a working call became
`invalid_arguments`.

The whole suite stayed green through it, which is the part worth keeping. Every
existing test omits its optional arguments; none sends a null. So the guard here
is not seven cases — it is derived from the functions themselves, and it covers
the next optional parameter somebody adds without their having to remember this.
"""

from __future__ import annotations

import inspect
from typing import get_args, get_type_hints

import pytest
from jsonschema import Draft202012Validator

from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry


def _all_tools():
    """Every registered tool, from both faces, deduped by name."""
    out = {}
    for registry in (build_meta_registry(), build_research_registry()):
        out.update(registry.tools)
    return sorted(out.items())


def _stub(schema: dict):
    """A minimal value satisfying `schema`, so a test can vary one field.

    Recursive because submit_brief's blocks are objects with their own required
    fields — the only nested schema in the registry, and the one whose gate
    matters most.
    """
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "object":
        props = schema.get("properties") or {}
        return {name: _stub(props[name]) for name in (schema.get("required") or [])}
    if kind == "array":
        items = schema.get("items") or {"type": "string"}
        return [_stub(items)] if schema.get("minItems") else []
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "number":
        return float(schema.get("minimum", 1))
    if kind == "boolean":
        return True
    enum = schema.get("enum")
    if enum:
        return next(v for v in enum if v is not None)
    return "NVDA"


def _nullable_params(tool):
    """Parameters whose ANNOTATION admits None — the function's own claim.

    The annotation, not the default. `benchmark: str | None = "SPY"` defaults to
    a benchmark and still treats None as a real value ('no comparison'), while
    `last_n: int = 12` is declared int and refusing a null for it is the schema
    telling the truth. Reading the default instead gets both of those backwards.
    """
    try:
        hints = get_type_hints(tool.fn)
    except Exception:                       # unresolvable forward ref
        hints = {}
    out = []
    for name, p in inspect.signature(tool.fn).parameters.items():
        if name == "db" or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        hint = hints.get(name)
        admits_none = (
            type(None) in get_args(hint) if hint is not None
            else "None" in str(p.annotation)
        )
        if admits_none or p.default is None:
            out.append(name)
    return out


@pytest.mark.parametrize("name, tool", _all_tools())
def test_every_registered_schema_is_a_valid_schema(name, tool):
    """Draft202012Validator is constructed per call inside invoke(). A malformed
    schema — or a pattern that is not a valid Python regex, which jsonschema
    compiles only when it validates — would raise straight out of the gate,
    which promises never to raise to its caller."""
    Draft202012Validator.check_schema(tool.json_schema)


@pytest.mark.parametrize("name, tool", _all_tools())
def test_an_optional_argument_accepts_the_null_its_function_accepts(name, tool):
    """If the fn's signature admits None, null is a value it handles, and the
    schema has to say so. Derived from the signature rather than listed, so the
    next optional parameter is covered by having been written."""
    base = _stub(tool.json_schema)
    for param in _nullable_params(tool):
        if param not in (tool.json_schema.get("properties") or {}):
            continue
        problems = validate_args(tool.json_schema, {**base, param: None})
        assert problems == [], (
            f"{name}.{param} defaults to None in the function but the schema "
            f"refuses null: {problems}"
        )


@pytest.mark.parametrize("name, tool", _all_tools())
def test_a_required_argument_is_one_the_function_does_not_default(name, tool):
    """The other direction: `required` must not name something the fn defaults,
    or the schema refuses a call the fn was written to accept."""
    defaulted = {
        p.name for p in inspect.signature(tool.fn).parameters.values()
        if p.default is not inspect.Parameter.empty and p.name != "db"
    }
    if "blocks" in {p.name for p in inspect.signature(tool.fn).parameters.values()}:
        return  # submit_brief takes **blocks; its contract is the schema itself
    over_required = sorted(set(tool.json_schema.get("required") or []) & defaulted)
    assert over_required == [], f"{name} requires what its function defaults: {over_required}"


def test_the_forms_a_filing_can_actually_have_are_selectable():
    """form_type's enum was ['10-K', '10-Q'], but amendments are ingested: the
    provider asks edgartools for a form and gets '10-K/A' too, and nothing skips
    them. So a passage's own citation could name a form the next call was then
    refused for passing back."""
    registry = build_read_registry()
    for tool_name in ("search_filing_passages", "get_filing_section"):
        enum = registry.get(tool_name).json_schema["properties"]["form_type"]["enum"]
        assert {"10-K", "10-Q", "10-K/A", "10-Q/A"} <= set(enum), tool_name


@pytest.mark.parametrize("name, tool", _all_tools())
def test_a_tool_without_kwargs_forbids_unknown_arguments(name, tool):
    """`invoke()` calls `fn(db, **args)`. For a fn with no **kwargs an unknown key
    is a TypeError — reported to the model as `tool_error` with a Python message,
    after the budget was already spent. For the one fn that DOES take **kwargs,
    submit_brief, it is worse: the key is silently dropped, so a mistyped block
    name produces a brief that looks complete and is missing a section.

    Derived from the signature so the next tool is covered by having been
    written, rather than by somebody remembering this paragraph.
    """
    takes_kwargs = any(
        p.kind is p.VAR_KEYWORD for p in inspect.signature(tool.fn).parameters.values()
    )
    assert tool.json_schema.get("additionalProperties") is False, (
        f"{name} accepts unknown arguments; its fn "
        + ("silently drops them" if takes_kwargs else "raises TypeError on them")
    )


@pytest.mark.parametrize("name, tool", _all_tools())
def test_nested_objects_forbid_unknown_arguments_too(name, tool):
    """submit_brief is the case: `citations` inside open_questions is accepted by
    the schema and then ignored, because the gate collects citations from the
    five cited blocks only. Ids that are never trail-checked, never stored and
    never shown, in the one tool whose entire job is citation discipline.

    Only objects that DECLARE properties are covered. An object with none is a
    free-form map — confidence_flags is one, an open set of flags landing in a
    JSONB column — and closing it would say 'no keys at all', which is a
    different claim and a false one.
    """
    for prop, sub in (tool.json_schema.get("properties") or {}).items():
        if isinstance(sub, dict) and sub.get("type") == "object" and sub.get("properties"):
            assert sub.get("additionalProperties") is False, f"{name}.{prop}"


_WINDOWED = {
    "get_fact_series": "last_n", "compute_change": "last_n", "compute_ratio": "last_n",
    "compute_combine": "last_n", "compute_stat": "last_n", "search_filing_passages": "k",
}


@pytest.mark.parametrize("name, param", sorted(_WINDOWED.items()))
def test_a_window_size_has_a_floor_as_well_as_a_ceiling(name, param):
    """Each of these had a maximum and no minimum, and the floor is where the
    damage was.

    load_fact_series does `limit = min(last_n or 40, 40)` and then
    `points[-limit:]`. So last_n=0 returned all forty points while the ledger
    row recorded 0; last_n=-4 returned the series with its four OLDEST points
    dropped, which is a window nobody asked for; and last_n=-20 on a
    twelve-point series returned NOTHING — successfully, with a calc_id, which
    the agent may then cite. A citable calculation backed by an empty series is
    the class V3-R spent a week closing.
    """
    tool = dict(_all_tools())[name]
    spec = tool.json_schema["properties"][param]
    assert spec.get("minimum", 0) >= 1, f"{name}.{param} has no floor: {spec}"

    base = _stub(tool.json_schema)
    for bad in (0, -4, -20):
        assert validate_args(tool.json_schema, {**base, param: bad}), \
            f"{name}.{param}={bad} is accepted"


@pytest.mark.parametrize("name, param", sorted(_WINDOWED.items()))
def test_a_window_size_written_as_a_float_does_not_reach_the_slice(name, param):
    """Draft 2020-12 counts 12.0 as an integer — deliberately, and jsonschema
    implements it — so no keyword rejects one. It then reaches `points[-12.0:]`
    and raises TypeError, which the wrapper reports as tool_error.

    Since the schema cannot express this, the fn coerces, the way
    filing_retrieval_service already did for k.
    """
    tool = dict(_all_tools())[name]
    # A float that is in range for THIS parameter — k's ceiling is 10, last_n's
    # is 40, and the point is the type, not the value.
    in_range = float(tool.json_schema["properties"][param].get("minimum", 1))
    assert validate_args(tool.json_schema, {**_stub(tool.json_schema), param: in_range}) == []

    import inspect
    source = inspect.getsource(inspect.getmodule(tool.fn))
    assert f"int({param})" in source, \
        f"nothing coerces {name}.{param}, and the schema cannot"
