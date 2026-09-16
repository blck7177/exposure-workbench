#!/usr/bin/env python3
"""conversation_battery.py with the model swapped, and nothing in the tree changed.

    python battery_with_model.py gpt-5.6-sol <conversation_battery args...>

The battery module loads .env with override=True at import, so OPENAI_MODEL set
beforehand would be overwritten; it is set after the import instead, and the
lazily built settings are reset (main() resets them again in --fixture mode).

gpt-5.6-* on /v1/chat/completions refuses function tools unless
reasoning_effort is 'none' (400: "Function tools with reasoning_effort are not
supported ... set reasoning_effort to 'none'"). gpt-5.4-mini on this same path
already runs with zero reasoning tokens (probe, 2026-09-16), so 'none' is the
like-for-like setting. It is added only for gpt-5.6-* and only when absent.
"""
import asyncio
import importlib.util
import os
import sys

MODEL, ARGV = sys.argv[1], sys.argv[2:]
spec = importlib.util.spec_from_file_location("conversation_battery", "scripts/conversation_battery.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

os.environ["OPENAI_MODEL"] = MODEL
from exposure_workbench.app_state import settings as _sm  # noqa: E402
_sm._settings = None

from openai.resources.chat.completions import AsyncCompletions  # noqa: E402
_create = AsyncCompletions.create


async def _create_with_effort(self, *args, **kwargs):
    if str(kwargs.get("model", "")).startswith("gpt-5.6") and "reasoning_effort" not in kwargs:
        kwargs["reasoning_effort"] = "none"
    return await _create(self, *args, **kwargs)

AsyncCompletions.create = _create_with_effort
raise SystemExit(asyncio.run(cb.main(ARGV)))
