"""The answer check (V33): a natural-language answer against the session ledger.

WHY THIS EXISTS. The exit it replaces (services/claims.py) asked the model to
type its own assertions — eleven relations over fact ids, `{cN}` placeholders
kept in step with a claims list by hand — and the 20-question round
(docs/spikes/v33) showed what that bought: 61 respond calls, 42 refused, and
twelve of the nineteen accepted answers false to a reader anyway, because the
gate checked the pointers and never the sentence. Q08 stated two superlatives
backwards over six legal `series` claims; Q17 shifted ten figures onto the
wrong companies when it renumbered claims; Q14 filled a date slot with a depth.

Here the model writes prose. This module reads it the way the reader will:

    G1  every figure POINTS: it is written as the desk showed it, followed by
        the id the desk showed it under — `16.0% [f_2592baab170e]` — and the
        check is a lookup on that id: the id is on the ledger, the fact holds
        the figure at the written precision          not_on_ledger / mark_mismatch
    G2  a bare number is one of three things and nothing else: a fact's own
        date/window/parameter, a figure a quoted passage states, or the user's
        own number; a bare number the ledger holds as a figure is refused with
        the ids it was shown under                   unpointed_figure / unsourced_figure
        (V34 inferred which fact a bare number meant from the sentence's words;
        round G refused 51 figures it could not place — the subject was in the
        previous sentence, or ten subjects were in this one — and refused true
        sentences to do it. Nothing here infers identity now: the writer points.)
    G3  the sentence around a figure agrees with the figure's identity:
          a superlative sits on a fact that carries a place in an ordering
          a change joins two readings of one measure of one subject, or one
            change node, and points the way the values moved
          a comparison joins two figures of one unit
          a tier word (warning, breach, limit) sits beside the tier it names
          a date word (started, troughed, as of) is followed by a date
          a company named in the sentence is the figure's company
                                                    superlative_without_rank / change_conflict /
                                                    tier_mismatch / date_expected / subject_mismatch /
                                                    measure_mismatch
    G4  quotation marks hold a passage's own words   unverified_quote
    G5  `[table: node]` / `[chart: node]` name a node whose facts are on the
        ledger; `[f_…]` names a fact on it            unknown_node / not_on_ledger

Every check is a lookup on the ledger (services/ledger.py) or a word from a
short closed list; nothing here judges meaning beyond what a fact's own fields
can settle. Problems are reported ALL AT ONCE, each with the way out. The
render (`accepted`) puts the ledger's value and identity where the number
stood, in the block shape the web already reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from exposure_workbench.services import answer as A
from exposure_workbench.services import facts as F
from exposure_workbench.services.gate import _core, quoted_spans, _normalise
from exposure_workbench.services.ledger import Ledger

# ── the marks a writer may put in prose ──────────────────────────────────────
MARK_BLOCK = re.compile(r"\[(table|chart):\s*([A-Za-z_][A-Za-z0-9_]*)\]")
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z“\"(\[])")
# THE POINTER A FIGURE CARRIES: the id the desk showed the figure under, in
# brackets after it. A unit tail the desk's own display puts after the digits
# ("$13.27B/day", "0.78×") or the analyst's own unit words ("4.0 percentage
# points") may sit between the figure and its bracket; a series' bracket may
# name the point's date (`f_…@2025-12-31`, as the desk shows it). Round H put
# eleven brackets after a quotation or a noun ("…” [f_passage]", "Item 7
# passage [f_…]"): those are CITATIONS — a fact named, no figure to check.
_UNIT_TAIL = (r"(?:/[A-Za-z]+|×|\s?(?:x|times|pp|bps|basis\s+points?|percentage\s+points?|points?|days?|years?|"
              r"quarters?|months?|shares?|sessions?))?")
_POINTER_AFTER = re.compile(_UNIT_TAIL + r"\s*\[\s*(f_[0-9A-Za-z]{4,})(?:@([0-9A-Za-z:.\-]{1,32}))?\s*\]")
_CITATION = re.compile(r"\[\s*(f_[0-9A-Za-z]{4,})(?:@[0-9A-Za-z:.\-]{1,32})?\s*\]")

# ── the closed word lists G3 reads ───────────────────────────────────────────
SUPERLATIVES = frozenset("""largest smallest biggest highest lowest most least top bottom worst best weakest
strongest greatest deepest longest shortest nearest closest farthest furthest heaviest lightest tightest widest
narrowest fastest slowest jumpiest leads leading dominant""".split())
# past and present forms both: round J accepted "Technology sector concentration
# falls to 35.3% from 35.0%" because the list held "fell" and not "falls"
UP_WORDS = frozenset("rose rises rising up increased increases increasing grew grows growing higher climbed climbs climbing "
                     "expanded expands expanding improved improves improving gained gains gaining widened widens widening "
                     "above outperformed outperforms".split())
DOWN_WORDS = frozenset("fell falls falling down decreased decreases decreasing declined declines declining lower dropped drops "
                       "dropping shrank shrinks shrinking narrowed narrows narrowing slipped slips slipping deteriorated "
                       "deteriorates deteriorating weakened weakens weakening below underperformed underperforms".split())
CHANGE_WORDS = frozenset("from to change changed moved moving move since versus vs against compared".split()) | UP_WORDS | DOWN_WORDS
# A CHANGE IS CLAIMED, not merely worded: "from A to B", or a verb that moves.
# A lone preposition does not claim one — "AAPL sits 3.9% from its 52-week high"
# put two quantities in a sentence and was refused as a change (V33F Q17).
# "above", "below", "higher", "lower" COMPARE two figures ("16.0% against a
# warning level of 15.0% … above warning"); they claim no change. Round H
# refused that sentence twice as a change between two quantities.
CHANGE_VERBS = (frozenset("change changed moved moving move moves".split())
                | (UP_WORDS - {"above", "higher", "outperformed", "outperforms"})
                | (DOWN_WORDS - {"below", "lower", "underperformed", "underperforms"}))
TIER_WORDS = frozenset("warning breach limit tier room headroom cap".split())
DATE_WORDS = ("started", "troughed", "peaked", "bottomed", "began", "ended", "recovered", "as of", "dated")
TIER_SUFFIXES = ("warning_level", "breach_level", "limit_value")
CHANGE_OPS = ("yoy", "qoq", "pct", "cagr", "subtract")
_WORD = re.compile(r"[A-Za-z][A-Za-z_']*")
_MIN_QUOTED_WORDS = 4


@dataclass
class Verdict:
    problems: list[dict] = field(default_factory=list)
    error: str | None = None
    detail: str | None = None
    links: dict[tuple[int, int], dict] = field(default_factory=dict)     # (para, token start) -> {to, ids, as_written}
    marks: list[dict] = field(default_factory=list)                       # block marks: {para, start, end, kind, node, ids}
    pointers: list[dict] = field(default_factory=list)                    # `[f_…]` spans the render drops: {para, start, end, id}
    citations: list[str] = field(default_factory=list)                    # facts named by a bracket that follows no figure
    refs: list[str] = field(default_factory=list)                         # every fact id the answer rests on
    sentences: list[dict] = field(default_factory=list)                   # {tag, para, text, span, checked, problems}

    @property
    def failed(self) -> list[dict]:
        return [s for s in self.sentences if s["problems"]]

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_refusal(self) -> dict:
        return {"error": self.error, "problems": self.problems, "detail": self.detail}


# ── helpers over the ledger ──────────────────────────────────────────────────

_QUOTE_CHARS = str.maketrans("", "", "\"'\u2018\u2019\u201c\u201d\u00ab\u00bb")


def _quoted(text: str) -> str:
    """A quotation is its WORDS. Quotation marks are delimiters, and nesting one
    quote inside another forces the inner marks to change — V33D refused 381
    verbatim characters of a 10-K because the source's inner `"` had to become
    `'` to sit inside the analyst's own quotation. A newline the digest showed
    JSON-escaped (`\\n`) is whitespace; the punctuation that closes the
    writer's own sentence inside the marks ("…call describe.") is not the
    source's (round H: nine boundary quotations refused for a full stop)."""
    plain = re.sub(r"(?<=\d),(?=\d)", "", (text or "").replace("\\n", " "))   # "90,757" as the ledger keeps a passage: 90757
    return _normalise(plain).translate(_QUOTE_CHARS).strip(" .,;:!?")


