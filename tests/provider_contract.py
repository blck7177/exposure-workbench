"""What the provider refuses before it reads a word of a request.

A Responses request replays the conversation as input items. A `function_call`
item the model produced must be followed by a `function_call_output` with its
call_id before the model is asked again, and an output may answer only a call that
precedes it. The provider answers anything else with a 400 and the turn ends in an
exception with no reply to the reader. Every scripted provider in these tests
checks its request here first, so a loop that builds a request the provider would
refuse fails the test that drives it.
"""

from __future__ import annotations


def check(input_items: list[dict], tools: list[dict] | None = None) -> None:
    """Raise AssertionError, in the provider's own words, where it would 400."""
    calls: dict[str, bool] = {}
    for i, item in enumerate(input_items):
        kind = item.get("type")
        if kind == "function_call":
            assert item.get("call_id"), f"input[{i}]: a function_call carries a call_id"
            calls[item["call_id"]] = False
        elif kind == "function_call_output":
            cid = item.get("call_id")
            assert cid in calls, f"input[{i}]: function_call_output answers no preceding function_call ({cid!r})"
            assert not calls[cid], f"input[{i}]: call {cid!r} answered twice"
            calls[cid] = True
        elif "role" in item:
            assert item["role"] in ("user", "assistant", "developer", "system"), f"input[{i}]: unknown role {item['role']!r}"
            assert isinstance(item.get("content"), (str, list)), f"input[{i}]: a message carries content"
        elif kind in ("message", "reasoning"):
            pass
        else:
            raise AssertionError(f"input[{i}]: unknown input item {item!r}"[:200])
    owed = [cid for cid, answered in calls.items() if not answered]
    assert not owed, f"the request ends with function calls unanswered: {owed}"
    for t in tools or []:
        assert t.get("type") == "function" and t.get("name") and isinstance(t.get("parameters"), dict), \
            f"a tool is {{type: function, name, parameters}}; got {t!r}"[:200]
