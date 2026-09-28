"""What a completion was actually handed (V2 P2, design v0.4 §07: "facts/ledger 的
存在与某 actor 的实际收到分别记录").

The ledger says what a turn PUT ON THE RECORD; it does not say what the model
read. Until V2 the llm_call row carried only how many characters and how many
tool results the completion read (V36.1). It now carries the ids inside them —
every fact row (`f_…`) and every call (`r_…`) named in the content appended
since the last completion — so a round can tell "on the ledger" from "handed to
the lead", which is the difference between a figure that was available and a
figure that was delivered (a gap of type delivery_missing, P3).

Read off the appended content by pattern, not off the ledger: what the model was
shown is exactly the text that went into the messages array, and the same
pattern that finds an id in a reply finds it here.
"""

from __future__ import annotations

import re

_FACT_ID = re.compile(r"\bf_[A-Za-z0-9_]{4,}\b")
_PULL_ID = re.compile(r"\br_[A-Za-z0-9]{6,}\b")


class Delivered:
    """One completion's reading, reset after it is recorded."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.chars = 0
        self.results = 0
        self.facts: set[str] = set()
        self.pulls: set[str] = set()

    def add(self, msg: dict) -> None:
        content = str(msg.get("content") or "")
        self.chars += len(content)
        self.results += int(msg.get("role") == "tool")
        self.facts.update(_FACT_ID.findall(content))
        self.pulls.update(_PULL_ID.findall(content))

    def note(self) -> dict | None:
        """The llm_call row's args, or None when nothing was read since the last one."""
        if not self.chars:
            return None
        out: dict = {"read": {"chars": self.chars, "results": self.results}}
        if self.facts or self.pulls:
            out["delivered"] = {"facts": sorted(self.facts), "pulls": sorted(self.pulls)}
        return out
