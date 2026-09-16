#!/usr/bin/env python3
"""Exit 0 when the battery's provider will answer, 3 when the account has no
credits (429 insufficient_quota), 1 on anything else. One completion of a few
tokens through the project's own client; nothing is written anywhere."""
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv(".env", override=True)
sys.path.insert(0, "src")
from exposure_workbench.llm import client as llm_client  # noqa: E402


async def main() -> int:
    try:
        _, _, usage = await llm_client.chat_with_tools(
            messages=[{"role": "user", "content": "Reply with the word ok."}], tools=None)
    except Exception as e:  # noqa: BLE001
        body = str(e)
        if "insufficient_quota" in body or "credit_balance_exhausted" in body:
            print(f"no credits: {type(e).__name__}: {body[:160]}")
            return 3
        print(f"provider error: {type(e).__name__}: {body[:300]}")
        return 1
    print(f"credits ok: {usage.get('model')} {usage.get('prompt_tokens')}/{usage.get('completion_tokens')} tok")
    return 0

raise SystemExit(asyncio.run(main()))
