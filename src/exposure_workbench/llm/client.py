"""The provider, through one door: the Responses API.

Every model request of this desk — the lead's, a specialist's, the research
run's, the daily report's — goes through `respond`. It returns a ModelTurn: the
text, the function calls, the native output items (replayable as the next
request's input, reasoning included), and the usage the provider actually
charged. Nothing is translated into a second dialect on the way.

Why Responses and not Chat Completions: the current model line refuses function
tools with reasoning on /v1/chat/completions (a 400 unless reasoning_effort is
'none'; measured 2026-10-02), and the reasoning the desk pays for has to be
replayable between tool calls. Chat Completions is not served here at all; a
configuration this door cannot send is a configuration error, never a quiet
substitution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_client = None


class ProviderUnavailable(RuntimeError):
    """No usable API key: the call cannot be made, and no mock stands in."""


def get_openai_client():
    """Return a cached async OpenAI client, or None if unavailable."""
    global _client
    if _client is not None:
        return _client
    try:
        from openai import AsyncOpenAI
        from exposure_workbench.app_state.settings import get_settings
        settings = get_settings()
        key = settings.openai_api_key
        if not key or key.startswith("your_") or key == "sk-...":
            logger.warning("OPENAI_API_KEY not set — no model call can be made")
            return None
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
        return _client
    except ImportError:
        logger.warning("openai package not installed — no model call can be made")
        return None


class EmbeddingUnavailable(RuntimeError):
    """Raised when embeddings are requested without a usable API key (fail-loud).

    There is deliberately no keyword-search degradation path: a missing key must
    stop the indexing step visibly rather than silently producing a weaker index.
    """


async def embed_texts(texts: list[str], model: str | None = None) -> tuple[list[list[float]], str]:
    """Embed a batch of texts. Returns (vectors, model_name).

    Vector dimension must match filing_chunks.embedding (1536 for
    text-embedding-3-small); a mismatch surfaces at insert time rather than
    being silently truncated.
    """
    from exposure_workbench.app_state.settings import get_settings

    settings = get_settings()
    effective_model = model or settings.embedding_model

    client = get_openai_client()
    if client is None:
        raise EmbeddingUnavailable(
            "OPENAI_API_KEY is not configured — filing indexing cannot run."
        )
    if not texts:
        return [], effective_model

    response = await client.embeddings.create(model=effective_model, input=texts)
    # OpenAI may return items out of order; sort by index before unpacking.
    ordered = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in ordered], response.model


# ── one model turn ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str            # the JSON string the model wrote, verbatim


@dataclass
class ModelTurn:
    """What one request produced, and what it cost."""
    text: str | None
    tool_calls: list[ToolCall]
    output: list[dict]                       # native output items, in order, replayable as input
    usage: dict[str, int | None]             # input_tokens, output_tokens, cached_input_tokens, reasoning_tokens
    status: str                              # completed | incomplete | failed | in_progress
    incomplete_reason: str | None = None
    response_id: str | None = None
    model: str | None = None                 # the version the provider SERVED

    @property
    def complete(self) -> bool:
        return self.status == "completed"


def function_tool(name: str, description: str, parameters: dict) -> dict:
    """A function tool in the shape this door sends."""
    return {"type": "function", "name": name, "description": description, "parameters": parameters, "strict": False}


def message(role: str, text: str) -> dict:
    """An input item carrying text under a role: user | developer | assistant."""
    return {"role": role, "content": [{"type": "input_text" if role != "assistant" else "output_text", "text": text}]}


def tool_output(call_id: str, output: str) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": output}


def _usage_of(response) -> dict[str, int | None]:
    u = getattr(response, "usage", None)
    if u is None:
        return {"input_tokens": None, "output_tokens": None, "cached_input_tokens": None, "reasoning_tokens": None}
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None)
    reasoning = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None)
    return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
            "cached_input_tokens": cached, "reasoning_tokens": reasoning}


def turn_of(response) -> ModelTurn:
    """A ModelTurn read off a Responses API response object."""
    output = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
    texts = [c.text for item in response.output if getattr(item, "type", None) == "message"
             for c in getattr(item, "content", []) if getattr(c, "type", None) == "output_text"]
    calls = [ToolCall(item.call_id, item.name, item.arguments) for item in response.output
             if getattr(item, "type", None) == "function_call"]
    incomplete = getattr(response, "incomplete_details", None)
    return ModelTurn(text="".join(texts) or None, tool_calls=calls, output=output, usage=_usage_of(response),
                     status=str(getattr(response, "status", None) or "completed"),
                     incomplete_reason=getattr(incomplete, "reason", None) if incomplete else None,
                     response_id=getattr(response, "id", None), model=getattr(response, "model", None))


async def respond(
    *,
    model: str,
    instructions: str,
    input_items: list[dict],
    tools: list[dict] | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int = 4096,
    tool_choice: str | dict | None = None,
) -> ModelTurn:
    """One request to the Responses API, stateless: nothing is stored provider-side,
    and the reasoning comes back encrypted so the caller can replay it. A provider
    error is raised as it is; this door translates nothing."""
    client = get_openai_client()
    if client is None:
        raise ProviderUnavailable("OPENAI_API_KEY is not configured — no model call can be made")
    kwargs: dict[str, Any] = {
        "model": model, "instructions": instructions, "input": input_items, "store": False,
        "max_output_tokens": max_output_tokens, "include": ["reasoning.encrypted_content"],
    }
    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}
    response = await client.responses.create(**kwargs)
    return turn_of(response)