def _short_subject(subject: str | None) -> str | None:
    """`issuer_concentration:MSFT` -> MSFT; `Technology` -> Technology; a row id -> None."""
    if not isinstance(subject, str) or not subject:
        return None
    if subject.startswith(("calc_", "run_", "port_", "task_", "rrun_")):
        return None
    return subject.rsplit(":", 1)[-1]


def _identity(rec: dict) -> tuple:
    return (rec.get("measure"), rec.get("subject"), rec.get("as_of"), str(rec.get("window")))


def _is_tier(rec: dict) -> bool:
    return any((rec.get("measure") or "").endswith(s) for s in TIER_SUFFIXES)


# Words a producer puts in a measure's own name when the figure IS a place in an
# ordering: the deepest episode, a max drawdown, the first of a list. Such a
# fact backs a superlative the way a rank entry does.
_ORDER_WORDS = frozenset("deepest largest smallest highest lowest worst best top max min first last peak trough".split())
MAX_WORDS = frozenset("largest biggest highest most top best widest deepest worst longest".split())
MIN_WORDS = frozenset("smallest lowest least bottom weakest narrowest shortest".split())


def _ordered(rec: dict) -> bool:
    if "rank" in (rec.get("params") or {}):
        return True
    parts = set(re.split(r"[^A-Za-z0-9]+", (rec.get("measure") or "").lower())) | ({"first"} if "[0]" in (rec.get("measure") or "") else set())
    return bool(parts & _ORDER_WORDS)


def _words(text: str) -> set[str]:
    return {w.lower().strip("'") for w in _WORD.findall(text)}


def _measure_words(measure: str | None) -> list[str]:
    """A measure as words: its alphanumeric runs, in order. A derived measure
    keeps its operands' words, so `divide(dividends_paid, operating_cash_flow)`
    reads as both quantities the sentence may name."""
    if not measure:
        return []
    tail = re.split(r"[.:]", measure)[-1] if "(" not in measure else measure
    return [w for w in re.split(r"[^A-Za-z0-9]+", tail) if w]


def _same_check(a: str | None, b: str | None) -> bool:
    """Whether a tier and a reading belong to one check: `issuer_concentration:MSFT`
    against itself, against `MSFT`, or against the check's default row."""
    ta, tb = str(a or ""), str(b or "")
    if not ta or not tb:
        return True
    return (ta == tb or ta.endswith(":" + tb) or tb.endswith(":" + ta)
            or ta.split(":")[0] == tb.split(":")[0])


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def _compound_before(text: str, start: int) -> bool:
    return start > 0 and (text[start - 1].isalpha() or (text[start - 1] == "-" and start > 1 and text[start - 2].isalnum()))


def _compound_after(text: str, end: int) -> bool:
    return end + 1 < len(text) and text[end] == "-" and (text[end + 1].isalpha() or text[end + 1] == "-")


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    out = text
    for s, e in spans:
        out = out[:s] + " " * (e - s) + out[e:]
    return out


# ── the check ────────────────────────────────────────────────────────────────

def check(text: str, ledger: Ledger, question: str | None = None) -> Verdict:
    v = Verdict()
    paras = [(m.start(), m.group(0)) for m in re.finditer(r"[^\n]+", text or "") if m.group(0).strip()]
    if not paras:
        v.error, v.detail = "empty_answer", "the answer has no text"
        return v
    asked = {_core(t["token"]) for t in A.tokens_in(question or "")}
    all_passages = list(ledger.passages)
    # THE TEXTS THIS TURN HOLDS, which quotation marks may claim: every text on
    # the ledger — a passage the desk read, the desk's own words for what it
    # could not do (a boundary is a fact, minted by the broker with the digest)
    # — and the question the user asked. Not an enumeration of sources: V33E
    # widened one (§8) and round G still refused the desk's own words, because
    # they had been shown and never recorded.
    turn_texts = [(pid, _quoted(txt)) for pid, txt in ledger.passages.items()]
    for r in ledger.by_id.values():
        if r.get("kind") in (F.SCALAR, F.SERIES, F.PASSAGE):
            continue
        txt = r.get("text") if isinstance(r.get("text"), str) else (r.get("value") if isinstance(r.get("value"), str) else None)
        if txt:
            turn_texts.append((r["id"], _quoted(txt)))
    if question:
        turn_texts.append((None, _quoted(question)))
    subjects_on_ledger = {s for s in (_short_subject(r.get("subject")) for r in ledger.by_id.values()) if s}
    # every phrase a measure on the ledger reads as, and the measures that read so
    phrases: dict[str, set[str]] = {}
    for r in ledger.by_id.values():
        ws = _measure_words(r.get("measure"))
        if len(ws) >= 2 and r.get("measure"):
            phrases.setdefault(" ".join(ws).lower(), set()).add(r["measure"])

    for i, (para_at, para) in enumerate(paras):
        # G5 — the marks
        mark_spans: list[tuple[int, int]] = []
        for m in MARK_BLOCK.finditer(para):
            kind, node = m.group(1), m.group(2)
            ids = [fid for fid, r in ledger.by_id.items() if (r.get("params") or {}).get("node") == node
                   and r.get("kind") in (F.SCALAR, F.SERIES)]
            if not ids:
                v.problems.append({"at": f"prose[{i}]", "_at": m.start(), "reason": "unknown_node", "node": node,
                                   "fix": "a [table: …] or [chart: …] names a binding of a program this turn ran, and its facts are on the ledger"})
            else:
                v.marks.append({"para": i, "start": m.start(), "end": m.end(), "kind": kind, "node": node, "ids": ids})
                v.refs += ids
            mark_spans.append((m.start(), m.end()))
        blanked = _blank(para, mark_spans)

        # G4 — quotations: verified spans exempt their digits
        quoted_ok: list[tuple[int, int]] = []
        for span in quoted_spans(blanked):
            want = _quoted(span)
            hit = [tid for tid, txt in turn_texts if want and want in txt]
            start = blanked.find(span)
            if hit:
                quoted_ok.append((start, start + len(span)))
                v.refs += [t for t in hit[:1] if t]
            else:
                v.problems.append({"at": f"prose[{i}]", "_at": max(start, 0), "reason": "unverified_quote", "quote": span[:120],
                                   "fix": "quotation marks say these words are verbatim in a text this turn holds — a passage "
                                          "the desk read, the desk's own words for what it could not do, or the question: "
                                          "reproduce the wording, or drop the marks"})

        sentences = _sentences(blanked)
        tokens = A.tokens_in(blanked)
        linked_by_sentence: dict[int, list[tuple[dict, list[dict]]]] = {}     # sentence idx -> [(token, [record])]

        # the pointers: a figure, then `[f_…]`; a bracket after anything else cites
        pointed: dict[int, tuple[str, str | None]] = {}                       # figure token start -> (fact id, period)
        consumed: set[int] = set()                                            # id token starts that are pointers/citations
        spans: list[tuple[int, int]] = []                                     # every bracket span (tokens inside are not prose)
        for t in tokens:
            if t["kind"] != "num":
                continue
            m = _POINTER_AFTER.match(blanked, t["end"])
            if not m:
                continue
            pointed[t["start"]] = (m.group(1), m.group(2))
            consumed.add(m.start(1))
            bracket = blanked.index("[", m.start())
            drop_from = bracket - 1 if bracket > 0 and blanked[bracket - 1] == " " else bracket
            v.pointers.append({"para": i, "start": drop_from, "end": m.end(), "id": m.group(1)})
            spans.append((bracket, m.end()))
        for m in _CITATION.finditer(blanked):
            if any(s <= m.start() < e for s, e in spans):
                continue
            fid = m.group(1)
            consumed.add(m.start(1))
            drop_from = m.start() - 1 if m.start() > 0 and blanked[m.start() - 1] == " " else m.start()
            v.pointers.append({"para": i, "start": drop_from, "end": m.end(), "id": fid})
            spans.append((m.start(), m.end()))
            if fid in ledger.by_id:
                v.citations.append(fid)
                v.refs.append(fid)
            else:
                v.problems.append({"at": f"prose[{i}]", "_at": m.start(), "reason": "not_on_ledger", "id": fid,
                                   "fix": "this bracket names no fact the desk showed this turn: copy the id from the evidence, or drop the bracket"})

        # G1 / G2 — every token
        for t in tokens:
            tok, kind, start, end = t["token"], t["kind"], t["start"], t["end"]
            if any(s <= start < e for s, e in quoted_ok):
                continue
            if any(s <= start < e for s, e in spans) and start not in consumed and start not in pointed:
                continue                                                      # a date inside a bracket: the pointer's, not prose
            if kind == "id":
                if start in consumed:
                    continue
                v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "id_in_prose", "id": tok,
                                   "fix": "an id is written in brackets — after the figure it points to (16.0% [f_…]), or after "
                                          "the quotation or name it cites; bare, it is a word the reader must not see"})
                continue
            if kind == "form":
                continue                                                      # "10-K", "DEF 14A": a filing's name, not a figure
            if kind == "num" and (_compound_before(blanked, start) or _compound_after(blanked, end)):
                # "1-year", "52-week", "10-K": the digits belong to a word, not to a
                # figure. V33D's "1-year" resolved to whatever the ledger held near 1.
                continue
            si = next((k for k, (s, e) in enumerate(sentences) if s <= start < e), 0)
            sentence = blanked[sentences[si][0]:sentences[si][1]]
            if start in pointed:
                # G1 — a pointed figure: the id is on the ledger and holds the figure
                fid, period = pointed[start]
                rec = ledger.by_id.get(fid)
                held_by = _holders(ledger, tok)
                if rec is None:
                    v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "not_on_ledger", "figure": tok, "id": fid,
                                       "candidates": held_by,
                                       "fix": "the id after a figure is the one the desk showed it under: copy the figure and "
                                              "its bracket from the evidence" + (" — the desk showed this figure under the ids listed" if held_by else "")})
                    continue
                if rec.get("kind") == F.PASSAGE:
                    # the figure a passage states, pointed at the passage (round I:
                    # Q04 "$65,179 million [f_passage]", Q19 nine segment figures)
                    if ledger.resolve_in_passages(tok, [fid]):
                        v.links[(i, start)] = {"to": "passage", "ids": [fid], "as_written": tok}
                        v.refs.append(fid)
                    else:
                        v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "mark_mismatch", "figure": tok, "id": fid,
                                           "holds": "passage", "candidates": held_by,
                                           "fix": f"{fid} is a passage and does not state this figure: quote the passage's own "
                                                  f"words, or point at the fact that holds it"})
                    continue
                hits = [p for f, p in ledger.readings(tok) if f == fid]
                if period is not None:
                    if period not in hits:
                        v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "mark_mismatch", "figure": tok, "id": fid,
                                           "holds": _shown_point(rec, period), "candidates": [c for c in held_by if c["id"] != fid],
                                           "fix": f"{fid} holds {_shown_point(rec, period)} on {period}, not this figure: write the point "
                                                  f"as the desk showed it, or point at the fact that holds it"})
                        continue
                elif not hits:
                    v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "mark_mismatch", "figure": tok, "id": fid,
                                       "holds": _shown(rec), "candidates": [c for c in held_by if c["id"] != fid],
                                       "fix": f"{fid} holds {_shown(rec)}, not this figure: write the figure as the desk showed "
                                              f"it, or point at the fact that holds it" + (" — the desk showed this figure under the ids listed" if held_by else "")})
                    continue
                elif rec.get("kind") == F.SERIES:
                    periods = sorted({p for p in hits if p})
                    named = [p for p in periods if p in sentence or p[:4] in sentence]
                    if len(periods) == 1:
                        period = periods[0]
                    elif len(named) == 1:
                        period = named[0]
                    else:
                        v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "ambiguous_point", "figure": tok, "id": fid,
                                           "periods": periods[:6],
                                           "fix": "this series holds the figure on several dates: write the point's bracket as the "
                                                  "desk showed it, with its date — " + ", ".join(f"[{fid}@{p}]" for p in periods[:4])})
                        continue
                v.links[(i, start)] = {"to": "fact", "ids": [fid], "primary": fid, "period": period, "as_written": tok}
                linked_by_sentence.setdefault(si, []).append((t, [_reading(rec, period)]))
                continue
            # G2 — a bare number: an identity field, the user's own, a passage's, or refused
            ids = ledger.resolve_identity(tok)
            if ids:
                # an identity field (a date, a year, a window's digits): a citation, never a figure
                v.links[(i, start)] = {"to": "fact", "ids": ids, "as_written": tok, "how": "identity"}
                continue
            if _core(tok) in asked:
                v.links[(i, start)] = {"to": "question", "ids": [], "as_written": tok}
                continue
            pids = ledger.resolve_in_passages(tok, all_passages)
            if pids:
                v.links[(i, start)] = {"to": "passage", "ids": pids, "as_written": tok}
                continue
            held_by = _holders(ledger, tok)
            if held_by:
                v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "unpointed_figure", "figure": tok, "candidates": held_by,
                                   "fix": "a figure the desk showed is written as shown, followed by its id in brackets "
                                          "(16.0% [f_…]); the desk showed this figure under the ids listed"})
                continue
            v.problems.append({"at": f"prose[{i}]", "_at": start, "reason": "unsourced_figure", "figure": tok,
                               "fix": "a number the ledger cannot account for: request the figure, quote the passage that states it, or drop it"})

        # G3 — the sentence around the figures
        for si, (s, e) in enumerate(sentences):
            sentence = blanked[s:e]
            linked = linked_by_sentence.get(si, [])
            words = _words(sentence)
            before = len(v.problems)
            _check_sentence(v, i, sentence, s, words, linked, tokens, ledger, subjects_on_ledger, phrases)
            # D — WHAT THE GATE CHECKED, SAID. A sentence with no figure and no
            # quotation is the analyst's judgement: nothing here can settle it, and
            # half of every answer is made of them (V33F: 223 of 443). The reader
            # is told which half, rather than being left to assume.
            mine = [p for p in v.problems[:before] if isinstance(p.get("_at"), int) and s <= p["_at"] < e
                     and "sentence" not in p] + list(v.problems[before:])
            tag = f"S{len(v.sentences) + 1}"
            for p in mine:
                p["sentence"] = tag
                p.pop("_at", None)
            quoted_here = any(s <= qs < e for qs, _qe in quoted_ok)
            v.sentences.append({"tag": tag, "para": i, "text": para[s:e], "span": (para_at + s, para_at + e),
                                "checked": bool(linked or quoted_here), "problems": mine,
                                "facts": [f for _t, recs in linked for f in [recs[0]["id"]]]})

    for p in v.problems:
        p.pop("_at", None)
    v.refs = list(dict.fromkeys([*v.refs, *[l.get("primary") or fid for l in v.links.values() for fid in l["ids"][:1]]]))
    if v.problems:
        order = ("not_on_ledger", "unknown_node", "id_in_prose", "mark_mismatch", "unsourced_figure", "unpointed_figure",
                 "ambiguous_point", "unverified_quote", "date_expected", "subject_mismatch", "measure_mismatch",
                 "superlative_without_rank", "change_conflict", "direction_conflict", "tier_mismatch")
        reasons = {p["reason"] for p in v.problems}
        v.error = next((r for r in order if r in reasons), v.problems[0]["reason"])
        v.detail = (f"{len(v.problems)} problem(s), all listed; the first: " + _one_line(v.problems[0]))
    return v


