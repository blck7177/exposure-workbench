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

    response = await client.chat.completions.create(
        model=effective_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    usage = response.usage
    return (
        content,
        response.model,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )
