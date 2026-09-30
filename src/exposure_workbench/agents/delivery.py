"""Record the actual prompt supplied to a completion, including STATE and PRIOR.

The ledger records existence; this collector records receipt. `facts` contains
rendered row headers outside assistant messages, while `mentioned` also keeps
bare pointers and model-authored mentions. Page ranges are separate from ids:
seeing a series id is not evidence of receiving all its points. The legacy
`read` counters still measure content appended since the previous completion.
"""

from __future__ import annotations

import json
import re

_FACT_ID = re.compile(r"\bf_[A-Za-z0-9_]{4,}\b")
_PULL_ID = re.compile(r"\br_[A-Za-z0-9]{6,}\b")
_ROW = re.compile(r'(?:^|[\n"]|\\n)\[(f_[A-Za-z0-9_]{4,})\]\s')


class Delivered:
    """One completion's reading, reset after it is recorded."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.chars = 0
        self.results = 0
        self.facts: set[str] = set()
        self.pulls: set[str] = set()
        self.mentioned: set[str] = set()
        self.ranges: list[dict] = []
        self.prompt_chars = 0

    def add(self, msg: dict) -> None:
        content = str(msg.get("content") or "")
        self.chars += len(content)
        self.results += int(msg.get("role") == "tool")
        self.mentioned.update(_FACT_ID.findall(content))
        if msg.get("role") != "assistant":
            self.facts.update(_ROW.findall(content))
        self.pulls.update(_PULL_ID.findall(content))

    def project(self, messages: list[dict]) -> None:
        """Record the assembled prompt, including replaced STATE and initial PRIOR.
        Mentioning an id is not delivery of its row or of an entire series.
        """
        self.facts.clear()
        self.pulls.clear()
        self.mentioned.clear()
        self.ranges = []
        self.prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        for msg in messages:
            content = str(msg.get("content") or "")
            self.mentioned.update(_FACT_ID.findall(content))
            if msg.get("role") == "assistant":
                continue
            self.facts.update(_ROW.findall(content))
            self.pulls.update(_PULL_ID.findall(content))
            # S1's initial page is in the replaced STATE block; subsequent
            # pages are tool results. Record both ranges as actually delivered.
            # Initial bound inputs also have explicit preview ranges. They
            # are runtime-generated in their own block, apart from TASK text.
            for block in re.findall(r'<input_evidence[^>]*>\n([^\n]+)\n', content):
                try:
                    pages = json.loads(block)
                except (ValueError, TypeError):
                    continue
                for page in pages if isinstance(pages, list) else []:
                    if isinstance(page, dict) and page.get("id") and "shown" in page and "total" in page:
                        self.ranges.append({k: page[k] for k in ("id", "shown", "total")})
            state_page = (msg.get("role") == "system" and content.startswith("<state ")
                          and content.endswith("\n</state>"))
            if msg.get("role") == "tool" or state_page:
                try:
                    body = content.split("\n", 1)[1].rsplit("\n</state>", 1)[0] if state_page else content
                    payload = json.loads(body)
                except (ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("id") and "shown" in payload and "total" in payload:
                    self.ranges.append({k: payload[k] for k in ("id", "shown", "total")})

    def note(self) -> dict | None:
        """The llm_call row's args, or None when nothing was read since the last one."""
        if not self.chars and not self.prompt_chars:
            return None
        out: dict = {"read": {"chars": self.chars, "results": self.results}}
        out["delivered"] = {"facts": sorted(self.facts), "pulls": sorted(self.pulls),
                            "mentioned": sorted(self.mentioned), "ranges": self.ranges,
                            "prompt_chars": self.prompt_chars}
        return out
