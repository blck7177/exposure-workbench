"""V15-S4. The one resolver: does every pointer in an answer land on the table?

Six invariants, each a lookup, none a judgement about content:

    V1 shape      the block grammar (schema first; answer_blocks.validate_shape
                  for callers that bypass it) and the one text rule — no digits
    V2 source     every ref is on this session's table
    V3 name       every slot's name is one its ref holds on the table
    V5 quotes     words in quotation marks appear verbatim in the block's cites
    V6 kind       a trend's ref is a series, an absence's ref is a refusal, an
                  action's ref is delegated work

(V4, the text rule, is inside V1.) `not_alone` needs no check here: the table
builder never put a collinear coefficient on the table, so its name is unknown
like any other name that was never shown.

There is deliberately nothing else. No search for which other ref holds a value
(values are not written), no arithmetic over cited values to suggest a call, no
tolerance. A refusal names the block, the reason, and — for a name — the names
that ref does hold, which is the whole way forward.

Every exit resolves here: respond (tools/meta_tools.py) and submit_brief
(tools/research_tools.py) call `resolve`; test_one_resolver pins that no second
implementation exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services import table as tb

# The names a refusal lists, at most. A run holds ~235; the model reads the
# list once and picks.
_MAX_NAMES = 80


@dataclass
class Verdict:
    problems: list[dict] = field(default_factory=list)
    error: str | None = None
    detail: str | None = None
    resolved: list[ab.Resolved] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    # The refs that are evidence — everything but delegated work. An action
    # block points at a task id, which the reader can follow to the run, not
    # to a row of evidence; listing it among the citations would send the
    # evidence drawer to a row that does not exist.
    citations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_refusal(self) -> dict:
        return {"error": self.error, "problems": self.problems, "detail": self.detail}


# ── V5: quotation marks ───────────────────────────────────────────────────────
_QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("‘", "’"))
_MIN_QUOTED_WORDS = 4
_WS = re.compile(r"\s+")
_TYPOGRAPHIC = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                              "–": "-", "—": "-", " ": " "})


def _normalise(text: str) -> str:
    return _WS.sub(" ", (text or "").translate(_TYPOGRAPHIC)).strip().lower()


def quoted_spans(text: str) -> list[str]:
    out: list[str] = []
    for open_q, close_q in _QUOTE_PAIRS:
        pattern = (re.escape(open_q) + r"([^" + re.escape(open_q + close_q) + r"]+)" + re.escape(close_q)
                   if open_q != close_q else
                   re.escape(open_q) + r"([^" + re.escape(open_q) + r"]+)" + re.escape(close_q))
        for m in re.finditer(pattern, text or ""):
            span = m.group(1).strip()
            if len(span.split()) >= _MIN_QUOTED_WORDS:
                out.append(span)
    return out


def verify_quotes(text: str, passages: list[str]) -> list[dict]:
    haystack = " … ".join(_normalise(p) for p in passages)
    return [{"quote": span, "reason": "not_in_cited_passages"}
            for span in quoted_spans(text) if _normalise(span) not in haystack]


# ── the pass ──────────────────────────────────────────────────────────────────

def resolve_against(blocks, table: tb.Table) -> Verdict:
    """Pure: the answer against a table already loaded."""
    v = Verdict()

    shape = ab.validate_shape(blocks)
    if shape:
        v.error, v.problems = "malformed_answer", shape
        v.detail = ("an answer is a list of blocks; a figure is a slot {ref, name}; text carries "
                    "no digits. Each problem names its block")
        return v

    v.refs = ab.refs_in(blocks)
    off = [r for r in v.refs if not table.holds(r)]
    if off:
        v.error = "not_on_table"
        v.problems = [{"id": r, "reason": "not_on_table"} for r in off]
        v.detail = ("every id an answer points at must be on the table a tool returned this "
                    "session. These are not — use an id from a result you have, or read it")
        return v

    for at, slot in ab.slots_in(blocks):
        q = table.quantity(slot["ref"], slot["name"])
        if q is None:
            names = table.names(slot["ref"])
            v.problems.append({
                "at": at, "ref": slot["ref"], "name": slot["name"], "reason": "unknown_name",
                "available": names[:_MAX_NAMES], "truncated": len(names) > _MAX_NAMES,
                "detail": ("use one of the names this id holds on the table"
                           if names else "this id holds no figures; it can be cited, not slotted"),
            })
            continue
        v.resolved.append(ab.Resolved(q.source_id, q.label, q.value, q.unit_class))
    if v.problems:
        v.error = "unknown_name"
        v.detail = "each slot names a figure by the name the table gave it; `available` lists them"
        return v

    for i, (at, prose) in enumerate(ab.text_by_block(blocks)):
        block = blocks[i]
        cites = [c for c in (block.get("cites") or []) if isinstance(c, str)]
        passages = [table.passages[c] for c in cites if c in table.passages]
        for p in verify_quotes(prose, passages):
            v.problems.append({"at": at, **p})
    if v.problems:
        v.error = "unverified_quote"
        v.detail = ("quotation marks say these words appear verbatim in a passage this block "
                    "cites. Reproduce the source wording and cite the passage, or drop the marks")
        return v

    v.citations = [r for r in v.refs if table.kind(r) not in ab.TASK_KINDS]
    wanted = {"series": ab.SERIES_KINDS, "absence": ab.ABSENCE_KINDS, "task": ab.TASK_KINDS}
    for at, need, ref in ab.assertions_in(blocks):
        if table.kind(ref) not in wanted[need]:
            v.problems.append({"at": at, "ref": ref, "reason": f"not_a_{need}",
                               "kind": table.kind(ref)})
    if v.problems:
        v.error = "unsupported_assertion"
        v.detail = ("a trend or chart points at a series; an absence at the row a refused read "
                    "minted; an action at work this turn started")
        return v
    return v


async def resolve(db: AsyncSession, session_id: str, blocks) -> Verdict:
    """The answer against the session's table."""
    return resolve_against(blocks, await tb.load(db, session_id))


def accepted(blocks, verdict: Verdict) -> dict:
    """What an exit returns when the verdict is clean."""
    filled = ab.rendered(blocks, verdict.resolved)
    return {
        "blocks": filled,
        "text": ab.prose_of(filled),
        "citations": list(verdict.citations),
        "verified": {
            "figures": len(verdict.resolved), "sources": len(verdict.citations),
            "matches": [{"label": r.label, "value": r.value, "unit_class": r.unit_class,
                         "source_id": r.ref} for r in verdict.resolved],
        },
    }
