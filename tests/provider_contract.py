"""What the provider refuses before it reads a word of a request (V38/A-R1).

An assistant message that carries `tool_calls` must be followed by one `tool`
message for each of its calls before anything else is said, and a `tool`
message must answer a call of the assistant message it follows. The provider
answers anything else with a 400, and the turn ends in an exception with no
reply to the reader.

The scripted models in these tests accepted any list of messages. So the
lead's repair branch, which asked again with a `repair_answer` call left
unanswered, passed offline for a whole version, and round C's Q13 crashed on
it (`git show 152375f:docs/spikes/v37/V37C_run.log`, NOTE ON Q13). Every scripted `chat` that
stands in for the provider checks its request here first, so a loop that
builds a request the provider would refuse fails the test that drives it.
"""

from __future__ import annotations


def check(messages: list[dict]) -> None:
    """Raise AssertionError, in the provider's own words, where it would 400."""
    owed: set[str] | None = None        # calls of the last assistant message not yet answered
    for i, m in enumerate(messages):
        if m.get("role") == "tool":
            assert owed is not None and m.get("tool_call_id") in owed, (
                f"messages[{i}]: messages with role 'tool' must be a response to a preceding message with "
                f"'tool_calls' (tool_call_id {m.get('tool_call_id')!r})")
            owed.discard(m["tool_call_id"])
            continue
        assert not owed, (
            f"messages[{i}]: an assistant message with 'tool_calls' must be followed by tool messages "
            f"responding to each 'tool_call_id'; not answered: {sorted(owed)}")
        owed = {tc["id"] for tc in m.get("tool_calls") or []} if m.get("role") == "assistant" else None
    assert not owed, (
        f"an assistant message with 'tool_calls' must be followed by tool messages responding to each "
        f"'tool_call_id'; the request ends with {sorted(owed)} not answered")
