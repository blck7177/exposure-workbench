"""The observer: validation that reads what the model wrote and what the desk recorded,
and asks nothing of the model.

The gate it replaces told the model how to write so that it could be checked — a
figure followed by its row's id, a repair by sentence tag — and refused what did
not fit the protocol: a correct "fell 19.3 percentage points" was refused and a
wrong "fell 19.3%" accepted (Q07, 2026-10-02). Here the model writes prose. The
observer takes the draft, the question and the analysis views the turn produced,
extracts every figure, finds the cell it states — by value at the written
precision, then by the subject and the unit the sentence gives it — and checks what
the sentence says about it: its kind (a percentage-point change is not a percent),
its direction, its subject, its place in an ordering. Figures that match nothing
the desk computed are unsupported; sentences without a figure are the model's
judgement, recorded as such and never gated.

A verdict carries every proposition with its status, the task's completion against
the requests that were analysed, and — only where a figure is wrong or unsupported
— feedback in business terms, with the desk's own figures, for the model to revise
from. No tag, no pointer, no format rule reaches the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.analytics import value_semantics as vs
from exposure_workbench.services import answer as A

SUPPORTED, CONTRADICTED, UNSUPPORTED, AMBIGUOUS = "supported", "contradicted", "insufficient_evidence", "ambiguous"
IDENTITY, QUESTION, PASSAGE, JUDGEMENT = "identity", "question", "passage", "judgement"
PROBLEMS = (CONTRADICTED, UNSUPPORTED, AMBIGUOUS)

# a sentence ends at its punctuation, which markdown may wrap in emphasis marks ("…deterioration.** It was…")
_SENTENCE_END = re.compile(r"(?<=[.!?;:])[*_)]*\s+(?=[A-Z“\"(\[\d*#•-])|\n+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'_-]*")
UP_WORDS = frozenset("rose rises rising up increased increases increasing grew grows growing higher climbed climbs "
                     "climbing gained gains gaining improved improves improving widened expanded strengthened".split())
DOWN_WORDS = frozenset("fell falls falling down decreased decreases decreasing declined declines declining lower "
                       "dropped drops dropping lost loses losing weakened worsened deteriorated deteriorates "
                       "narrowed contracted shrank slipped slid".split())
MAX_WORDS = frozenset("largest biggest highest most top best strongest greatest widest deepest longest sharpest "
                      "leading leads first".split())
MIN_WORDS = frozenset("smallest lowest least bottom weakest worst narrowest shortest last".split())
DECLINE_NOUNS = frozenset("deterioration decline fall drop loss decrease weakening contraction slide slip falls declines "
                          "drops losses decreases shrinkage".split())
NEGATIONS = frozenset("not no never neither nor isn't aren't wasn't weren't doesn't don't cannot can't".split())
PP_WORDS = re.compile(r"^\s*(?:percentage[\s-]+points?|pp\b|pps\b|points?\b)", re.I)
RELATIVE_WORDS = frozenset("relative relatively".split())
MONEY_SCALE = re.compile(r"^\s?(bn|billion|b|mm|million|m|k|thousand)\b", re.I)
_SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_NUMBER = re.compile(r"^(?P<sign>[+\-−])?(?P<dollar>\$)?(?P<num>\d[\d,]*(?:\.(?P<frac>\d+))?)(?P<pct>%)?$")
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


@dataclass(frozen=True)
class Cell:
    """One figure a view holds, as the observer matches against it."""
    ref: str
    view: str
    subject: str
    measure: str
    role: str                 # current | baseline | change
    kind: str                 # value_semantics kind
    unit: str | None
    value: float
    display: str
    period: str
    label: str
    column: str


def cells_of(views: Iterable[dict]) -> list[Cell]:
    out: list[Cell] = []
    for v in views:
        columns = {c["key"]: c for c in v.get("columns") or []}
        for row in v.get("rows") or []:
            for key, cell in (row.get("cells") or {}).items():
                if not isinstance(cell, dict) or "value" not in cell:
                    continue
                col = columns.get(key) or {}
                out.append(Cell(ref=str(cell.get("ref")), view=str(v.get("view")), subject=str(row.get("subject")),
                                measure=str(col.get("measure") or key), role=str(col.get("role") or "current"),
                                kind=str(col.get("kind") or vs.LEVEL), unit=col.get("unit"), value=float(cell["value"]),
                                display=str(cell.get("display") or ""), period=str(cell.get("period") or ""),
                                label=str(col.get("label") or key), column=key))
    return out


@dataclass
class Proposition:
    sentence: int
    start: int
    end: int
    token: str
    status: str
    cell: Cell | None = None
    reason: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        out = {"sentence": self.sentence, "span": [self.start, self.end], "token": self.token, "status": self.status}
        if self.cell:
            out["ref"] = self.cell.ref
            out["cell"] = {"subject": self.cell.subject, "measure": self.cell.measure, "role": self.cell.role,
                           "kind": self.cell.kind, "display": self.cell.display, "period": self.cell.period}
        if self.reason:
            out["reason"] = self.reason
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class Verdict:
    sentences: list[dict] = field(default_factory=list)
    propositions: list[Proposition] = field(default_factory=list)
    completion: dict = field(default_factory=dict)
    superlatives: list[dict] = field(default_factory=list)

    @property
    def problems(self) -> list[Proposition]:
        return [p for p in self.propositions if p.status in PROBLEMS]

    @property
    def ok(self) -> bool:
        return not self.problems and not any(s.get("status") == CONTRADICTED for s in self.superlatives)

    @property
    def citations(self) -> list[str]:
        return list(dict.fromkeys(p.cell.ref for p in self.propositions if p.status == SUPPORTED and p.cell))

    def summary(self) -> dict:
        figures = [p for p in self.propositions if p.status not in (IDENTITY, QUESTION)]
        return {"figures": len(figures),
                "supported": sum(p.status in (SUPPORTED, PASSAGE) for p in figures),
                "contradicted": (sum(p.status == CONTRADICTED for p in figures)
                                 + sum(s.get("status") == CONTRADICTED for s in self.superlatives)),
                "unsourced": sum(p.status == UNSUPPORTED for p in figures),
                "ambiguous": sum(p.status == AMBIGUOUS for p in figures),
                "sentences_checked": sum(s["status"] == "checked" for s in self.sentences),
                "sentences_judgement": sum(s["status"] == JUDGEMENT for s in self.sentences),
                "completion": self.completion.get("status")}

    def as_dict(self) -> dict:
        return {"summary": self.summary(), "sentences": self.sentences,
                "propositions": [p.as_dict() for p in self.propositions],
                "superlatives": self.superlatives, "completion": self.completion}

    def feedback(self) -> str | None:
        """What the model is told, only when something is wrong: the sentence, what it
        states, and the desk's figure. Business terms; no format rule."""
        lines: list[str] = []
        for p in self.problems:
            sent = self.sentences[p.sentence]["text"].strip()
            if p.status == CONTRADICTED:
                lines.append(f"- In \"{sent}\": {p.detail}")
            elif p.status == UNSUPPORTED:
                lines.append(f"- In \"{sent}\": the figure {p.token} matches nothing the desk computed this turn. "
                             f"Use the figures of the analysis table, run the analysis that produces it, or leave it out.")
            else:
                lines.append(f"- In \"{sent}\": {p.detail}")
        for s in self.superlatives:
            if s.get("status") == CONTRADICTED:
                lines.append(f"- In \"{s['text'].strip()}\": {s['detail']}")
        if not lines:
            return None
        return ("The desk checked the draft against the analysis it recorded. These statements do not hold as written; "
                "revise them (the rest stands):\n" + "\n".join(lines))


