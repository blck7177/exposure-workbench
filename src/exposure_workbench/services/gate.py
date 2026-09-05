"""The gate (V24): three lookups against the session ledger, and nothing else.

WHAT IT CHECKS — and what it does not. It does not check whether a figure is
right: no figure the reader sees was written by the model, so there is
nothing to check. It checks whether the model POINTED right:

    G1  every id in the answer is on this session's ledger          not_on_ledger
    G2  the layout admits the fact's kind: a cell is a standalone
        scalar, a chart is a series, an inline fact stands alone, and
        `f_…@period` addresses a point the series actually holds; a
        cite is any fact the block rests on                           kind_does_not_fit / not_standalone /
                                                                      unknown_point
        (a pointer the model wrapped in the old object decoration is
        NORMALISED to the pointer, not refused: services/answer.WRAPPED)
    G3  the prose carries nothing the ledger cannot account for:
        every digit token resolves — to a fact it equals (exactly, at
        the written precision, under a money scale), to a fact's
        identity field (an as-of, a period, a window, a parameter),
        or to a passage the block cites; a name the ledger holds is
        not written as words; a pointer has a space before it; a
        quotation is verbatim in a cited passage                                                       unsourced_figure / id_in_prose /
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


def _core(token: str) -> str:
    """A number stripped of sign, currency, separators and percent — what two
    spellings of one figure share ("+100bp" and "100bp"; "5%" and "5")."""
    return re.sub(r"[+\-−$,%\s]", "", token or "").lower()


def _compound(measures: set[str]) -> list[str]:
    return sorted(m for m in measures if isinstance(m, str) and any(c in m for c in _NAME_MARKS))


# ── the pass ──────────────────────────────────────────────────────────────────

def check(blocks, ledger: Ledger, question: str | None = None) -> Verdict:
    """`question` is the user's message this turn answers: a number the user
    wrote ("100bp", "5%", "half") is the question's, and a sentence that repeats
    it rests on the question — a lookup over its tokens, not an exemption class.
    The first live round refused "+100bp" as unsourced in the answer to "rates
    back up 100bp"."""
    v = Verdict()
    asked = {_core(t["token"]) for t in A.tokens_in(question or "")}
    shape = A.validate_shape(blocks)
    if shape:
        v.error, v.problems = "malformed_answer", shape
        v.detail = ("an answer is a list of blocks: paragraph (runs of strings and {fact: id}), "
                    "table (rows of fact ids), chart (kind + a series fact). Each problem names its block")
        return v

    refs = A.refs_in(blocks)
    v.refs = list(dict.fromkeys(A.split_point(t)[0] for _, t, _ in refs))

    # G1 — on the ledger
    off = [(at, A.split_point(t)[0]) for at, t, _ in refs if not ledger.holds(A.split_point(t)[0])]
    if off:
        v.error = "not_on_ledger"
        v.problems = [{"at": at, "id": fid, "reason": "not_on_ledger"} for at, fid in off]
        v.detail = ("every id an answer points at is a fact a tool result showed this session "
                    "(an f_… id from a `facts` block). These are not — use one you were shown, or read it. "
                    "A figure a passage states is not a fact of its own: write it in the prose and put the "
                    "passage in `cites`; a point of a series is computed from the series, not pointed at")
        return v

    # G2 — the layout admits the kind
    for at, token, role in refs:
        fid, period = A.split_point(token)
        kind = ledger.kind(fid)
        if period is not None:
            # An address into a series: the point has to be one the series holds.
            if kind != F.SERIES:
                v.problems.append({"at": at, "id": token, "reason": "kind_does_not_fit", "kind": kind,
                                   "detail": "f_…@period addresses one point of a SERIES; this fact is not one"})
            else:
                held = [str(p[0]) for p in (ledger.by_id[fid].get("points") or [])]
                if period not in held:
                    near = [p for p in held if p[:4] == period[:4]] or held
                    v.problems.append({"at": at, "id": token, "reason": "unknown_point", "period": period,
                                       "available": near[:12], "truncated": len(near) > 12,
                                       "detail": "this series holds no point at that period; `available` lists "
                                                 "the periods it does hold"})
            continue
        if role == A.CELL and kind != F.SCALAR:
            v.problems.append({"at": at, "id": fid, "reason": "kind_does_not_fit", "kind": kind,
                               "detail": "a table cell is a scalar fact; a series, a passage, an absence or a task goes in a paragraph"})
        elif role == A.CHART and kind != F.SERIES:
            v.problems.append({"at": at, "id": fid, "reason": "kind_does_not_fit", "kind": kind,
                               "detail": "a chart draws a series fact"})
        elif role in (A.CELL, A.INLINE) and not ledger.standalone(fid):
            rec = ledger.by_id[fid]
            v.problems.append({"at": at, "id": fid, "reason": "not_standalone",
                               "detail": (rec.get("params") or {}).get("reason")
                               or "this figure is not determined on its own (the row says so); point at the figure that is"})
    if v.problems:
        reasons = [p["reason"] for p in v.problems]
        v.error = next(r for r in ("kind_does_not_fit", "unknown_point", "not_standalone") if r in reasons)
        v.detail = "a pointer's place in the answer must fit what the fact is"
        return v

    # G3 — the prose
    names = _compound(ledger.measures)
    for i, prose, cites in A.prose_by_block(blocks):
        at = f"blocks[{i}]"
        for m in A.GLUED.finditer(prose):
            v.problems.append({"at": at, "reason": "pointer_not_separated", "id": m.group(0),
                               "detail": "a fact id is read as a pointer only when a space (or a mark) "
                                         "comes before it; this one is glued to the word in front of it"})
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
            if _core(tok) in asked:
                v.links[(i, t["start"])] = {"to": "question", "ids": [], "as_written": tok}
                continue
            v.problems.append({"at": at, "reason": "unsourced_figure", "figure": tok, "detail": _FIX})
        passages = [ledger.passages[c] for c in cites if c in ledger.passages]
        for p in verify_quotes(prose, passages):
            v.problems.append({"at": at, **p, "reason": "unverified_quote"})
    if v.problems:
        reasons = {p["reason"] for p in v.problems}
        v.error = ("pointer_not_separated" if "pointer_not_separated" in reasons else
                   "unsourced_figure" if "unsourced_figure" in reasons else
                   "id_in_prose" if "id_in_prose" in reasons else
                   "name_in_prose" if "name_in_prose" in reasons else "unverified_quote")
        v.detail = {"pointer_not_separated": "put a space before the fact id so it reads as a pointer",
                    "unsourced_figure": _FIX,
                    "id_in_prose": "a fact's id (f_…) is written into the sentence and becomes the figure; "
                                   "any other id belongs in `cites`, never in a sentence",
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
    # a figure is counted once per place it stands — a pointer, or a written
    # number — not once per fact that shares the written value
    pointed = [f for _, f, role in A.refs_in(blocks) if role in (A.INLINE, A.CELL, A.CHART) and ledger.kind(f) in (F.SCALAR, F.SERIES)]
    written = [l for l in verdict.links.values() if l["to"] == "fact"]
    return {
        "blocks": filled,
        "text": A.prose_of(filled),
        "citations": facts_used,
        "verified": {
            "figures": len(pointed) + len(written), "sources": len(passages),
            "matches": [{"label": r.get("measure"), "value": r.get("value"), "unit_class": r.get("unit"),
                         "source_id": r["id"], "subject": r.get("subject"), "as_of": r.get("as_of")}
                        for r in figures],
        },
    }