def _one_line(p: dict) -> str:
    what = p.get("figure") or p.get("id") or p.get("node") or p.get("quote") or p.get("word") or ""
    return f"{p['at']} {p['reason']}" + (f" ({what!r})" if what else "") + (f": {p['fix']}" if p.get("fix") else "")


def _reading(rec: dict, period: str | None) -> dict:
    """One reading of a fact, as the sentence checks see it: a scalar as it is, a
    series' point as a scalar on its own date. The id stays the fact's."""
    if period is None:
        return rec
    value = next((float(p[1]) for p in (rec.get("points") or []) if str(p[0]) == period), None)
    return {**rec, "kind": F.SCALAR, "value": value, "as_of": period, "window": None, "points": None}


def _group_key(rec: dict, period: str | None) -> tuple:
    """Facts that hold one written figure on one date for one subject are ONE
    READING under several names — a holding's weight, the concentration check's
    current_value that reads it, the rank entry over it, the same series fetched
    twice. They are aliases, not an ambiguity; the ambiguity the reader cares
    about is two subjects or two dates holding the same number."""
    return (_short_subject(rec.get("subject")) or rec.get("subject"), period or rec.get("as_of"))


def _holders(ledger: Ledger, tok: str) -> list[dict]:
    """The facts that hold a written figure, as candidates a refusal names —
    a lookup, so the writer picks among what it was shown."""
    seen = list(dict.fromkeys(f for f, _p in ledger.readings(tok)))
    return [{"id": f, "measure": ledger.by_id[f].get("measure"), "subject": ledger.by_id[f].get("subject"),
             "as_of": ledger.by_id[f].get("as_of")} for f in seen[:6]]