# ── reading the draft ─────────────────────────────────────────────────────────

def sentences_of(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        if m.start() > start:
            spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _words(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s)}


def _parse(token: str) -> dict | None:
    m = _NUMBER.match(token.strip())
    if not m:
        return None
    num = float(m.group("num").replace(",", ""))
    frac = m.group("frac")
    return {"value": num, "decimals": len(frac) if frac else 0, "pct": bool(m.group("pct")),
            "dollar": bool(m.group("dollar")), "sign": m.group("sign")}


def _core(token: str) -> str:
    """A written number without its sign, currency, grouping or percent sign."""
    return token.strip().lstrip("+-−$").replace(",", "").rstrip("%")


def _tolerance(decimals: int) -> float:
    return 0.5 * 10 ** (-decimals) + 1e-9


def _matches(written: float, cell_scaled: float, decimals: int) -> bool:
    return abs(abs(written) - abs(cell_scaled)) <= _tolerance(decimals)


def _subjects_in(sentence: str, subjects: Iterable[str]) -> list[str]:
    found = []
    for s in subjects:
        if re.search(rf"(?<![A-Za-z]){re.escape(s)}(?![A-Za-z])", sentence):
            found.append(s)
    return found


def _candidates(parsed: dict, after: str, cells: list[Cell]) -> tuple[list[Cell], str]:
    """The cells whose value reads as the written figure, and the unit the sentence
    gave the figure: pct | pp | money | plain."""
    written = parsed["value"]
    d = parsed["decimals"]
    if PP_WORDS.match(after):
        return [c for c in cells if c.kind == vs.ABSOLUTE_CHANGE and c.unit in ("RATIO", "PERCENT")
                and _matches(written, c.value * 100, d)], "pp"
    if parsed["pct"]:
        return [c for c in cells if c.unit in ("RATIO", "PERCENT") and _matches(written, c.value * 100, d)], "pct"
    if parsed["dollar"] or MONEY_SCALE.match(after):
        scale = 1.0
        m = MONEY_SCALE.match(after)
        if m:
            scale = _SCALES[m.group(1).lower()]
        return [c for c in cells if c.unit in ("MONEY", "MONEY_PER_SHARE", "MONEY_PER_DAY")
                and _matches(written, c.value / scale, d)], "money"
    plain = [c for c in cells if c.unit in ("RATIO", "MULTIPLE", "COUNT", "PERCENT") and _matches(written, c.value, d)]
    return plain, "plain"


