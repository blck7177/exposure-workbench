"""V38/A-R1: the scripted models check a request the way the provider does.

`tests/provider_contract.check` stands between every scripted provider and the
loop that calls it. A Responses request replays the conversation as input items;
these pin what the check refuses — a function call replayed without its output,
an output answering no call, the shapes the Responses API does not know — and
what it lets through, so a loop test that passes is a request the provider would
have read.
"""

from __future__ import annotations

import pytest

from tests import provider_contract

_USER = {"role": "user", "content": [{"type": "input_text", "text": "how much is held?"}]}


def _call(cid: str) -> dict:
    return {"type": "function_call", "call_id": cid, "name": "analyze", "arguments": "{}"}


def _answer(cid: str) -> dict:
    return {"type": "function_call_output", "call_id": cid, "output": "{}"}


def test_every_call_answered_before_anything_else_is_read():
    provider_contract.check([_USER, _call("a"), _call("b"), _answer("b"), _answer("a"),
                             {"role": "developer", "content": "refused"}, _call("c"), _answer("c")])


def test_a_call_replayed_without_its_output_is_refused():
    """The shape round C's Q13 sent: the repair call left without its output, and
    the lead asked again."""
    with pytest.raises(AssertionError, match="unanswered"):
        provider_contract.check([_USER, _call("r1"), _answer("r1"), _call("r1")])


def test_one_call_of_two_answered_is_refused():
    with pytest.raises(AssertionError, match=r"\['b'\]"):
        provider_contract.check([_USER, _call("a"), _call("b"), _answer("a")])


def test_an_output_answers_one_call_that_precedes_it():
    with pytest.raises(AssertionError, match="no preceding function_call"):
        provider_contract.check([_USER, _answer("a")])
    with pytest.raises(AssertionError, match="answered twice"):
        provider_contract.check([_USER, _call("a"), _answer("a"), _answer("a")])


def test_the_shapes_the_responses_api_does_not_know_are_refused():
    """A function_call carries its call_id; a chat-completions `tool` message and
    an item of an unknown type are not input items."""
    with pytest.raises(AssertionError, match="carries a call_id"):
        provider_contract.check([_USER, {"type": "function_call", "name": "analyze", "arguments": "{}"}])
    with pytest.raises(AssertionError, match="unknown role"):
        provider_contract.check([{"role": "tool", "content": "{}"}])
    with pytest.raises(AssertionError, match="unknown input item"):
        provider_contract.check([_USER, {"type": "tool_result", "id": "x"}])


def test_a_tool_is_a_flat_function_definition():
    """{type: function, name, parameters} — not the nested chat-completions shape."""
    provider_contract.check([_USER], tools=[{"type": "function", "name": "analyze", "parameters": {"type": "object"}}])
    with pytest.raises(AssertionError, match="a tool is"):
        provider_contract.check([_USER], tools=[{"type": "function", "function": {"name": "analyze"}}])
