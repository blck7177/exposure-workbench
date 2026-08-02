"""Context measurement (V3-B0) — how big the prompt actually is.

Observation first, policy second. Nothing here decides anything; it counts, and
B1's refusal and B3's go/no-go on summarisation both read the numbers it records.
Building compaction before knowing whether a real session ever approaches the
window would have been a guess wearing an implementation.

Two details that are easy to get wrong and change the answer:

  * TOOL SCHEMAS COUNT. They are passed to the provider on every single request
    and appear nowhere in `messages`, so counting messages alone under-reports
    the prompt by a fixed amount that is larger than most conversations.
  * THE ENCODING IS PINNED, NOT LOOKED UP. tiktoken.encoding_for_model does not
    know this project's model and raises; more importantly, a lookup means the
    numbers stop being comparable the moment the model changes. o200k_base is
    what the counts mean, and if the model moves far enough for that to be wrong,
    that is a decision to take deliberately rather than to absorb silently.

The encoder is fetched once per process. tiktoken downloads its BPE table over
the network on first use, so the images bake it at build time (see
infra/Dockerfile.api); if that bake is missing the failure is a slow first
request, which is exactly the kind of thing this module exists to notice.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

import tiktoken

logger = logging.getLogger(__name__)

ENCODING = "o200k_base"


@lru_cache(maxsize=1)
def _encoder():
    return tiktoken.get_encoding(ENCODING)


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text or ""))


def count_prompt(messages: list[dict], tools: list[dict] | None = None) -> int:
    """Approximate prompt size for one provider call, tool schemas included.

    Approximate on purpose: the exact figure depends on provider-side framing
    this code cannot see. It is consistent across turns and across sessions,
    which is what a budget and a trend line both need.
    """
    total = 0
    for m in messages:
        total += count_tokens(m.get("content") or "")
        calls = m.get("tool_calls")
        if calls:
            total += count_tokens(json.dumps(calls, default=str))
        # Role, name and the provider's per-message framing. Four is the figure
        # OpenAI documents for its chat encodings and is close enough for a
        # measurement whose purpose is "are we anywhere near the ceiling".
        total += 4
    if tools:
        total += count_tokens(json.dumps(tools, default=str))
    return total