def _kind_problem(cell: Cell, unit_word: str, sentence_words: set[str]) -> str | None:
    """A change written in the wrong unit, or a level written as one."""
    if cell.kind == vs.ABSOLUTE_CHANGE and cell.unit in ("RATIO", "PERCENT") and unit_word == "pct":
        return ("the figure is the change in percentage POINTS, not a percent change: "
                f"{cell.subject}'s {cell.label} is {cell.display} ({cell.period}); write it as percentage points, "
                f"or ask for the relative change")
    if cell.kind == vs.LEVEL and unit_word == "pp":
        return f"{cell.display} is a level of {cell.label} for {cell.subject}, not a change: it is not percentage points"
    if cell.kind == vs.RELATIVE_CHANGE and unit_word == "pp":
        return f"{cell.display} is a relative change, a percent of the earlier reading, not percentage points"
    return None


def _direction_problem(cell: Cell, parsed: dict, sentence_words: set[str]) -> str | None:
    if cell.kind not in vs.CHANGES:
        return None
    negative = cell.value < 0
    says_up, says_down = bool(sentence_words & UP_WORDS), bool(sentence_words & DOWN_WORDS)
    signed_neg = parsed["sign"] in ("-", "−")
    signed_pos = parsed["sign"] == "+"
    if negative and (says_up or signed_pos) and not says_down:
        return f"{cell.subject}'s {cell.label} FELL: the desk's figure is {cell.display} ({cell.period})"
    if not negative and (says_down or signed_neg) and not says_up:
        return f"{cell.subject}'s {cell.label} ROSE: the desk's figure is {cell.display} ({cell.period})"
    if negative and not (says_down or signed_neg):
        return f"the change is negative — {cell.subject}'s {cell.label} is {cell.display} — and the sentence says neither"
    return None


