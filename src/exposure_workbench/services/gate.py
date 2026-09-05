"""The gate (V24): three lookups against the session ledger, and nothing else.

WHAT IT CHECKS — and what it does not. It does not check whether a figure is
right: no figure the reader sees was written by the model, so there is
nothing to check. It checks whether the model POINTED right:

    G1  every id in the answer is on this session's ledger          not_on_ledger
    G2  the layout admits the fact's kind: a cell is a standalone
        scalar, a chart is a series, a cite is a passage, an inline
        fact stands alone                                             kind_does_not_fit / not_standalone
    G3  the prose carries nothing the ledger cannot account for:
        every digit token resolves — to a fact it equals (exactly, at
        the written precision, under a money scale), to a fact's
        identity field (an as-of, a period, a window, a parameter),
        or to a passage the block cites; a name the ledger holds is
        not written as words; a quotation is verbatim in a cited
        passage                                                       unsourced_figure / id_in_prose /
                                                                      name_in_prose / unverified_quote

Every check is a dictionary lookup on the ledger (services/ledger.py). The
one regular expression on the path FINDS tokens (services/answer.tokens_in);
it decides nothing. There is no list of digit classes exempt from the rule:
a date is a fact's as_of, a window is a fact's window, a confidence level is
a fact's parameter, a form name is a passage's — and a token the ledger
cannot account for is refused with the three ways out: compute it, cite the
passage that states it, or drop it (IMPLEMENTATION_PLAN_V24 §6.2, §7).

Both exits resolve here: respond (tools/meta_tools.py) and submit_brief
(tools/research_tools.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from exposure_workbench.services import answer as A
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger

# ── quotations (unchanged from the V15 resolver) ──────────────────────────────
_QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("‘", "’"))
_MIN_QUOTED_WORDS = 4
_WS = re.compile(r"\s+")
_TYPOGRAPHIC = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", " ": " "})


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


# ── the verdict ───────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    problems: list[dict] = field(default_factory=list)
    error: str | None = None
    detail: str | None = None
    refs: list[str] = field(default_factory=list)                     # every fact id pointed at, in order
    links: dict[tuple[int, int], dict] = field(default_factory=dict)  # (block, token start) -> {to, ids, as_written}

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_refusal(self) -> dict:
        return {"error": self.error, "problems": self.problems, "detail": self.detail}


_FIX = ("a figure in prose is either a fact on the ledger — point at it as {fact: id}, or it is "
        "linked for you when it equals one — a figure a cited passage states, or a result "
        "compute has not produced yet. Compute it, cite the passage that states it, or drop it")

# Names the ledger holds that are unmistakably the desk's, not words: only a
# measure with a separator is looked for, so `capex` in a sentence is a word.
_NAME_MARKS = (".", ":", "@")


def _compound(measures: set[str]) -> list[str]:
    return sorted(m for m in measures if isinstance(m, str) and any(c in m for c in _NAME_MARKS))


# ── the pass ──────────────────────────────────────────────────────────────────

def check(blocks, ledger: Ledger) -> Verdict:
    v = Verdict()
    shape = A.validate_shape(blocks)
    if shape:
        v.error, v.problems = "malformed_answer", shape
        v.detail = ("an answer is a list of blocks: paragraph (runs of strings and {fact: id}), "
                    "table (rows of fact ids), chart (kind + a series fact). Each problem names its block")
        return v

    refs = A.refs_in(blocks)
    v.refs = list(dict.fromkeys(fid for _, fid, _ in refs))

    # G1 — on the ledger
    off = [(at, fid) for at, fid, _ in refs if not ledger.holds(fid)]
    if off:
        v.error = "not_on_ledger"
        v.problems = [{"at": at, "id": fid, "reason": "not_on_ledger"} for at, fid in off]
        v.detail = ("every id an answer points at is a fact a tool result showed this session "
                    "(an f_… id from a `facts` block). These are not — use one you were shown, or read it")
        return v

    # G2 — the layout admits the kind
    for at, fid, role in refs:
        kind = ledger.kind(fid)
        if role == A.CELL and kind != F.SCALAR:
            v.problems.append({"at": at, "id": fid, "reason": "kind_does_not_fit", "kind": kind,
                               "detail": "a table cell is a scalar fact; a series, a passage, an absence or a task goes in a paragraph"})
        elif role == A.CHART and kind != F.SERIES:
            v.problems.append({"at": at, "id": fid, "reason": "kind_does_not_fit", "kind": kind,
                               "detail": "a chart draws a series fact"})
        elif role == A.CITE and kind != F.PASSAGE:
            v.problems.append({"at": at, "id": fid, "reason": "kind_does_not_fit", "kind": kind,
                               "detail": "cites are passage facts (filing text, web sources); a figure is pointed at inline"})
        elif role in (A.CELL, A.INLINE) and not ledger.standalone(fid):
            rec = ledger.by_id[fid]
            v.problems.append({"at": at, "id": fid, "reason": "not_standalone",
                               "detail": (rec.get("params") or {}).get("reason")
                               or "this figure is not determined on its own (the row says so); point at the figure that is"})
    if v.problems:
        v.error = "kind_does_not_fit" if any(p["reason"] == "kind_does_not_fit" for p in v.problems) else "not_standalone"
        v.detail = "a pointer's place in the answer must fit what the fact is"
        return v

    # G3 — the prose
    names = _compound(ledger.measures)
    for i, prose, cites in A.prose_by_block(blocks):
        at = f"blocks[{i}]"
        written = sorted({n for n in names if n in prose})
        if written:
            v.problems.append({"at": at, "reason": "name_in_prose", "names": written,
                               "detail": "a measure's name is the name OF a figure, not a word: point at the fact "
                                         "{fact: id} and the reader is shown its value and what it is"})
        for t in A.tokens_in(prose):
            tok, kind = t["token"], t["kind"]
            if kind == "id":
                if F.is_fact_id(tok) and ledger.holds(tok):
                    v.links[(i, t["start"])] = {"to": "fact", "ids": [tok], "as_written": tok}
                    continue
                v.problems.append({"at": at, "reason": "id_in_prose", "id": tok,
                                   "detail": "an id is a pointer, not a word: a fact goes in {fact: id}, a passage in cites"})
                continue
            ids: list[str] = []
            if kind == "num":
                ids = ledger.resolve_number(tok)
            if not ids:
                ids = ledger.resolve_identity(tok)
            if ids:
                v.links[(i, t["start"])] = {"to": "fact", "ids": ids, "as_written": tok}
                continue
            pids = ledger.resolve_in_passages(tok, cites)
            if pids:
                v.links[(i, t["start"])] = {"to": "passage", "ids": pids, "as_written": tok}
                continue
            v.problems.append({"at": at, "reason": "unsourced_figure", "figure": tok, "detail": _FIX})
        passages = [ledger.passages[c] for c in cites if c in ledger.passages]
        for p in verify_quotes(prose, passages):
            v.problems.append({"at": at, **p, "reason": "unverified_quote"})
    if v.problems:
        reasons = {p["reason"] for p in v.problems}
        v.error = ("unsourced_figure" if "unsourced_figure" in reasons else
                   "id_in_prose" if "id_in_prose" in reasons else
                   "name_in_prose" if "name_in_prose" in reasons else "unverified_quote")
        v.detail = {"unsourced_figure": _FIX,
                    "id_in_prose": "ids belong in {fact: id} or in cites, never in a sentence",
                    "name_in_prose": "a name the ledger holds is written as {fact: id}, not as words",
                    "unverified_quote": ("quotation marks say these words appear verbatim in a passage this "
                                         "block cites. Reproduce the source wording and cite the passage, or "
                                         "drop the marks")}[v.error]
        return v
    return v


def accepted(blocks, verdict: Verdict, ledger: Ledger) -> dict:
    """What an exit returns when the verdict is clean: the blocks filled, the
    prose, the facts the answer rests on, and what was verified — one record
    of what the gate found, made at the moment it decided."""
    filled = A.rendered(blocks, ledger.by_id, verdict.links)
    linked = [fid for l in verdict.links.values() for fid in l["ids"]]
    facts_used = list(dict.fromkeys([*verdict.refs, *linked]))
    figures = [ledger.by_id[f] for f in facts_used if ledger.kind(f) in (F.SCALAR, F.SERIES)]
    passages = [f for f in facts_used if ledger.kind(f) == F.PASSAGE]
    return {
        "blocks": filled,
        "text": A.prose_of(filled),
        "citations": facts_used,
        "verified": {
            "figures": len(figures), "sources": len(passages),
            "matches": [{"label": r.get("measure"), "value": r.get("value"), "unit_class": r.get("unit"),
                         "source_id": r["id"], "subject": r.get("subject"), "as_of": r.get("as_of")}
                        for r in figures],
        },
    }