def _shown_point(rec: dict, period: str) -> str:
    val = next((p[1] for p in (rec.get("points") or []) if str(p[0]) == period), None)
    if val is None:
        return "no point"
    try:
        return A.fill({**rec, "kind": F.SCALAR, "value": float(val), "points": None}).get("display") or str(val)
    except Exception:  # noqa: BLE001
        return str(val)


def _shown(rec: dict) -> str:
    """A fact's value as the desk showed it — what a mark_mismatch names."""
    try:
        d = A.fill(rec)
        shown = d.get("display")
    except Exception:  # noqa: BLE001 — a display failure must not fail the check
        shown = None
    return str(shown if shown else rec.get("value"))


def _ranked_aliases(ledger: Ledger, recs: list[dict]) -> list[dict]:
    """The facts on the ledger that hold the same reading as `recs` AND carry a
    place in an ordering — what a superlative can rest on. A lookup."""
    out: list[dict] = []
    for r in recs:
        for cand in ledger.by_id.values():
            if cand is r or cand.get("id") == r.get("id") or cand.get("kind") != F.SCALAR:
                continue
            p = cand.get("params") or {}
            if not (isinstance(p.get("place"), int) or "rank" in p):
                continue
            if (_short_subject(cand.get("subject")) or cand.get("subject")) != (_short_subject(r.get("subject")) or r.get("subject")):
                continue
            try:
                if abs(float(cand.get("value")) - float(r.get("value"))) > 1e-9:
                    continue
            except (TypeError, ValueError):
                continue
            out.append({"id": cand["id"], "measure": cand.get("measure"), "subject": cand.get("subject"), "as_of": cand.get("as_of"),
                        "place": p.get("place") or p.get("rank")})
    return out[:6]