def observe(draft: str, *, question: str, views: list[dict], passages: dict[str, str] | None = None) -> Verdict:
    """Every figure of `draft` against the cells of `views`; every sentence classified."""
    cells = cells_of(views)
    subjects = sorted({c.subject for c in cells}, key=len, reverse=True)
    asked_cores = {_core(t["token"]) for t in A.tokens_in(question or "") if t["kind"] == "num"}
    v = Verdict()
    spans = sentences_of(draft or "")
    tokens = A.tokens_in(draft or "")
    last_subjects: list[str] = []
    for si, (s, e) in enumerate(spans):
        sentence = draft[s:e]
        words = _words(sentence)
        mentioned = _subjects_in(sentence, subjects)
        context_subjects = mentioned or last_subjects
        if mentioned:
            last_subjects = mentioned
        props: list[Proposition] = []
        for t in tokens:
            if not (s <= t["start"] < e):
                continue
            tok, kind = t["token"], t["kind"]
            if kind in ("date", "form", "id"):
                props.append(Proposition(si, t["start"], t["end"], tok, IDENTITY))
                continue
            if kind != "num":
                continue
            if _core(tok) in asked_cores:
                props.append(Proposition(si, t["start"], t["end"], tok, QUESTION))
                continue
            before = draft[max(0, t["start"] - 1):t["start"]]
            if before in ("-", "–") and re.search(r"\d[-–]$", draft[:t["start"]]):
                props.append(Proposition(si, t["start"], t["end"], tok, IDENTITY))   # the second half of a range or a compound
                continue
            parsed = _parse(tok)
            if parsed is None:
                continue
            if parsed["value"] in (0.0,) and not parsed["pct"]:
                continue
            after = draft[t["end"]:t["end"] + 24]
            # an ordinal or a count that names a place or a number of subjects is not a figure
            if re.match(r"^(st|nd|rd|th)\b", after) or (parsed["decimals"] == 0 and parsed["value"] <= 12
                                                        and not parsed["pct"] and not parsed["dollar"]
                                                        and not PP_WORDS.match(after) and not MONEY_SCALE.match(after)):
                props.append(Proposition(si, t["start"], t["end"], tok, IDENTITY))
                continue
            candidates, unit_word = _candidates(parsed, after, cells)
            if context_subjects:
                narrowed = [c for c in candidates if c.subject in context_subjects]
                if narrowed:
                    candidates = narrowed
            if not candidates:
                hit = next((pid for pid, text in (passages or {}).items() if tok.lstrip("+-−$") in (text or "")), None)
                if hit:
                    props.append(Proposition(si, t["start"], t["end"], tok, PASSAGE, reason="passage", detail=hit))
                else:
                    props.append(Proposition(si, t["start"], t["end"], tok, UNSUPPORTED, reason="unsourced_figure"))
                continue
            by_subject = {c.subject for c in candidates}
            if len(by_subject) > 1:
                shown = "; ".join(f"{c.display} is {c.subject}'s {c.label}" for c in candidates[:4])
                props.append(Proposition(si, t["start"], t["end"], tok, AMBIGUOUS, reason="ambiguous_subject",
                                         detail=f"{tok} could be more than one subject's figure ({shown}); name the subject in the sentence"))
                continue
            # one subject: prefer the cell whose kind the unit word asks for, then the change
            preferred = [c for c in candidates if (c.kind == vs.ABSOLUTE_CHANGE) == (unit_word == "pp")] or candidates
            cell = preferred[0]
            problem = _kind_problem(cell, unit_word, words) or _direction_problem(cell, parsed, words)
            if problem:
                props.append(Proposition(si, t["start"], t["end"], tok, CONTRADICTED, cell=cell,
                                         reason="unit_kind" if "percentage" in problem or "level" in problem or "relative" in problem else "direction",
                                         detail=problem))
            else:
                props.append(Proposition(si, t["start"], t["end"], tok, SUPPORTED, cell=cell))
        checked = any(p.status not in (IDENTITY, QUESTION) for p in props)
        v.sentences.append({"tag": f"S{si + 1}", "text": sentence, "span": [s, e],
                            "status": "checked" if checked else JUDGEMENT,
                            "subjects": mentioned})
        v.propositions.extend(props)
        # superlatives: a subject called the weakest or the largest sits at an extreme of an
        # ordering. Each subject takes the superlative nearest to it in the sentence; a
        # superlative over a decline ("sharpest deterioration") names the bottom, not the top;
        # a negated sentence ("not the one that grew most") is the model's judgement.
        if mentioned and not (words & NEGATIONS) and any(vw.get("ranks") for vw in views):
            sups = [(m.start(), m.group(0).lower()) for m in _WORD.finditer(sentence)
                    if m.group(0).lower() in MAX_WORDS | MIN_WORDS]
            if sups:
                for subject in mentioned:
                    at = sentence.find(subject)
                    pos, word = min(sups, key=lambda sw: abs(sw[0] - at))
                    if abs(pos - at) > 80:
                        continue
                    want = "max" if word in MAX_WORDS else "min"
                    tail_words = _words(sentence[pos:pos + 40])
                    if want == "max" and tail_words & DECLINE_NOUNS:
                        want = "min"
                    extremes = _extremes(subject, views)
                    ok = want in extremes
                    v.superlatives.append({"sentence": si, "text": sentence, "subject": subject, "word": word,
                                           "status": SUPPORTED if ok else CONTRADICTED,
                                           **({} if ok else {"detail": f"{subject} is at no {'top' if want == 'max' else 'bottom'} of any "
                                                                       f"ordering the desk computed this turn: " + _rank_words(views)})})
    v.completion = completion_of(draft, views, v)
    return v


