"""V38/A-R1: the scripted models check a request the way the provider does.

`tests/provider_contract.check` stands between every scripted `chat` and the
loop that calls it. These pin what it refuses — the shape round C's Q13 sent —
and what it lets through, so a loop test that passes is a request the provider
would have read.
"""

from __future__ import annotations

import pytest

from tests import provider_contract

_SYSTEM = {"role": "system", "content": "desk"}
_USER = {"role": "user", "content": "how much is held?"}


def _calls(*ids: str) -> dict:
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": i, "function": {"name": "repair_answer", "arguments": "{}"}} for i in ids]}


def _answer(i: str) -> dict:
    return {"role": "tool", "tool_call_id": i, "content": "{}"}


def test_every_call_answered_before_anything_else_is_read():
    provider_contract.check([_SYSTEM, _USER, _calls("a", "b"), _answer("b"), _answer("a"),
                             {"role": "user", "content": "refused"}, _calls("c"), _answer("c")])


def test_the_request_round_c_q13_sent_is_refused():
    """The repair call left without its tool message, and the lead asked again."""
    q13 = [_SYSTEM, _USER, {"role": "assistant", "content": "reply"}, {"role": "user", "content": "refused"},
           _calls("r1"), _answer("r1"), _calls("r1")]
    with pytest.raises(AssertionError, match="not answered"):
        provider_contract.check(q13)
    with pytest.raises(AssertionError, match="must be followed by tool messages"):
        provider_contract.check(q13 + [{"role": "user", "content": "Write the answer."}])


def test_one_call_of_two_answered_is_refused():
    with pytest.raises(AssertionError, match=r"\['b'\]"):
        provider_contract.check([_SYSTEM, _calls("a", "b"), _answer("a"), _USER])


def test_a_tool_message_answers_a_call_it_follows():
    with pytest.raises(AssertionError, match="must be a response"):
        provider_contract.check([_SYSTEM, _USER, _answer("a")])
    with pytest.raises(AssertionError, match="must be a response"):
        provider_contract.check([_SYSTEM, _calls("a"), _answer("a"), _answer("a")])