def _place_fits(words: set[str], rec: dict) -> bool:
    """Whether the figure holds the place the sentence claims. A vector's entries
    carry their place the moment the desk builds them (program_service._facts_of),
    so this is a lookup: `highest` is first, `lowest` is last."""
    p = rec.get("params") or {}
    place, of = p.get("place"), p.get("of")
    if not isinstance(place, int) or not isinstance(of, int):
        return _ordered(rec)
    want_max, want_min = bool(words & MAX_WORDS), bool(words & MIN_WORDS)
    if want_max and not want_min:
        return place == 1
    if want_min and not want_max:
        return place == of
    return place in (1, of)


def _check_sentence(v: Verdict, i: int, sentence: str, offset: int, words: set[str], linked: list, tokens: list,
                    ledger: Ledger, subjects_on_ledger: set[str], phrases: dict[str, set[str]]) -> None:
    """The sentence around its figures. `linked` is [(token, [alias records])]
    in reading order; a check that any alias satisfies is satisfied."""
    at = f"prose[{i}]"
    groups = [recs for _t, recs in linked if recs and recs[0].get("kind") == F.SCALAR]
    firsts = [recs[0] for recs in groups]
    low = sentence.lower()

    # a company named in the sentence is the figure's company (tickers only:
    # a sector or a check name is not something a reader mis-attributes)
    tickers = {s for s in subjects_on_ledger if s.isupper() and 1 <= len(s) <= 6}
    named = {w.upper() for w in words if w.upper() in tickers}
    if named:
        for t, recs in linked:
            short = _short_subject(recs[0].get("subject"))
            if short and short in tickers and short not in named:
                v.problems.append({"at": at, "reason": "subject_mismatch", "figure": t["token"], "id": recs[0]["id"],
                                   "figure_subject": recs[0].get("subject"), "sentence_names": sorted(named)[:6],
                                   "fix": f"this figure is {recs[0].get('subject')}'s ({recs[0].get('measure')}); the sentence names {', '.join(sorted(named)[:3])}"})

    # A MEASURE THE SENTENCE NAMES IS THE MEASURE OF A FIGURE IN IT, or one the
    # figure is built from. The phrase's words must be among the linked measure's
    # words — the sentence may say "dividends paid were 12% of operating cash
    # flow" beside divide(dividends_paid, operating_cash_flow), and may NOT say
    # "factor share 0.85%" beside alpha_plus_residual (V33B Q18, the one reader-
    # visible falsehood nothing else catches).
    linked_words = [set(w.lower() for w in _measure_words(r.get("measure"))) for _t, recs in linked for r in recs]
    for phrase, measures in phrases.items():
        if not phrase or phrase not in low or not linked_words:
            continue
        want = set(phrase.split())
        if not any(want <= have for have in linked_words):
            v.problems.append({"at": at, "reason": "measure_mismatch", "phrase": phrase,
                               "linked": [recs[0]["id"] for _t, recs in linked][:4],
                               "fix": f"the sentence says '{phrase}' but the figure beside it is "
                                      f"{', '.join(sorted({str(r.get('measure')) for _t, recs in linked for r in recs})[:3])}; "
                                      f"the ledger holds {' / '.join(sorted(measures)[:2])} as its own fact — write that value, or drop the phrase"})
            break

    # A SUPERLATIVE RESTS ON AN ORDERING — one the desk computed (a rank node), or
    # one the paragraph puts in front of the reader: the same measure read for
    # several subjects, with the figure called extreme actually extreme among
    # them. V33F refused 12 superlatives whose own paragraph listed the readings
    # they ordered ("Microsoft has the highest capex intensity at 22.9%. Alphabet
    # follows at 22.7%, and Amazon is lower at 18.4%").
    if words & SUPERLATIVES and groups:
        if not any(_place_fits(words, r) for recs in groups for r in recs):
            ranked = _ranked_aliases(ledger, firsts)
            v.problems.append({"at": at, "reason": "superlative_without_rank", "word": sorted(words & SUPERLATIVES)[0],
                               "linked": [r["id"] for r in firsts][:4], "candidates": ranked,
                               "fix": "a largest/smallest/most/least rests on the figure's own place in an ordering the desk built; "
                                      "this figure does not hold that place — "
                                      + ("the desk's ordering holds the same reading as " + ", ".join(f"[{c['id']}]" for c in ranked[:3])
                                         + ": point at that one, or drop the word" if ranked else
                                         "request compare: rank over it, or drop the word")})

    # a date word is followed by a date
    for dw in DATE_WORDS:
        for m in re.finditer(r"\b" + re.escape(dw) + r"\b", sentence, flags=re.IGNORECASE):
            nxt = next((t for t in tokens if t["start"] >= offset + m.end() and t["start"] < offset + len(sentence)), None)
            if nxt and nxt["kind"] == "num" and nxt["start"] - (offset + m.end()) <= 12:
                v.problems.append({"at": at, "reason": "date_expected", "word": dw, "figure": nxt["token"],
                                   "fix": f"'{dw}' introduces a date; this figure is not one — the date is on the facts' window (start/end) or as_of"})

    # tier words sit beside the tier they name
    # A TIER WORD NAMES THE TIER'S KIND — a lookup on each pointed tier fact. Which
    # reading a tier sits "against" is not judged here: round G paired every tier
    # in a sentence with every reading in it and refused a true sentence 12 times
    # (four issuers' checks listed in one breath); with the writer pointing, the
    # reader opens the tier and sees whose it is.
    tier_words = words & TIER_WORDS
    tiers = [r for recs in groups for r in recs if _is_tier(r)]
    if tier_words and tiers:
        kinds = {("warning" if t["measure"].endswith("warning_level") else "breach" if t["measure"].endswith("breach_level") else "limit") for t in tiers}
        if "warning" in words and "warning" not in kinds and kinds:
            v.problems.append({"at": at, "reason": "tier_mismatch", "id": tiers[0]["id"],
                               "fix": f"the sentence says warning; the tier figure here is the {sorted(kinds)[0]} tier"})
        if "breach" in words and "breach" not in kinds and kinds:
            v.problems.append({"at": at, "reason": "tier_mismatch", "id": tiers[0]["id"],
                               "fix": f"the sentence says breach; the tier figure here is the {sorted(kinds)[0]} tier"})
    # a change or a comparison joins the right two figures, and points the way they moved
    up, down = words & UP_WORDS, words & DOWN_WORDS
    # A CHANGE IS TWO FIGURES. "went from 10.7% to 32.5%, then down to 3.81%, then
    # back up to 5.05%" is a trajectory: which leg a direction word names is not
    # the check's to decide, and the first two figures settle nothing (round I
    # refused Q03 twice for it). With exactly two figures the sentence claims
    # one move, and that one is judged.
    if words & CHANGE_WORDS and len(groups) == 2:
        ga, gb = groups[0], groups[1]
        a, b = ga[0], gb[0]
        # Two units in one sentence are not checked as units: a comparison
        # ("$1.72M against $10.51B/day of volume") is prose, and a CHANGE across
        # units is already two different measures, which the branch below refuses.
        # Judging by unit refused 15 comparisons in V33D and caught nothing the
        # measure test does not.
        # one reading under two names is one subject, one date AND one value:
        # two different quantities of one subject on one day are not a change
        same_group = (_group_key(a, None) == _group_key(b, None)
                      and abs(float(a["value"]) - float(b["value"])) < 1e-12)
        same_measure = a.get("measure") == b.get("measure") or same_group
        same_subject = (_short_subject(a.get("subject")) or a.get("subject")) == (_short_subject(b.get("subject")) or b.get("subject"))
        va, vb = float(a["value"]), float(b["value"])
        if same_group and abs(va - vb) < 1e-12:
            v.problems.append({"at": at, "reason": "change_conflict", "ids": [a["id"], b["id"]],
                               "fix": "the two figures are one reading written twice; a change is two dates, a comparison two subjects"})
        elif same_measure and same_subject:
            if a.get("as_of") and b.get("as_of") and a.get("as_of") != b.get("as_of"):
                earlier, later = sorted((a, b), key=lambda r: str(r.get("as_of")))
                moved_up = float(later["value"]) > float(earlier["value"])
            else:
                moved_up = vb > va            # "from A to B": the order written
            if (up and not moved_up) or (down and moved_up):
                v.problems.append({"at": at, "reason": "direction_conflict", "ids": [a["id"], b["id"]],
                                   "fix": f"the figure moved {'up' if moved_up else 'down'}; the sentence says the opposite"})
        elif same_measure and not same_subject:
            if up or down:
                first_higher = va > vb
                if (up and not first_higher) or (down and first_higher):
                    v.problems.append({"at": at, "reason": "direction_conflict", "ids": [a["id"], b["id"]],
                                       "fix": f"{a.get('subject')} is {'above' if first_higher else 'below'} {b.get('subject')} on {a.get('measure')}; the sentence says the opposite"})
        elif not same_measure and (("from" in words and "to" in words) or words & CHANGE_VERBS):
            if not any((r.get("params") or {}).get("op") in CHANGE_OPS for r in (a, b)):
                v.problems.append({"at": at, "reason": "change_conflict", "ids": [a["id"], b["id"]],
                                   "fix": f"{a.get('measure')} and {b.get('measure')} are two different quantities; a change is one measure of one subject at two dates"})
    elif (up or down) and len(groups) == 1:
        r = next((x for x in groups[0] if (x.get("params") or {}).get("op") in CHANGE_OPS), None)
        if r is not None:
            val = float(r["value"])
            if (up and val < 0) or (down and val > 0):
                v.problems.append({"at": at, "reason": "direction_conflict", "ids": [r["id"]],
                                   "fix": f"this change is {'negative' if val < 0 else 'positive'}; the sentence points the other way"})


# ── the render ───────────────────────────────────────────────────────────────

def accepted(text: str, verdict: Verdict, ledger: Ledger) -> dict:
    """The answer as stored and shown: paragraphs whose numbers carry their
    fact, the tables and charts the marks asked for, in the block shape
    services/answer.rendered already emits."""
    paras = [p for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()]
    blocks: list[dict] = []
    for i, para in enumerate(paras):
        cuts: list[tuple[int, int, str, Any]] = []
        for mk in verdict.marks:
            if mk["para"] == i:
                cuts.append((mk["start"], mk["end"], "block", mk))
        for (pi, start), link in verdict.links.items():
            if pi == i and link["to"] != "question":
                cuts.append((start, start + len(link["as_written"]), "link", link))
        for pt in verdict.pointers:
            if pt["para"] == i:
                # the bracket is the writer's pointing, not the reader's text: the
                # figure before it carries the link the bracket named
                cuts.append((pt["start"], pt["end"], "drop", pt))
        cuts.sort(key=lambda c: c[0])
        runs: list = []
        pos = 0
        after: list[dict] = []
        for s, e, kind, payload in cuts:
            if s < pos:
                continue
            if s > pos:
                runs.append(para[pos:s])
            if kind == "link":
                # THE READER SEES THE WORDS THE ANALYST WROTE. A resolved figure is
                # that text, underlined, opening the fact it equals (the page's
                # LinkText, built for exactly this). Substituting the fact's display
                # for the text was the placeholder grammar's job, and V33 deleted the
                # placeholders: it now only makes true sentences false — "1-year" came
                # out "$251.89 (2026-09-10)-year", "in 2023" came out "in $717B".
                runs.append({"link": {"to": payload["to"], "ids": payload["ids"], "as_written": para[s:e]}})
            elif kind == "block":
                after.append(_block_for(payload, ledger))
            pos = e
        if pos < len(para):
            runs.append(para[pos:])
        runs = [r for r in runs if r != ""]
        if runs:
            blocks.append({"type": "paragraph", "runs": runs})
        blocks += [b for b in after if b]
    facts_used = list(dict.fromkeys(verdict.refs))
    figures = [ledger.by_id[f] for f in facts_used if f in ledger.by_id and ledger.kind(f) in (F.SCALAR, F.SERIES)]
    passages = [f for f in facts_used if ledger.kind(f) == F.PASSAGE]
    checked = [x for x in verdict.sentences if x["checked"]]
    unchecked = [x for x in verdict.sentences if not x["checked"]]
    return {"blocks": blocks, "text": A.prose_of(blocks), "citations": facts_used,
            "verified": {"figures": len(figures), "sources": len(passages),
                         # D: the gate says what it settled and what it did not. A
                         # sentence with no figure and no quotation is the analyst's
                         # judgement; nothing here can settle it, and the reader is
                         # told which sentences those are rather than left to assume.
                         "sentences": {"checked": len(checked), "unchecked": len(unchecked),
                                       "judgement": [x["text"] for x in unchecked]},
                         "matches": [{"label": r.get("measure"), "value": r.get("value"), "unit_class": r.get("unit"),
                                      "source_id": r["id"], "subject": r.get("subject"), "as_of": r.get("as_of")} for r in figures]}}


def repair(text: str, verdict: Verdict, replacements: dict[str, str]) -> str:
    """The answer with the refused sentences replaced and every accepted sentence
    kept EXACTLY as written. This is what makes a second attempt converge: the
    accepted set can only grow, where a whole-reply rewrite re-rolled every
    sentence and 17 of 20 questions spent both attempts without landing (V33F).
    A tag with an empty replacement drops its sentence."""
    spans = sorted(((x["span"], replacements[x["tag"]]) for x in verdict.sentences if x["tag"] in replacements),
                   key=lambda t: t[0][0], reverse=True)
    out = text
    for (start, end), new in spans:
        new = (new or "").strip()
        out = out[:start] + new + out[end:]
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _block_for(mark: dict, ledger: Ledger) -> dict | None:
    recs = [ledger.by_id[fid] for fid in mark["ids"]]
    series = [r for r in recs if r.get("kind") == F.SERIES]
    if mark["kind"] == "chart" and series:
        return {"type": "chart", "kind": "line", "title": mark["node"], "fact": A.fill(series[0])}
    rows = [r for r in recs if r.get("kind") == F.SCALAR]
    if not rows and series:
        return {"type": "chart", "kind": "line", "title": mark["node"], "fact": A.fill(series[0])}
    if not rows:
        return None
    grid = [[A.fill(r)] for r in rows]
    return {"type": "table", "title": mark["node"], "rows": [[{"fact": f} for f in row] for row in grid], **A.derive_table(grid)}