def _extremes(subject: str, views: list[dict]) -> set[str]:
    out: set[str] = set()
    for vw in views:
        for key, rank in (vw.get("ranks") or {}).items():
            order = rank.get("order") or []
            if not order:
                continue
            first, last = order[0]["place"], order[-1]["place"]
            places = {o["subject"]: o["place"] for o in order}
            if subject not in places:
                continue
            at_top = places[subject] == first
            at_bottom = places[subject] == last
            highest_first = rank.get("direction", "highest") == "highest"
            if (at_top and highest_first) or (at_bottom and not highest_first):
                out.add("max")
            if (at_bottom and highest_first) or (at_top and not highest_first):
                out.add("min")
    return out


def _rank_words(views: list[dict]) -> str:
    said = []
    for vw in views:
        for key, rank in (vw.get("ranks") or {}).items():
            order = rank.get("order") or []
            if order:
                said.append(f"{key}: " + " > ".join(f"{o['subject']} {o['display']}" for o in order))
    return "; ".join(said)


def completion_of(draft: str, views: list[dict], verdict: Verdict) -> dict:
    """What the analysis asked for against what the draft states — from the requests
    the views were built for, never from the model's own word."""
    cited = {p.cell.ref for p in verdict.propositions if p.status == SUPPORTED and p.cell}
    requests: list[dict] = []
    status_words = []
    for vw in views:
        cols = {c["key"]: c for c in vw.get("columns") or []}
        refs_by_col: dict[str, set[str]] = {}
        for row in vw.get("rows") or []:
            for key, cell in (row.get("cells") or {}).items():
                if isinstance(cell, dict) and cell.get("ref"):
                    refs_by_col.setdefault(key, set()).add(cell["ref"])
        for req in vw.get("requests") or []:
            m = req["measure"]
            entry = {"view": vw.get("view"), "measure": m, "compare": req.get("compare"), "rank": bool(req.get("rank")),
                     "cited": len(cited & refs_by_col.get(m, set())),
                     "change_cited": len(cited & refs_by_col.get(f"{m}.change", set())) if req.get("compare") else None,
                     "subjects": len(vw.get("rows") or [])}
            stated = entry["cited"] + (entry["change_cited"] or 0)
            entry["ranked_said"] = any(s.get("status") == SUPPORTED for s in verdict.superlatives) or entry["cited"] >= 2 \
                or (entry["change_cited"] or 0) >= 2
            done = stated > 0 and (not req.get("compare") or entry["change_cited"]) and (not req.get("rank") or entry["ranked_said"])
            entry["status"] = "covered" if done else ("partial" if stated else "not_stated")
            requests.append(entry)
            status_words.append(entry["status"])
        scope = vw.get("scope") or {}
        if scope.get("status") == "mismatch":
            expected, resolved = scope.get("expected_count"), scope.get("resolved_count")
            words = _words(draft)
            acknowledged = str(resolved) in draft or next((w for w, n in _COUNT_WORDS.items() if n == resolved), None) in words
            requests.append({"view": vw.get("view"), "scope": "mismatch", "expected": expected, "resolved": resolved,
                             "acknowledged": bool(acknowledged), "status": "covered" if acknowledged else "not_stated"})
            status_words.append(requests[-1]["status"])
    if not requests:
        status = "unknown"
    elif all(w == "covered" for w in status_words):
        status = "full"
    elif any(w != "not_stated" for w in status_words):
        status = "partial"
    else:
        status = "not_stated"
    return {"status": status, "requests": requests}
