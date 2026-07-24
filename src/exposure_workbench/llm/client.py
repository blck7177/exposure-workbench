"""OpenAI async client wrapper."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_client = None


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
            logger.warning("OPENAI_API_KEY not set — LLM calls will use mock output")
            return None
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
        return _client
    except ImportError:
        logger.warning("openai package not installed — LLM calls will use mock output")
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


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> tuple[str | None, list[dict] | None, dict]:
    """One tool-calling turn. Returns (content, tool_calls, usage).

    tool_calls are returned as plain dicts in the exact shape the API accepts back
    in a subsequent assistant message, so the caller can append and continue.
    """
    from exposure_workbench.app_state.settings import get_settings

    settings = get_settings()
    client = get_openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not configured — the research session cannot run.")

    response = await client.chat.completions.create(
        model=model or settings.openai_model,
        messages=messages,          # type: ignore[arg-type]
        tools=tools,                # type: ignore[arg-type]
        max_completion_tokens=max_tokens,
    )
    choice = response.choices[0].message
    tool_calls = None
    if choice.tool_calls:
        tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in choice.tool_calls
        ]
    usage = response.usage
    usage_dict = {
        "prompt_tokens": usage.prompt_tokens if usage else 0,
        "completion_tokens": usage.completion_tokens if usage else 0,
    }
    return choice.content, tool_calls, usage_dict


async def chat_complete(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> tuple[str, str, int, int]:
    """
    Call OpenAI chat completion.

    Returns: (content, model_name, prompt_tokens, completion_tokens)
    Raises on API errors.
    """
    from exposure_workbench.app_state.settings import get_settings
    settings = get_settings()
    effective_model = model or settings.openai_model

    client = get_openai_client()
    if client is None:
        raise RuntimeError("OpenAI client not available")

    # gpt-5.x models take max_completion_tokens and only the default temperature.
    response = await client.chat.completions.create(
        model=effective_model,
        messages=messages,  # type: ignore[arg-type]
        max_completion_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    usage = response.usage
    return (
        content,
        response.model,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )
